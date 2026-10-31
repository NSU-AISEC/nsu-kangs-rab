"""세션 종료의 정리 문서 만들기 (K-16; FR-13, 결정 0028, `docs/plan/prompt-spec.md` 8절). Qt 를 가져오지 않는다.

두 경로가 있다.
- 이력이 있는 경로(`run_resident`): 상주 프로세스에 단독 `/effort high`(세션의 effort 가 high 가 아닐 때, A-22)를 보낸 뒤 정리 요청을 보낸다.
  요청이 진행 중이거나 대기 중이면 이력 없는 경로로 만든다(임의). 사건은 `SessionRuntime.set_listener` 로 직접 받는다.
- 이력이 없는 경로(`run_history_less`): `session.jsonl` 로 요청을 만들어 일회성 프로세스에 보낸다(세션 메뉴의 다시 만들기, 8-3-1절).

어느 경로든 끝나면 `on_done(EndResult)` 를 한 번만 호출한다. 실패해도 `session.jsonl` 은 그대로이다.
"""
from __future__ import annotations
from .i18n import t as _t

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import cleanup_doc, doc_images, resources
from .oneshot import OneShot, Outcome
from .session import read_jsonl
from .types import OutgoingMessage, ProcessExited, Result, TextDelta, Error

DONE, FAILED, CANCELLED = "done", "failed", "cancelled"


@dataclass(frozen=True)
class EndResult:
    status: str                      # done | failed | cancelled
    path: Optional[Path] = None
    kind: Optional[str] = None       # 실패 종류(error_kind)
    detail: str = ""
    route: str = ""                  # resident | history_less


def template_for(data: Mapping, doc_kind: str) -> str:
    """설정의 `templates.lecture` · `templates.meeting`(비면 기본, AC-FR13-9)."""
    key = "lecture" if doc_kind == "수업" else "meeting"
    custom = ((data or {}).get("templates") or {}).get(key)
    if isinstance(custom, str) and custom.strip():
        return custom
    return resources.lecture_template() if doc_kind == "수업" else resources.meeting_template()


def view_of(folder, emit: Optional[Callable] = None) -> Optional[cleanup_doc.View]:
    p = Path(folder) / "session.jsonl"
    if not p.exists():
        return None
    events, rec = read_jsonl(p, emit)
    return cleanup_doc.session_view(events, rec)


_H2 = re.compile(r"^## ", re.M)


def count_sections(text: str) -> int:
    """출력의 처음 또는 줄바꿈 바로 뒤의 세 글자가 정확히 `## ` 인 줄의 수(결정 0154 ⑤). 코드 블록은 구분하지 않는다."""
    return len(_H2.findall(text or ""))


def format_elapsed(seconds: float) -> str:
    """경과 시간: 60분 미만은 mm:ss, 이상은 h:mm:ss(결정 0154 ⑥)."""
    sec = max(0, int(seconds))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


class SectionProgress:
    """정리 문서 생성의 절 단위 진행(결정 0154). Qt 를 가져오지 않는다. 시계는 주입할 수 있다(`clock`, `shift`)."""

    def __init__(self, template: str, clock: Callable[[], float] = time.monotonic):
        self.total = count_sections(template)
        self._clock = clock
        self._shift = 0.0
        self._t0 = clock()
        self._buf = ""
        self._mu = threading.Lock()

    def restart(self) -> None:
        """요청을 새로 보낸 때(다시 만들기 · 재시도)부터 다시 센다."""
        with self._mu:
            self._t0, self._buf, self._shift = self._clock(), "", 0.0

    def shift(self, seconds: float) -> None:
        """시험용: 기준 시각을 `seconds` 만큼 앞당긴다(`--dev-control` 의 `elapsed_shift`)."""
        with self._mu:
            self._shift += float(seconds)

    def feed(self, delta: str) -> None:
        with self._mu:
            self._buf += delta or ""

    def snapshot(self) -> tuple:
        """(n, N, 경과 초, 조각을 받았는가). n 은 N 을 넘지 않는다."""
        with self._mu:
            n = min(count_sections(self._buf), self.total)
            return n, self.total, self._clock() + self._shift - self._t0, bool(self._buf)


