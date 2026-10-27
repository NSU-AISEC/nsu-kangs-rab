"""요청 메시지의 구성 (K-06; prompt-spec 4 · 4-1 · 4-2절, FR-7 · FR-8)과 대기열 · 카드 삭제 · 숨긴 응답 상한 · 재시작 (K-07; D8, A-14 · A-18 · A-19).

모든 메시지는 앱의 머리(`[요청] …`)로 시작하고 사용자 글은 맨 끝의 `[사용자]` 블록에 둔다(AC-FR7-20).
content 의 순서: ① 머리 텍스트 블록 ② 이미지 줄과 이미지 블록의 쌍(사전 지식 이미지가 앞, 첨부 · 캡처가 뒤) ③ `[사용자]`.
`Composer` 는 `Transcript` 와 "첫 요청 · 재시작 뒤" 의 사전 지식 이미지 규칙을 묶는다. 전달에 성공한 뒤에만 `delivered` 를
호출하므로, 전달 전에 대기열에서 지워진 요청의 조각 · 사전 지식 이미지는 다음 요청에 다시 담긴다(AC-FR2-8).
"""
from __future__ import annotations
from .i18n import t as _t

import base64
import hashlib
import re
import threading
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from . import imageinfo
from .context import escape_lines, ref_name
from .transcript import Delta, Transcript, compress_ids, hms, one_line
from .types import (Compacted, Compacting, ControlResponse, Error, Init, OutgoingMessage, ProcessExited, Result,
                    TextDelta)

KINDS = ("트리거", "답변", "고찰", "요약", "자유질의", "화면메모")
FINAL_WAIT_CAP_S = 2.0          # 확정 대기 상한의 초깃값(기술 계획 2-8절, S10-1)
LAST30_KINDS = ("트리거", "답변")   # FR-7 표: 마지막 30초를 표시하는 요청 종류
IMAGE_SOURCES = ("캡처", "붙여넣기", "끌어다 놓기")


@dataclass(frozen=True)
class AttachedImage:
    """첨부 · 캡처 이미지 하나. `data` 는 보낼 바이트(축소를 마친 것)."""
    source: str
    t_wall: str
    media_type: str
    data: bytes = field(repr=False)
    name: str = ""                     # 카드에 뺀 첨부를 표시할 때 쓰는 이름. 비면 `source`


@dataclass(frozen=True)
class Composed:
    message: OutgoingMessage
    delta: Delta
    registered_included: bool
    log: dict   # AC-FR8-1: 이벤트 로그에 남길 값(본문 없음). 사건 이름은 K-07 이 정한다
    dropped: tuple = ()   # 요청 합계 상한(결정 0059 · 0061) 때문에 싣지 않은 첨부의 이름(첨부한 순서). 요청은 그대로 보낸다


def _segment_line(s) -> str:
    return "%d %s-%s %s" % (s.n, hms(s.start_wall), hms(s.end_wall), one_line(s.text))


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _image_block(media_type: str, data: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(data).decode("ascii")}}


def _escape_bracket(text: str) -> str:
    """본문 첫 글자가 "[" 이면 줄 이름으로 읽히지 않게 "\\[" 로 바꾼다(prompt-spec 4절 `[잠정]`)."""
    return "\\" + text if text.startswith("[") else text


def compose_message(kind: str, n: int, t_wall: str, delta: Delta, *, selected: Sequence[int] = (),
                    user_text: Optional[str] = None, images: Sequence[AttachedImage] = (),
                    registered: Sequence = ()) -> OutgoingMessage:
    """`registered`: 사전 지식 이미지(`context.Material`, kind=image)를 이 요청에 담을 때만 준다."""
    if kind not in KINDS:
        raise ValueError("알 수 없는 요청 종류: %r" % (kind,))
    head = ["[요청] 종류=%s 시각=%s 번호=%d" % (kind, hms(t_wall), n)]
    if delta.resend:
        a, b = delta.resend_range
        head.append("[재전송] 범위=%s~%s 조각=%s" % (hms(a), hms(b), compress_ids(s.n for s in delta.resend)))
        head += [_segment_line(s) for s in delta.resend]
    if delta.segments:
        a, b = delta.new_range
        head.append("[새 조각] 범위=%s~%s 조각=%s 글자=%d" % (
            hms(a), hms(b), compress_ids(s.n for s in delta.segments), delta.new_chars))
        head += [_segment_line(s) for s in delta.segments]
    else:
        head.append("[새 조각] 없음")
    if delta.partial:
        ptext, pa, pb = delta.partial
        head.append("[잠정] 범위=%s~%s %s" % (hms(pa), hms(pb), _escape_bracket(one_line(ptext))))
    if selected:
        head.append("[선택 조각] 조각=%s" % compress_ids(selected))
    elif kind in LAST30_KINDS:
        head.append("[마지막 30초] 조각=%s" % compress_ids(s.n for s in delta.last30)
                    if delta.last30 else "[마지막 30초] 없음")
    blocks = [_text_block("\n".join(head))]
    imgs = [m for m in registered if getattr(m, "kind", "image") == "image" and m.bytes]
    for i, m in enumerate(imgs, 1):
        blocks.append(_text_block("[사전 지식 이미지] 순서=%d 전체=%d 이름=%s" % (i, len(imgs), ref_name(m.name))))
        blocks.append(_image_block(m.media_type, m.bytes))
    for im in images:
        blocks.append(_text_block("[이미지] 출처=%s 시각=%s" % (im.source, hms(im.t_wall))))
        blocks.append(_image_block(im.media_type, im.data))
    if user_text is not None and user_text != "":
        first, _, rest = user_text.partition("\n")
        body = first if not rest else first + "\n" + escape_lines(rest)
        blocks.append(_text_block("[사용자] " + body))
    return OutgoingMessage(n, tuple(blocks))


