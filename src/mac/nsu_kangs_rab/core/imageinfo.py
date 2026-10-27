"""이미지 파일의 크기 판독과 축소 비율 (B-11, AC-FR2-8). 표준 라이브러리만 쓴다(Qt 를 가져오지 않는다).

- `read_size(data)` 는 png · jpg · gif · webp 의 머리에서 (형식, 가로, 세로)를 읽는다. 디코딩하지 않는다.
- `target_size(w, h, limit)` 는 긴 변이 `limit` 이하이면 그대로, 넘으면 긴 변을 `limit` 으로 줄이고
  짧은 변은 반올림한다(원본 비율과 1px 안).
- `is_animated(data, fmt)` 는 gif · webp 가 프레임을 둘 이상 가졌는지 머리 구조로 판별한다(결정 0058 1항).
- `fit_bytes(...)` 는 변환 · 축소 뒤에도 바이트 상한을 넘는 이미지를 JPEG(품질 85)로 다시 부호화한다(결정 0058 2항).
- `ImageShrinker(scale)` 는 실제 축소를 하는 `scale(data, fmt, width, height) -> bytes` 를 주입받는다
  (구현은 Qt 의 `QImage.scaled`, B-11. `core/` 는 Qt 를 가져오지 않는다).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Optional

LONG_SIDE_LIMIT = 1568
# 바이트 상한(결정 0058 · 0059 · 0060 · 0061). MB = 10^6 바이트. 넘으면 거부하고 같은 값은 받는다.
IMAGE_BYTES_CAP = 3_750_000                 # 보내는 이미지 한 장
REQUEST_IMAGE_BYTES_CAP = 20_000_000        # 한 요청에 새로 싣는 이미지의 합계
REGISTERED_IMAGE_BYTES_CAP = 15_000_000     # 사전 지식 이미지의 합계
JPEG_QUALITY = 85
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


class ImageFormatError(ValueError):
    """png · jpg · gif · webp 가 아니거나 머리가 깨졌다."""


class ImageTooLarge(ValueError):
    """변환 · 축소 · JPEG 재부호화 뒤에도 한 장의 바이트가 상한을 넘는다(결정 0058 2항). 그 이미지를 거부한다."""

    def __init__(self, size: int, cap: int):
        super().__init__("이미지 바이트 %d 가 상한 %d 를 넘는다" % (size, cap))
        self.size, self.cap = size, cap


def read_size(data: bytes) -> tuple:
    """(형식 `png`|`jpg`|`gif`|`webp`, 가로, 세로). 읽을 수 없으면 `ImageFormatError`."""
    if data[:8] == _PNG_SIG:
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ImageFormatError("PNG 머리가 깨졌다")
        w, h = struct.unpack(">II", data[16:24])
        if w <= 0 or h <= 0:
            raise ImageFormatError("PNG 크기가 0 이다")
        return "png", w, h
    if data[:2] == b"\xff\xd8":
        i, n = 2, len(data)
        while i + 4 <= n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker == 0xFF:  # 채움 바이트
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            if marker == 0xD9:
                break
            seg = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if i + 9 > n:
                    break
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                if w <= 0 or h <= 0:
                    raise ImageFormatError("JPEG 크기가 0 이다")
                return "jpg", w, h
            i += 2 + seg
        raise ImageFormatError("JPEG 크기 표지를 찾지 못했다")
    if data[:6] in (b"GIF87a", b"GIF89a"):  # 결정 0057: 사전 지식 이미지도 첨부와 같이 gif · webp 를 받는다
        if len(data) < 10:
            raise ImageFormatError("GIF 머리가 깨졌다")
        w, h = struct.unpack("<HH", data[6:10])
        if w <= 0 or h <= 0:
            raise ImageFormatError("GIF 크기가 0 이다")
        return "gif", w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        r = _webp_size(data)
        if r is None:
            raise ImageFormatError("WebP 머리가 깨졌다")
        return r
    raise ImageFormatError("png · jpg · gif · webp 가 아니다")


def is_animated(data: bytes, fmt: str) -> bool:
    """gif: 이미지 기술자(0x2C)가 둘 이상. webp: VP8X 의 애니메이션 플래그 또는 `ANIM` 청크. 그 밖의 형식은 거짓이다.
    머리 구조가 깨져 판별하지 못하면 거짓(정적으로 본다)이다."""
    try:
        if fmt == "gif":
            return _gif_frames(data) > 1
        if fmt == "webp":
            d = data
            if len(d) >= 21 and d[12:16] == b"VP8X" and (d[20] & 0x02):
                return True
            i = 12
            while i + 8 <= len(d):          # 청크 목록에서 ANIM 을 찾는다
                tag, size = d[i:i + 4], struct.unpack("<I", d[i + 4:i + 8])[0]
                if tag == b"ANIM":
                    return True
                i += 8 + size + (size & 1)
            return False
    except (struct.error, IndexError):
        return False
    return False


def _gif_frames(d: bytes) -> int:
    """GIF 블록을 건너뛰며 이미지 기술자의 수를 센다(둘을 넘기면 멈춘다)."""
    if len(d) < 13:
        return 0
    i = 13
    flags = d[10]
    if flags & 0x80:
        i += 3 * (2 << (flags & 0x07))
    frames, n = 0, len(d)
    while i < n:
        b = d[i]
        if b == 0x3B:
            break
        if b == 0x21:                         # 확장 블록: 부호 · 하위 블록 열
            i += 2
            while i < n and d[i] != 0:
                i += 1 + d[i]
            i += 1
        elif b == 0x2C:                       # 이미지 기술자
            frames += 1
            if frames > 1:
                return frames
            if i + 10 > n:
                break
            f = d[i + 9]
            i += 10
            if f & 0x80:
                i += 3 * (2 << (f & 0x07))
            i += 1                            # LZW 최소 부호 크기
            while i < n and d[i] != 0:
                i += 1 + d[i]
            i += 1
        else:
            break
    return frames


def _webp_size(d: bytes):
    if len(d) < 30:
        return None
    chunk = d[12:16]
    if chunk == b"VP8 ":
        if d[23:26] != b"\x9d\x01\x2a":
            return None
        w, h = struct.unpack("<HH", d[26:30])
        w, h = w & 0x3FFF, h & 0x3FFF
    elif chunk == b"VP8L":
        if d[20] != 0x2F:
            return None
        bits = int.from_bytes(d[21:25], "little")
        w, h = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    elif chunk == b"VP8X":
        w = int.from_bytes(d[24:27], "little") + 1
        h = int.from_bytes(d[27:30], "little") + 1
    else:
        return None
    return ("webp", w, h) if w and h else None


def target_size(width: int, height: int, limit: int = LONG_SIDE_LIMIT) -> tuple:
    """보낼 크기. 긴 변이 `limit` 이하이면 (width, height) 그대로."""
    long_side = max(width, height)
    if long_side <= limit:
        return width, height
    if width >= height:
        return limit, max(1, round(height * limit / width))
    return max(1, round(width * limit / height)), limit


@dataclass
class Shrunk:
    data: bytes
    fmt: str
    width: int
    height: int
    resized: bool
    reencoded: bool = False     # 바이트 상한 때문에 JPEG 으로 다시 부호화했다(결정 0058 2항)


def fit_bytes(data: bytes, fmt: str, width: int, height: int, scale: Optional[Callable], max_bytes: Optional[int]) -> tuple:
    """바이트가 `max_bytes` 이하이면 그대로. 넘으면 같은 크기의 JPEG(품질 85)로 다시 부호화하고
    `scale(data, "jpg", width, height)` 를 호출한다(Qt 쪽은 출력 형식이 `jpg` 이면 품질 `JPEG_QUALITY` 로 저장한다).
    그래도 넘으면 `ImageTooLarge`. 반환: (바이트, 형식, 다시 부호화했는지)."""
    if max_bytes is None or len(data) <= max_bytes:
        return data, fmt, False
    if scale is None:
        raise RuntimeError("이미지 축소 구현이 주입되지 않았다")
    out = scale(data, "jpg", width, height)
    if len(out) > max_bytes:
        raise ImageTooLarge(len(out), max_bytes)
    return out, "jpg", True


class ImageShrinker:
    def __init__(self, scale: Optional[Callable[[bytes, str, int, int], bytes]] = None, limit: int = LONG_SIDE_LIMIT):
        self._scale = scale
        self.limit = limit

    def __call__(self, data: bytes, fmt: str, width: int, height: int, max_bytes: Optional[int] = None) -> Shrunk:
        """`max_bytes`: 한 장의 바이트 상한. 넘으면 JPEG 으로 다시 부호화하고, 그래도 넘으면 `ImageTooLarge`."""
        tw, th = target_size(width, height, self.limit)
        animated = fmt in ("gif", "webp") and is_animated(data, fmt)   # 결정 0058 1항: 크기와 관계없이 첫 프레임 png
        if (tw, th) == (width, height) and not animated:
            d, f, re = fit_bytes(data, fmt, width, height, self._scale, max_bytes)
            return Shrunk(d, f, width, height, False, re)
        if self._scale is None:
            raise RuntimeError("이미지 축소 구현이 주입되지 않았다")
        out = self._scale(data, fmt, tw, th)
        # gif · webp 는 줄이면 첫 프레임을 png 로 바꾼다(결정 0057). png · jpg 는 형식을 유지한다
        ofmt = fmt if fmt in ("png", "jpg") else "png"
        d, f, re = fit_bytes(out, ofmt, tw, th, self._scale, max_bytes)
        return Shrunk(d, f, tw, th, True, re)
