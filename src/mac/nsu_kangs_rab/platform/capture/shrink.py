"""이미지 축소 (기술 계획 B-11, AC-FR7-18). 비율 계산은 `core/imageinfo` 가 맡고 실제 크기 변경만 `scale` 이 맡는다.

- 긴 변이 1568 px 이하이고 움직이는 gif · webp 가 아니면 바이트를 그대로 쓴다(형식도 그대로). 움직이는 것은 첫 프레임 png.
- 바이트가 상한(`IMAGE_BYTES_CAP`)을 넘으면 JPEG(품질 85)로 다시 부호화하고, 그래도 넘으면 `ImageTooLarge` (결정 0058).
- 넘으면 `scale(data, fmt, width, height) -> png 바이트` 를 호출한다. png · jpg 는 입력 형식을 유지해 달라고 요청하고,
  gif · webp 는 첫 프레임을 png 로 바꾼다(결과 형식 `png`).
- `QtScaler` 는 PySide6 의 `QImage.scaled(SmoothTransformation)` 을 지연 import 한다. 이 환경에는 PySide6 가 없어
  단위 시험은 가짜 `qt` 로 한다 (실제 `QImage` 는 실행하지 않았다).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ...core import imageinfo
from .imagetypes import image_size


@dataclass(frozen=True)
class Prepared:
    data: bytes
    fmt: str
    width: int          # 원본
    height: int
    sent_width: int     # 보낼 크기
    sent_height: int
    resized: bool
    reencoded: bool = False     # 바이트 상한 때문에 JPEG 으로 다시 부호화했다(결정 0058 2항)


class ImageError(ValueError):
    """이미지가 아니거나 머리가 깨졌다."""


def prepare(data: bytes, scale: Optional[Callable[[bytes, str, int, int], bytes]] = None,
            limit: int = imageinfo.LONG_SIDE_LIMIT, max_bytes: Optional[int] = imageinfo.IMAGE_BYTES_CAP) -> Prepared:
    """`max_bytes`: 한 장의 바이트 상한(기본 `IMAGE_BYTES_CAP`, `None` 이면 검사하지 않는다). 넘으면 JPEG 으로 다시
    부호화하고, 그래도 넘으면 `imageinfo.ImageTooLarge` 를 올린다(호출한 쪽은 첨부하지 않고 사유를 표시한다)."""
    info = image_size(data)
    if info is None:
        raise ImageError("이미지로 읽을 수 없다")
    fmt, w, h = info
    r = imageinfo.ImageShrinker(scale, limit)(data, fmt, w, h, max_bytes)   # 규칙의 원본은 core (결정 0058 · 0061)
    return Prepared(r.data, r.fmt, w, h, r.width, r.height, r.resized, r.reencoded)


class QtScaler:
    """`QImage` 로 축소한다. `qt` 는 `QImage` · `Qt` · `QBuffer` · `QIODevice` 를 가진 객체(기본: PySide6.QtGui/QtCore)."""

    def __init__(self, qt=None):
        self._qt = qt

    def _api(self):
        if self._qt is not None:
            return self._qt
        from PySide6 import QtCore, QtGui  # 지연 import

        class _Q:
            QImage = QtGui.QImage
            Qt = QtCore.Qt
            QBuffer = QtCore.QBuffer
            QIODevice = QtCore.QIODevice
            QPainter = QtGui.QPainter
        return _Q

    @staticmethod
    def _on_white(q, img, width: int, height: int):
        canvas = q.QImage(width, height, q.QImage.Format_RGB32)
        canvas.fill(0xFFFFFFFF)
        painter = q.QPainter(canvas)
        painter.drawImage(0, 0, img)
        painter.end()
        return canvas

    def __call__(self, data: bytes, fmt: str, width: int, height: int) -> bytes:
        q = self._api()
        img = q.QImage()
        if not img.loadFromData(data):
            raise ImageError("QImage 가 읽지 못했다")
        scaled = img.scaled(width, height, q.Qt.IgnoreAspectRatio, q.Qt.SmoothTransformation)
        if fmt == "jpg" and getattr(scaled, "hasAlphaChannel", lambda: False)():
            scaled = self._on_white(q, scaled, width, height)   # JPEG 에는 알파가 없다: 흰 배경에 합성한다
        buf = q.QBuffer()
        buf.open(q.QIODevice.WriteOnly)
        if fmt == "jpg":
            ok = scaled.save(buf, "JPG", imageinfo.JPEG_QUALITY)
        else:
            ok = scaled.save(buf, "PNG")
        if not ok:
            raise ImageError("QImage 가 저장하지 못했다")
        return bytes(buf.data())
