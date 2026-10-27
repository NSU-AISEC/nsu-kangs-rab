"""[정지] 확인 창 (결정 0149, 시안 "5-1 종료 확인", FR-11 "정지 확인 창").

메인 창 앞의 모달 창(560 × 250)이다. 제목 · 본문 · 단추 [끝내기] · [계속]. 기본 단추(Return)와 강조는 [계속] 이다.
[계속] · 창 닫기 · Esc 는 모두 계속이다(`rejected`). [끝내기] 는 `end_chosen` 을 낸다.

모달 방식(임의): 비모달(`NonModal`)이며 `show()` 로 연다. 창이 떠 있는 동안에도 수집 · 전사 · 응답 수신이 계속되고,
⌘Q · Dock 의 종료 · 로그아웃의 종료 요청이 왔을 때 호출한 쪽이 `dismiss()` 로 창을 닫고 종료 흐름에 들어간다(FR-11 ⑥).
메인 창의 조작 불가(FR-11 ③)는 창이 떠 있는 동안만 설치하는 이벤트 필터(`MainInputBlock`)가 지킨다: 메인 창의 위젯에 오는
마우스 누름 · 놓음 · 두 번 누름과 키 입력을 버리고 확인 창을 앞으로 가져온다. 휠(전사 · AI 창 스크롤)과 메뉴 막대, 전역 키는 막지 않는다.
창 단위 모달(`WindowModal`, `open()`)과 앱 단위 모달은 쓰지 않는다: macOS 에서 시트가 열려 있으면 ⌘Q 와 종료 Apple 이벤트
(Dock 의 "종료")가 앱에 닿지 않는다(b38 실기, 2026-10-23 09:03). 다시 [정지] 를 누르면 열린 창을 앞으로 가져온다(`request_stop`).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.i18n import t as _t

WIDTH, HEIGHT = 560, 250


class StopConfirm(QDialog):
    end_chosen = Signal()

    def __init__(self, parent, body: str):
        super().__init__(parent)
        self.setObjectName("stop_confirm")
        from .screens import APP_NAME
        self.setWindowTitle(APP_NAME)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setFixedSize(WIDTH, HEIGHT)
        self.setAccessibleName(_t("stopc.new28"))
        self._dismissed = False
        title = QLabel(_t("stopc.new28"))
        title.setObjectName("stop_confirm_title")
        title.setStyleSheet("font-weight: 600; font-size: 17pt;")
        self.body = QLabel(body)
        self.body.setObjectName("stop_confirm_body")
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.btn_end = QPushButton(_t("stopc.new31"))
        self.btn_end.setObjectName("stop_confirm_end")
        self.btn_end.setAutoDefault(False)
        self.btn_end.setAccessibleName(_t("stopc.new31"))
        self.btn_continue = QPushButton(_t("stopc.new32"))
        self.btn_continue.setObjectName("stop_confirm_continue")
        self.btn_continue.setProperty("primary", True)         # 강조(채운 모양)는 [계속] 이다
        self.btn_continue.setDefault(True)
        self.btn_continue.setAccessibleName(_t("stopc.new32"))
        self.btn_end.clicked.connect(self._on_end)
        self.btn_continue.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_end)
        row.addWidget(self.btn_continue)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        lay.addWidget(title)
        lay.addWidget(self.body, 1)
        lay.addLayout(row)

    def _on_end(self) -> None:
        self.accept()
        self.end_chosen.emit()

    def dismiss(self) -> None:
        """종료 요청이 와서 창을 닫는다(계속도 끝내기도 고른 것이 아니다)."""
        self._dismissed = True
        self.done(QDialog.DialogCode.Rejected)

    def was_dismissed(self) -> bool:
        return self._dismissed


class MainInputBlock(QObject):
    """확인 창이 떠 있는 동안 메인 창(`main`)의 위젯에 오는 마우스 누름 · 키 입력을 버린다(FR-11 ③).
    `setEnabled(False)` 는 메인 창 전체를 흐리게 그리므로 쓰지 않는다. 설정 창 등 다른 창과 메뉴 막대는 막지 않는다."""

    _BLOCKED = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
                QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.ContextMenu)

    def __init__(self, main: QWidget, dialog: QWidget, block_all: bool = False):
        super().__init__(dialog)
        self._main, self._dialog = main, dialog
        self._block_all = block_all       # 참이면 `dialog` 의 창을 뺀 이 앱의 모든 창을 막는다(종료 창, 결정 0172 1항)

    def install(self) -> None:
        QApplication.instance().installEventFilter(self)

    def remove(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt)
        if ev.type() not in self._BLOCKED or not isinstance(obj, QWidget):
            return False
        try:
            w = obj.window()
            if self._block_all:
                if w is self._dialog:
                    return False
            elif w is not self._main:
                return False
        except RuntimeError:
            return False
        if ev.type() == QEvent.Type.MouseButtonPress:
            self._dialog.raise_()
            self._dialog.activateWindow()
        return True
