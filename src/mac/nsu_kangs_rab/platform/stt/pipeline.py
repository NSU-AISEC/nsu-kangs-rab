"""`SttPipeline` (기술 계획 2-8절, 결정 0162 · 0166 ~ 0168): 수집 블록 → `stt_speech` 보조 프로세스 → 콜백.

구간 분할 · 환각 필터 · 전사 스레드는 없다. 엔진(SpeechTranscriber)이 구간을 정하고, 이 클래스는 `PcmBlock` 을 보조 프로세스의 stdin 으로
보내고(`A`), 끊기(`C`)와 끝(`Q`)을 보내고, stdout 줄을 콜백으로 낸다. 형식의 원본은 기술 계획 2-8-2절이다.

콜백(2-8-3절). 모두 `post` 로 배달한다(기본은 호출 스레드에서 직접).
- `on_segment(Segment)`: 확정(`final`). 도착한 뒤 바뀌지 않는다(FR-5). 본문이 비면 조각을 만들지 않고 `on_dropped(n)` 으로 알린다.
- `on_partial(PartialSegment)`: 잠정(`partial`). 표시 전용이며 기록하지 않는다. 같은 구간에서는 이전 잠정을 대체한다.
- `on_error(Error("stt_fail", …))`: 구간 하나의 실패(`error.kind` = `segment_failed`, 프로세스는 계속 돈다). 오류 횟수에 더하는 것은 이것뿐이다.
- `on_dropped(n)`: 구간이 조각 없이 끝났다는 통지 — 본문이 공백뿐인 `final` 이 왔다(`n` 은 소비한 번호). 앱은 열린 구간과 잠정 행을 닫는다.
  `segment_failed` 는 이것이 아니라 `on_error` 로만 낸다(결정 0168: 필터는 없다).
- `on_pending`: 호환을 위해 인자만 받고 호출하지 않는다(구현 정리 과제에서 뺀다).
- 아래 셋은 2-8-3절에 없는 추가 콜백이다(준비 표시와 종료 처리표를 위한 것이며 모두 선택이다).
  `on_asset(dict)`: `asset` 줄(`state` · `fraction` · `installed`). `on_ready()`: `ready` 줄.
  `on_exit(reason, detail)`: 보조 프로세스가 스스로 끝났을 때 한 번. `reason` ∈ unsupported_locale · asset_failed · analyzer_error · os_too_old
  (`stt_speech.classify_exit`). `detail` 은 `error` 줄의 `detail` 이다(경로 없음). `stop()` 으로 끝낸 경우에는 부르지 않는다.

스레드: 전송 스레드 하나(블록 큐 → stdin, 큐 순서가 곧 `A` · `C` · `Q` 의 순서)와 `SttSpeechProcess` 의 읽기 스레드. 수집 콜백은 큐에 넣기만 한다.

끊기(`C`)를 보내는 때: `pause()`(일시 정지, 결정 0147)와 `cut()`([고찰] · `/답변` 의 대기, `transcript.wait_final`). `stop()` 과 수집 중단에서는 보내지 않는다.
파일 입력이 끝나면(`on_state("종료", "eof")`) 꼬리 구간을 잃지 않도록 `C` 를 한 번 보내고 확정을 `drain_s` 까지 기다린 뒤 끝낸다(임의로 정함).
"""
from __future__ import annotations

import datetime as _dt
import queue
import threading
import unicodedata
import time
from typing import Callable, Optional, Sequence, Union

from ...core.types import Error, PartialSegment, Segment
from ..audio.types import PcmBlock
from .stt_speech import SttSpeechProcess, helper_command

_STOP = object()
_CUT = object()
_DRAIN = object()

DRAIN_S = 3.0          # 파일 입력이 끝난 뒤 꼬리 구간의 확정을 기다리는 상한(임의로 정함)


def _iso(dt: _dt.datetime) -> str:
    return dt.isoformat(timespec="milliseconds")


