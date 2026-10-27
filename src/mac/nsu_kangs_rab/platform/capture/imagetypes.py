"""이미지 형식 판별과 크기 판독 (내용 기준, 디코딩하지 않는다). 받는 형식: png · jpg · gif · webp (AC-FR7-15).

크기 판독은 `core/imageinfo.read_size` 하나만 쓴다(같은 규칙을 두 곳에 두지 않는다). 이 파일의 `sniff_format` 은 머리 표지만 본다.
"""
from __future__ import annotations

from typing import Optional, Tuple

from ...core import imageinfo

FORMATS = ("png", "jpg", "gif", "webp")


def sniff_format(data: bytes) -> Optional[str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def image_size(data: bytes) -> Optional[Tuple[str, int, int]]:
    """(형식, 가로, 세로). 형식을 모르거나 머리가 깨졌으면 None."""
    if sniff_format(data) is None:
        return None
    try:
        return imageinfo.read_size(data)
    except imageinfo.ImageFormatError:
        return None
