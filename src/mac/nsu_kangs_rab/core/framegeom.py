"""캡처 액자의 좌표 계산 (결정 0010 · 0077 · 0080 ~ 0082, FR-12, K-14). Qt 에 의존하지 않는다(플랫폼 비의존).

용어. **액자 사각형** 은 테두리를 포함한 바깥 사각형이며 설정에 저장하는 값이고 액자 창의 사각형과 같다(이름표 띠가
없다, 결정 0080). **안쪽 영역** 은 테두리를 뺀 사각형이며 `screencapture -R` 에 넘기는 값이다(AC-FR12-10). 네 모서리의
손잡이 12 × 12 는 바깥 사각형 안쪽에 있다. 모든 좌표는 포인트이다(Qt 전역 좌표와 `screencapture -R` 은 같은 체계이다,
시제품 `experiments/frame_qt/frame_qt.py`).

경계(FR-12 크기와 위치 ① ~ ④). 왼쪽 · 오른쪽 · 아래 변의 경계는 그 화면 전체이고, 윗변은 그 화면 가용 영역의 위 끝
(메뉴 막대 아래)보다 위로 올라갈 수 없다. 이 모듈의 함수에서 `screens` 는 화면 전체, `avails` 는 가용 영역이며 같은
순서의 목록이다(`avails` 가 없으면 `screens` 와 같다).
"""
from __future__ import annotations
from .i18n import t as _t

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

BORDER = 2.5          # 테두리 두께(시각 설계 7-11, 결정 0089 4항 · 0093, @2x 5 px)
FLASH_BORDER = 4      # 캡처 직후 잠시 굵어지는 테두리
HANDLE = 14           # 손잡이 14 × 14(결정 0083)
OVERLAP = HANDLE - BORDER      # 손잡이 네모가 캡처 영역과 겹치는 모서리: 11.5 × 11.5
_IB = 3               # 정수 좌표로 환산한 테두리(올림). 캡처 영역 · 최소 크기 · 기본 크기는 이 값으로 계산한다
MIN_INNER_W, MIN_INNER_H = 200, 120      # 안쪽 영역의 최소 크기(master 의 기술 기본값, 2026-10-17)
MIN_W, MIN_H = MIN_INNER_W + 2 * _IB, MIN_INNER_H + 2 * _IB        # 액자 사각형의 최소 크기
DEFAULT_INNER_W, DEFAULT_INNER_H = 960, 540      # 기본 안쪽 영역. 가용 영역의 80% 를 넘으면 16:9 를 유지하며 줄인다
OFF_SCREEN_NOTICE = _t("framegeom.off_screen_notice")


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


def from_setting(value) -> Optional[Rect]:
    """설정의 `frame` 값을 읽는다. 형식이 맞지 않으면 None(기본 위치)이다."""
    if not isinstance(value, dict):
        return None
    try:
        vals = [value[k] for k in ("x", "y", "w", "h")]
    except KeyError:
        return None
    if any(isinstance(v, bool) or not isinstance(v, int) for v in vals):
        return None
    r = Rect(*vals)
    return r if r.w >= MIN_W and r.h >= MIN_H else None


def top_of(index: Optional[int], screens: Sequence[Rect], avails: Optional[Sequence[Rect]] = None) -> int:
    """`index` 번 화면의 윗변 한계(가용 영역의 위 끝). 가용 영역이 없으면 화면의 위 끝이다."""
    i = 0 if index is None else index
    src = avails if avails is not None and i < len(avails) else screens
    return src[i].y


def placeable(frame: Rect, s: Rect, top: Optional[int] = None) -> bool:
    """바깥 사각형이 화면 전체 안에 있고 윗변이 가용 영역의 위 끝(`top`, 없으면 화면의 위 끝) 이상이다."""
    return contains(s, frame) and frame.y >= (s.y if top is None else top)


def inner_region(frame: Rect, border: float = BORDER) -> Rect:
    """캡처할 안쪽 영역(테두리 제외, AC-FR12-10). 좌표는 정수 포인트이므로 테두리가 늘 영역 밖에 있도록 안쪽 모서리를
    올림(왼쪽 위) · 내림(오른쪽 아래)한다(테두리 2.5 는 3 으로 환산되어 영역 크기가 바뀌지 않는다)."""
    import math
    x0, y0 = math.ceil(frame.x + border), math.ceil(frame.y + border)
    x1, y1 = math.floor(frame.right - border), math.floor(frame.bottom - border)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def intersection_area(a: Rect, b: Rect) -> int:
    w = min(a.right, b.right) - max(a.x, b.x)
    h = min(a.bottom, b.bottom) - max(a.y, b.y)
    return w * h if w > 0 and h > 0 else 0


def contains(outer: Rect, inner: Rect) -> bool:
    return inner.x >= outer.x and inner.y >= outer.y and inner.right <= outer.right and inner.bottom <= outer.bottom


def pick_screen(window: Rect, screens: Sequence[Rect]) -> Optional[int]:
    """창 사각형과 겹침이 가장 큰 화면의 번호. 겹치는 화면이 없으면 None."""
    best, best_area = None, 0
    for i, s in enumerate(screens):
        a = intersection_area(window, s)
        if a > best_area:
            best, best_area = i, a
    return best