def _has_letter_or_digit(text: str) -> bool:
    """유니코드 범주 L(글자) 또는 N(숫자) 문자가 하나라도 있으면 참 (결정 0171 1항)."""
    return any(unicodedata.category(c)[0] in ("L", "N") for c in text)


class SttPipeline:
    def __init__(self, helper: Union[str, Sequence[str]], locale: str = "ko_KR", start_n: int = 1, eventlog=None,
                 post: Callable[[Callable[[], None]], None] = lambda f: f(),
                 mono: Callable[[], float] = time.monotonic,
                 wall_now: Callable[[], _dt.datetime] = lambda: _dt.datetime.now().astimezone(),
                 process_factory=SttSpeechProcess, drain_s: float = DRAIN_S, extra_args: Sequence[str] = ()):
        """`helper`: 실행 파일 경로(또는 앞에 붙일 명령 목록, 예: `[python, fake.py]`). `--locale <로캘> --start-n <n>` 을 덧붙이고
        `extra_args`(예: 가짜의 `--scenario <파일>`)를 그 뒤에 붙인다. `start_n`: [다시 시도] 때 이어서 매길 `n`."""
        prefix = [helper] if isinstance(helper, str) else list(helper)
        self._cmd = prefix[:-1] + helper_command(prefix[-1], locale, start_n) + list(extra_args)
        self._locale = locale
        self._start_n = int(start_n)
        self._log = eventlog
        self._post = post
        self._mono = mono
        self._wall_now = wall_now
        self._factory = process_factory
        self._drain_s = drain_s
        self._q: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._proc = None
        self._source = None
        self._cb: dict = {}
        self._wall0: Optional[_dt.datetime] = None
        self._mono0 = 0.0
        self._stopping = threading.Event()
        self._exited = threading.Event()
        self._begun = False
        self._lock = threading.Lock()
        self._ready = False
        self._draining = False
        self._open = False                    # 진행 중 구간이 있다(잠정을 받았고 확정은 아직 없다)
        self._first_partial_seen = False
        self._closed_open = threading.Event()  # 꼬리 대기 중 확정이 도착하면 켠다
        self._last_n = self._start_n - 1
        self._fatal_full = ""
        self._t_start = 0.0
        self.locales: Optional[list] = None   # 마지막 `locales` 줄

    # ---- 공개 ----
    @property
    def pid(self) -> Optional[int]:
        return getattr(self._proc, "pid", None)

    @property
    def next_n(self) -> int:
        """[다시 시도] 때 `start_n` 에 넘길 값: 이미 받은 마지막 `n` 의 다음."""
        return self._last_n + 1

    def start(self, audio_source, on_segment, on_pending=None, on_error=None, on_dropped=None, on_partial=None,
              begin: bool = True, on_asset=None, on_ready=None, on_exit=None) -> None:
        """보조 프로세스를 시작한다. `begin=False` 이면 소스는 `begin_capture()` 에서 시작한다(결정 0150: 처음 [재생] 에서 연다)."""
        self._source = audio_source
        self._cb = {"segment": on_segment, "partial": on_partial, "error": on_error, "dropped": on_dropped, "asset": on_asset,
                    "ready": on_ready, "exit": on_exit}
        self._wall0, self._mono0 = self._wall_now(), self._mono()
        self._t_start = self._mono()
        self._proc = self._factory(self._cmd, self._on_line, self._on_proc_exit, self._on_bad_line)
        try:
            self._proc.start()
        except OSError as e:                  # 실행 파일이 없다 등: 시작하지 못한 것도 같은 분류로 낸다
            self._exited.set()
            self._emit("stt_error", reason="analyzer_error", error=type(e).__name__)
            self._q.put(_STOP)                # 전송 스레드는 바로 끝난다
            self._deliver("exit", "analyzer_error", type(e).__name__)
        self._thread = threading.Thread(target=self._send_loop, name="stt-send", daemon=True)
        self._thread.start()
        if begin:
            self.begin_capture()

    def begin_capture(self) -> None:
        """소스를 시작한다(처음 [재생]). 시작에 실패하면 소스가 `on_state("중단", …)` 로 알린다."""
        if self._source is not None and not self._stopping.is_set() and not self._begun:
            self._begun = True
            self._source.start(self._on_block, self._on_state)

    def cut(self) -> None:
        """끊기 신호(`C`): 진행 중 구간을 지금 확정하게 한다. 이미 큐에 있는 음성 뒤에 간다. 진행 중 구간이 없으면 아무 일도 없다."""
        if not self._stopping.is_set():
            self._q.put(_CUT)

    def pause(self) -> None:
        """일시 정지: 소스를 닫고 진행 중 구간을 끊는다(`C`). 이미 맡긴 확정은 도착하는 대로 받는다 (결정 0147)."""
        if self._stopping.is_set() or not self._begun:
            return
        fn = getattr(self._source, "pause", None)
        if fn is not None:
            fn()
        self._q.put(_CUT)

    def resume(self) -> bool:
        """[재생]: 일시 정지 중인 소스를 다시 연다. 처음 [재생] 이면 `begin_capture()` 와 같다. 열지 못하면 False (소스가 상태로 알린다)."""
        if self._stopping.is_set():
            return False
        if not self._begun:
            self.begin_capture()
            return True
        fn = getattr(self._source, "resume", None)
        return bool(fn()) if fn is not None else False

    def stop(self) -> None:
        """수집을 멈추고 보조 프로세스를 끝낸다(`Q` → 닫기). `C` 를 보내지 않고 진행 중 구간은 쓰지 않는다. 이미 끝났으면 아무것도 하지 않는다."""
        if self._stopping.is_set():
            return
        self._stopping.set()
        if self._source is not None:
            self._source.stop()
        self._q.put(_STOP)

    def join(self, timeout: Optional[float] = None) -> bool:
        t = self._thread
        if t is None:
            return True
        t.join(timeout)
        return not t.is_alive()

    # ---- 수집 콜백 (복사 없이 큐에 넣기만) ----
    def _on_block(self, block: PcmBlock) -> None:
        if not self._stopping.is_set():
            self._q.put(block)

    def _on_state(self, state: str, detail: str = "") -> None:
        if state != "종료" or self._stopping.is_set():
            return
        if detail == "eof":
            self._q.put(_DRAIN)               # 파일 입력의 끝: 꼬리 구간을 확정시키고 끝낸다
        else:
            self._stopping.set()
            self._q.put(_STOP)

    # ---- 전송 스레드 ----
    def _send_loop(self) -> None:
        proc = self._proc
        while True:
            b = self._q.get()
            if b is _STOP:
                break
            if b is _DRAIN:
                self._draining = True
                self._stopping.set()
                self._closed_open.clear()
                if self._open and proc.send_cut():
                    self._closed_open.wait(self._drain_s)
                break
            if b is _CUT:
                proc.send_cut()
                continue
            proc.send_audio(b.t_mono, b.samples)
        if not self._exited.is_set():
            proc.send_quit()
        proc.close()

    # ---- 보조 프로세스의 줄 ----
    def _wall(self, mono: float) -> str:
        return _iso(self._wall0 + _dt.timedelta(seconds=mono - self._mono0))

    def _deliver(self, name: str, *args) -> None:
        fn = self._cb.get(name)
        if fn is None:
            return

        def call():
            try:
                fn(*args)
            except Exception:  # 호출자의 콜백 오류가 읽기 스레드를 멈추지 않게 한다
                pass
        self._post(call)

    def _emit(self, type_: str, **fields) -> None:
        if self._log is not None:
            self._log.emit(type_, **fields)

    def _on_bad_line(self, raw: bytes) -> None:
        self._emit("stt_error", reason="bad_line")

    def _on_line(self, d: dict) -> None:
        t = d.get("type")
        if t == "locales":
            lst = d.get("list")
            if isinstance(lst, list):
                self.locales = [str(x) for x in lst]
        elif t == "asset":
            if "installed" in d:
                self._emit("stt_asset", phase="start", locale=self._locale, installed=bool(d.get("installed")))
            fields = {"phase": "state", "locale": self._locale, "state": d.get("state")}
            if d.get("fraction") is not None:
                fields["fraction"] = d.get("fraction")
            for k in ("completed", "total", "indeterminate"):      # Q-52: D-182 를 기록으로 확인하는 진단 필드
                if d.get(k) is not None:
                    fields[k] = d.get(k)
            self._emit("stt_asset", **fields)
            self._deliver("asset", dict(d))
        elif t == "ready":
            self._ready = True
            self._emit("stt_asset", phase="ready", locale=self._locale, elapsed_s=round(self._mono() - self._t_start, 3))
            self._deliver("ready")
        elif t == "partial":
            if self._stopping.is_set() and not self._draining:
                return
            text = str(d.get("text", ""))
            s, e = float(d.get("start_mono", 0.0)), float(d.get("end_mono", 0.0))
            self._open = True
            if not self._first_partial_seen:
                self._first_partial_seen = True
                self._emit("stt_partial_first", latency_s=round(self._mono() - s, 3))
            self._deliver("partial", PartialSegment(text, s, e))
        elif t == "final":
            self._open = False
            self._first_partial_seen = False
            self._closed_open.set()
            n = int(d.get("n", self._last_n + 1))
            self._last_n = max(self._last_n, n)
            text = str(d.get("text", "")).strip()
            s, e = float(d.get("start_mono", 0.0)), float(d.get("end_mono", 0.0))
            if not _has_letter_or_digit(text):
                # 결정 0171 1항: 공백뿐이거나 글자·숫자(유니코드 L · N 범주)가 하나도 없는 확정("." · "?!" 등)은 조각이 아니다.
                # 본문은 기록하지 않는다(글자 수와 사유만).
                self._emit("stt_dropped", n=n, chars=len(text), reason="empty" if not text else "no_letter_digit")
                self._deliver("dropped", n)
                return
            seg = Segment(n=n, start_wall=self._wall(s), end_wall=self._wall(e), start_mono=s, end_mono=e, text=text)
            self._emit("segment_arrived", n=n, start_mono=s, end_mono=e, chars=len(text),
                       latency_s=round(self._mono() - e, 3))
            self._deliver("segment", seg)
        elif t == "error":
            kind = str(d.get("kind", ""))
            if kind == "segment_failed":
                self._open = False
                self._first_partial_seen = False
                self._closed_open.set()
                fields = {"reason": "segment_failed"}
                if d.get("full"):
                    fields["error"] = str(d["full"])
                self._emit("stt_error", **fields)
                self._deliver("error", Error("stt_fail", "segment_failed"))
            else:
                self._fatal_full = str(d.get("full") or d.get("detail") or "")

    def _on_proc_exit(self, reason: str, code, detail: str) -> None:
        """읽기 스레드에서: 보조 프로세스가 스스로 끝났다(`close()` 로 끝낸 경우는 오지 않는다)."""
        self._exited.set()
        self._closed_open.set()
        if reason == "ended":
            return
        full = self._fatal_full or detail
        if not self._ready and not self._stopping.is_set():
            self._emit("stt_asset", phase="failed", locale=self._locale, kind=reason, error=full,
                       elapsed_s=round(self._mono() - self._t_start, 3))
        fields = {"reason": reason}
        if full:
            fields["error"] = full
        self._emit("stt_error", **fields)
        self._q.put(_STOP)                    # 전송 스레드를 끝낸다 (이미 끝난 프로세스에는 보내지 않는다)
        self._deliver("exit", reason, detail)
