"""하위 프로세스의 시작과 종료 (docs/plan/technical-plan.md 2-2절 5항, B-06).

- 모든 종료는 이 모듈이 시작한 PID 로만 한다. 이름으로 종료하지 않는다(`operation-safety.md` 2절).
- PID 상태 파일과 고아 정리(B-10, FR-11)는 K-04 가 `on_change` 로 붙인다.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence


@dataclass
class ProcHandle:
    popen: subprocess.Popen
    role: str
    started_mono: float
    pid: int = 0
    closing: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        self.pid = self.popen.pid

    def alive(self) -> bool:
        return self.popen.poll() is None


class Procs:
    def __init__(self, on_change: Optional[Callable[[str, "ProcHandle"], None]] = None,
                 mono: Callable[[], float] = time.monotonic):
        self._mono = mono
        self._on_change = on_change
        self._live: dict = {}
        self._lock = threading.Lock()

    def spawn(self, cmd: Sequence[str], env: Mapping[str, str], cwd: str, role: str) -> ProcHandle:
        """OSError(실행 파일 없음 · 권한)는 호출한 쪽이 처리한다."""
        p = subprocess.Popen(list(cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace", cwd=cwd, env=dict(env), bufsize=1)
        h = ProcHandle(p, role, self._mono())
        with self._lock:
            self._live[h.pid] = h
        self._notify("start", h)
        return h

    def live(self) -> list:
        with self._lock:
            return [h for h in self._live.values() if h.alive()]

    def reap(self, h: ProcHandle) -> Optional[int]:
        code = h.popen.poll()
        if code is not None:
            with self._lock:
                gone = self._live.pop(h.pid, None)
            if gone is not None:
                self._notify("exit", h)
        return code

    def terminate(self, h: ProcHandle, stdin_wait_s: float = 3.0, term_wait_s: float = 3.0) -> Optional[int]:
        """B-06: 표준 입력을 닫고 `stdin_wait_s` 기다린 뒤 기록한 PID 에 SIGTERM, `term_wait_s` 뒤 SIGKILL."""
        h.closing = True
        try:
            if h.popen.stdin and not h.popen.stdin.closed:
                h.popen.stdin.close()
        except (OSError, ValueError):
            pass
        for sig, wait in ((None, stdin_wait_s), (signal.SIGTERM, term_wait_s), (signal.SIGKILL, 5.0)):
            if sig is not None and h.alive():
                try:
                    os.kill(h.pid, sig)
                except ProcessLookupError:
                    pass
            try:
                h.popen.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
        return self.reap(h)

    def kill(self, h: ProcHandle) -> Optional[int]:
        """Q11: 기록한 PID 에 곧바로 SIGKILL. 정상 종료를 기다리지 않는다(요청이 나가기 전에 끊는다)."""
        h.closing = True
        try:
            if h.alive():
                os.kill(h.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            h.popen.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass
        return self.reap(h)

    def _notify(self, what: str, h: ProcHandle) -> None:
        if self._on_change:
            try:
                self._on_change(what, h)
            except Exception:  # 상태 파일의 오류가 프로세스 관리를 멈추지 않는다
                pass
