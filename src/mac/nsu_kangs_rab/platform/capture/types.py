"""`capture` 의 자료형. `CaptureItem` 과 출처 상수는 `core/types.py` 의 정의를 쓴다. `FrameRegion` 은 `capture` 안에서만 쓴다."""
from __future__ import annotations

from dataclasses import dataclass

from ...core.types import (CAPTURE_SOURCES, SOURCE_CAPTURE, SOURCE_DROP, SOURCE_PASTE,  # noqa: F401
                           CaptureItem)

SOURCES = CAPTURE_SOURCES


@dataclass(frozen=True)
class FrameRegion:
    """액자 안쪽 영역(포인트). 액자 창은 `app` 이 그리고 좌표만 넘긴다."""
    x: int
    y: int
    width: int
    height: int