def default_frame(avail: Rect) -> Rect:
    """주 화면의 기본 위치와 크기: 안쪽 영역 960 × 540, 가용 영역의 가운데. 가용 영역의 80% 를 넘으면 16:9 를 유지하며 줄인다."""
    s = min(1.0, 0.8 * avail.w / DEFAULT_INNER_W, 0.8 * avail.h / DEFAULT_INNER_H)
    iw, ih = max(MIN_INNER_W, int(DEFAULT_INNER_W * s)), max(MIN_INNER_H, int(DEFAULT_INNER_H * s))      # 소수 포인트는 내린다
    w, h = iw + 2 * _IB, ih + 2 * _IB
    return Rect(avail.x + (avail.w - w) // 2, avail.y + (avail.h - h) // 2, w, h)


def screen_containing(point: Tuple[int, int], screens: Sequence[Rect]) -> Optional[int]:
    """점(포인터)이 있는 화면의 번호. 어느 화면에도 없으면 None."""
    for i, s in enumerate(screens):
        if s.x <= point[0] < s.right and s.y <= point[1] < s.bottom:
            return i
    return None


def restore(saved, screens: Sequence[Rect]) -> Tuple[Rect, bool]:
    """시작 때의 액자 사각형. `screens` 는 가용 영역이며 첫 번째가 주 화면이다.
    저장값의 바깥 사각형이 한 화면 안에 온전히 들어오면 그대로 쓰고, 아니면 주 화면의 기본값이다(AC-FR12-12).
    반환: (액자 사각형, 저장값이 있었으나 화면 밖이어서 기본값을 쓴 경우의 알림 여부)."""
    r, source, reason = restore_info(saved, screens)
    return r, reason in ("off_screen", "invalid")


def restore_info(saved, screens: Sequence[Rect], avails: Optional[Sequence[Rect]] = None) -> Tuple[Rect, str, str]:
    """`restore` 와 같고 출처를 함께 반환한다: (액자 사각형, "saved" | "default", 기본값으로 연 사유
    "" | "none_saved" | "invalid" | "off_screen"). 이벤트 로그의 `frame_restore` 가 쓴다.
    `screens` 는 화면 전체의 사각형(경계), `avails` 는 가용 영역(기본 위치 계산용, 없으면 `screens`).
    저장값의 바깥 사각형이 한 화면 안에 온전히 들어오지 않거나 윗변이 그 화면 가용 영역의 위 끝보다 위이면 기본값이다(AC-FR12-12)."""
    base = (avails or screens)[0]
    if saved is None:
        return default_frame(base), "default", "none_saved"
    r = from_setting(saved)
    if r is None:
        return default_frame(base), "default", "invalid"
    if any(placeable(r, s, top_of(i, screens, avails)) for i, s in enumerate(screens)):
        return r, "saved", ""
    return default_frame(base), "default", "off_screen"


def resize(press: Rect, edges, dx: int, dy: int, screen: Rect, top: Optional[int] = None) -> Rect:
    """크기 조절: `press` 는 누른 때의 바깥 사각형, `edges` 는 끄는 변("l" · "r" · "t" · "b", 손잡이는 아래 두 모서리라서
    "r" + "b" 또는 "l" + "b"), `dx` · `dy` 는 끈 거리. 반대쪽 변은 움직이지 않고, 끄는 변은 그 화면 전체의 경계에서 멈추되
    윗변은 가용 영역의 위 끝(`top`)에서 멈추며, 너비와 높이는 화면을 넘지 않고 최소 크기 아래로 줄지 않는다
    (FR-12 크기와 위치 ① ~ ④, D-113)."""
    s = screen
    ceil = s.y if top is None else top
    left, t, right, bottom = press.x, press.y, press.right, press.bottom
    if "l" in edges:
        left = min(max(left + dx, s.x), right - MIN_W)
    if "r" in edges:
        right = max(min(right + dx, s.right), left + MIN_W)
    if "t" in edges:
        t = min(max(t + dy, ceil, bottom - (s.bottom - ceil)), bottom - MIN_H)
    if "b" in edges:
        bottom = max(min(bottom + dy, s.bottom, t + (s.bottom - ceil)), t + MIN_H)
    return Rect(left, t, right - left, bottom - t)


def clamp(frame: Rect, screens: Sequence[Rect], pointer: Optional[Tuple[int, int]] = None,
          avails: Optional[Sequence[Rect]] = None) -> Rect:
    """이동 · 크기 조절을 놓은 뒤에 액자가 한 화면 안에만 있게 한다(AC-FR12-12). 끄는 동안에는 두 화면에 걸칠 수 있다.
    `pointer` 가 있으면 그 점이 있는 화면, 없거나 어느 화면에도 없으면 겹침이 가장 큰 화면(그것도 없으면 주 화면)을
    고르고, 그 화면(윗변은 가용 영역 아래)보다 크면 비율을 유지하며 줄이고, 밖으로 나가면 안으로 옮긴다."""
    idx = screen_containing(pointer, screens) if pointer is not None else None
    if idx is None:
        idx = pick_screen(frame, screens)
    if idx is None:
        idx = 0
    s, top = screens[idx], top_of(idx, screens, avails)
    w, h = frame.w, frame.h
    room_h = s.bottom - top
    if w > s.w or h > room_h:       # 규칙을 넘으면 비율을 유지하며 줄이되 최소 크기 아래로는 줄이지 않는다
        k = min(s.w / w, room_h / h)
        w, h = int(w * k), int(h * k)
    w, h = max(MIN_W, w), max(MIN_H, h)
    x = min(max(frame.x, s.x), s.right - w)
    y = min(max(frame.y, top), s.bottom - h)
    return Rect(x, y, w, h)
