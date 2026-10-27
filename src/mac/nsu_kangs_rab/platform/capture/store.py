"""캡처 파일 저장: 세션 폴더의 `captures/` 안에서만 쓴다 (AC-FR12-6)."""
from __future__ import annotations

import os

from .screenshotter import unique_path

EXT = {"png": ".png", "jpg": ".jpg", "gif": ".gif", "webp": ".webp"}


def write_bytes(data: bytes, fmt: str, captures_dir: str, stem: str) -> str:
    os.makedirs(captures_dir, exist_ok=True)
    dest = unique_path(captures_dir, stem, EXT[fmt])
    with open(dest, "xb") as f:
        f.write(data)
    return dest
