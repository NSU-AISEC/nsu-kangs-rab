"""`stt_speech` 보조 프로세스 (기술 계획 2-8절, 결정 0162 · 0166 ~ 0168): 프로세스 수명 · 프레임 송신 · 줄 해석.

보조 프로세스(`native/stt_speech.swift`)는 SpeechAnalyzer + SpeechTranscriber 로 전사한다. 이 파일은 그 프로세스를 시작하고,
`PcmBlock` 을 stdin 프레임으로 보내고, stdout 의 JSON 줄을 읽어 콜백으로 낸다. 형식의 원본은 기술 계획 2-8-2절이다.

- 프레임(stdin): 1바이트 종류 + 4바이트 길이(little-endian) + 본문. `A` = float64 `t_mono` + float32 표본, `C` = 끊기, `Q` = 끝.
- 줄(stdout): `type` ∈ locales · asset · ready · partial · final · error. 해석할 수 없는 줄은 `on_bad_line` 으로 알리고 무시한다.
- 종료 분류(2-8-4절 5항): `error` 줄이 있었으면 그 `kind`, 없으면 종료 코드. 종료 코드 0 인데 `Q` 를 보내지 않았거나, 신호로 끝났거나,
  stdout 이 닫힌 경우는 `analyzer_error` 와 같이 취급한다.
- 시작한 PID 를 `pid` 에 기록하고 그 PID 로만 끝낸다: stdin 닫기 → 대기 → SIGTERM → 대기 → SIGKILL. 이름으로 종료하지 않는다.
- `subprocess` 를 직접 쓴다(`core/procs` 는 텍스트 모드 파이프이고 프레임은 이진이다. `system_sound.SckStream` 과 같다).
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import threading
from typing import Callable, Optional

import numpy as np

# 종료 코드 → 사유 (native/stt_speech.swift 머리 주석)
EXIT_REASONS = {1: "unsupported_locale", 2: "asset_failed", 3: "analyzer_error", 4: "os_too_old"}
FATAL_KINDS = frozenset(EXIT_REASONS.values())
LINE_TYPES = frozenset({"locales", "asset", "ready", "partial", "final", "error"})

_HEADER = struct.Struct("<BI")
_T = struct.Struct("<d")


def frame(kind: bytes, body: bytes = b"") -> bytes:
    """stdin 프레임 하나."""
    return _HEADER.pack(kind[0], len(body)) + body


def audio_frame(t_mono: float, samples: np.ndarray) -> bytes:
    """`A` 프레임: float64 `t_mono` + float32 표본(little-endian)."""
    return frame(b"A", _T.pack(float(t_mono)) + np.asarray(samples, dtype="<f4").tobytes())


CUT_FRAME = frame(b"C")
QUIT_FRAME = frame(b"Q")


def parse_line(raw: bytes | str) -> Optional[dict]:
    """JSON 줄 하나를 해석한다. 객체가 아니거나 `type` 이 알려진 것이 아니면 None."""
    try:
        d = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(d, dict) or d.get("type") not in LINE_TYPES:
        return None
    return d


def classify_exit(code: Optional[int], error_kind: Optional[str], sent_quit: bool) -> str:
    """종료의 사유. `error` 줄의 `kind`(치명 종류)가 있으면 그것, 없으면 종료 코드이다. 알 수 없는 것은 `analyzer_error`.
    `code` 0 인데 `Q` 를 보내지 않았거나(`sent_quit` False), 음수(신호)이거나, None(코드를 읽지 못함)이면 `analyzer_error`.
    정상 종료(`Q` 를 보낸 뒤 0)는 `"ended"` 이다."""
    if error_kind in FATAL_KINDS:
        return error_kind
    if code == 0 and sent_quit:
        return "ended"
    if code in EXIT_REASONS:
        return EXIT_REASONS[code]
    return "analyzer_error"


def helper_command(helper_path: str, locale: str, start_n: int = 1) -> list:
    return [helper_path, "--locale", locale, "--start-n", str(int(start_n))]


def build_helper(dest: str, swift_source: Optional[str] = None, run=subprocess.run) -> str:
    """`swiftc` 로 보조 프로세스를 빌드한다(`-parse-as-library`: `@main`). 반환: dest."""
    src = swift_source or os.path.join(os.path.dirname(__file__), "native", "stt_speech.swift")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    run(["swiftc", "-O", "-parse-as-library", src, "-o", dest], check=True)
    return dest


def list_locales(cmd: list, timeout_s: float = 5.0, popen=subprocess.Popen) -> Optional[list]:
    """설정 창용 일회성 실행(`--list-locales`). `locales` 줄의 목록을 반환한다. 시간이 지나거나 실패하면 None (호출한 쪽은 모든 언어를
    선택할 수 있게 둔다). 시간이 지나면 그 PID 만 끝낸다."""
    try:
        p = popen(list(cmd) + ["--list-locales"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    try:
        out, _ = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            p.communicate(timeout=2.0)
        except Exception:
            pass
        return None
    if p.returncode != 0:
        return None
    for raw in out.splitlines():
        d = parse_line(raw)
        if d and d["type"] == "locales" and isinstance(d.get("list"), list):
            return [str(x) for x in d["list"]]
    return None


class SttSpeechProcess:
    """보조 프로세스 하나. `start()` 에서 시작하고 읽기 스레드가 줄마다 `on_line` 을 호출한다.

    `on_line(dict)`: 해석된 줄. `on_bad_line(raw)`: 해석할 수 없는 줄(무시한다). `on_exit(reason, code, detail)`: 프로세스가 끝났을 때 한 번
    (`reason` 은 `classify_exit`, `detail` 은 마지막 `error` 줄의 `detail`). `close()` 로 끝낸 경우에는 호출하지 않는다.
    """

    def __init__(self, cmd, on_line: Callable[[dict], None], on_exit: Callable[[str, Optional[int], str], None],
                 on_bad_line: Optional[Callable[[bytes], None]] = None, popen=subprocess.Popen,
                 stdin_wait_s: float = 3.0, term_wait_s: float = 2.0):
        self._cmd, self._on_line, self._on_exit, self._on_bad = list(cmd), on_line, on_exit, on_bad_line
        self._popen = popen
        self._stdin_wait_s, self._term_wait_s = stdin_wait_s, term_wait_s
        self.pid: Optional[int] = None
        self._p = None
        self._closing = False
        self._sent_quit = False
        self._wlock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._error_kind: Optional[str] = None
        self._error_detail = ""

    def start(self) -> None:
        self._p = self._popen(self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.pid = self._p.pid
        self._thread = threading.Thread(target=self._read, name="stt-speech-read", daemon=True)
        self._thread.start()

    # ---- 송신 ----
    def _write(self, data: bytes) -> bool:
        p = self._p
        if p is None or p.stdin is None:
            return False
        with self._wlock:
            try:
                p.stdin.write(data)
                return True
            except (OSError, ValueError):        # 보조 프로세스가 끝났다: 읽기 스레드가 종료를 처리한다
                return False

    def send_audio(self, t_mono: float, samples: np.ndarray) -> bool:
        return self._write(audio_frame(t_mono, samples))

    def send_cut(self) -> bool:
        return self._write(CUT_FRAME)

    def send_quit(self) -> bool:
        self._sent_quit = True
        return self._write(QUIT_FRAME)

    # ---- 수신 ----
    def _read(self) -> None:
        p = self._p
        try:
            for raw in iter(p.stdout.readline, b""):
                raw = raw.strip()
                if not raw:
                    continue
                d = parse_line(raw)
                if d is None:
                    if self._on_bad:
                        self._on_bad(raw)
                    continue
                if d["type"] == "error":
                    k = d.get("kind")
                    if k in FATAL_KINDS:
                        self._error_kind, self._error_detail = k, str(d.get("detail", ""))
                self._on_line(d)
        except (OSError, ValueError):
            pass
        if self._closing:
            return
        code = None
        try:
            code = p.wait(timeout=5.0)
        except Exception:
            pass
        self._release_pipes()
        self._on_exit(classify_exit(code, self._error_kind, self._sent_quit), code, self._error_detail)

    def _release_pipes(self) -> None:
        p = self._p
        for f in (getattr(p, "stdin", None), getattr(p, "stdout", None)):
            try:
                if f is not None and not f.closed:
                    f.close()
            except (OSError, ValueError):
                pass

    def close(self) -> None:
        """기록한 PID 의 프로세스만 끝낸다 (stdin 닫기 → SIGTERM → SIGKILL)."""
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
        self._release_pipes()
