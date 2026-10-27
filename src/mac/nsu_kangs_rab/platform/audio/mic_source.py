"""`MicSource`: 시스템 마이크(기본 입력 장치) 수집 (기술 계획 2-4절 audio.py, K-10).

장치를 여는 부분은 `backend` 로 분리했다. 이 파일의 논리(변환 · 레벨 · 무음 감시 · 중단 감시 · 기본 장치 변경 추적 · 재시작)는
가짜 `backend` 로 시험한다. 실제 장치는 `SoundDeviceBackend` 만 연다.

`backend` 의 규약:
    default_input() -> (이름, 기본 샘플링 속도, 채널 수) 또는 None (기본 입력 장치 없음)
    open(callback, finished, device, samplerate, channels) -> 스트림(start() · stop() · close())
    callback(indata: ndarray[frames, channels], status) 는 PortAudio 스레드에서 호출되며 큐에 넣기만 한다.
    finished() 는 스트림이 끝났을 때(장치 분리 등) 호출된다.

상태(`on_state(state, detail)`): `수집 중` · `입력 없음` · `중단` · `장치 변경` · `종료`.
  - `입력 없음`: 입력 RMS(16 kHz 로 변환한 뒤의 블록 값) 가 `SILENCE_DBFS`(-80 dBFS) 이하인 상태가 `silence_s`(10초) 연속되었다 (AC-FR3-2, A-10).
    기준을 넘는 블록이 오면 곧바로 `수집 중` 으로 돌아온다(블록 단위 판정이므로 2초 안이다).
  - `중단`: 블록이 `stall_s` 동안 오지 않았거나, 스트림이 끝났거나, 열기에 실패했거나, 기본 장치가 없다 (AC-FR3-3).
    `retry_s` 간격으로 다시 열며, 열리면 `수집 중`. 복구할 때까지 계속 시도한다(앱은 종료하지 않는다).
    예외: 백엔드가 `no_retry()` 로 True 를 내면(보조 프로세스의 종료 코드 3 `no_permission`, AC-FR3-11, 그리고 시작 실패:
    보조 프로그램 없음 · 종료 코드 1 · 2, 결정 0069) 열기 · 끝남 · 기본 장치 없음 어느 경우에도 다시 열지 않는다.
    이 상태는 `stop()` 까지 이어지며 `중단` 의 상세에 사유가 있다.
  - `장치 변경`: 기본 입력 장치의 이름이나 속도가 바뀌어 새 장치로 다시 열었다 (AC-FR3-8).
이벤트 로그(`eventlog.emit`): `capture_start`(source · device · samplerate · channels) · `device_change`(from · to) ·
`capture_stalled`(reason) · `capture_open_failed`(error_class). 본문 · 오디오는 넣지 않는다.
한 인스턴스에서 스트림은 하나뿐이다 (`start()` 를 두 번 불러도 두 번째는 무시한다, AC-FR3-7).

일시 정지 (결정 0147 · 0150): `start()` 가 처음 [재생] 에서 장치(보조 프로세스)를 연다. `pause()` 는 장치를 닫고(보조 프로세스는
기록한 PID 로 끝나고 운영체제의 마이크 사용 표시가 꺼진다) 들어오던 블록을 버리며, `on_state` 를 부르지 않는다(상태는 호출한 쪽이
"일시 정지" 로 보인다). `resume()` 은 처음 [재생] 과 같은 경로(`_open`)로 다시 열고 `capture_start` 사건을 더하지 않는다(AC-FR3-7).
다시 열기에 실패하면 `start()` 의 실패와 같이 `on_state("중단", 상세)` 를 내고 `False` 를 반환한다. 권한 없음(`no_retry`)이면 `중단` 이
`stop()` 까지 이어진다. 무음은 다시 열 때 처음부터 센다(AC-FR3-15).
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional, Tuple

import numpy as np

from ...core.appstate import START_FAILED_PREFIX
from ...core.i18n import t
from .resampler import TARGET, Resampler
from .types import SAMPLE_RATE, PcmBlock

SILENCE_DBFS = -80.0          # A-10: 이 값 이하의 RMS 가 `silence_s` 연속이면 무음이다
SILENCE_RMS = 10 ** (SILENCE_DBFS / 20)
DBFS_FLOOR = -120.0           # `level_dbfs()` 의 하한(무음 0 의 값)


class SoundDeviceBackend:
    """PortAudio(sounddevice) 위의 실제 장치 열기. 시험에서는 쓰지 않는다 (장치 잠금 아래에서만 연다)."""

    def default_input(self) -> Optional[Tuple[str, int, int]]:
        import sounddevice as sd
        try:
            info = sd.query_devices(None, "input")
        except Exception:
            return None
        return (str(info["name"]), int(info["default_samplerate"]), max(1, min(int(info["max_input_channels"]), 2)))

    def open(self, callback, finished, device, samplerate, channels):
        import sounddevice as sd
        return sd.InputStream(device=None, samplerate=samplerate, channels=channels, dtype="float32",
                              callback=lambda indata, frames, t, status: callback(indata, status),
                              finished_callback=finished)


class MicSource:
    def __init__(self, backend=None, eventlog=None, source_name: str = "mic", silence_s: float = 10.0,
                 stall_s: float = 5.0, retry_s: float = 2.0, poll_s: float = 1.0, tick_s: float = 0.2,
                 mono: Callable[[], float] = time.monotonic):
        self._backend = backend or SoundDeviceBackend()
        self._log = eventlog
        self._source = source_name
        self._silence_s, self._stall_s, self._retry_s, self._poll_s, self._tick_s = silence_s, stall_s, retry_s, poll_s, tick_s
        self._mono = mono
        self._q: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._on_block = None
        self._on_state = None
        self._stream = None
        self._device: Optional[Tuple[str, int, int]] = None
        self._rs: Optional[Resampler] = None
        self._level = 0.0
        self._reset_run()
        self._state = None
        self._last_poll = 0.0
        self._next_retry: Optional[float] = None
        self._halted = False                  # 다시 열지 않는 중단(예: 권한 없음)
        self._paused = False
        self._ever_opened = False             # 처음 열기에 성공했는지: 다시 열 때 `capture_start` 를 더하지 않는 기준
        self._gen = 0                         # 열 때마다 늘린다: 닫힌 스트림이 뒤늦게 넣은 블록 · 끝남을 버린다
        self._io = threading.RLock()          # 논리 한 번(블록 처리 · 점검)과 `pause` · `resume` 이 겹치지 않게 한다

    # ---- AudioSource ----
    def level(self) -> float:
        """마지막 블록의 RMS (0..1)."""
        return self._level

    def level_dbfs(self) -> float:
        """마지막 블록의 RMS 를 dBFS 로(하한 `DBFS_FLOOR`). 레벨 막대 `level_to_cells` 의 입력이다(AC-FR3-10)."""
        return max(DBFS_FLOOR, 20.0 * float(np.log10(max(self._level, 1e-12))))

    def start(self, on_block, on_state=lambda state, detail="": None) -> None:
        with self._lock:
            if self._thread is not None:
                return  # 스트림은 하나뿐이다
            self._on_block, self._on_state = on_block, on_state
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="mic-source", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=5)

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """장치를 닫고 블록을 버린다(결정 0147). 시작하지 않았거나 이미 일시 정지이면 아무것도 하지 않는다. `on_state` 를 부르지 않는다."""
        with self._io:
            if self._thread is None or self._paused or self._stop.is_set():
                return
            self._paused = True
            self._close()
            self._gen += 1
            self._drain()
            self._level = 0.0
            self._state = None
            self._next_retry = None
            self._halted = False
            self._reset_run()

    def resume(self) -> bool:
        """일시 정지에서 다시 연다(처음 [재생] 과 같은 `_open`, `capture_start` 사건 없음). 열었으면 True.
        실패하면 `on_state("중단", 상세)` 를 내고 False 이다(결정 0147 ⑦). 일시 정지가 아니면 False."""
        with self._io:
            if not self._paused or self._stop.is_set():
                return False
            self._paused = False
            self._state = None
            return self._open(self._mono(), announce=not self._ever_opened)

    def _drain(self) -> None:
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    # ---- 내부: 논리 (시험에서 직접 호출) ----
    def _reset_run(self) -> None:
        self._anchor: Optional[float] = None  # 출력 표본 0 의 단조 시각
        self._out_samples = 0
        self._quiet_since: Optional[float] = None   # 기준 이하가 이어지기 시작한 입력 시간(출력 표본 수 / 16 kHz)
        self._silent = False
        self._last_block_mono: Optional[float] = None
        self._attempt = False

    def _emit_log(self, type_: str, **f) -> None:
        if self._log is not None:
            self._log.emit(type_, **f)

    def _set_state(self, state: str, detail: str = "") -> None:
        if state == self._state and state in ("입력 없음", "중단"):
            return
        self._state = state
        if self._on_state is not None:
            try:
                self._on_state(state, detail)
            except Exception:
                pass

    def _open(self, now: float, changed_from: Optional[str] = None, announce: bool = True, attempt: bool = True) -> bool:
        """`attempt`: [재생] 의 시도(처음 시작 · 재개)로 여는가. 소스가 스스로 다시 여는 자동 재시도는 False (D-195)."""
        dev = self._backend.default_input()
        if dev is None:
            self._emit_log("capture_stalled", reason="no_default_device")
            why = getattr(self._backend, "last_error", lambda: None)()
            self._set_state("중단", why or t("mic.open_428"))
            if self._no_retry():
                self._halted = True          # 보조 프로그램 없음 등: 다시 시도해도 같다(결정 0069)
                return False
            self._next_retry = now + self._retry_s
            return False
        name, rate, ch = dev
        try:
            self._gen += 1
            gen = self._gen
            stream = self._backend.open(lambda indata, status: self._callback(indata, status, gen),
                                        lambda: self._finished(gen), name, rate, ch)
            stream.start()
        except Exception as e:  # 권한 · 장치 오류. 앱은 종료하지 않는다
            self._emit_log("capture_open_failed", error_class=type(e).__name__)
            why = getattr(self._backend, "last_error", lambda: None)()
            self._set_state("중단", why or t("mic.open_429") % type(e).__name__)
            if self._no_retry():
                self._halted = True
                return False
            self._next_retry = now + self._retry_s
            return False
        self._stream, self._device = stream, dev
        self._ever_opened = True
        self._rs = Resampler(rate)
        self._reset_run()
        # 결정 0091 M2 (D-193): [재생] 의 시도로 연 스트림은 첫 음성 블록이 오기 전에는 정지 감시를 하지 않고 자동으로 다시 시작하지 않는다
        # (`_last_block_mono` 를 None 으로 둔다). 시도에는 시간 제한이 없다. 스트림 종료는 시작 실패로 알린다(D-194, `_handle_finished`).
        # 소스가 스스로 다시 연 스트림(자동 재시도, D-195)은 b56 이전대로 열린 직후의 유예를 두고 정지 감시를 한다.
        self._attempt = attempt
        self._last_block_mono = None if attempt else now
        self._last_poll = now
        self._next_retry = None
        if announce:
            self._emit_log("capture_start", source=self._source, device=name, samplerate=rate, channels=ch)
        if changed_from is not None:
            self._set_state("장치 변경", "%s → %s" % (changed_from, name))
        self._state = None  # 다음 블록에서 `수집 중` 을 낸다
        return True

    def _close(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            for fn in ("stop", "close"):
                try:
                    getattr(s, fn)()
                except Exception:
                    pass

    def _callback(self, indata, status, gen=None) -> None:  # PortAudio 스레드: 복사하고 넣기만 한다
        self._q.put(("block", np.array(indata, dtype=np.float32, copy=True), self._gen if gen is None else gen))

    def _finished(self, gen=None) -> None:
        self._q.put(("finished", None, self._gen if gen is None else gen))

    def _handle_block(self, indata: np.ndarray, now: float) -> None:
        self._last_block_mono = now
        self._attempt = False               # 첫 블록을 받았다: 시도가 끝났다
        if self._rs is None:
            return
        y = self._rs.process(indata)
        if y.size == 0:
            return
        if self._anchor is None:
            self._anchor = now - y.size / SAMPLE_RATE
        t_block = self._anchor + self._out_samples / SAMPLE_RATE
        self._out_samples += y.size
        rms = float(np.sqrt(np.mean(y.astype(np.float64) ** 2)))
        self._level = rms
        in_time = self._out_samples / SAMPLE_RATE
        if self._state in (None, "장치 변경"):
            self._set_state("수집 중", self._device[0] if self._device else "")
        if rms > SILENCE_RMS:
            self._quiet_since = None
            if self._silent:
                self._silent = False
                self._set_state("수집 중", "level changed")
        else:
            if self._quiet_since is None:
                self._quiet_since = in_time - y.size / SAMPLE_RATE      # 이 블록의 시작
            if not self._silent and in_time - self._quiet_since >= self._silence_s:
                self._silent = True
                self._set_state("입력 없음", t("mic.handle_block_431") % (SILENCE_DBFS, self._silence_s))
        if self._on_block is not None:
            try:
                self._on_block(PcmBlock(samples=y, t_mono=t_block))
            except Exception:
                pass

    def _check(self, now: float) -> None:
        """주기 점검: 재시도, 중단(입력 끊김), 기본 장치 변경."""
        if self._halted:
            return
        if self._stream is None:
            if self._next_retry is None or now >= self._next_retry:
                self._open(now, attempt=False)
            return
        if self._last_block_mono is not None and now - self._last_block_mono >= self._stall_s:
            self._emit_log("capture_stalled", reason="no_blocks")
            self._set_state("중단", t("mic.check_432") % self._stall_s)
            self._close()
            self._next_retry = now + self._retry_s
            return
        if now - self._last_poll >= self._poll_s:
            self._last_poll = now
            cur = self._backend.default_input()
            if cur is None:
                self._emit_log("capture_stalled", reason="no_default_device")
                self._set_state("중단", t("mic.open_428"))
                self._close()
                self._next_retry = now + self._retry_s
            elif self._device is not None and cur[:2] != self._device[:2]:
                old = self._device[0]
                self._emit_log("device_change", **{"from": old, "to": cur[0]})
                self._close()
                self._open(now, changed_from=old, attempt=False)

    def _no_retry(self) -> bool:
        return bool(getattr(self._backend, "no_retry", lambda: False)())

    def _handle_finished(self, now: float) -> None:
        self._emit_log("capture_stalled", reason="stream_finished")
        why = getattr(self._backend, "last_error", lambda: None)()   # 백엔드가 알려 주는 끝난 까닭(예: 권한 없음)
        before_first = self._attempt                                 # [재생] 의 시도가 첫 음성 블록 전에 끝났는가(자동 재시도는 해당 없음)
        detail = why or t("mic.handle_finished_433")
        if before_first and not detail.startswith(START_FAILED_PREFIX) and not self._no_retry():
            # 결정 0178 · D-194: 첫 블록 전에 권한이 아닌 까닭(종료 코드 4 · 0 등)으로 끝난 시도는 수집 시작 실패와 같다.
            # 상태 알림의 중단 상세를 `START_FAILED_PREFIX + ": " + 사유` 로 내고(컨트롤러가 audio_start_failed 로 분류) 다시 시작하지 않는다.
            detail = "%s: %s" % (START_FAILED_PREFIX, detail)
        self._set_state("중단", detail)
        self._close()
        if before_first:
            self._halted = True              # 첫 블록 전에 끝난 스트림은 자동으로 다시 시작하지 않는다(첫 블록 뒤의 종료는 그대로 재시작)
            return
        if self._no_retry():
            self._halted = True              # 권한 없음 · 시작 실패 등: 다시 시작하지 않는다(AC-FR3-11, 결정 0069)
            return
        self._next_retry = now + self._retry_s

    def _run(self) -> None:
        try:
            with self._io:
                if not self._paused:             # 시작 직후 `pause()` 가 먼저 들어온 경우 열지 않는다
                    self._open(self._mono())
            while not self._stop.is_set():
                try:
                    kind, data, gen = self._q.get(timeout=self._tick_s)
                except queue.Empty:
                    kind, gen = None, self._gen
                with self._io:
                    if self._paused:
                        continue                 # 일시 정지 중: 수집 오류도 감시하지 않는다(결정 0147 ⑦)
                    now = self._mono()
                    if gen != self._gen:
                        kind = None              # 닫힌 스트림의 뒤늦은 블록 · 끝남
                    if kind == "block":
                        self._handle_block(data, now)
                    elif kind == "finished":
                        self._handle_finished(now)
                    self._check(now)
        finally:
            self._close()
            self._set_state("종료", "stop")
