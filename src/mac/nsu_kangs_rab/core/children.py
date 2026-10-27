"""앱이 시작한 하위 프로세스의 PID 상태 파일과 고아 정리 (B-10, AC-FR11-1 · 3).

- 상태 파일: `<설정 폴더>/state/children.json`. 항목마다 `pid` · `started`(`ps -p <pid> -o lstart=` 의 값) · `role` · `argv0`.
  임시 파일 뒤 이름 변경으로 쓴다.
- 고아 정리: 시작할 때 항목의 PID 가 살아 있고 `started` 가 일치하는 것만 SIGTERM 한다. 일치하지 않으면 건드리지 않는다.
- 이름으로 종료하지 않는다(`operation-safety.md` 2절). 이 모듈은 Qt 와 플랫폼 모듈을 가져오지 않는다.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

PS_PATH = "/bin/ps"
STATE_NAME = "children.json"
PROMPT_GLOB = "system-prompt-*.txt"


def process_started(pid: int, *, ps: str = PS_PATH, timeout_s: float = 3.0) -> Optional[str]:
    """`ps -p <pid> -o lstart=` 의 값. 프로세스가 없거나 `ps` 가 실패하면 None. 좀비(상태 Z)는 끝난 것으로 본다."""
    try:
        r = subprocess.run([ps, "-p", str(int(pid)), "-o", "stat=", "-o", "lstart="], capture_output=True, text=True,
                           timeout=timeout_s, env={"LC_ALL": "C", "PATH": "/bin:/usr/bin"})
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    parts = r.stdout.strip().split(None, 1)
    if r.returncode != 0 or len(parts) != 2 or parts[0].startswith("Z"):
        return None
    return parts[1].strip() or None


class ChildRegistry:
    """`Procs(on_change=registry.on_change)` 로 연결한다. 시작하면 항목을 더하고 끝나면 지운다."""

    def __init__(self, config_dir, started: Callable[[int], Optional[str]] = process_started):
        self.dir = Path(config_dir) / "state"
        self.path = self.dir / STATE_NAME
        self._started = started
        self._lock = threading.Lock()
        self.failed = False

    def entries(self) -> list:
        with self._lock:
            return self._read()

    def _read(self) -> list:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("children") if isinstance(data, dict) else None
        out = []
        for e in items if isinstance(items, list) else []:
            if isinstance(e, dict) and isinstance(e.get("pid"), int) and isinstance(e.get("started"), str):
                out.append({"pid": e["pid"], "started": e["started"], "role": str(e.get("role", "")),
                            "argv0": str(e.get("argv0", ""))})
        return out

    def _write(self, items: list) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.dir, 0o700)
            tmp = self.dir / (STATE_NAME + ".tmp-%d" % os.getpid())
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"children": items}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            self.failed = True

    def add(self, pid: int, role: str, argv0: str) -> bool:
        started = self._started(pid)
        if started is None:  # 이미 끝났다. 기록할 시작 시각이 없으므로 더하지 않는다.
            return False
        with self._lock:
            items = [e for e in self._read() if e["pid"] != pid]
            items.append({"pid": pid, "started": started, "role": role, "argv0": argv0})
            self._write(items)
        return True

    def remove(self, pid: int) -> None:
        with self._lock:
            items = self._read()
            rest = [e for e in items if e["pid"] != pid]
            if len(rest) != len(items):
                self._write(rest)

    def kill_all(self, kill: Callable[[int, int], object] = os.kill) -> list:
        """종료 상한(결정 0172 2항)이 지났을 때 기록한 항목 중 살아 있고 `started` 가 일치하는 것만 PID 로 SIGKILL 한다.
        반환값은 신호를 보낸 PID 목록. 이름으로 종료하지 않는다."""
        sent = []
        for e in self.entries():
            if self._started(e["pid"]) == e["started"]:
                try:
                    kill(e["pid"], signal.SIGKILL)
                    sent.append(e["pid"])
                except OSError:
                    pass
        return sent

    def clear(self) -> None:
        with self._lock:
            self._write([])

    def on_change(self, what: str, handle) -> None:
        if what == "start":
            popen = getattr(handle, "popen", None)
            args = getattr(popen, "args", None)
            argv0 = str(args[0]) if isinstance(args, (list, tuple)) and args else ""
            self.add(handle.pid, handle.role, argv0)
        elif what == "exit":
            self.remove(handle.pid)


def cleanup_orphans(config_dir, *, emit: Optional[Callable[..., object]] = None,
                    started: Callable[[int], Optional[str]] = process_started,
                    kill: Callable[[int, int], None] = os.kill,
                    own_pid: Optional[int] = None, term_wait_s: float = 3.0, poll_s: float = 0.1,
                    sleep: Callable[[float], None] = time.sleep) -> list:
    """직전 실행이 남긴 상태 파일의 항목을 정리한다. 반환: 항목별 결과 사전의 목록.

    결과 `result`: `terminated`(SIGTERM 으로 끝남) · `killed`(SIGKILL 이 필요했음) · `gone`(이미 없음) ·
    `skipped_mismatch`(시작 시각이 달라 건드리지 않음) · `skipped_self`(자기 자신) · `failed`(종료 신호 실패).
    `emit(type, **fields)` 는 이벤트 로그(`orphan_cleanup`)이며 본문과 키를 넣지 않는다.
    """
    me = os.getpid() if own_pid is None else own_pid
    reg = ChildRegistry(config_dir, started)
    results = []
    for e in reg.entries():
        pid, rec = e["pid"], e["started"]
        res = {"pid": pid, "role": e["role"], "recorded_started": rec}
        now = started(pid)
        if pid == me:
            res["result"] = "skipped_self"
        elif now is None:
            res["result"] = "gone"
        elif now != rec:
            res["result"] = "skipped_mismatch"
            res["current_started"] = now
        else:
            res["result"] = _terminate(pid, rec, started, kill, term_wait_s, poll_s, sleep)
        results.append(res)
        if emit:
            try:
                emit("orphan_cleanup", **res)
            except Exception:
                pass
    reg.clear()
    return results


def _alive_same(pid: int, rec: str, started: Callable[[int], Optional[str]]) -> bool:
    return started(pid) == rec


def _terminate(pid, rec, started, kill, term_wait_s, poll_s, sleep) -> str:
    try:
        kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "gone"
    except OSError:
        return "failed"
    waited = 0.0
    while waited < term_wait_s:
        if not _alive_same(pid, rec, started):
            return "terminated"
        sleep(poll_s)
        waited += poll_s
    if not _alive_same(pid, rec, started):
        return "terminated"
    try:
        kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "terminated"
    except OSError:
        return "failed"
    return "killed"


def remove_stale_prompt_files(config_dir) -> list:
    """`<설정 폴더>/run/system-prompt-*.txt`(A-28)를 지운다. 앱이 비정상 종료했을 때 남은 것이다."""
    removed = []
    d = Path(config_dir) / "run"
    try:
        files = list(d.glob(PROMPT_GLOB))
    except OSError:
        return removed
    for p in files:
        try:
            p.unlink()
            removed.append(p.name)
        except OSError:
            pass
    return removed
