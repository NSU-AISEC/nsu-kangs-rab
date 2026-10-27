"""메뉴 막대 · 상태 아이콘 · 창 다시 열기 (K-13; FR-14 · FR-15 의 메뉴 항목).

- 메뉴 구조(`MENU_SPEC`)와 상태별 활성 규칙(`core.appstate.is_active`)은 표 데이터이며 Qt 없이 대조할 수 있다.
- 메뉴 막대는 부모 없는 `QMenuBar` 이다(macOS 에서 메인 창이 닫혀도 메뉴 막대가 남는다).
- 항목을 고르면 `command(id)` 를 낸다. 실제 동작(요청 · 종료 흐름 · 창)은 호출한 쪽이 한다.
- 상태 아이콘 메뉴의 항목은 같은 `command` id 를 쓴다(AC-FR14-4: 같은 요청 · 같은 동작).
"""
from __future__ import annotations
from ..core.i18n import t as _t

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTranslator, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMenuBar, QSystemTrayIcon, QWidget

from ..core import appstate, i18n, resources
from . import screens, theme

APP_MENU = screens.APP_NAME

# (메뉴 제목, [(command id, 문구, 단축키 또는 None)]). id 가 `appstate.item_ids()` 에 있으면 그 상태 규칙을 따른다.
MENU_SPEC = (
    (APP_MENU, (
        ("app.about", _t("menu.mac_app_menu_text"), None),
        ("app.settings", _t("menu.mac_app_menu_text_2"), "Ctrl+,"),       # Qt 의 Ctrl 은 macOS 에서 ⌘ 이다
        ("app.hide", _t("menu.mac_app_menu_text_3"), "Ctrl+H"),
        ("app.hide_others", _t("menu.mac_app_menu_text_4"), "Ctrl+Alt+H"),
        ("app.show_all", _t("menu.mac_app_menu_text_5"), None),
        ("app.quit", _t("label.quit"), "Ctrl+Q"),
    )),
    (_t("menu.menu_spec"), (
        ("session.open_folder", _t("end.init___150"), None),
        ("session.rebuild_summary", _t("menu.menu_spec_2"), None),
        ("session.pause", _t("pause.new20"), None),          # 결정 0147: 단축키 없음. 수집 중일 때만 활성
        ("session.play", _t("pause.new19"), None),           # 일시 정지 중 · 수집 전에만 활성(결정 0150)
    )),
    (_t("menu.menu_spec_12"), (
        ("window.main", _t("menu.menu_spec_13"), None),
        ("window.frame", _t("menu.m_117"), None),       # "액자 보이기" · "액자 숨기기" 로 바뀐다
        ("window.minimize", _t("menu.menu_spec_14"), "Ctrl+M"),
        ("window.zoom", _t("menu.menu_spec_15"), None),
    )),
    (_t("menu.menu_spec_16"), (
        ("help.first_run_notice", _t("menu.menu_spec_17"), None),
        ("help.permissions", _t("menu.menu_spec_18"), None),
    )),
)

# 메뉴 막대에는 요청 메뉴가 없다(결정 0156). 앱 창 안 고찰 키 · 전역 액자 캡처 키의 동작은 메뉴에 없는 이 두 동작이 맡고,
# 상태 아이콘 메뉴의 두 항목이 같은 id 를 쓴다. 키는 `attach_shortcuts` 로 창에 연결해야 동작한다.
REQUEST_ACTIONS = (
    ("request.trigger", _t("newlang.new42")),
    ("request.capture", _t("newlang.new44")),
)

TRAY_ITEMS = (  # 상태 줄(비활성 글) 다음의 항목: (command id, 문구)
    ("request.trigger", _t("newlang.new42")),
    ("request.capture", _t("newlang.new44")),
    ("window.frame", _t("menu.m_117")),
    ("window.main", _t("menu.tray_items_2")),
)

# macOS 의 앱 메뉴에는 운영체제(Qt 의 기본 메뉴)가 이미 숨기기 · 다른 앱 숨기기 · 모두 보기를 둔다. 같은 항목을 일반 메뉴에
# 또 더하면 같은 이름의 둘째 메뉴가 생기므로(D-078) macOS 에서는 메뉴에 더하지 않는다. 이름은 아래 번역기가 정한다(D-079).
NATIVE_APP_ITEMS = ("app.hide", "app.hide_others", "app.show_all")

