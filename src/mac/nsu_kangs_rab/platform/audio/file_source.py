"""`FileSource`: 음성 파일 입력의 시험 연결점 (기술 계획 5절 `--dev-audio-file` · `--dev-speed`).

16 kHz · 모노 · 16비트 WAV 만 읽는다(표준 `wave`). 다른 형식은 `on_state("중단", ...)` 를 낸다.
`speed` 1 이 실시간이고 0 이하나 `None` 이면 기다리지 않고 가능한 한 빨리 낸다. 배속은 블록이 도착하는 간격만 바꾼다.
블록의 `t_mono` 는 배속과 무관하게 시작 시각에 파일 위치(표본 수 / 16 kHz)를 더한 값이다(결정 D-063: 분할이 배속 1 과
같아지며, 배속에서 전사 시각은 파일 시각이다). 읽기가 끝나면 `on_state("종료", "eof")` 를 낸다.

시계와 일시 정지 (결정 0147 · 0150, 기능 정의 5-1절 "음성 파일 입력"):
  - 파일은 `start()` 전에 열지도 읽지도 않는다(`bytes_read` 0, `opened` False). `start()` 는 처음 [재생] 에서 호출되고, 시계는 그때 시작해
    벽시계(배속 지정이 있으면 그 배속)로 흐른다.
  - `pause()` 는 소리의 전달을 멈춘다(`on_block` 호출 없음, `on_state` 호출 없음). 시계는 계속 흐르고, 그 구간의 소리는 읽지 않고 버린다.
  - `resume()` 은 흐른 만큼 건너뛴 파일 위치부터 읽는다. 기다리지 않는 모드(`speed` 가 `None` 또는 0 이하)에서는 시계가 없으므로
    건너뛰지 않고 멈춘 자리에서 이어 읽는다. 건너뛴 위치가 파일 끝을 넘으면 `on_state("종료", "eof")` 이다.
  - `bytes_read` 는 파일에서 읽은 오디오 바이트의 합계이다(건너뛴 구간은 읽지 않으므로 세지 않는다). 시험의 관찰 수단이다(AC-FR3-17 · 18).
"""
from __future__ import annotations

import threading
import time
import wave
from typing import Callable, Optional

import numpy as np

from .types import SAMPLE_RATE, PcmBlock

BLOCK_S = 0.1


class FileSource:
    def __init__(self, path: str, speed: Optional[float] = 1.0, block_s: float = BLOCK_S,
                 mono: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 eventlog=None):
        self._log = eventlog
        self._path = path
        self._speed = speed
        self._block = max(1, int(SAMPLE_RATE * block_s))
        self._mono = mono
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._level = 0.0
        self._paused = False
        self._skip = False                 # `resume()` 직후 한 번: 흐른 만큼 건너뛴다
        self._deliver = threading.Lock()   # `on_block` 호출과 `pause()` 가 겹치지 않게 한다
        self._bytes_read = 0
        self._opened = False

    @property
    def bytes_read(self) -> int:
        return self._bytes_read

    @property
    def opened(self) -> bool:
        return self._opened

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """소리의 전달을 멈춘다. 반환한 뒤에는 `on_block` 이 호출되지 않는다. 시계는 흐른다."""
        with self._deliver:
            self._paused = True
            self._level = 0.0

    def resume(self) -> bool:
        """흐른 만큼 건너뛴 위치부터 다시 전달한다. 시작하지 않았거나 일시 정지가 아니면 False."""
        with self._deliver:
            if not self._paused or self._thread is None or self._stop.is_set():
                return False
            self._skip = True
            self._paused = False
            return True

    def level(self) -> float:
        return self._level

    def level_dbfs(self) -> float:
        """마지막 블록의 RMS 를 dBFS 로(하한 -120). `MicSource.level_dbfs` 와 같다."""
        return max(-120.0, 20.0 * float(np.log10(max(self._level, 1e-12))))

    def start(self, on_block, on_state=lambda state, detail="": None) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(on_block, on_state), name="file-source", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=5)

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, on_block, on_state) -> None:
        try:
            with wave.open(self._path, "rb") as w:
                self._opened = True
                if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE, 1, 2):
                    on_state("중단", "형식: 16 kHz · 모노 · 16비트 WAV 가 아니다")
                    return
                on_state("수집 중", "file")
                if self._log is not None:             # 처음 [재생] 의 "수집 시작" 1건 (AC-FR3-7 · 17). 파일 이름은 넣지 않는다
                    self._log.emit("capture_start", source="file", device="file", samplerate=SAMPLE_RATE, channels=1)
                t0 = self._mono()
                pos = 0
                total = w.getnframes()
                clocked = bool(self._speed and self._speed > 0)
                while not self._stop.is_set():
                    if self._paused:
                        self._sleep(0.02)                   # 일시 정지: 읽지 않는다. 시계는 흐른다
                        continue
                    if self._skip:
                        with self._deliver:
                            self._skip = False
                            if clocked:
                                target = int((self._mono() - t0) * self._speed * SAMPLE_RATE)
                                target = target // self._block * self._block
                                if target > pos:
                                    pos = min(target, total)
                                    w.setpos(pos)
                    raw = w.readframes(self._block)
                    if not raw:
                        break
                    self._bytes_read += len(raw)
                    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                    at = pos / SAMPLE_RATE
                    t_block = t0 + at                       # 파일 위치: 배속과 무관(D-063)
                    if clocked:
                        wait = t0 + at / self._speed - self._mono()   # 도착 시각만 배속에 따른다
                        if wait > 0:
                            self._sleep(wait)
                    with self._deliver:
                        if self._paused or self._skip or self._stop.is_set():
                            pos += x.size                    # 기다리는 사이에 일시 정지: 이 블록은 버린다
                            continue
                        self._level = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
                        on_block(PcmBlock(samples=x, t_mono=t_block))
                    pos += x.size
            on_state("종료", "eof")
        except (OSError, wave.Error, EOFError) as e:
            on_state("중단", "읽기 실패: %s" % type(e).__name__)