class Composer:
    """`Transcript` 와 사전 지식 이미지 규칙(첫 요청 · 재시작 · 이력 압축 뒤 한 번)을 묶는다."""

    def __init__(self, transcript: Transcript, context=None,
                 request_image_bytes_cap: int = imageinfo.REQUEST_IMAGE_BYTES_CAP):
        self.t = transcript
        self.ctx = context
        self.request_image_bytes_cap = request_image_bytes_cap
        self._registered_due = True   # 세션 시작 뒤 첫 요청
        self._lock = threading.Lock()

    def mark_restart(self) -> None:
        """프로세스 재시작 또는 이력 압축 뒤(AC-FR8-6 · AC-FR2-8)."""
        self.t.mark_restart()
        with self._lock:
            self._registered_due = True

    def compose(self, kind: str, n: int, t_wall: str, t_trigger_mono: float, *, selected: Sequence[int] = (),
                user_text: Optional[str] = None, images: Sequence[AttachedImage] = (),
                partial: Optional[tuple] = None, final_wait_s: float = 0.0) -> Composed:
        delta = self.t.delta(t_trigger_mono, partial)
        with self._lock:
            due = self._registered_due
        reg = list(self.ctx.first_request_images()) if (due and self.ctx is not None) else []
        # 결정 0061: 합계에는 이 요청이 싣는 사전 지식 이미지를 먼저 넣고 첨부를 순서대로 더한다. 상한을 넘게 하는 첫 첨부와
        # 그 뒤의 첨부를 모두 뺀다(같은 값은 받는다). 뺀 첨부가 있어도 요청은 보낸다.
        total = sum(len(m.bytes or b"") for m in reg if getattr(m, "kind", "image") == "image")
        kept, dropped = [], []
        for i, im in enumerate(images):
            if total + len(im.data) > self.request_image_bytes_cap:
                dropped = [x.name or x.source for x in images[i:]]
                break
            total += len(im.data)
            kept.append(im)
        images = kept
        msg = compose_message(kind, n, t_wall, delta, selected=selected, user_text=user_text, images=images,
                              registered=reg)
        acc = self.t.accumulated_range()
        nr, rr = delta.new_range, delta.resend_range
        log = {"request_n": n, "kind": kind,
               "new_start": nr[0] if nr else None, "new_end": nr[1] if nr else None,
               "new_segments": len(delta.segments), "new_chars": delta.new_chars,
               "resend_segments": len(delta.resend),
               "partial_included": delta.partial is not None,
               "partial_range": [hms(delta.partial[1]), hms(delta.partial[2])] if delta.partial else None,
               "final_wait_s": round(float(final_wait_s), 3),
               "accumulated_start": acc[0] if acc else None, "accumulated_end": acc[1] if acc else None,
               "registered_images": len(reg), "images": len(images), "images_dropped": len(dropped),
               "request_image_bytes": total,
               # D-036 ①: 기능 정의 5-1절 "마지막 30초로 표시한 조각" (선택 조각이 있거나 이 종류에 표시가 없으면 0 · None)
               "last30_segments": len(delta.last30) if (kind in LAST30_KINDS and not selected) else 0,
               "last30": compress_ids(s.n for s in delta.last30) if (kind in LAST30_KINDS and not selected and delta.last30) else None}
        return Composed(msg, delta, bool(reg), log, tuple(dropped))

    def delivered(self, composed: Composed) -> None:
        """요청이 모델 프로세스에 전달되었다: 조각을 보낸 것으로 기록하고 사전 지식 이미지 · 재전송을 끝낸다."""
        self.t.commit(composed.delta)
        with self._lock:
            if composed.registered_included or self.ctx is None or not self.ctx.first_request_images():
                self._registered_due = False