# Qt 의 macOS 앱 메뉴 문구(문맥 MAC_APPLICATION_MENU 또는 QMenuBar) → 기능 정의 표의 한국어 항목 이름.
MAC_APP_MENU_TEXT = {
    "About %1": _t("menu.mac_app_menu_text"), "Preferences...": _t("menu.mac_app_menu_text_2"), "Services": _t("menu.mac_app_menu_text_6"), "Hide %1": _t("menu.mac_app_menu_text_3"),
    "Hide Others": _t("menu.mac_app_menu_text_4"), "Show All": _t("menu.mac_app_menu_text_5"), "Quit %1": _t("label.quit"),
}


class MacAppMenuTranslator(QTranslator):
    """macOS 앱 메뉴의 표준 항목 이름을 표의 한국어로 바꾼다(D-079). 메뉴 막대를 만들기 전에 설치한다.
    표에 없는 문구는 빈 문자열을 반환해 번역하지 않은 것으로 둔다."""

    def translate(self, context, source_text, disambiguation=None, n=-1) -> Optional[str]:  # noqa: N802 (Qt)
        if context in ("MAC_APPLICATION_MENU", "QMenuBar"):
            return MAC_APP_MENU_TEXT.get(source_text)
        return None

    def isEmpty(self) -> bool:  # noqa: N802 (Qt)
        return False


# 입력 칸의 오른쪽 클릭 메뉴(Qt 표준 문맥 메뉴)의 항목 이름: 앱 언어가 한국어이면 아래 한국어, English 이면 Qt 의 영어 그대로이다(D-160).
# 문맥은 QLineEdit(한 줄 입력 칸)와 QWidgetTextControl(여러 줄 입력 칸)이다. 한국어 낱말은 결정 0153 으로 표에서 빠진 옛 편집 메뉴
# 항목(UI-103 ~ UI-107 · UI-109)과 같게 하고, 표에 없던 "다시 실행" 은 기능 정의 FR-14 의 단축키 설명 어휘를 따랐다(임의).
TEXT_MENU_KO = {
    "&Undo": "실행 취소", "&Redo": "다시 실행", "Cu&t": "오려내기", "&Copy": "복사", "&Paste": "붙여넣기",
    "Delete": "삭제", "Select All": "모두 선택",
}


class TextMenuTranslator(QTranslator):
    """입력 칸의 오른쪽 클릭 메뉴 항목 이름을 앱 언어로 바꾼다(D-160). 메뉴를 만들 때마다 현재 앱 언어를 확인한다."""

    def translate(self, context, source_text, disambiguation=None, n=-1) -> Optional[str]:  # noqa: N802 (Qt)
        if context in ("QLineEdit", "QWidgetTextControl") and i18n.language() == "ko":
            return TEXT_MENU_KO.get(source_text)
        return None

    def isEmpty(self) -> bool:  # noqa: N802 (Qt)
        return False


def install_text_menu_translator(app) -> TextMenuTranslator:
    tr = TextMenuTranslator(app)
    app.installTranslator(tr)
    return tr


def install_mac_menu_translator(app) -> MacAppMenuTranslator:
    tr = MacAppMenuTranslator(app)
    app.installTranslator(tr)
    return tr


FRAME_SHOW, FRAME_HIDE = _t("menu.m_117"), _t("frame.tips_2")


def menu_structure() -> list:
    """(메뉴 제목, [항목 문구]) 목록. 구분선은 없다. AC-FR14-1 의 대조용."""
    return [(title, [label for _id, label, _s in items]) for title, items in MENU_SPEC]


