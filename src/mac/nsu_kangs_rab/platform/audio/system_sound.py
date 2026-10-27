"""`SystemSoundSource`: 시스템 사운드 수집 (기술 계획 K-18, 결정 0064 6항: ScreenCaptureKit 오디오가 1차, BlackHole 은 대안).

수집은 보조 프로세스(`native/sck_audio.swift`, 원시 float32 · 인터리브 2채널 · 48 kHz 를 stdout 으로 낸다)가 하고,
이 파일은 그 프로세스를 `MicSource` 의 `backend` 규약(`mic_source.py` 머리 주석)에 맞춘다. 그래서 변환 · 레벨 ·
무음 감시 · 중단 감시 · 재시작 논리는 `MicSource` 의 것을 그대로 쓴다(한 스트림, AC-FR3-7).

- 보조 프로세스는 `subprocess` 로 직접 시작한다(`core/procs` 는 텍스트 모드 파이프라 이진 stdout 을 읽지 못한다). 시작한 PID 를
  `SckStream.pid` 에 기록하고 그 PID 로만 끝낸다: stdin 닫기 → 대기 → SIGTERM → 대기 → SIGKILL (이름으로 종료하지 않는다).
- 보조 프로세스가 끝나면 `finished()` 를 호출한다. 종료 코드와 stderr 한 줄 JSON 의 분류가 `last_error()` 에 남고
  `MicSource` 는 이를 `중단` 상태의 상세로 낸다(예: 화면 기록 권한 없음).
- 시스템 출력 장치가 바뀌어도 이 방식에서 스트림이 이어지는지는 M8-E2 가 잰다(블루투스 이어폰 준비 뒤).
- 앱 자신의 화면 기록 권한 창과 안내는 K-17 의 몫이다.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Mapping
from typing import Callable, Optional, Tuple

import numpy as np

from ...core.appstate import START_FAILED_PREFIX
from ...core.i18n import t
from .mic_source import MicSource

RATE = 48000
CHANNELS = 2
FRAME_BYTES = 4 * CHANNELS
CHUNK_FRAMES = 4800          # 0.1 s
DEVICE_NAME = "시스템 사운드"

# 보조 프로세스의 종료 코드 → 오류 분류 (native/sck_audio.swift 머리 주석)
EXIT_REASONS = {1: "start_failed", 2: "no_display", 3: "no_permission", 4: "stream_error"}
_REASON_KEYS = {
    "no_permission": "ctl.permission_screen_text",
    "no_display": "sysaudio.reason_text",
    "start_failed": "sysaudio.reason_text_2",
    "stream_error": "sysaudio.reason_text_3",
    "ended": "sysaudio.reason_text_4",
    "helper_missing": "sysaudio.reason_text_5",
}


class _ReasonText(Mapping):
    """오류 분류 → 표시 문구. 값은 조회할 때마다 문구 표에서 가져온다(언어는 init 뒤에 정해진다)."""

    def __getitem__(self, k):
        return t(_REASON_KEYS[k])

    def __iter__(self):
        return iter(_REASON_KEYS)

    def __len__(self):
        return len(_REASON_KEYS)


REASON_TEXT = _ReasonText()


# 시작 실패의 분류(기술 계획 2-2절 3항, 결정 0069): 중단 상세가 START_FAILED_PREFIX 로 시작하고 다시 시작하지 않는다.
START_FAILED_REASONS = frozenset({"helper_missing", "start_failed", "no_display"})
NO_RETRY_REASONS = START_FAILED_REASONS | {"no_permission"}


class SckStream:
    """보조 프로세스 하나. `start()` 에서 시작하고 읽기 스레드가 callback 을 호출한다."""

    def __init__(self, cmd, callback, finished, on_error, popen=subprocess.Popen,
                 stdin_wait_s: float = 1.0, term_wait_s: float = 2.0):
        self._cmd, self._callback, self._finished, self._on_error = cmd, callback, finished, on_error
        self._popen = popen
        self._stdin_wait_s, self._term_wait_s = stdin_wait_s, term_wait_s
        self.pid: Optional[int] = None
        self._p = None
        self._closing = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        try:
            self._p = self._popen(self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  bufsize=0)
        except OSError as e:                       # 실행 파일이 실행되지 않는다(권한 · 형식)
            self._on_error("start_failed", type(e).__name__)
            raise
        self.pid = self._p.pid
        self._thread = threading.Thread(target=self._read, name="sck-read", daemon=True)
        self._thread.start()

    def _read(self) -> None:
        p, buf = self._p, b""
        want = CHUNK_FRAMES * FRAME_BYTES
        try:
            while True:
                data = p.stdout.read(want)
                if not data:
                    break
                buf += data
                n = len(buf) // FRAME_BYTES * FRAME_BYTES
                if n:
                    x = np.frombuffer(buf[:n], dtype="<f4").reshape(-1, CHANNELS)
                    buf = buf[n:]
                    self._callback(x, None)
        except (OSError, ValueError):
            pass
        if self._closing:
            return
        code = None
        try:
            code = p.wait(timeout=2.0)
        except Exception:
            pass
        reason = EXIT_REASONS.get(code, "ended") if code else "ended"
        detail = ""
        try:
            err = p.stderr.read().decode("utf-8", "replace").strip().splitlines()
            if err:
                j = json.loads(err[-1])
                reason = j.get("error", reason)
                detail = str(j.get("detail", ""))   # 원래 오류 문자열(결정 0065 의 요청: 분류가 틀렸는지 K-17 실기에서 대조한다)
        except Exception:
            pass
        self._on_error(reason, detail)
        self._finished()

    def stop(self) -> None:
        pass

    def close(self) -> None:
        """기록한 PID 의 프로세스만 끝낸다."""
        p = self._p
        if p is None:
            return
        self._closing = True
        try:
            if p.stdin and not p.stdin.closed:
                p.stdin.close()
        except (OSError, ValueError):
            pass
        for sig, wait in ((None, self._stdin_wait_s), ("TERM", self._term_wait_s), ("KILL", 5.0)):
            if sig is not None and p.poll() is None:
                try:
                    (p.terminate if sig == "TERM" else p.kill)()
                except OSError:
                    pass
            try:
                p.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2.0)


class SckBackend:
    """`MicSource` 의 backend 규약. `helper_path` 는 `sck_audio.swift` 를 빌드한 실행 파일."""

    def __init__(self, helper_path: str, popen=subprocess.Popen, exists: Callable[[str], bool] = os.path.exists):
        self._helper, self._popen, self._exists = helper_path, popen, exists
        self._last_error: Optional[str] = None
        self.last_detail: str = ""     # 보조 프로세스가 낸 원래 오류 문자열. 이벤트 로그에는 넣지 않는다
        self.streams: list = []

    def default_input(self) -> Optional[Tuple[str, int, int]]:
        if not self._exists(self._helper):
            self._last_error = "helper_missing"
            return None
        return (DEVICE_NAME, RATE, CHANNELS)

    def open(self, callback, finished, device, samplerate, channels):
        self._last_error, self.last_detail = None, ""
        s = SckStream([self._helper], callback, finished, self._set_error, popen=self._popen)
        self.streams.append(s)
        return s

    def _set_error(self, reason: str, detail: str = "") -> None:
        self._last_error, self.last_detail = reason, detail

    def no_retry(self) -> bool:
        """다시 시작해도 같은 사유(`no_permission` · `helper_missing` · `start_failed` · `no_display`)이면 True 이다.
        `MicSource` 는 다시 열지 않는다(AC-FR3-11, D-056, 결정 0069). `stream_error` · `ended` 는 다시 시작한다."""
        return self._last_error in NO_RETRY_REASONS

    def last_error(self) -> Optional[str]:
        """사람이 읽는 마지막 오류 문구. 없으면 None. 시작 실패 사유는 `START_FAILED_PREFIX + ": " + 사유 문구` 이다
        (컨트롤러가 접두어로 `audio_start_failed` 를 분류하고 `": "` 뒤를 카드 상세로 쓴다)."""
        if not self._last_error:
            return None
        text = REASON_TEXT.get(self._last_error, self._last_error)
        if self._last_error in START_FAILED_REASONS:
            return "%s: %s" % (START_FAILED_PREFIX, text)
        return text


def SystemSoundSource(helper_path: str, eventlog=None, **kw) -> MicSource:
    """시스템 사운드를 수집하는 `AudioSource`. 인자는 `MicSource` 와 같다(`silence_s` · `stall_s` · `retry_s` ...)."""
    return MicSource(SckBackend(helper_path), eventlog=eventlog, source_name="system", **kw)


def build_helper(dest: str, swift_source: Optional[str] = None, run=subprocess.run) -> str:
    """`swiftc` 로 보조 프로그램을 빌드한다. 반환: dest. 배포 방식(미리 빌드해 넣을지)은 K-19 가 정한다."""
    src = swift_source or os.path.join(os.path.dirname(__file__), "native", "sck_audio.swift")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    run(["swiftc", "-O", src, "-o", dest], check=True)
    return dest
