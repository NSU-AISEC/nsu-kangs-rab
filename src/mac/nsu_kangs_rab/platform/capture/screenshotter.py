"""`Screenshotter`: `screencapture` 명령 구성과 결과 검증 (기술 계획 A-20). 이 단계에서는 실행하지 않는다.

`build_command(region, out_path)` → `["/usr/sbin/screencapture", "-x", "-R", "x,y,w,h", out_path]`. `-x` 는 소리 없음이다.
`Screenshotter(runner, captures_dir)` 의 `runner(cmd, timeout_s) -> (returncode, stderr_text)` 는 주입한다.
`ProcsRunner` 는 `core/procs.Procs` 로 시작하고 PID 로만 종료하는 실제 실행기이다(이 세션에서는 실행하지 않았다).
결과: 파일이 없거나 0 바이트이거나 이미지가 아니면 `CaptureError`(화면 기록 권한이 없을 때 macOS 는 빈 이미지 · 바탕화면만
찍힌 이미지를 줄 수 있어 이 검증으로는 구별되지 않는다, 미검증).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import time
from typing import Callable, Optional, Tuple

from ...core.i18n import t as _t
from .imagetypes import image_size
from .shrink import prepare
from .types import SOURCE_CAPTURE, CaptureItem, FrameRegion

SCREENCAPTURE = "/usr/sbin/screencapture"


class CaptureError(RuntimeError):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__("%s: %s" % (kind, detail))
        self.kind = kind     # "region" | "exit" | "timeout" | "no_file" | "not_image"
        self.detail = detail


def build_command(region: FrameRegion, out_path: str) -> list:
    if region.width <= 0 or region.height <= 0:
        raise CaptureError("region", "영역의 가로 · 세로는 양수여야 한다")
    r = ",".join(str(int(round(v))) for v in (region.x, region.y, region.width, region.height))
    return [SCREENCAPTURE, "-x", "-R", r, out_path]


def unique_path(directory: str, stem: str, ext: str, exists: Callable[[str], bool] = os.path.exists) -> str:
    p = os.path.join(directory, stem + ext)
    n = 2
    while exists(p):
        p = os.path.join(directory, "%s-%d%s" % (stem, n, ext))
        n += 1
    return p


class ProcsRunner:
    def __init__(self, procs, cwd: str, env: Optional[dict] = None):
        self._procs, self._cwd, self._env = procs, cwd, dict(env if env is not None else {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})

    def __call__(self, cmd, timeout_s: float) -> Tuple[Optional[int], str]:
        import subprocess
        h = self._procs.spawn(cmd, self._env, self._cwd, "screencapture")
        try:
            h.popen.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._procs.terminate(h)
            return None, "timeout"
        code = self._procs.reap(h)
        try:
            err = h.popen.stderr.read() if h.popen.stderr else ""
        except Exception:
            err = ""
        return code, err or ""


class Screenshotter:
    def __init__(self, runner: Callable, captures_dir: str, timeout_s: float = 10.0, scale=None,
                 now: Callable[[], _dt.datetime] = lambda: _dt.datetime.now().astimezone()):
        self._run, self._dir, self._timeout, self._scale, self._now = runner, captures_dir, timeout_s, scale, now

    def capture(self, region: FrameRegion) -> CaptureItem:
        t = self._now()
        stem = "capture-" + t.strftime("%Y%m%d-%H%M%S-") + "%03d" % (t.microsecond // 1000)
        out = unique_path(self._dir, stem, ".png")
        cmd = build_command(region, out)
        code, err = self._run(cmd, self._timeout)
        if code is None:
            raise CaptureError("timeout", _t("shot.capture_443") % self._timeout)
        if code != 0:
            raise CaptureError("exit", _t("shot.capture_444") % code)
        try:
            with open(out, "rb") as f:
                data = f.read()
        except OSError:
            raise CaptureError("no_file", _t("shot.capture_445"))
        if not data:
            raise CaptureError("no_file", _t("shot.capture_446"))
        info = image_size(data)
        if info is None:
            raise CaptureError("not_image", _t("shot.capture_447"))
        _, w, h = info
        sw, sh = w, h
        if self._scale is not None:
            p = prepare(data, self._scale)
            sw, sh = p.sent_width, p.sent_height
        return CaptureItem(path=out, source=SOURCE_CAPTURE, width=w, height=h, sent_width=sw, sent_height=sh,
                           sha256=hashlib.sha256(data).hexdigest(), t_wall=t.isoformat(timespec="milliseconds"))
