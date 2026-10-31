"""JPEG 저장 (기술 계획 2-13절 S18-1, 결정 0194 1 · 3 · 9항). 액자 캡처(`Screenshotter`)와 정리 문서의 이미지 변환(S18-2, coder)이 함께 쓴다.

`save_jpeg(src, dest, quality=80)`: `src`(파일 경로 또는 이미지 바이트)를 `QImage` 로 읽어 JPEG 로 저장한다.
  1. 투명 화소가 있으면 흰 배경에 합성한다(없으면 RGB32 로 바꾼다).
  2. 긴 변이 `limit`(1568) 이하이면 화소 수를 그대로 둔다. 넘으면 `core/imageinfo.target_size` 의 정확한 크기로
     `scaled(IgnoreAspectRatio, SmoothTransformation)` 해 줄인다(비율은 `target_size` 가 맞춘다).
  3. `QImage.save(dest, "JPEG", quality)` 로 한 번만 부호화한다.
  반환: `(원본 가로, 원본 세로, 저장 가로, 저장 세로)`. 읽을 수 없으면 `JpegError("not_image")`, 저장하지 못하면 `JpegError("save_failed")`.
  `src` 는 지우지 않는다(임시 파일 삭제는 호출한 쪽의 몫이다). 저장에 실패하면 `dest` 에 부분 파일을 남기지 않는다.
`convert_file(src_path, dest_path, quality=80)`: 경로 입력용 이름. `save_jpeg` 와 같다.

`QImage` 만 쓰고 `QPixmap` 은 쓰지 않으므로 GUI 스레드가 아니어도 호출할 수 있다. PySide6 는 지연 import 한다.
"""
from __future__ import annotations

import os
from typing import Tuple, Union

from ...core import imageinfo

CAPTURE_JPEG_QUALITY = 80


class JpegError(RuntimeError):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__("%s: %s" % (kind, detail))
        self.kind = kind       # "not_image" | "save_failed"
        self.detail = detail


def _qt():
    from PySide6 import QtCore, QtGui
    return QtCore, QtGui


def save_jpeg(src: Union[str, bytes], dest: str, quality: int = CAPTURE_JPEG_QUALITY,
              limit: int = imageinfo.LONG_SIDE_LIMIT) -> Tuple[int, int, int, int]:
    QtCore, QtGui = _qt()
    img = QtGui.QImage.fromData(src) if isinstance(src, (bytes, bytearray)) else QtGui.QImage(str(src))
    if img.isNull() or img.width() <= 0 or img.height() <= 0:
        raise JpegError("not_image", "이미지로 읽을 수 없다")
    w, h = img.width(), img.height()
    if img.hasAlphaChannel():
        flat = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
        flat.fill(0xFFFFFFFF)
        p = QtGui.QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        img = flat
    else:
        img = img.convertToFormat(QtGui.QImage.Format.Format_RGB32)
    sw, sh = imageinfo.target_size(w, h, limit)
    if (sw, sh) != (w, h):
        img = img.scaled(sw, sh, QtCore.Qt.AspectRatioMode.IgnoreAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
    try:
        ok = img.save(dest, "JPEG", quality)
    except Exception as e:
        ok = False
        err = type(e).__name__
    else:
        err = ""
    if not ok:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise JpegError("save_failed", err or "저장하지 못했다")
    return w, h, sw, sh


def convert_file(src_path: str, dest_path: str, quality: int = CAPTURE_JPEG_QUALITY) -> Tuple[int, int, int, int]:
    return save_jpeg(src_path, dest_path, quality)
