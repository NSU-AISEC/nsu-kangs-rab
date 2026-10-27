"""캡처 액자 창 (결정 0010 · 0077 · 0080 ~ 0083, FR-12, 시각 설계 7-11 · 7-12, K-14).

테두리와 네 모서리의 손잡이만 보이고 안쪽이 투명하며 항상 맨 위에 있다. 이름표와 별도의 숨기기 단추는 없다. 창 사각형은
액자의 바깥 사각형과 같다. 안쪽 클릭의 통과는 창 마스크(테두리 고리 + 손잡이 네모만 창의 일부)로 구현한다
(시제품 `experiments/frame_qt/frame_qt.py`). 좌표 계산은 `core/framegeom.py`, 캡처 실행은 `controller` 가 맡는다.

손잡이(바깥 사각형 모서리 안쪽 14 × 14, `r3`): 왼쪽 위 옮기기, 오른쪽 위 닫기(누른 뒤 네모 안에서 놓을 때만 숨기기),
오른쪽 아래 · 왼쪽 아래 크기 바꾸기(반대쪽 모서리 고정). 손잡이가 아닌 테두리는 입력을 받고 아무 일도 하지 않으며 화살표
커서이고 도움말이 없다. 놓을 때 한 화면 안으로 보정하고 `committed(Rect)` 를 낸다(저장은 `controller`).
캡처하는 동안(`begin_capture` ~ `end_capture`)은 네 손잡이(그림 포함)를 그리지 않고 테두리를 2.5 로 그린다.
투명 · 클릭 통과 · 맨 위 표시는 실기로만 확인된다.
"""
from __future__ import annotations
from ..core.i18n import t as _t

import math
import time

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

from ..core import framegeom as G
from ..platform import nswindow
from . import theme

FLASH_MS = 600
LINE_W = 1.5             # 손잡이 그림의 선 굵기(시각 설계 7-11)
RADIUS = 3               # 손잡이의 모서리 반지름 r3

MOVE, CLOSE, RESIZE_BL, RESIZE_BR = "move", "close", "resize_bl", "resize_br"
TIPS = {MOVE: _t("frame.tips"), CLOSE: _t("frame.tips_2"), RESIZE_BL: _t("frame.tips_3"), RESIZE_BR: _t("frame.tips_3")}
_OUT = ""                # 폴링에서 포인터가 클릭을 받는 영역 밖일 때의 값
POLL_MS = 30            # 앱이 활성이 아닐 때 포인터를 읽는 주기(D-145)
TIP_DELAY_S = 0.5      # 같은 손잡이 위에 머문 뒤 도움말을 띄우는 시간
CURSORS = {MOVE: Qt.OpenHandCursor, CLOSE: Qt.ArrowCursor, RESIZE_BL: Qt.SizeBDiagCursor, RESIZE_BR: Qt.SizeFDiagCursor}
EDGES = {RESIZE_BR: {"r", "b"}, RESIZE_BL: {"l", "b"}}      # 끄는 변. 반대쪽 모서리가 고정된다

# 손잡이 그림: 14 × 14 좌표(원점은 네모의 왼쪽 위)의 꺾은선 목록(시각 설계 7-11, 결정 0082 · 0083)
ICONS: Dict[str, List[List[tuple]]] = {
    MOVE: [[(7, 2), (7, 12)], [(2, 7), (12, 7)],
           [(5, 4), (7, 2), (9, 4)], [(5, 10), (7, 12), (9, 10)],
           [(4, 5), (2, 7), (4, 9)], [(10, 5), (12, 7), (10, 9)]],
    CLOSE: [[(3.5, 3.5), (10.5, 10.5)], [(10.5, 3.5), (3.5, 10.5)]],
    RESIZE_BR: [[(3, 3), (11, 11)], [(11, 7), (11, 11), (7, 11)], [(3, 7), (3, 3), (7, 3)]],
    RESIZE_BL: [[(3, 11), (11, 3)], [(7, 3), (11, 3), (11, 7)], [(3, 7), (3, 11), (7, 11)]],
}