# ======================================================================================================
# K-07: 대기열 · 카드 · 숨긴 응답 상한 · 재시작
# ======================================================================================================
DROPPED_REASON = _t("req.dropped_reason")            # 카드에 표시하는 뺀 첨부의 사유(결정 0061 3항)
STATE_WAITING, STATE_ACTIVE, STATE_DONE, STATE_HIDDEN, STATE_ERROR = "대기", "진행", "완료", "숨김", "오류"
JUDGMENTS = ("질문", "이미 답이 나온 질문", "질문 없음")
JUDGMENT_UNCONFIRMED = "미확인"
_JUDGMENT_Q = re.compile(r'^판단: (질문|이미 답이 나온 질문) \| "(.+)"$')
_JUDGMENT_NONE = re.compile(r"^판단: (질문 없음) \| (.+)$")


def _wall_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def parse_judgment(text: str) -> tuple:
    """응답의 첫 줄을 판단 형식(prompt-spec 2절)으로 읽는다. 반환: (판단, 주제 · 질문 문장, 본문).
    형식에 맞지 않으면 (`미확인`, None, 응답 전체) — AC-FR7-21."""
    first, _, rest = text.partition("\n")
    first = first.rstrip("\r").strip()
    m = _JUDGMENT_Q.match(first) or _JUDGMENT_NONE.match(first)
    if not m or not m.group(2).strip():
        return JUDGMENT_UNCONFIRMED, None, text
    return m.group(1), m.group(2), rest.lstrip("\n")


@dataclass
class Request:
    """`app` · `capture` → `requests`. `n` 은 등록할 때 `RequestManager` 가 부여한다."""
    kind: str
    input: Optional[str] = None
    images: tuple = ()                 # AttachedImage
    selected: tuple = ()               # 선택한 조각 번호
    created_mono: float = 0.0
    t_trigger_mono: Optional[float] = None   # 마지막 30초의 기점. None 이면 보내는 시각


@dataclass
class Card:
    """`requests` → `app`. 콜백에는 복사본을 넘긴다(`snapshot`)."""
    n: int
    kind: str
    state: str = STATE_WAITING
    judgment: Optional[str] = None
    judgment_subject: Optional[str] = None
    text: str = ""
    t_wall: str = ""
    error: Optional[tuple] = None      # (kind, detail)
    usage: dict = field(default_factory=dict)
    dropped: tuple = ()                # 요청 합계 상한으로 싣지 못한 첨부의 이름. 사유는 `DROPPED_REASON`
    partial: Optional[tuple] = None    # 확정 대기 상한을 넘겨 잠정 문장을 넣은 요청의 시각 범위 (시작, 끝) HH:MM:SS (AC-FR7-14, NEW-60)
    question: Optional[str] = None     # 자유 질의 카드의 질문 줄(결정 0151). 사용자가 입력한 문장 그대로이며 다른 카드는 None

    def snapshot(self) -> "Card":
        return Card(self.n, self.kind, self.state, self.judgment, self.judgment_subject, self.text, self.t_wall,
                    self.error, dict(self.usage), tuple(self.dropped), self.partial, self.question)


@dataclass
class _Entry:
    card: Card
    req: Request
    sent_mono: Optional[float] = None
    first_token_mono: Optional[float] = None
    deltas: list = field(default_factory=list)
    hidden_since: Optional[float] = None
    interrupted: bool = False
    interrupt_id: Optional[str] = None
    hidden_timer: Optional[threading.Timer] = None
    ack_timer: Optional[threading.Timer] = None
    wait_start: Optional[float] = None   # 확정 대기를 시작한 단조 시각(대기하지 않았으면 None)
    waiter: bool = False               # 확정을 기다리는 스레드가 있다
    first_line_done: bool = False      # 트리거 응답의 첫 줄이 끝나 판단을 읽었는지 (AC-FR9-22)