class EndFlow:
    def __init__(self, *, folder, doc_kind: str, template: str, eventlog=None, to_jpeg=None):
        self.folder = Path(folder)
        self._to_jpeg = to_jpeg              # 단계 18: 문서의 이미지 링크를 JPEG 사본으로 바꾼다(None 이면 바꾸지 않는다)
        self._skip: set = set()
        self.doc_kind = doc_kind
        self.template = template
        self._log = eventlog
        self._mu = threading.Lock()
        self._done = False
        self._on_done: Optional[Callable[[EndResult], None]] = None
        self._oneshot: Optional[OneShot] = None
        self._runtime = None
        self._text = ""
        self._effort_pending = False
        self._route = ""
        self.progress = SectionProgress(template)

    # ---- 이력이 있는 경로 ----
    def can_use_resident(self, runtime) -> bool:
        m = runtime.manager
        return m.in_flight() is None and not m.queue_numbers()

    def run_resident(self, runtime, view: cleanup_doc.View, session_effort: Optional[str],
                     on_done: Callable[[EndResult], None]) -> bool:
        self._on_done, self._runtime, self._route = on_done, runtime, "resident"
        self._skip = doc_images.deleted_paths(view)
        self.progress.restart()
        text = cleanup_doc.build_request(view, self.doc_kind, self.template, history=True)
        runtime.set_listener(self._on_event)
        model = runtime.model
        if session_effort != "high":
            self._effort_pending = True
            if not model.set_effort("high"):
                runtime.set_listener(None)
                return False
        if not model.send(OutgoingMessage(0, ({"type": "text", "text": text},))):
            runtime.set_listener(None)
            return False
        self._emit("cleanup_start", route="resident", effort_switch=self._effort_pending)
        return True

    def _on_event(self, ev) -> None:
        if isinstance(ev, TextDelta):
            self._text += ev.text
            self.progress.feed(ev.text)
        elif isinstance(ev, Result):
            if self._effort_pending and ev.ok and ev.num_turns == 0:
                self._effort_pending = False       # `/effort` 의 지역 명령 결과이다
                return
            if ev.ok:
                self._finish_text(ev.text or self._text)
            else:
                self._fail(ev.error_kind or "unknown", (ev.text or "")[:400])
        elif isinstance(ev, Error):
            if ev.kind in ("auth", "no_claude", "process_exit", "io"):
                self._fail(ev.kind, ev.detail)
        elif isinstance(ev, ProcessExited):
            if not ev.expected:
                self._fail("process_exit", _t("endflow.on_event_291"))

    # ---- 이력이 없는 경로 ----
    def run_history_less(self, view: cleanup_doc.View, oneshot: OneShot, on_done: Callable[[EndResult], None]) -> bool:
        self._on_done, self._oneshot, self._route = on_done, oneshot, "history_less"
        self._skip = doc_images.deleted_paths(view)
        self.progress.restart()
        oneshot.on_text = self.progress.feed
        text = cleanup_doc.build_request(view, self.doc_kind, self.template, history=False)
        self._emit("cleanup_start", route="history_less", effort_switch=False)
        return oneshot.run(text, self._on_outcome)

    def _on_outcome(self, o: Outcome) -> None:
        if o.ok:
            self._finish_text(o.text)
        elif o.cancelled:
            self._finish(EndResult(CANCELLED, route=self._route))
        else:
            self._fail(o.error_kind or "unknown", o.detail)

    # ---- 취소 · 종료 ----
    def cancel(self) -> None:
        if self._oneshot is not None:
            self._oneshot.cancel()          # `_on_outcome` 이 취소로 끝낸다
        else:
            rt = self._runtime
            if rt is not None:
                try:
                    rt.model.interrupt()
                except Exception:
                    pass
            self._finish(EndResult(CANCELLED, route=self._route))

    def _finish_text(self, text: str) -> None:
        if not (text or "").strip():
            self._fail("no_text", _t("endflow.finish_text_292"))
            return
        if self._to_jpeg is not None:
            try:
                text = doc_images.convert_links(text, self.folder, self._to_jpeg, self._emit, skip=self._skip)
            except Exception:  # noqa: BLE001 — 변환 오류가 문서 저장을 막지 않는다
                self._emit("doc_image", kind="convert_failed", path="", detail="unexpected")
        try:
            path = cleanup_doc.save_document(self.folder, self.doc_kind, text)
        except OSError as e:
            self._fail("io", _t("endflow.finish_text_293") % type(e).__name__)
            return
        self._finish(EndResult(DONE, path=path, route=self._route))

    def _fail(self, kind: str, detail: str) -> None:
        self._finish(EndResult(FAILED, kind=kind, detail=detail, route=self._route))

    def _finish(self, r: EndResult) -> None:
        with self._mu:
            if self._done:
                return
            self._done = True
        if self._runtime is not None:
            self._runtime.set_listener(None)
        self._emit("cleanup_end", status=r.status, route=r.route, error_kind=r.kind)
        cb = self._on_done
        if cb is not None:
            try:
                cb(r)
            except Exception:
                pass

    def _emit(self, type_: str, **f) -> None:
        if self._log is not None:
            try:
                self._log.emit(type_, **f)
            except Exception:
                pass
