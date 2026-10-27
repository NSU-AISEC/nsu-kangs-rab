"""메인 창의 뼈대: 상태 기계에 따른 화면 전환과 창 닫기 규칙 (K-11; FR-14 · FR-11).

세션 중의 내용(STT 창 · AI 창 · 카드)은 K-12, 메뉴 막대 · 상태 아이콘은 K-13 이 채운다.
이 위젯은 세션을 시작하지 않는다. 시작 요청은 `session_start_requested` 로 알리고, 호출한 쪽이 성공하면
`session_started()` 를 호출한다(인증 불일치 등으로 시작하지 못하면 화면은 시작 화면에 남는다).
창 닫기가 앱 종료인 상태(①②)에서는 `quit_requested` 를 낸다. 이 위젯을 쓰는 앱은 `QApplication.setQuitOnLastWindowClosed(False)` 로 둔다.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from ..core import appstate
from . import mainview, screens


MIN_WINDOW = (800, 560)
DEFAULT_WINDOW = (1280, 960)
DIALOG_MIN_HEIGHT = 420
DIALOG_AVAIL_MARGIN = 20          # 첫 실행 고지 · 세션 시작 창의 높이 상한 = 가용 높이 − 20(결정 0190 2항). 설정 · 다시 보기 · 메인 창은 80 그대로


def fit_to_screen(size, margin: int = 80, screen=None):
    """기본 크기를 화면의 가용 영역 안으로 줄인다(결정 0068 4항). 최소 크기보다 작아지지 않는다.
    `screen` 은 창이 있는 화면(`availableGeometry()` 를 가진 객체)이며, 없으면 주 화면을 쓴다(D-105)."""
    try:
        from PySide6.QtGui import QGuiApplication
        scr = screen if screen is not None else QGuiApplication.primaryScreen()
        if scr is None:
            return size
        g = scr.availableGeometry()
        return (max(MIN_WINDOW[0], min(size[0], g.width())), max(MIN_WINDOW[1], min(size[1], g.height() - margin)))
    except Exception:
        return size


def position_within(x: int, y: int, w: int, h: int, avail) -> tuple:
    """창(x, y, w, h)이 가용 영역 `avail`(left/top/width/height 를 가진 객체) 밖에 걸치면 안으로 옮긴 좌표를 반환한다(D-105).
    창이 영역보다 크면 왼쪽 위 모서리를 영역의 왼쪽 위에 맞춘다."""
    left, top = avail.left(), avail.top()
    right, bottom = left + avail.width(), top + avail.height()
    nx = max(left, min(x, right - w))
    ny = max(top, min(y, bottom - h))
    return nx, ny


class MainShell(QMainWindow):
    session_start_requested = Signal(dict)
    quit_requested = Signal()
    ending_quit_requested = Signal()   # 종료 창이 떠 있는 동안의 종료 요청(결정 0169 1항)
    end_flow_requested = Signal()   # 세션 종료 흐름("세션 종료…" · 세션 중 ⌘Q, AC-FR14-9)

    def __init__(self, data: Mapping, default_save_dir: str, claude_path: Optional[str], *,
                 first_run: bool, emit: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(screens.APP_NAME)
        self.setMinimumSize(*MIN_WINDOW)          # design 의 layout-values 회신(D-086): 최소 800×560, 기본 1280×960
        self.resize(*self._fit(DEFAULT_WINDOW))
        self._dialog_sized = False
        self.machine = appstate.AppStateMachine(first_run=first_run, on_change=self._on_state, emit=emit)
        self.first_run_page = screens.FirstRunNotice()
        self.start_page = screens.SessionStartForm(data, default_save_dir)
        self.session_page = mainview.SessionView("F2" if data.get("trigger_key") is None else str(data.get("trigger_key")))   # K-12
        self.stack = QStackedWidget()
        for w in (self.first_run_page, self.start_page, self.session_page):
            self.stack.addWidget(w)
        self.setCentralWidget(self.stack)
        self.status = screens.StatusBar()
        self.setStatusBar(self.status)
        self.first_run_page.acknowledged.connect(self.acknowledge_first_run)
        self.first_run_page.quit_requested.connect(self.request_quit)     # [종료] = 앱 종료(시안 `FirstRun`)
        self.start_page.start_requested.connect(self.session_start_requested.emit)
        self.start_page.content_changed.connect(self.refit_dialog)      # AC-FR1-25: 내용 높이가 바뀌면 창 높이를 다시 정한다
        self.start_page.cancel_requested.connect(self.request_quit)     # [취소] = 앱 종료(시안 `Session`, 결정 0068)
        self._show_for(self.machine.state)

    def _screen_obj(self):
        try:
            return self.screen()
        except Exception:
            return None

    def _fit(self, size, margin: int = 80):
        return fit_to_screen(size, margin, self._screen_obj())

    def _keep_on_screen(self) -> None:
        """키운 창이 있는 화면의 가용 영역 밖에 걸치면 안으로 옮긴다(D-105)."""
        scr = self._screen_obj()
        if scr is None:
            return
        try:
            g = self.frameGeometry()
            nx, ny = position_within(g.x(), g.y(), g.width(), g.height(), scr.availableGeometry())
            if (nx, ny) != (g.x(), g.y()):
                self.move(self.x() + nx - g.x(), self.y() + ny - g.y())
        except Exception:
            pass

    def _show_for(self, state: appstate.State) -> None:
        page = {appstate.State.FIRST_RUN: self.first_run_page,
                appstate.State.BEFORE_SESSION: self.start_page}.get(state, self.session_page)
        self.stack.setCurrentWidget(page)
        self._apply_window_rules(page)

    def _apply_window_rules(self, page) -> None:
        """창의 공통 규칙(결정 0068 5항): 첫 실행 · 세션 시작 화면은 폭을 고정하고 상태 표시줄이 없으며, 높이는
        내용 높이와 가용 높이 − 20 중 작은 값(최소 420, 결정 0190 2항)이다. 메인 창은 최소 800×560 · 기본 1280×960 이다."""
        width = getattr(page, "WIDTH", None)
        QWIDGETSIZE_MAX = 16777215
        if width is None:
            self.setMinimumSize(*MIN_WINDOW)
            self.setMaximumWidth(QWIDGETSIZE_MAX)
            self.status.setVisible(True)
            if self.width() < MIN_WINDOW[0] or self._dialog_sized:
                self.resize(*self._fit(DEFAULT_WINDOW))
            self._dialog_sized = False
            self._keep_on_screen()
            return
        self._dialog_sized = True
        self.status.setVisible(False)
        self._fit_dialog_height(page, width)
        self._keep_on_screen()

    def _frame_extra(self) -> int:
        """제목줄 등 창틀의 높이(바깥 높이 − 안쪽 높이). 아직 화면에 나오지 않았거나 제목줄이 없으면 0 이다."""
        try:
            return max(0, self.frameGeometry().height() - self.geometry().height())
        except Exception:
            return 0

    def _avail_height(self) -> int:
        """창이 놓인 화면의 가용 높이 − 20(`QScreen.availableGeometry`, AC-FR1-25, 결정 0190 2항). 첫 실행 고지와 세션 시작 두 화면에만 쓴다."""
        scr = self._screen_obj()
        if scr is None:
            return 100000
        return scr.availableGeometry().height() - DIALOG_AVAIL_MARGIN

    def _fit_dialog_height(self, page, width: int) -> None:
        """대화 상자 창의 바깥 높이 = max(420, min(내용 높이, 가용 높이 − 20)) (결정 0117 4항 · 0190 2항, 시각 설계 7-12 "높이").
        내용 높이는 제목줄을 포함하므로 안쪽 내용 높이에 창틀의 높이를 더한다. 위쪽 모서리는 그대로 둔다."""
        extra = self._frame_extra()
        outer = max(DIALOG_MIN_HEIGHT, min(page.content_height() + extra, self._avail_height()))
        self.setMinimumSize(width, max(0, DIALOG_MIN_HEIGHT - extra))
        self.setMaximumWidth(width)
        self.resize(width, outer - extra)

    def refit_dialog(self) -> None:
        """열려 있는 동안 내용 높이가 바뀌었을 때(점검 줄 · 띠 · 모델 카드 · 사전 지식 표의 행 수) 같은 규칙으로 다시 정한다."""
        try:
            page = self.stack.currentWidget()
            width = getattr(page, "WIDTH", None)
            if width is None or not self._dialog_sized:
                return
            self._fit_dialog_height(page, width)
        except RuntimeError:        # 지연 호출이 도착하기 전에 창이 삭제되었다
            return

    def showEvent(self, ev) -> None:  # noqa: N802 (Qt)
        super().showEvent(ev)
        QTimer.singleShot(0, self.refit_dialog)          # 창이 나온 뒤에야 제목줄의 높이를 안다

    def _on_state(self, old, new) -> None:
        self._show_for(new)
        cb = getattr(self, "on_state_change", None)      # 메뉴 · 입력창의 활성을 전이 때 곧바로 맞춘다(D-072)
        if cb is not None:
            cb(old, new)

    def acknowledge_first_run(self) -> None:
        if self.machine.state is appstate.State.FIRST_RUN:
            self.machine.acknowledge_first_run()

    def session_started(self) -> None:
        self.machine.start_session()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt)
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:      # D-111 · 결정 0074 2항: 설정 창이 메인 창의 최소화를 따른다
            cb = getattr(self, "on_minimized_changed", None)
            if cb is not None:
                cb(self.isMinimized())

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        # ①②: 창 닫기는 앱 종료. ③④: 창만 닫고 세션 · 프로세스는 그대로이다(AC-FR14-7).
        if appstate.close_window_quits(self.machine.state):
            self.quit_requested.emit()
        event.accept()

    def show_main_window(self) -> None:
        """닫혀 있던 메인 창을 다시 연다(상태 아이콘 "앱 창 열기" · Dock · 앱 메뉴 "메인 창", AC-FR14-8). 상태는 바꾸지 않는다."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def request_quit(self) -> str:
        """⌘Q · "종료": 세션 시작 전은 즉시 종료, 세션 중은 종료 흐름, 종료 처리 중은 종료 창의 그 단계 단추와 같게 처리한다(결정 0169). 처리 결과를 반환한다."""
        action = appstate.resolve_quit(self.machine.state)
        if action == "quit_now":
            self.quit_requested.emit()
        elif action == "end_flow":
            self.end_flow_requested.emit()
        elif action == "already_ending":
            self.ending_quit_requested.emit()
        return action

    def request_end_session(self) -> bool:
        """"세션 종료…": 세션 중일 때만 종료 흐름을 요청한다."""
        if self.machine.state is appstate.State.IN_SESSION:
            self.end_flow_requested.emit()
            return True
        return False
