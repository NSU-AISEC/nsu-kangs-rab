"""`claude` 실행 파일의 탐색 (B-03, AC-FR1-4 · AC-FR1-21).

순서: 설정의 `claude_path` → 앱 환경의 `PATH` → 로그인 셸의 `command -v claude` → 알려진 설치 위치.
실행 가능 여부만 확인하고 Claude Code 의 자격 증명 경로는 읽지 않는다. 스크립트(`#!`)여도 건너뛰지 않는다.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

KNOWN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin")


@dataclass(frozen=True)
class Found:
    path: str
    is_script: bool
    source: str  # settings | path | login_shell | known_dir


def _executable(p: str) -> bool:
    return os.path.isfile(p) and os.access(p, os.X_OK)


def is_executable(p: str) -> bool:
    """실행할 수 있는 파일인가(설정 창의 설명 줄 NEW-66 의 판정)."""
    return _executable(p)


def is_script(path: str) -> bool:
    """첫 2바이트가 `#!` 인가."""
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def shell_lookup(shell: Optional[str], timeout_s: float = 5.0) -> Optional[str]:
    """로그인 셸에서 `command -v claude` 의 결과 한 줄. 실패하면 None."""
    if not shell:
        return None
    try:
        r = subprocess.run([shell, "-lc", "command -v claude"], capture_output=True, text=True, timeout=timeout_s,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return line if r.returncode == 0 and line.startswith("/") else None


def find_claude(configured: Optional[str], env: Mapping[str, str],
                login_shell: Optional[Callable[[], Optional[str]]] = None,
                known_dirs: Sequence[str] = KNOWN_DIRS, home: Optional[str] = None) -> Optional[Found]:
    """찾지 못하면 None(호출한 쪽이 `no_claude` 오류와 지정 방법을 표시한다)."""
    home = home or os.path.expanduser("~")
    if configured:
        c = os.path.expanduser(configured)
        return Found(c, is_script(c), "settings") if _executable(c) else None  # 지정했는데 없으면 다른 곳을 찾지 않는다
    for d in (env.get("PATH") or "").split(os.pathsep):
        if d and _executable(os.path.join(d, "claude")):
            p = os.path.join(d, "claude")
            return Found(p, is_script(p), "path")
    if login_shell is not None:
        p = login_shell()
        if p and _executable(p):
            return Found(p, is_script(p), "login_shell")
    for d in known_dirs:
        p = os.path.join(d.replace("~", home, 1) if d.startswith("~") else d, "claude")
        if _executable(p):
            return Found(p, is_script(p), "known_dir")
    return None