def screen_rects(full: bool = False) -> List[G.Rect]:
    """가용 영역(`full` 이면 화면 전체)의 목록. 첫 번째가 주 화면이다."""
    app = QApplication.instance()
    out: List[G.Rect] = []
    primary = app.primaryScreen()
    ordered = ([primary] if primary is not None else []) + [s for s in app.screens() if s is not primary]
    for s in ordered:
        g = s.geometry() if full else s.availableGeometry()
        out.append(G.Rect(g.x(), g.y(), g.width(), g.height()))
    return out or [G.Rect(0, 0, 1280, 800)]


class FrameWindow(QWidget):
    committed = Signal(object)          # 이동 · 크기 조절을 마친 액자 사각형(framegeom.Rect)
    hide_requested = Signal()

    def __init__(self, scheme: Callable[[], str] = lambda: "light"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
                         | Qt.NoDropShadowWindowHint | Qt.Tool)      # Tool: macOS 에서 NSPanel 이 된다(결정 0112)      # D-124: 고리 창의 그림자가 캡처 영역(구멍) 가장자리를 어둡게 한다
        self.setObjectName("capture_frame")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)      # 활성 창이 아니어도 도움말이 보인다(W-57)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)  # 패널이 다른 앱이 앞일 때도 보인다
        self.pretend_method_missing = False              # 5-1절 개발 옵션: 비활성화 메서드가 없는 것으로 움직인다(AC-FR12-20 ⓕ)
        self.native_info: dict = {}                      # 마지막 `make_nonactivating` 결과
        self.on_native_created: Callable[[dict], None] = lambda info: None      # 새 네이티브 창마다 한 번(이벤트 로그)
        self._native_id = None
        self.setMouseTracking(True)
        self.setMinimumSize(G.MIN_W, G.MIN_H)            # D-117: 어떤 경로로도 최소 크기 아래로 줄지 않는다
        self._scheme = scheme
        self._border = G.BORDER
        self._capturing = False
        self._hover_name: Optional[str] = None
        self._poll_name: Optional[str] = _OUT            # D-145: 앱이 활성이 아닐 때 포인터 위치를 읽어 정한 손잡이
        self._poll_since = 0.0
        self._poll_tip = False
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_tick)
        self._mode: Optional[str] = None
        self._press: Optional[QPoint] = None
        self._press_frame: Optional[G.Rect] = None
        self._press_screen = G.Rect(0, 0, 1 << 20, 1 << 20)
        self._press_top = 0
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)
        self._screens: Callable[[], List[G.Rect]] = lambda: screen_rects(True)      # 화면 전체(경계)
        self._avails: Callable[[], List[G.Rect]] = screen_rects                     # 가용 영역(윗변 한계)
        self._update_mask()
        nswindow.disable_native_resize(self)             # D-120: macOS 기본 크기 조절을 끈다(손잡이 경로만 크기를 바꾼다)

    def showEvent(self, e) -> None:  # noqa: N802 (Qt)
        info = nswindow.make_nonactivating(self, self.pretend_method_missing)      # 결정 0112 (D-120 의 크기 조절 끄기를 포함한다)
        self.native_info = info
        nid = int(self.winId()) if info.get("native") else None
        if nid != self._native_id or nid is None:      # 새 네이티브 창일 때만 기록한다(cocoa 가 아니면 보일 때마다)
            self._native_id = nid
            self.on_native_created(info)
        nswindow.allow_background_cursor()               # D-145
        self._poll.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802 (Qt)
        self._poll.stop()
        super().hideEvent(e)

    # ---- 활성 앱이 아닐 때의 포인터 (D-145) ----
    def _poll_tick(self) -> None:
        """다른 앱이 앞일 때 Qt 는 이 창으로 포인터 이동 사건을 보내지 않는다(실측: `experiments/frame_track`, 사건 수 1건 대 167건).
        그래서 포인터의 전역 위치를 주기로 읽어 손잡이 위의 커서와 도움말을 직접 정한다. 앱이 활성일 때도 Qt 의 도움말 사건이 오지 않는
        것이 같은 실측에서 확인되어 상태를 가리지 않는다. 끌기 중에는 Qt 사건이 맡는다."""
        if not self.isVisible():
            self._poll_reset()
            return
        if self._mode is not None:                        # 끌기 중: 맨 앞 앱이 되돌린 커서(쥔 손 · 크기 조절)를 다시 적용한다
            nswindow.apply_cursor(self)
            return
        pt = self.mapFromGlobal(QCursor.pos())
        inside = self.mask_region().contains(pt)          # 클릭을 받는 고리와 손잡이만이다. 안쪽은 아래 앱의 영역이므로 건드리지 않는다
        name = self._handle_at(pt) if inside else None
        key = name if inside else _OUT
        if inside and key == self._poll_name:             # 맨 앞 앱(Qt 시험 창 등)이 0.2 ~ 0.5 초 뒤 커서를 되돌리므로 영역 안에서는 매 주기 다시 적용한다
            nswindow.apply_cursor(self)
        if key != self._poll_name:                        # 바뀔 때는 커서를 정하고 도움말 시간을 새로 잰다
            if inside:
                self._hover(pt)
            self._poll_name, self._poll_since = key, time.monotonic()
            if self._poll_tip:
                QToolTip.hideText()
                self._poll_tip = False
        elif name is not None and not self._poll_tip and time.monotonic() - self._poll_since >= TIP_DELAY_S:
            QToolTip.showText(QCursor.pos(), TIPS[name], self, self.handle_rects()[name])
            self._poll_tip = True

    def _poll_reset(self) -> None:
        if self._poll_tip:
            QToolTip.hideText()
        self._poll_name, self._poll_tip = _OUT, False

    # ---- 좌표 ----
    def frame_rect(self) -> G.Rect:
        g = self.geometry()
        return G.Rect(g.x(), g.y(), g.width(), g.height())

    def set_frame(self, frame: G.Rect) -> None:
        frame = G.Rect(frame.x, frame.y, max(G.MIN_W, frame.w), max(G.MIN_H, frame.h))
        self.setGeometry(frame.x, frame.y, frame.w, frame.h)
        self._update_mask()

    def capture_region(self) -> G.Rect:
        """`screencapture -R` 에 넘길 안쪽 영역(테두리 제외, 숨긴 동안에도 같은 값)."""
        return G.inner_region(self.frame_rect())

    # ---- 모양 ----
    def handle_rects(self) -> Dict[str, QRect]:
        """손잡이 네모(창 좌표): 바깥 사각형의 네 모서리 안쪽 14 × 14."""
        w, h, s = self.width(), self.height(), G.HANDLE
        return {MOVE: QRect(0, 0, s, s), CLOSE: QRect(w - s, 0, s, s),
                RESIZE_BL: QRect(0, h - s, s, s), RESIZE_BR: QRect(w - s, h - s, s, s)}

    def _handle_at(self, pt: QPoint) -> Optional[str]:
        for name, r in self.handle_rects().items():
            if r.contains(pt):
                return name
        return None

    def _ring(self) -> QRegion:
        """클릭을 받는 고리(정수 좌표이므로 테두리를 올림한다)."""
        f, b = self.rect(), int(math.ceil(self._border))
        return QRegion(f).subtracted(QRegion(f.adjusted(b, b, -b, -b)))

    def _ring_path(self) -> QPainterPath:
        """그리는 고리: 테두리 2.5(@2x 5 px) · 4 를 소수 좌표로 그린다."""
        f, b = QRectF(self.rect()), float(self._border)
        outer = QPainterPath()
        outer.addRect(f)
        inner = QPainterPath()
        inner.addRect(f.adjusted(b, b, -b, -b))
        return outer.subtracted(inner)

    def mask_region(self) -> QRegion:
        """마우스 입력을 받는 영역: 테두리 고리와 네 손잡이 네모(안쪽과 겹치는 모서리 11 × 11 은 클릭 통과에서 뺀다)."""
        reg = self._ring()
        for r in self.handle_rects().values():
            reg = reg.united(QRegion(r))
        return reg

    def _update_mask(self) -> None:
        self.setMask(self.mask_region())      # 마스크 밖(안쪽)은 창이 아니므로 클릭이 아래 창으로 간다

    def resizeEvent(self, e) -> None:  # noqa: N802 (Qt)
        super().resizeEvent(e)
        self._update_mask()

    def paintEvent(self, e) -> None:  # noqa: N802 (Qt)
        t = theme.tokens(self._scheme())
        info, ink = QColor(t["info"]), QColor(t["info-bg"])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), Qt.transparent)
        p.setPen(Qt.NoPen)
        p.setBrush(info)
        p.drawPath(self._ring_path())            # 테두리 고리(소수 두께)
        if self._capturing:                      # 캡처하는 동안 손잡이(그림 포함)를 그리지 않는다(AC-FR12-15, D-118)
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        for name, r in self.handle_rects().items():
            p.setPen(Qt.NoPen)
            p.setBrush(info)
            p.drawRoundedRect(QRectF(r), RADIUS, RADIUS)
            pen = QPen(ink, LINE_W)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            for line in ICONS[name]:
                path = QPainterPath(QPointF(r.x() + line[0][0], r.y() + line[0][1]))
                for x, y in line[1:]:
                    path.lineTo(r.x() + x, r.y() + y)
                p.drawPath(path)

    # ---- 캡처 ----
    def begin_capture(self) -> None:
        """캡처를 시작한다: 강조를 멈추고 테두리를 2.5 로 하며 손잡이를 지우고 화면에 곧바로 반영한다(D-118 · D-119)."""
        self._flash_timer.stop()
        self._border = G.BORDER
        self._capturing = True
        self._update_mask()
        if self.isVisible():
            self.repaint()

    def end_capture(self) -> None:
        """캡처가 끝났다(실패 포함): 손잡이를 다시 그린다. 숨긴 채 캡처했으면 숨은 채로 둔다."""
        self._capturing = False
        self.update()

    def is_capturing(self) -> bool:
        return self._capturing

    # ---- 캡처 직후 표시 ----
    def flash(self) -> None:
        """캡처가 끝난 뒤 테두리를 잠시 굵게 한다(7-11). 캡처하는 동안에는 하지 않는다. 안쪽을 밝히는 처리는
        클릭 통과(마스크)와 양립하지 않아 하지 않는다."""
        if self._capturing:
            return
        self._border = G.FLASH_BORDER
        self._update_mask()
        self.update()
        self._flash_timer.start(FLASH_MS)

    def is_flashing(self) -> bool:
        return self._border != G.BORDER

    def _end_flash(self) -> None:
        self._border = G.BORDER
        self._update_mask()
        self.update()

    # ---- 조작 ----
    def _hover(self, pt: QPoint) -> None:
        """손잡이 위에서는 기능에 맞는 커서와 도움말, 그 밖의 테두리 위에서는 화살표 커서와 도움말 없음(W-57)."""
        if self._mode is not None:               # D-145: 누른 동안(끌기 중)에는 들어옴 사건 등이 쥔 손 · 크기 조절 커서를 열린 손으로 되돌리지 못하게 한다
            return
        name = self._handle_at(pt)
        self.setCursor(CURSORS.get(name, Qt.ArrowCursor))
        nswindow.apply_cursor(self)              # D-123: Qt 의 커서 사각형은 키 창이 아니면 적용되지 않으므로 직접 적용한다
        tip = TIPS.get(name, "")
        if name != self._hover_name:             # 손잡이가 바뀌면 같은 문구여도 도움말을 새로 띄운다(왼쪽 아래 → 오른쪽 아래)
            self._hover_name = name
            QToolTip.hideText()
        if self.toolTip() != tip:
            self.setToolTip(tip)

    def tooltip_state(self) -> dict:
        """개발 제어 `frame_query` 용(W-133): 액자의 도움말이 지금 보이는지(`visible`)와 그 글(`label`). 다른 위젯의 도움말은 보이지 않는 것으로 본다."""
        text = QToolTip.text() if QToolTip.isVisible() else ""
        shown = text in TIPS.values()
        return {"visible": bool(text) and shown, "label": text if shown else ""}      # `text` 는 이벤트 로그가 지우는 이름이라 `label` 로 쓴다(D-146)

    def event(self, e) -> bool:
        """도움말은 손잡이 사각형을 영역으로 지정해 띄운다. 같은 문구를 쓰는 두 손잡이(크기 바꾸기) 사이를 옮겨도 새로 뜬다."""
        if e.type() == QEvent.ToolTip:
            name = self._handle_at(e.pos())
            if name is None:
                QToolTip.hideText()
                e.ignore()
            else:
                QToolTip.showText(e.globalPos(), TIPS[name], self, self.handle_rects()[name])
            return True
        return super().event(e)

    def enterEvent(self, e) -> None:  # noqa: N802 (Qt)
        super().enterEvent(e)
        self._hover(self.mapFromGlobal(self.cursor().pos()))

    def mousePressEvent(self, e) -> None:  # noqa: N802 (Qt)
        if e.button() != Qt.LeftButton:
            return
        pt = e.position().toPoint()
        self._mode = self._handle_at(pt)          # 손잡이가 아닌 테두리는 입력을 받고 아무 일도 하지 않는다
        if self._mode is None:
            return
        self._press = e.globalPosition().toPoint()
        self._press_frame = self.frame_rect()
        screens, avails = self._screens(), self._avails()
        idx = G.pick_screen(self._press_frame, screens)
        self._press_screen = screens[0 if idx is None else idx]
        self._press_top = G.top_of(idx, screens, avails)
        if self._mode == MOVE:
            self.setCursor(Qt.ClosedHandCursor)
            nswindow.apply_cursor(self)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802 (Qt)
        if self._mode is None or self._press is None:
            self._hover(e.position().toPoint())
            return
        if not (e.buttons() & Qt.LeftButton):      # 놓음 사건을 받지 못한 경우: 끌기를 끝내고 더는 크기를 바꾸지 않는다(D-117)
            self._finish(e, commit=True)
            return
        if self._mode == CLOSE:
            return
        d = e.globalPosition().toPoint() - self._press
        f = self._press_frame
        if self._mode == MOVE:
            gp = e.globalPosition().toPoint()
            screens, avails = self._screens(), self._avails()
            idx = G.screen_containing((gp.x(), gp.y()), screens)
            top = self._press_top if idx is None else G.top_of(idx, screens, avails)
            self.set_frame(G.Rect(f.x + d.x(), max(f.y + d.y(), top), f.w, f.h))      # 윗변은 가용 영역의 위 끝 위로 가지 않는다
        else:      # 크기 조절은 액자가 있는 화면 안에서만 되고 그 화면의 경계에서 멈춘다(D-113)
            self.set_frame(G.resize(f, EDGES[self._mode], d.x(), d.y(), self._press_screen, self._press_top))

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802 (Qt)
        if e.button() != Qt.LeftButton:
            return
        self._finish(e, commit=True)

    def _finish(self, e, commit: bool) -> None:
        mode, self._mode, self._press = self._mode, None, None
        pt = e.position().toPoint()
        self._hover(pt)
        if mode is None:
            return
        if mode == CLOSE:      # 누른 뒤 네모 안에서 놓을 때만 숨긴다. 밖에서 놓으면 아무 일도 없다(W-58)
            if self.handle_rects()[CLOSE].contains(pt) and (e.buttons() & Qt.LeftButton) == Qt.NoButton:
                self.hide_requested.emit()
            return
        if mode == MOVE:      # 놓으면 포인터가 있는 화면 안으로(AC-FR12-12). 크기 조절은 끄는 중에 이미 경계 안이다
            p = e.globalPosition().toPoint()
            self.set_frame(G.clamp(self.frame_rect(), self._screens(), (p.x(), p.y()), self._avails()))
        if commit:
            self.committed.emit(self.frame_rect())