def tray_status_text(state: appstate.State, elapsed_s: Optional[int] = None, capture_state: Optional[str] = None) -> str:
    """상태 줄(비활성 글). 예: `세션 중 01:12:30 · 수집 중`."""
    if state is appstate.State.IN_SESSION:
        t = ""
        if elapsed_s is not None:
            h, r = divmod(max(0, int(elapsed_s)), 3600)
            t = " %02d:%02d:%02d" % (h, r // 60, r % 60)
        out = _t("menu.out") + t
        if capture_state:
            out += " · " + menu_collect_state(capture_state)
        return out
    if state is appstate.State.ENDING:
        return _t("menu.tray_status_text_126")
    return _t("menu.tray_status_text_127")


def tray_dot(state: appstate.State, capture_state: Optional[str] = None) -> Optional[str]:
    """상태 점: 세션이 없으면 없음, 세션 중이면 `info`, 수집 중단이나 오류이면 `warn`."""
    if state in (appstate.State.IN_SESSION, appstate.State.ENDING):
        return "warn" if menu_collect_state(capture_state) in (COLLECT_STOPPED, COLLECT_ERROR) else "info"
    return None


COLLECT_ACTIVE, COLLECT_STOPPED, COLLECT_ERROR = _t("label.capture_running"), _t("menu.m_129"), _t("menu.m_130")      # 표시 어휘
# 앱의 수집 상태 값(`controller.COLLECT_*`: 수집 중 · 입력 없음 · 중단)을 상태 아이콘 어휘로 바꾼다(D-070)
_APP_TO_MENU = {appstate.COLLECT_STOPPED: COLLECT_STOPPED, appstate.COLLECT_RUNNING: COLLECT_ACTIVE,
                appstate.COLLECT_NO_INPUT: _t("state.m_273"),
                appstate.COLLECT_PAUSED: _t("pause.new23"), appstate.COLLECT_BEFORE: _t("before.new33")}


def menu_collect_state(capture_state: Optional[str]) -> Optional[str]:
    return _APP_TO_MENU.get(capture_state, capture_state) if capture_state else capture_state


_ICON_STATE = {None: "none", "info": "session", "warn": "warn"}      # tray_dot 의 값 → 아이콘 상태


def _icon(dot: Optional[str]) -> QIcon:
    """만화 얼굴의 색 그림(결정 0085, 시각 설계 7-13). 상태는 점이 아니라 사각형 배경색이다(결정 0122: 없음 회색 · 세션 파랑 · 경고 주황, 머리카락은 갈색). 템플릿(마스크)이 아니므로 막대 외관을 따라 바뀌지 않는다.
    18 × 18 pt: @1x 18 px 와 @2x 36 px 의 미리 만든 그림을 쓴다."""
    state = _ICON_STATE[dot]
    ic = QIcon()
    for px, dpr in ((18, 1), (36, 2)):
        pm = QPixmap(str(resources.menubar_icon_path(state, px)))
        pm.setDevicePixelRatio(dpr)
        ic.addPixmap(pm)
    ic.setIsMask(False)
    return ic


DIALOG_BLOCKED_ITEMS = ("app.about", "app.settings")


class MenuController(QObject):
    command = Signal(str)

    def __init__(self, trigger_key: str = "F2", capture_key: str = "", parent=None):
        super().__init__(parent)
        self.menubar = QMenuBar(None)
        self.actions: dict = {}
        self._menu_actions: dict = {}
        self._tray_actions: dict = {}
        self._state = appstate.State.BEFORE_SESSION
        self._has_input = False
        self._dialog_block = False        # 종료 창이 떠 있는 동안 "앱 정보" · "설정…" 을 끈다(결정 0172 1항)
        for title, items in MENU_SPEC:
            menu = self.menubar.addMenu(title)
            for cid, label, shortcut in items:
                a = QAction(label, menu)
                if shortcut:
                    a.setShortcut(QKeySequence(shortcut))
                a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
                if cid == "app.about":
                    a.setMenuRole(QAction.MenuRole.AboutRole)
                elif cid == "app.settings":
                    a.setMenuRole(QAction.MenuRole.PreferencesRole)
                elif cid == "app.quit":
                    a.setMenuRole(QAction.MenuRole.QuitRole)
                a.triggered.connect(lambda _c=False, c=cid: self._fire(c))
                if not (cid in NATIVE_APP_ITEMS and QGuiApplication.platformName() == "cocoa"):
                    menu.addAction(a)
                self.actions[cid] = a
        for cid, label in REQUEST_ACTIONS:        # 메뉴에 두지 않는 동작: 키만 받는다(결정 0156)
            a = QAction(label, self)
            a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            a.triggered.connect(lambda _c=False, c=cid: self._fire(c))
            self.actions[cid] = a
        self.set_trigger_key(trigger_key)
        self.set_capture_key(capture_key)
        # 상태 아이콘
        self.tray = QSystemTrayIcon(_icon(None))
        self.tray_menu = QMenu()
        self.status_action = QAction(tray_status_text(self._state), self.tray_menu)
        self.status_action.setEnabled(False)
        self.tray_menu.addAction(self.status_action)
        for cid, label in TRAY_ITEMS:
            a = QAction(label, self.tray_menu)
            a.triggered.connect(lambda _c=False, c=cid: self._fire(c))
            self.tray_menu.addAction(a)
            self._tray_actions[cid] = a
        self.tray.setContextMenu(self.tray_menu)
        self.dot: Optional[str] = None
        self.set_frame_visible(False)
        self.refresh(self._state)

    def attach_shortcuts(self, widget) -> None:
        """메뉴에 없는 동작(고찰 · 액자 캡처)의 키가 앱 안에서 동작하도록 창에 연결한다. 컨트롤러가 메인 창으로 한 번 호출한다."""
        for cid, _label in REQUEST_ACTIONS:
            widget.addAction(self.actions[cid])

    def _fire(self, cid: str) -> None:
        self.command.emit(cid)

    # --- 동적 표시 ---
    def set_trigger_key(self, key: str) -> None:
        """트리거 항목에 설정된 트리거 키를 표시한다(AC-FR14-2). 키를 바꾸면 표시가 바뀐다."""
        a = self.actions["request.trigger"]
        a.setShortcut(QKeySequence(key) if key else QKeySequence())
        a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

    def set_capture_key(self, key: str) -> None:
        a = self.actions["request.capture"]
        a.setShortcut(QKeySequence(key) if key else QKeySequence())
        a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

    def set_frame_visible(self, visible: bool) -> None:
        """액자가 보이는 동안 두 항목의 문구는 "액자 숨기기" 이다(AC-FR14-6)."""
        label = FRAME_HIDE if visible else FRAME_SHOW
        self.actions["window.frame"].setText(label)
        self._tray_actions["window.frame"].setText(label)

    def set_status(self, state: appstate.State, elapsed_s: Optional[int] = None, capture_state: Optional[str] = None) -> None:
        self._capture_state = capture_state
        self.status_action.setText(tray_status_text(state, elapsed_s, capture_state))
        dot = tray_dot(state, capture_state)
        if dot != self.dot:
            self.dot = dot
            self.tray.setIcon(_icon(dot))
        self.refresh(state)

    def refresh(self, state: appstate.State, has_input: bool = False) -> None:
        """상태별 활성 · 비활성(AC-FR14-3). 표에 없는 항목(최소화 · 숨기기 등)은 항상 활성이다."""
        self._state, self._has_input = state, has_input
        play, pause, _stop, _emph = appstate.transport_enabled(getattr(self, "_capture_state", None), state is appstate.State.ENDING)
        for cid, a in self.actions.items():
            try:
                on = appstate.is_active(cid, state, has_input=has_input)
            except KeyError:
                on = True
            if state is appstate.State.IN_SESSION:       # 재생 · 일시 정지는 수집 상태가 정한다(FR-14, 결정 0147 · 0150)
                if cid == "session.play":
                    on = play
                elif cid == "session.pause":
                    on = pause
            if self._dialog_block and cid in DIALOG_BLOCKED_ITEMS:
                on = False
            a.setEnabled(on)
        for cid, a in self._tray_actions.items():
            try:
                a.setEnabled(appstate.is_active(cid, state))
            except KeyError:
                a.setEnabled(True)

    def set_dialog_block(self, on: bool) -> None:
        self._dialog_block = bool(on)
        self.refresh(self._state, self._has_input)

    def show_tray(self) -> bool:
        """상태 아이콘을 표시한다. 시스템 트레이가 없는 환경(offscreen 등)에서는 표시하지 않고 False."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        self.tray.show()
        return True


class ReopenFilter(QObject):
    """Dock 아이콘을 눌러 앱이 다시 활성화되면 `reopen_requested` 를 낸다(AC-FR14-8). 실제 Dock 동작은 실기에서 확인한다."""
    reopen_requested = Signal()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt)
        if ev.type() == QEvent.Type.ApplicationActivate:
            self.reopen_requested.emit()
        return False


class ClickActivateFilter(QObject):
    """D-131: 다른 앱이 맨 앞일 때 메인 창의 어느 곳을 눌러도 앱을 활성화한다(macOS 의 기본 동작, 기능 정의 FR-14).
    눌림 사건은 소비하지 않으므로 [트리거] · [액자 캡처] 는 그 첫 클릭에 실행된다(AC-FR7-24). 대상은 `window` 하나뿐이며
    액자 · 손잡이 창(활성화하지 않는 창, 결정 0080 · 0086)은 다루지 않는다. 원인은 확인하지 못했다(추정: 합성 클릭에서 Qt 가 활성화를 요청하지 않음)."""

    def __init__(self, window, is_active=None, activate=None, parent=None):
        super().__init__(parent)
        self._window = window
        self._is_active = is_active or (lambda: QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive)
        self._activate = activate or self._default_activate
        self.activations = 0

    def _default_activate(self) -> None:
        self._window.raise_()
        self._window.activateWindow()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt)
        if ev.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget) and obj.window() is self._window \
                and not self._is_active():
            self.activations += 1
            self._activate()
        return False