class RequestManager:
    """요청의 순서를 소유한다(A-14: 앱이 FIFO 대기열을 소유한다, 한 번에 한 요청, `Result` 뒤에 다음 요청).

    - `session`: `send(OutgoingMessage)` · `interrupt()` · `restart()` 를 가진 객체(`ModelSession`).
    - `on_card(card, change)`: change 는 `new` · `update` · `removed`. 잠금 안에서 호출되므로 짧게 반환해야 한다.
    - `on_notice(kind, info)`: `trigger_busy` · `history_compacting` · `history_compacted` · `restarted` 등 표시용 알림.
    - 사건 이름(이벤트 로그): `request_sent` · `first_token` · `request_done` · `request_interrupted` · `card_deleted` ·
      `queue_enter` · `trigger_held` · `trigger_run` · `judgment` · `history_compacted` · `request_restart` (기능 정의 이벤트 로그 필드의 사건 종류에 대응).
      본문 · 입력문은 남기지 않고 입력문은 해시만 남긴다.
    """

    def __init__(self, session, composer: Composer, *, eventlog=None, on_card: Optional[Callable] = None,
                 on_notice: Optional[Callable] = None, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], str] = _wall_iso, hidden_limit_s: float = 60.0, interrupt_ack_s: float = 10.0,
                 final_wait_cap_s: float = FINAL_WAIT_CAP_S, cut: Optional[Callable] = None):
        self._session, self._composer, self._log = session, composer, eventlog
        self._on_card, self._on_notice = on_card, on_notice
        self._clock, self._wall = clock, wall
        self._hidden_limit, self._ack_s, self._final_cap, self._cut = hidden_limit_s, interrupt_ack_s, final_wait_cap_s, cut
        self._mu = threading.RLock()
        self._queue: list = []            # [_Entry]
        self._cards: dict = {}            # n -> _Entry (대기 · 진행 · 완료 · 오류 · 숨김)
        self._inflight: Optional[_Entry] = None
        self._next_n = 1
        self._needs_restart = False
        self._auto_pending = False      # D-065: 다음 요청에서의 자동 재시작이 예약되었다
        self._restarting = False
        self._capture_busy = False        # screencapture 를 실행하는 동안(앱이 `set_capture_busy` 로 켜고 끈다)
        self._capture_cards: set = set()  # 캡처가 등록한 화면 메모 카드(`track_capture`). 끝날 때까지 캡처 처리 중이다
        self._held_trigger: Optional[tuple] = None   # (source, 누른 시각)
        self._closed = False

    # ---- 조회 ----
    def cards(self) -> list:
        with self._mu:
            return [e.card.snapshot() for e in self._cards.values() if e.card.state != STATE_HIDDEN]

    def queue_numbers(self) -> list:
        with self._mu:
            return [e.card.n for e in self._queue]

    def in_flight(self) -> Optional[int]:
        with self._mu:
            return self._inflight.card.n if self._inflight else None

    # ---- 등록 ----
    def submit(self, req: Request, front: bool = False) -> Card:
        """카드는 요청을 등록할 때 생긴다(FR-10 의 `n`). 앞선 요청이 없으면 곧바로 보낸다. `front` 이면 대기열의 맨 앞에 둔다
        (캡처 처리 중에 보류한 트리거, D-115)."""
        if req.kind not in KINDS:
            raise ValueError("알 수 없는 요청 종류: %r" % (req.kind,))
        with self._mu:
            if not req.created_mono:
                req.created_mono = self._clock()
            if req.t_trigger_mono is None:   # AC-FR7-7 개정: 대기열에서 보낸 요청도 T = 요청한 시각
                req.t_trigger_mono = req.created_mono
            card = Card(self._next_n, req.kind, STATE_WAITING, t_wall=self._wall(),
                        question=(req.input if req.kind == "자유질의" and req.input else None))
            self._next_n += 1
            e = _Entry(card, req)
            self._cards[card.n] = e
            if front:
                self._queue.insert(0, e)
            else:
                self._queue.append(e)
            # D-036 ②: 기능 정의 5-1절 "대기열 진입(대기 수)". waiting 은 이 요청을 포함한 대기열 길이이다.
            self._emit("queue_enter", request_n=card.n, card_kind=req.kind, waiting=len(self._queue),
                       in_flight=self._inflight is not None)
            self._card(card, "new")
            if not self._schedule_auto_restart():
                self._pump()
            return card.snapshot()

    def trigger(self, source: str = "key") -> str:
        """반환: `started`(곧바로 등록) · `waiting`(미완료 조각을 기다린다) · `busy`(무시, 진행 중 표시) · `held`(캡처 처리 뒤 실행)."""
        with self._mu:
            if self._closed:
                return "busy"
            now = self._clock()
            if self._capture_active():          # AC-FR12-4: FR-7 의 응답 진행 중 무시 규칙보다 먼저 판정한다(D-114)
                if self._held_trigger is None:   # 처리 중에 여러 번 눌러도 하나만 보류한다(임의)
                    self._held_trigger = (source, now)
                self._emit("trigger_held", source=source, reason="캡처 처리", action="deferred")
                return "held"
            # D-065: `_needs_restart` 만으로는 무시하지 않는다. 요청을 등록하면 `submit` 이 프로세스를 다시 시작한다(FR-8).
            if self._inflight is not None or self._queue or self._restarting:
                reason = "전사 처리 대기" if self._queue and self._inflight is None and self._queue[0].waiter else "응답 진행"
                self._emit("trigger_held", source=source, reason=reason, action="ignored")
                self._notice("trigger_busy", {"source": source})
                return "busy"
            return self._start_trigger(source, now)

    def set_capture_busy(self, busy: bool) -> None:
        """`screencapture` 를 실행하는 동안 켠다. 캡처 처리는 그 실행부터 화면 메모 요청이 끝날 때까지이며(`track_capture`),
        그동안 누른 트리거는 보류했다가 처리가 끝나면 실행한다(AC-FR12-4)."""
        with self._mu:
            self._capture_busy = bool(busy)
            self._release_held()

    def track_capture(self, n: int) -> None:
        """캡처가 등록한 화면 메모 카드 `n` 이 끝날 때(완료 · 오류 · 숨김 · 삭제)까지 캡처 처리 중으로 본다."""
        with self._mu:
            self._capture_cards.add(n)

    def _capture_active(self) -> bool:
        if self._capture_busy:
            return True
        for n in list(self._capture_cards):
            e = self._cards.get(n)
            if e is None or e.card.state in (STATE_DONE, STATE_ERROR, STATE_HIDDEN):
                self._capture_cards.discard(n)
        return bool(self._capture_cards)

    def _release_held(self) -> None:
        """잠금 안에서 호출한다. 캡처 처리가 끝났고 보류한 트리거가 있으면 실행한다."""
        if self._held_trigger is None or self._closed or self._capture_active():
            return
        run, self._held_trigger = self._held_trigger, None
        self._start_trigger(run[0], run[1], front=True)      # 버리지 않는다. 대기열의 질의보다 먼저 보낸다(D-115)

    def _start_trigger(self, source: str, t_mono: float, front: bool = False) -> str:
        """대기열에 등록한다. 진행 중 구간의 확정 대기는 대기열의 차례가 왔을 때 `_pump_queue` 가 한다(T 부터 센다)."""
        self._emit("trigger_run", source=source)
        card = self.submit(Request("트리거", created_mono=t_mono, t_trigger_mono=t_mono), front=front)
        e = self._cards.get(card.n)
        return "waiting" if e is not None and e.waiter else "started"

    # ---- 카드 삭제 ----
    def delete_card(self, n: int) -> bool:
        """x 버튼. 확인 없이 지우며 되돌릴 수 없다(AC-FR9-16). 반환: 그런 카드가 있었는지."""
        with self._mu:
            e = self._cards.get(n)
            if e is None or e.card.state == STATE_HIDDEN:
                return False
            c = e.card
            if c.state == STATE_WAITING:        # AC-FR9-19: 대기열에서 빼고 보내지 않는다
                if e in self._queue:
                    self._queue.remove(e)
                phase = "대기 중"
                del self._cards[n]
            elif e is self._inflight:           # AC-FR9-2: 숨기고 응답은 끝까지 읽는다 (D-035: 진행 중 오류 카드도 같다)
                phase = "진행 중"
                c.state = STATE_HIDDEN
                e.hidden_since = self._clock()
                self._arm_hidden(e)
            else:
                phase = c.state
                del self._cards[n]
            self._emit("card_deleted", card_kind=c.kind, request_n=n, phase=phase, in_progress=(phase == "진행 중"))
            self._card(c, "removed")
            return True

    # ---- 모델 사건 ----
    def on_model_event(self, ev) -> None:
        """`ModelSession` 의 `on_event` 로 연결한다(읽기 스레드에서 호출)."""
        with self._mu:
            e = self._inflight
            if isinstance(ev, TextDelta):
                if e is not None:
                    self._on_delta(e, ev.text)
            elif isinstance(ev, Result):
                if e is not None:
                    self._on_result(e, ev)
            elif isinstance(ev, Error):
                if e is not None and e.card.state != STATE_HIDDEN:
                    e.card.error = (ev.kind, ev.detail)
                    e.card.state = STATE_ERROR
                    self._card(e.card, "update")
            elif isinstance(ev, ControlResponse):
                if e is not None and e.interrupt_id and ev.request_id == e.interrupt_id:
                    self._cancel(e, ack=True)
            elif isinstance(ev, Compacting):
                self._notice("history_compacting", {})
            elif isinstance(ev, Compacted):
                self._composer.mark_restart()   # 압축 뒤 전사 전체와 사전 지식 이미지를 한 번 다시 보낸다(FR-8)
                self._emit("history_compacted", trigger=ev.trigger, pre_tokens=ev.pre_tokens, post_tokens=ev.post_tokens)
                self._notice("history_compacted", {"pre_tokens": ev.pre_tokens, "post_tokens": ev.post_tokens})
            elif isinstance(ev, ProcessExited):
                if not ev.expected:
                    self._on_exit(e)

    def _on_delta(self, e: _Entry, text: str) -> None:
        if e.first_token_mono is None:
            e.first_token_mono = self._clock()
            self._emit("first_token", request_n=e.card.n, latency_s=round(e.first_token_mono - (e.sent_mono or e.first_token_mono), 3),
                       hidden=e.card.state == STATE_HIDDEN)
        e.deltas.append(text)
        if e.card.state != STATE_HIDDEN:     # 숨긴 응답은 표시하지 않는다(AC-FR9-2 ⑤)
            full = "".join(e.deltas)
            c = e.card
            if c.kind == "트리거":
                # AC-FR9-22: 첫 줄이 끝나기 전에는 본문에 아무것도 보이지 않는다. 끝나면 판단 라벨을 표시하고
                # 본문은 둘째 줄부터이다. 판단 형식이 아니면 첫 줄을 본문 맨 앞에 두고 "미확인" 으로 표시한다.
                if not e.first_line_done:
                    if "\n" not in full:
                        return
                    e.first_line_done = True
                    c.judgment, c.judgment_subject, c.text = parse_judgment(full)
                    self._card(c, "update")
                    return
                if c.judgment == JUDGMENT_UNCONFIRMED:
                    c.text = full
                else:
                    c.text = full.partition("\n")[2].lstrip("\n")
            else:
                c.text = full
            self._card(c, "update")

    def _on_result(self, e: _Entry, r: Result) -> None:
        self._cancel(e, ack=True, hidden=True)
        c = e.card
        hidden = c.state == STATE_HIDDEN
        text = r.text or "".join(e.deltas)
        if r.ok:
            judgment = None
            if c.kind == "트리거":
                judgment, subject, text = parse_judgment(text)
                c.judgment, c.judgment_subject = judgment, subject
                self._emit("judgment", request_n=c.n, judgment=judgment, subject_chars=len(subject or ""))
            c.state = STATE_HIDDEN if hidden else STATE_DONE
            c.text, c.error = text, None
        else:
            c.state = STATE_HIDDEN if hidden else STATE_ERROR
            if c.error is None:
                c.error = (r.error_kind or "process_exit", r.terminal_reason or "")
        c.usage = dict(r.usage or {})
        done_s = round(self._clock() - (e.sent_mono or self._clock()), 3)
        self._emit("request_done", request_n=c.n, card_kind=c.kind, ok=r.ok, hidden=hidden, interrupted=e.interrupted,
                   terminal_reason=r.terminal_reason, stop_reason=r.stop_reason, done_s=done_s, usage=c.usage)
        if hidden:
            self._cards.pop(c.n, None)
        else:
            self._card(c, "update")
        self._inflight = None
        self._pump()

    def _on_exit(self, e: Optional[_Entry]) -> None:
        """예기치 않은 종료. 진행 중이던 요청은 오류이고 다음 요청은 `restart` 뒤에 보낸다."""
        self._needs_restart = True
        if e is None:
            self._schedule_auto_restart()
            return
        self._cancel(e, ack=True, hidden=True)
        c = e.card
        if c.state == STATE_HIDDEN:
            self._cards.pop(c.n, None)
        else:
            c.state = STATE_ERROR
            c.error = c.error or ("process_exit", _t("end.reasons_5"))
            self._card(c, "update")
        self._emit("request_done", request_n=c.n, card_kind=c.kind, ok=False, hidden=False, interrupted=e.interrupted,
                   terminal_reason="process_exit", stop_reason=None, done_s=None, usage={})
        self._inflight = None
        self._schedule_auto_restart()       # 종료 시점의 대기열이 "다음 요청" 이다(D-065 재수정)

    # ---- 숨긴 응답의 상한 · interrupt ----
    def _arm_hidden(self, e: _Entry) -> None:
        t = threading.Timer(self._hidden_limit, self._hidden_expired, args=(e,))
        t.daemon = True
        e.hidden_timer = t
        t.start()

    def _hidden_expired(self, e: _Entry) -> None:
        with self._mu:
            if self._closed or e is not self._inflight or e.card.state != STATE_HIDDEN or e.interrupted:
                return
            e.interrupted = True
            rid = self._session.interrupt()
            self._emit("request_interrupted", request_n=e.card.n, reason="숨긴 응답의 상한 초과",
                       limit_s=self._hidden_limit, interrupt_sent=rid is not None)
            if rid is None:     # 쓰지 못했다: 확인을 기다리지 않고 재시작한다
                threading.Thread(target=self.restart, args=("interrupt_failed",), daemon=True).start()
                return
            e.interrupt_id = rid
            t = threading.Timer(self._ack_s, self._ack_expired, args=(e,))
            t.daemon = True
            e.ack_timer = t
            t.start()

    def _ack_expired(self, e: _Entry) -> None:
        with self._mu:
            if self._closed or e is not self._inflight:
                return
        self.restart("interrupt_timeout")   # AC-FR9-18 ⒞: 기록한 PID 의 프로세스를 끝내고 새 PID 로 시작한다

    def _cancel(self, e: _Entry, ack: bool = False, hidden: bool = False) -> None:
        if hidden and e.hidden_timer is not None:
            e.hidden_timer.cancel()
            e.hidden_timer = None
        if ack and e.ack_timer is not None:
            e.ack_timer.cancel()
            e.ack_timer = None

    # ---- 재시작 ----
    def restart(self, reason: str) -> bool:
        """프로세스를 PID 로 끝내고 같은 설정으로 새로 시작한다. 재시작 뒤 첫 요청에 전사 전체와 사전 지식 이미지를 합친다."""
        with self._mu:
            if self._closed or self._restarting:
                return False
            self._restarting = True
            e = self._inflight
            old_pid = getattr(self._session, "pid", None)
            if e is not None:
                self._cancel(e, ack=True, hidden=True)
                c = e.card
                if c.state == STATE_HIDDEN:
                    self._cards.pop(c.n, None)
                else:
                    c.state = STATE_ERROR
                    c.error = c.error or ("process_exit", _t("req.restart_426"))
                    self._card(c, "update")
                self._emit("request_done", request_n=c.n, card_kind=c.kind, ok=False, hidden=c.state == STATE_HIDDEN,
                           interrupted=e.interrupted, terminal_reason="restart", stop_reason=None, done_s=None, usage={})
                self._inflight = None
        ok = False
        try:
            ok = bool(self._session.restart())   # 잠금 밖: 종료를 기다리는 동안 사건 콜백이 막히지 않게 한다
        finally:
            with self._mu:
                self._restarting = False
                self._needs_restart = not ok
                if ok:
                    self._composer.mark_restart()
                self._emit("request_restart", reason=reason, old_pid=old_pid, new_pid=getattr(self._session, "pid", None), ok=ok)
                self._notice("restarted", {"reason": reason, "ok": ok})
                self._pump()
        return ok

    def _schedule_auto_restart(self) -> bool:
        """잠금 안에서 호출한다. 재시작이 필요하고 대기열에 요청이 있으면(= 다음 요청) 자동 재시작을 예약한다
        (D-065 · 기능 정의 6절 process_exit). 예약했으면 True."""
        if (self._needs_restart and self._queue and not self._restarting and not self._auto_pending
                and self._inflight is None and not self._closed):
            self._auto_pending = True
            threading.Thread(target=self._auto_restart, daemon=True).start()
            return True
        return False

    def _auto_restart(self) -> None:
        """예기치 않은 종료 뒤 다음 요청에서 호출한다. 실패하면 대기 중인 카드를 오류로 끝내 재시도할 수 있게 한다."""
        try:
            ok = self.restart("process_exit")
        finally:
            with self._mu:
                self._auto_pending = False
        if ok:
            with self._mu:
                self._schedule_auto_restart()   # 재시작 직후의 전송 실패가 대기열을 남겼으면 다시 시도한다(요청마다 하나씩 소모)
            return
        with self._mu:
            if self._closed or self._restarting or not self._needs_restart:
                return      # 닫혔거나 다른 재시작이 진행 중이다: 대기 카드를 그대로 둔다
            while self._queue:
                e = self._queue.pop(0)
                c = e.card
                c.state, c.error = STATE_ERROR, ("process_exit", _t("err.restart_failed"))      # error_text.RESTART_FAILED 와 같은 값(D-109)
                self._emit("request_done", request_n=c.n, card_kind=c.kind, ok=False, hidden=False, interrupted=False,
                           terminal_reason="restart_failed", stop_reason=None, done_s=None, usage={})
                self._card(c, "update")

    def close(self) -> None:
        with self._mu:
            self._closed = True
            for e in list(self._cards.values()):
                self._cancel(e, ack=True, hidden=True)

    # ---- 내부 ----
    def _pump(self) -> None:
        """잠금 안에서 호출한다. 대기열의 맨 앞을 보낸 뒤, 캡처 처리가 끝났으면 보류한 트리거를 실행한다."""
        self._release_held()          # 보류한 트리거를 대기열의 질의보다 먼저 보낸다(D-115)
        self._pump_queue()

    def _pump_queue(self) -> None:
        """진행 중인 요청이 없고 재시작이 필요하지 않으면 대기열의 맨 앞을 보낸다."""
        if self._closed or self._inflight is not None or self._needs_restart or self._restarting:
            return
        while self._queue:
            e = self._queue[0]
            c, r = e.card, e.req
            now = self._clock()
            t_trig = r.t_trigger_mono if r.t_trigger_mono is not None else now
            partial = None
            if self._wants_final(r):
                t = self._composer.t
                left = t_trig + self._final_cap - now
                if e.waiter:
                    return                          # 확정을 기다리는 스레드가 다시 호출한다
                if t.open_for(t_trig) is not None and left > 0:
                    e.waiter = True
                    e.wait_start = now
                    self._emit("trigger_held", source="queue", reason="전사 처리 대기", action="waiting")
                    threading.Thread(target=self._wait_final, args=(e, t_trig, left), daemon=True).start()
                    return
                partial = t.partial_for(t_trig)     # 상한이 지났거나 확정 없이 끊긴 경우: 남은 잠정은 상한을 넘긴 것만 넣는다
            self._queue.pop(0)
            comp = self._composer.compose(r.kind, c.n, self._wall(), t_trig, selected=r.selected, user_text=r.input,
                                          images=r.images, partial=partial,
                                          final_wait_s=(now - e.wait_start) if e.wait_start is not None else 0.0)
            c.partial = (hms(comp.delta.partial[1]), hms(comp.delta.partial[2])) if comp.delta.partial else None
            if not self._session.send(comp.message):
                c.state, c.error = STATE_ERROR, ("process_exit", _t("req.pump_queue_427"))
                self._needs_restart = True
                self._emit("request_done", request_n=c.n, card_kind=c.kind, ok=False, hidden=False, interrupted=False,
                           terminal_reason="send_failed", stop_reason=None, done_s=None, usage={})
                self._card(c, "update")
                self._schedule_auto_restart()
                return
            self._composer.delivered(comp)
            c.dropped = tuple(comp.dropped)
            e.sent_mono = now
            c.state = STATE_ACTIVE
            self._inflight = e
            fields = dict(comp.log)
            fields.pop("request_n", None)
            fields.pop("kind", None)
            self._emit("request_sent", request_n=c.n, card_kind=r.kind, pid=getattr(self._session, "pid", None),
                       model=getattr(getattr(self._session, "init", None), "model", None),
                       selected=list(r.selected), input_sha256=hashlib.sha256(r.input.encode("utf-8")).hexdigest() if r.input else None,
                       queued_s=round(now - r.created_mono, 3), **fields)
            self._card(c, "update")
            return

    @staticmethod
    def _wants_final(r: Request) -> bool:
        """확정 대기와 `[잠정]` 줄은 마지막 30초를 입력으로 쓰는 요청에만 적용한다(FR-7): [고찰]과 선택한 조각이 없는 `/답변`."""
        return r.kind == "트리거" or (r.kind == "답변" and not r.selected)

    def _wait_final(self, e: _Entry, t_trig: float, left: float) -> None:
        try:
            self._composer.t.wait_final(t_trig, left, cut=self._cut)
        finally:
            with self._mu:
                e.waiter = False
                if not self._closed:
                    self._pump()

    def _card(self, c: Card, change: str) -> None:
        if self._on_card is not None:
            try:
                self._on_card(c.snapshot(), change)
            except Exception:
                pass

    def _notice(self, kind: str, info: dict) -> None:
        if self._on_notice is not None:
            try:
                self._on_notice(kind, info)
            except Exception:
                pass

    def _emit(self, type_: str, **fields) -> None:
        if self._log is not None:
            self._log.emit(type_, **fields)
