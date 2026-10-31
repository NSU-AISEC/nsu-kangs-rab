"""세션 하나의 핵심 부품을 묶는 조립부 (기술 계획 2-4절 `app.py` 의 "핵심 모듈을 만들고 연결한다", 진입점 조립).

Qt 를 가져오지 않는다. 화면 쪽(`app/controller.py`)은 이 객체를 만들고 콜백(`on_card` · `on_notice`)만 연결한다.

- `Transcript` · `ContextStore` · `Composer` · `RequestManager` · `ModelSession` 과 세션 폴더의 기록(`SessionLog`)을 묶는다.
- 조각이 도착하면 이력(`Transcript`)과 `session.jsonl` 에 덧붙인다(결정 0196: `transcript.txt` · `session.md` 는 만들지 않는다).
- 카드의 변화를 세션 기록의 `request` · `response` · `delete` 사건으로 옮긴다(본문은 `session.jsonl` 에만 남고 이벤트 로그에는 남지 않는다).
- 모델 호출은 `submit_*` · `trigger` 를 부를 때만 일어난다(AC-FR7-8). 만드는 것만으로 호출하지 않는다.
- `RequestManager` 의 콜백 제약(2-4절): `on_card` · `on_notice` 는 잠금 안에서 호출되므로 `RequestManager` 를 다시 호출하지 않는다.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import i18n, languages
from . import requests as R
from .context import ContextStore
from .session import SessionLog
from .transcript import Transcript, compress_ids, hms
from .types import Error, Init, PartialSegment, Segment

# 카드의 상태 → 세션 기록의 `response.status`(임의: 오류로 끝난 응답은 "중단" 으로 쓴다)
_RESPONSE_STATUS = {R.STATE_DONE: "완료", R.STATE_ERROR: "중단"}
# 응답이 끝난 카드는 오류로 끝난 카드 · 중단된 카드를 포함해 `완료` 이다(AC-FR9-16, D-046)
_DELETE_STATE = {R.STATE_ACTIVE: "진행 중", R.STATE_WAITING: "대기 중", R.STATE_DONE: "완료", R.STATE_ERROR: "완료"}


def judgment_first_line(card: R.Card) -> Optional[str]:
    """`response.judgment`: 응답의 첫 줄(판단 줄). 판단이 없거나 미확인이면 None."""
    j = card.judgment
    if j is None or j == R.JUDGMENT_UNCONFIRMED:
        return None
    subject = card.judgment_subject or ""
    if j == "질문 없음":
        return "판단: 질문 없음 | %s" % subject
    return '판단: %s | "%s"' % (j, subject)


@dataclass
class _Meta:
    kind: str
    input: str
    capture_paths: tuple = ()      # ((세션 폴더 기준 상대 경로, 출처), ...)


class SessionRuntime:
    def __init__(self, *, folder, log: SessionLog, transcript: Transcript,
                 context: ContextStore, composer: R.Composer, model, eventlog=None,
                 on_card: Optional[Callable] = None, on_notice: Optional[Callable] = None,
                 on_error: Optional[Callable] = None, manager_factory: Optional[Callable] = None, **manager_kwargs):
        self.folder = Path(folder)
        self.log = log
        self.transcript, self.context, self.composer = transcript, context, composer
        self.model = model
        self._eventlog = eventlog
        self._ext_on_card, self._ext_on_notice, self._ext_on_error = on_card, on_notice, on_error
        self._tl = threading.local()
        self._requested: set = set()
        self._meta: dict = {}                      # 카드 번호 → _Meta
        self._responded: set = set()
        self._mu = threading.Lock()
        self._closed = False
        self._pause_start: Optional[str] = None
        make = manager_factory or R.RequestManager
        self.manager = make(model, composer, eventlog=eventlog, on_card=self._on_card, on_notice=self._on_notice,
                            **manager_kwargs)

    # ---- 시작 · 종료 ----
    def start(self) -> bool:
        """상주 프로세스를 시작한다(모델 호출은 없다). 실패하면 `Error` 사건이 `on_model_event` 로 간다."""
        return bool(self.model.start())

    def set_init_hook(self, fn: Optional[Callable]) -> None:
        """모델의 `Init` 사건(인증 출처 확인을 통과한 것)을 한 번 받는다. 앱이 세션 화면으로 가는 시점이다(결정 0056)."""
        self._init_hook = fn

    def set_listener(self, fn: Optional[Callable]) -> None:
        """종료 흐름이 상주 프로세스의 사건을 직접 받는다(요청 관리자는 사건을 받지 못한다). None 이면 해제한다."""
        self._listener = fn

    def on_model_event(self, ev) -> None:
        fn = getattr(self, "_listener", None)
        if fn is not None:
            fn(ev)
            return
        hook = getattr(self, "_init_hook", None)
        if hook is not None and isinstance(ev, Init):
            self._init_hook = None
            hook(ev)
        self.manager.on_model_event(ev)
        # 진행 중인 요청이 없을 때의 오류(시작 실패 · 인증 불일치 등)는 카드가 없으므로 호출한 쪽이 표시한다.
        if isinstance(ev, Error) and self._ext_on_error is not None and not any(
                c.state == R.STATE_ERROR and c.error == (ev.kind, ev.detail) for c in self.manager.cards()):
            self._ext_on_error(ev.kind, ev.detail)

    # ---- 일시 정지 (결정 0147) ----
    def pause_begin(self) -> Optional[str]:
        """일시 정지의 시작을 기록한다(`pause` `시작`). 이미 일시 정지 중이면 아무것도 하지 않는다. 반환: 기록한 시각(HH:MM:SS)."""
        with self._mu:
            if self._closed or self._pause_start is not None:
                return None
            ts = self._pause_start = self.log._wall()
        try:
            self.log.append("pause", state="시작", ts=ts)
        except Exception:
            pass
        return ts

    def pause_end(self) -> Optional[tuple]:
        """일시 정지의 끝을 기록한다(`pause` `끝` + 전사 문서의 구간 블록). 일시 정지 중이 아니면 None. 반환: (시작, 끝)."""
        with self._mu:
            start, self._pause_start = self._pause_start, None
            if start is None or self._closed:
                return None
            ts = self.log._wall()
        try:
            self.log.append("pause", state="끝", ts=ts)
        except Exception:
            pass
        return start, ts

    def paused_since(self) -> Optional[str]:
        return self._pause_start

    def mark_end(self) -> None:
        """`end` 사건을 한 번만 덧붙인다. 정리 문서의 요청이 종료 시각을 읽기 전에 호출한다(K-16).
        일시 정지 중이면 종료 시각이 일시 정지의 끝이므로 `end` 바로 앞에 `pause` `끝` 을 쓴다(결정 0147)."""
        if self._closed or getattr(self, "_end_marked", False):
            return
        self._end_marked = True
        self.pause_end()
        try:
            self.log.append("end")
        except Exception:
            pass

    def finish(self) -> None:
        """세션 종료: `end` 사건을 덧붙이고 닫는다(FR-13). 이미 닫혔으면 아무것도 하지 않는다."""
        self.mark_end()
        self.close()

    def close(self) -> None:
        with self._mu:
            if self._closed:
                return
            self._closed = True
        try:
            self.manager.close()
        finally:
            try:
                self.model.close()
            finally:
                self.log.close()

    # ---- 조각 ----
    def on_segment(self, seg: Segment) -> bool:
        """STT 에서 도착한 확정 조각. 이력 → `session.jsonl`. 같은 번호는 한 번만 쓴다."""
        if not self.transcript.add(seg):
            return False
        self.log.append("segment", n=seg.n, start=hms(seg.start_wall), end=hms(seg.end_wall), text=seg.text)
        return True

    def on_partial(self, p: PartialSegment, start_wall: str, end_wall: str) -> None:
        """진행 중 구간의 잠정 문장. 대기 상한을 넘긴 요청에만 쓰이며 저장 · 기록하지 않는다(결정 0166)."""
        self.transcript.set_open(p.text, start_wall, end_wall, p.start_mono, p.end_mono)

    def close_open(self) -> None:
        """확정 없이 끝난 구간(구간 실패 · 일시 정지 · 수집 중단 · 세션 종료 · 보조 프로세스 종료)의 잠정을 버린다."""
        self.transcript.close_open()

    def abandon_open(self) -> None:
        """[일시 정지]: 진행 중 구간을 끊긴 것으로 표시한다(확정은 기다리고, 없으면 잠정은 요청에 쓰지 않는다)."""
        self.transcript.abandon_open()

    def resume_open(self) -> None:
        """[재생] 으로 일시 정지가 끝났다(권고 62): 끊긴 구간은 더 이상 진행 중이 아니다."""
        self.transcript.resume_open()

    stt_cut = None      # 컨트롤러가 정한다: 진행 중 구간에 끊기 신호를 한 번 보내는 호출 가능 객체

    # ---- 요청 ----
    def trigger(self, source: str = "button") -> str:
        """반환: `started` · `waiting` · `busy` · `held`(`RequestManager.trigger`)."""
        return self.manager.trigger(source)

    def set_capture_busy(self, busy: bool) -> None:
        self.manager.set_capture_busy(busy)

    def submit(self, kind: str, *, text: str = "", selected: Sequence[int] = (), images: Sequence = (),
               capture_paths: Sequence = (), record_input: Optional[str] = None) -> R.Card:
        """`kind` 의 요청을 등록한다. `record_input`: `session.jsonl` 의 `request.input`(없으면 규칙대로 정한다)."""
        sel = tuple(sorted(set(selected)))
        if record_input is None:
            record_input = self._record_input(kind, text, sel, images, capture_paths)
        req = R.Request(kind, input=text or None, images=tuple(images), selected=sel)
        self._tl.meta = _Meta(kind, record_input, tuple(capture_paths))
        try:
            return self.manager.submit(req)
        finally:
            self._tl.meta = None

    @staticmethod
    def _record_input(kind: str, text: str, selected: tuple, images: Sequence, capture_paths: Sequence) -> str:
        """prompt-spec 8-3-1 의 `request.input` 값."""
        if kind == "트리거" or kind in ("고찰", "요약"):
            return {"트리거": "", "고찰": "/고찰", "요약": "/요약"}[kind]
        if kind == "답변":
            return "/답변" if not selected else "/답변 조각=%s" % compress_ids(selected)
        if kind == "화면메모":
            return capture_paths[0][0] if capture_paths else ""
        return text + (" (이미지 첨부)" if images else "")

    def delete_card(self, n: int) -> bool:
        card = next((c for c in self.manager.cards() if c.n == n), None)
        ok = self.manager.delete_card(n)
        if ok and card is not None and card.state in _DELETE_STATE:
            self.log.append("delete", n=n, kind=card.kind, card_ts=hms(card.t_wall) if card.t_wall else "00:00:00",
                            state=_DELETE_STATE[card.state])
        return ok

    # ---- 콜백 ----
    def _on_card(self, card: R.Card, change: str) -> None:
        try:
            self._record(card, change)
        finally:
            if self._ext_on_card is not None:
                self._ext_on_card(card, change)

    def _record(self, card: R.Card, change: str) -> None:
        try:
            if change == "new":
                meta = getattr(self._tl, "meta", None) or _Meta(card.kind, "")
                self._meta[card.n] = meta
                # D-127: `request` 줄은 요청을 보낼 때(상태가 진행이 될 때) 쓴다. 보내기 전에 지운 요청은 기록하지 않는다.
                if card.state == R.STATE_ACTIVE:
                    self._write_request(card)
            elif change == "update" and card.state == R.STATE_ACTIVE and card.n not in self._requested:
                self._write_request(card)
            elif change == "update" and card.state in _RESPONSE_STATUS and card.n not in self._responded:
                self._responded.add(card.n)
                if card.n not in self._requested:      # 보내기를 시도한 뒤 끝난 요청(전달 실패 등)
                    self._write_request(card)
                self.log.append("response", n=card.n, judgment=judgment_first_line(card), text=card.text,
                                status=_RESPONSE_STATUS[card.state], ts=self._now_hms())
        except Exception:
            # 기록 실패가 요청 처리를 막지 않는다. 이벤트 로그에는 종류만 남긴다(본문 없음).
            if self._eventlog is not None:
                try:
                    self._eventlog.emit("error", module="session", kind="io", detail="세션 기록을 쓰지 못했다")
                except Exception:
                    pass

    def _write_request(self, card: R.Card) -> None:
        meta = self._meta.get(card.n) or _Meta(card.kind, "")
        self._requested.add(card.n)
        ts = hms(card.t_wall) if card.t_wall else "00:00:00"
        self.log.append("request", n=card.n, kind=card.kind, input=meta.input, ts=ts)
        for rel, source in meta.capture_paths:
            self.log.append("capture", n=card.n, path=rel, source=source, ts=ts)

    @staticmethod
    def _now_hms() -> str:
        from datetime import datetime
        return datetime.now().astimezone().strftime("%H:%M:%S")

    def _on_notice(self, kind: str, info: dict) -> None:
        if self._ext_on_notice is not None:
            self._ext_on_notice(kind, info)



# ======================================================================================================
# 조립
# ======================================================================================================
SOURCE_LABELS = {"system_sound": "시스템 사운드", "system_mic": "시스템 마이크"}      # 내부 값(세션 기록의 머리). 화면은 `source_display`


def source_display(source) -> Optional[str]:
    """화면에 보이는 입력 이름(앱 언어)."""
    from .i18n import t
    key = {"system_sound": "label.source_system_sound", "system_mic": "label.source_system_mic"}.get(source)
    return t(key) if key else None
MODE_BY_SOURCE = {"system_sound": "화상", "system_mic": "대면"}      # FR-10 header: 마이크이면 대면, 사운드이면 화상
AUTH_BY_PROVIDER = {"claude_subscription": "subscription", "claude_api": "api"}


def build_runtime(*, params: dict, data: dict, devopts, config_dir, save_base, claude_path: str,
                  claude_is_script: Optional[bool], parent_env, procs, eventlog, context: ContextStore,
                  api_key: Optional[str] = None, on_card=None, on_notice=None, on_error=None, today=None,
                  model_factory: Optional[Callable] = None) -> SessionRuntime:
    """세션 시작 화면의 값(`params`)으로 세션 폴더 · 기록 · 모델 프로세스 객체를 만든다. 프로세스는 시작하지 않는다(`start()`).

    `params`: `SessionStartForm.values()` 와 같다(provider · model · effort · source · kind · title · save_dir · session_prompt).
    `api_key`: 제공자가 API 일 때 호출한 쪽이 키체인에서 읽어 넘긴다(여기서 키체인에 접근하지 않는다).
    """
    from datetime import date as _date, datetime

    from . import i18n, languages, llm, resources, settings
    from .model_session import ModelSession
    from .session import SessionFolder

    provider = params.get("provider") or settings.DEFAULT_PROVIDER
    auth = llm.Auth.API if AUTH_BY_PROVIDER.get(provider) == "api" else llm.Auth.SUBSCRIPTION
    family, effort = params.get("model"), params.get("effort")
    source = params.get("source") or "system_sound"
    stt_language = languages.normalize_stt(params.get("stt_language") or data.get("stt_language"))     # 세션이 시작할 때의 값을 끝까지 쓴다(FR-16)
    prompt_source, prompt = settings.resolve_session_prompt(data, params.get("session_prompt"), resources.default_session_prompt())
    system_prompt = context.system_prompt(resources.app_rules(stt_language), prompt)

    base = devopts.get("save_dir") or params.get("save_dir") or save_base
    day = today or _date.today()
    folder = SessionFolder.create(base, day)
    log = SessionLog(folder)
    log.append("header", date=day.isoformat(), provider=provider, model=str(family), effort=effort or "(없음)",
               source=SOURCE_LABELS.get(source, "시스템 사운드"), materials=[m.name for m in context.materials()],
               kind=params.get("kind") or "수업", title=params.get("title") or "(이름 없음)",
               number=str(SessionFolder.number(folder)), mode=MODE_BY_SOURCE.get(source, "화상"),
               start=datetime.now().astimezone().strftime("%H:%M:%S"))
    transcript = Transcript()
    composer = R.Composer(transcript, context,
                          request_image_bytes_cap=devopts.get("request_image_bytes_cap") or R.imageinfo.REQUEST_IMAGE_BYTES_CAP)
    cfg = llm.SessionConfig(claude_path=claude_path, model=str(family), effort=effort)
    holder: dict = {}
    make_model = model_factory or ModelSession
    model = make_model(cfg, auth, lambda ev: holder["rt"].on_model_event(ev), procs=procs,
                       parent_env=parent_env, cwd=str(folder), api_key=api_key if auth is llm.Auth.API else None,
                       eventlog=eventlog, prompt_text=system_prompt, run_dir=str(Path(config_dir) / "run"))
    kwargs = {}
    if devopts.get("hidden_cap_s"):
        kwargs["hidden_limit_s"] = float(devopts.get("hidden_cap_s"))
    if devopts.get("final_wait_cap_s"):
        kwargs["final_wait_cap_s"] = float(devopts.get("final_wait_cap_s"))
    kwargs["cut"] = lambda: (holder["rt"].stt_cut or (lambda: None))()
    rt = SessionRuntime(folder=folder, log=log, transcript=transcript, context=context, composer=composer,
                        model=model, eventlog=eventlog, on_card=on_card, on_notice=on_notice, on_error=on_error, **kwargs)
    holder["rt"] = rt
    rt.stt_language = stt_language
    if eventlog is not None:
        eventlog.session_start(kind=params.get("kind") or "수업", save_dir=str(folder), claude_path=claude_path,
                               claude_is_script=claude_is_script, provider=provider, auth=auth.value,
                               model=str(family), effort=effort, audio_source=source, prompt_source=prompt_source,
                               prompt_sha256=settings.text_sha256(prompt),
                               materials=[m.name for m in context.materials()], dev_options=list(devopts.names), stt_language=stt_language,
                               app_language=i18n.language())
    return rt
