"""정리 문서를 만드는 동안 표시하는 창 (K-16; FR-13 "종료 흐름", AC-FR13-5; 시안 `EndDialog`, 결정 0068).

폭 640 의 앱 모달 창이다. 제목 · 부제 · 파일 세 줄(transcript.txt · 정리 문서 · captures/)의 상태 알약 · 진행 막대 · 저장 위치,
아래 줄에 버튼 둘. 상태마다 버튼이 다르다: 진행 중 [취소] + 꺼진 [폴더 열기], 완료 [닫기] + 기본 [폴더 열기],
실패 [폴더 열기] + 기본 [정리 문서 다시 만들기]. 막는 대화 상자가 아니라 `open()` 으로 연다.
실패 상태에는 [닫기] 가 없으므로 창 닫기(Esc · 닫기 단추)가 `close_requested` 이다. 진행 중에는 창을 닫지 못한다.
"""
from __future__ import annotations
from ..core.endflow import format_elapsed
from ..core.i18n import t as _t, tn

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

WORKING_TITLE = _t("end.working_title")
WORKING_SUB = _t("end.working_sub")
DONE_TITLE = _t("end.done_title")
DONE_SUB = _t("end.done_sub")
FAILED_TITLE = _t("end.failed_title")
FAILED_SUB = _t("end.failed_sub")
# 호환: 이전 이름(진행 · 완료 · 실패 한 줄 안내)
WORKING_TEXT = WORKING_TITLE
DONE_TEXT = DONE_TITLE
FAILED_TEXT = FAILED_SUB

WIDTH = 640
MIN_HEIGHT = 420
_PILL = {"ok": ("label.result_done", "end_pill_ok"), "run": ("label.result_running", "end_pill_run"), "bad": ("label.result_failed", "end_pill_bad")}

_REASONS = {"rate_limit": _t("end.reasons"), "no_claude": _t("end.reasons_2"), "unknown": "", "no_text": _t("end.reasons_3"), "io": _t("end.reasons_4"),
            "process_exit": _t("end.reasons_5"), "timeout": _t("end.reasons_6"), "auth": _t("end.reasons_7")}


class _Row(QWidget):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        self.pill = QLabel("")
        self.pill.setFixedWidth(56)
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name = QLabel(name)
        self.name.setObjectName("end_name")
        self.note = QLabel("")
        self.note.setObjectName("end_note")
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(self.name)
        col.addWidget(self.note)
        lay.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(col, 1)

    def set_state(self, state: str, note: str) -> None:
        text, obj = _PILL[state]
        self.pill.setText(_t(text))
        self.pill.setObjectName(obj)
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        self.note.setText(note)


class _ActivateFilter(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt)
        t = ev.type()
        if t in (QEvent.Type.ApplicationActivate, QEvent.Type.WindowActivate, QEvent.Type.Show):
            d = self._dialog
            try:
                other = not isinstance(obj, QWidget) or obj.window() is not d
                if other and d.isVisible():
                    d._raise_later()
            except RuntimeError:
                pass
        return False


class EndDialog(QDialog):
    cancel_requested = Signal()
    open_folder_requested = Signal()
    close_requested = Signal()
    retry_requested = Signal()
    visibility_changed = Signal(bool)      # 열림 · 닫힘(앱 메뉴의 "앱 정보" · "설정…" 을 끄고 켠다, D-186 후속)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("end.init___147"))
        # 결정 0172 1항: 앱 전체 모달은 Dock "종료" · Apple 이벤트 quit · ⌘Q 가 도착하지 못하게 한다(D-184).
        # 비모달로 두고 `MainInputBlock` 이 열려 있는 동안 이 창을 뺀 앱의 모든 창의 마우스 · 키 입력을 막는다.
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._input_block = None
        self.setFixedWidth(WIDTH)
        self.setMinimumHeight(MIN_HEIGHT)
        self._state = "working"
        self._programmatic = False
        self._segments = 0
        self._captures = 0
        self._qa = 0
        self._doc_name = "lecture.md"
        self.title = QLabel(WORKING_TITLE)
        self.title.setObjectName("end_title")
        self.message = QLabel(WORKING_SUB)             # 부제(사유 포함)
        self.message.setObjectName("end_sub")
        self.message.setWordWrap(True)
        self.path_label = QLabel("")
        self.path_label.setObjectName("end_path")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.rows_frame = QFrame()
        self.rows_frame.setObjectName("doc_panel")
        rl = QVBoxLayout(self.rows_frame)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.row_transcript = _Row("transcript.txt")
        self.row_doc = _Row(self._doc_name)
        self.row_captures = _Row("captures/")
        for r in (self.row_transcript, self.row_doc, self.row_captures):
            rl.addWidget(r)
        self.bar = QProgressBar()
        self.bar.setObjectName("end_progress")
        self.bar.setRange(0, 0)                          # 첫 절 전 · 절 수를 모르는 경우는 불확정 막대이다(결정 0154)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.progress_text = QLabel("")
        self.progress_text.setObjectName("end_progress_text")
        self.progress_text.setWordWrap(False)
        self.bar_row = QWidget()
        brl = QHBoxLayout(self.bar_row)
        brl.setContentsMargins(0, 0, 0, 0)
        brl.setSpacing(12)
        brl.addWidget(self.bar, 1, Qt.AlignmentFlag.AlignVCenter)
        brl.addWidget(self.progress_text, 0, Qt.AlignmentFlag.AlignVCenter)
        self._provider = None
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh_progress)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(28, 22, 28, 22)
        bl.setSpacing(14)
        bl.addWidget(self.title)
        bl.addWidget(self.message)
        bl.addWidget(self.rows_frame)
        bl.addWidget(self.bar_row)
        bl.addWidget(self.path_label)
        bl.addStretch(1)

        self.cancel_button = QPushButton(_t("label.cancel"))
        self.close_button = QPushButton(_t("end.init___149"))
        self.folder_button = QPushButton(_t("end.init___150"))
        self.retry_button = QPushButton(_t("end.init___151"))
        bottom = QFrame()
        bottom.setObjectName("win_bottom")
        bottom.setFixedHeight(56)
        row = QHBoxLayout(bottom)
        row.setContentsMargins(28, 0, 28, 0)
        row.setSpacing(10)
        row.addStretch(1)
        for b in (self.cancel_button, self.close_button, self.folder_button, self.retry_button):
            b.setFixedHeight(36)
            row.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(body, 1)
        lay.addWidget(bottom)
        self.cancel_button.clicked.connect(self._cancel)
        self.folder_button.clicked.connect(self.open_folder_requested.emit)
        self.close_button.clicked.connect(self.close_requested.emit)
        self.retry_button.clicked.connect(self._retry)
        self.set_info()
        self._apply("working")

    # ---- 내용 ----
    def set_info(self, segments: int = 0, captures: int = 0, qa: int = 0, folder: str = "", doc_name: Optional[str] = None,
                 title: str = "") -> None:
        """파일 줄의 설명에 쓰는 값(조각 · 캡처 · 질의응답 수, 저장 위치)을 할당한다."""
        self._segments, self._captures, self._qa = segments, captures, qa
        if doc_name:
            self._doc_name = doc_name
            self.row_doc.name.setText(doc_name)
        self._title = title
        self.path_label.setText(_t("end.set_info_152") % folder if folder else "")
        self._apply(self._state)

    def _apply(self, state: str, reason: str = "") -> None:
        self._state = state
        seg = tn("end.seg", self._segments) % self._segments
        cap = tn("end.cap", self._captures) % self._captures
        if state == "working":
            self.title.setText(WORKING_TITLE)
            self.message.setText(WORKING_SUB)
            self.row_transcript.set_state("ok", _t("end.apply_155") % seg)
            self.row_doc.set_state("run", tn("end.apply_156", self._qa) % (cap, self._qa))
            self.row_captures.set_state("ok", _t("end.apply_157") % cap)
        elif state == "done":
            self.title.setText(DONE_TITLE)
            self.message.setText(DONE_SUB)
            self.row_transcript.set_state("ok", seg)
            self.row_doc.set_state("ok", getattr(self, "_title", "") or _t("end.apply_158"))
            self.row_captures.set_state("ok", tn("end.apply_159", self._captures) % self._captures)
        else:
            self.title.setText(FAILED_TITLE)
            sub = _t("end.sub_2") % reason if reason else _t("end.sub")
            self.message.setText(sub + FAILED_SUB)
            self.row_transcript.set_state("ok", _t("end.apply_155") % seg)
            self.row_doc.set_state("bad", _t("end.apply_162"))
            self.row_captures.set_state("ok", tn("end.apply_159", self._captures) % self._captures)
        working, done, fail = state == "working", state == "done", state == "fail"
        self.bar_row.setVisible(working)
        if working:
            self._timer.start()
            self.refresh_progress()
        else:
            self._timer.stop()
        self.cancel_button.setVisible(working)
        self.close_button.setVisible(done)
        self.folder_button.setVisible(True)
        self.retry_button.setVisible(fail)
        self.cancel_button.setEnabled(True)
        self.folder_button.setEnabled(not working)           # 진행 중에는 꺼 둔다(시안)
        self._set_primary(self.folder_button, done)
        self._set_primary(self.retry_button, fail)
        default = self.folder_button if done else self.retry_button if fail else None
        for b in (self.cancel_button, self.close_button, self.folder_button, self.retry_button):
            b.setAutoDefault(False)
            b.setDefault(b is default)

    @staticmethod
    def _set_primary(button: QPushButton, on: bool) -> None:
        button.setObjectName("primary" if on else "")
        button.style().unpolish(button)
        button.style().polish(button)

    # ---- 진행 표시 (결정 0154) ----
    def set_progress_provider(self, provider) -> None:
        """`provider()` 는 (n, N, 경과 초, 조각을 받았는가) 를 반환한다(`endflow.SectionProgress.snapshot`)."""
        self._provider = provider
        self.refresh_progress()

    def refresh_progress(self) -> None:
        if self._provider is None:
            self.progress_text.setText("")
            return
        try:
            n, total, elapsed, _streamed = self._provider()
        except Exception:
            return
        el = _t("endprog.new41").replace("{mm:ss}", format_elapsed(elapsed))
        if total <= 0:
            self.bar.setRange(0, 0)
            self.progress_text.setText(el)
            return
        if n <= 0:
            self.bar.setRange(0, 0)
            head = _t("endprog.new39")
        else:
            self.bar.setRange(0, total)
            self.bar.setValue(n)
            key = "endprog.new40" if n >= total else "endprog.new38"
            head = _t(key).replace("{n}", str(n)).replace("{N}", str(total))
        self.progress_text.setText(head + " · " + el)

    # ---- 상태 전환 ----
    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_requested.emit()

    def _retry(self) -> None:
        self.show_working()
        self.retry_requested.emit()

    def show_working(self) -> None:
        self._apply("working")

    def show_done(self, name: str) -> None:
        if name:
            self._doc_name = name
            self.row_doc.name.setText(name)
        self._apply("done")

    def show_failed(self, kind: str, detail: str = "") -> None:
        self._apply("fail", _REASONS.get(kind or "", ""))     # 알 수 없는 종류의 영문 코드는 화면에 쓰지 않는다(D-102)

    @property
    def state(self) -> str:
        return self._state

    # ---- 닫기 ----
    def open(self) -> None:             # noqa: A003 (Qt) `QDialog.open()` 은 창 모달로 바꾸므로 쓰지 않는다
        from .stopconfirm import MainInputBlock
        self.show()
        if self._input_block is None and self.parent() is not None:
            self._input_block = MainInputBlock(self.parent().window(), self, block_all=True)
            self._input_block.install()
            self._activate_filter = _ActivateFilter(self)          # D-186: 다른 창의 활성화 뒤에도 종료 창이 위에 남게 한다(창의 자식이어서 창이 삭제되면 함께 제거된다)
            QApplication.instance().installEventFilter(self._activate_filter)
        self.visibility_changed.emit(True)
        self._raise_later()

    def _to_front(self) -> None:
        try:
            if not self.isVisible() or self._programmatic:
                return
            if QApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
                return                  # 앱이 활성일 때만 올린다: 다른 앱이 앞에 있으면 그 앱의 창을 빼앗지 않는다
            self.raise_()
            self.activateWindow()
        except RuntimeError:
            pass                        # 예약한 사이에 창이 삭제되었다

    def _raise_later(self) -> None:
        """운영체제가 창 순서를 바꾼 뒤(Dock 아이콘 · 메인 창 클릭의 활성화)에 종료 창을 다시 맨 위로 올린다."""
        QTimer.singleShot(0, self._to_front)


    def hideEvent(self, event) -> None:  # noqa: N802 (Qt)
        blk, self._input_block = self._input_block, None
        if blk is not None:
            blk.remove()
            app = QApplication.instance()
            f = getattr(self, "_activate_filter", None)
            if app is not None and f is not None:
                app.removeEventFilter(f)
            self.visibility_changed.emit(False)
        super().hideEvent(event)

    def dismiss(self) -> None:
        """호출한 쪽이 창을 닫는다. `close_requested` 를 내지 않는다."""
        self._programmatic = True
        self.close()

    def reject(self) -> None:           # Esc
        if self._programmatic:
            return
        if self._state == "working":
            if self.cancel_button.isEnabled():
                self._cancel()          # VD 261행: 정리 문서를 만드는 중의 Esc 는 [취소] 와 같다
            return
        self.close_requested.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        if self._programmatic:
            event.accept()
            return
        if self._state == "working":
            event.ignore()
            return
        event.ignore()                  # 창을 닫는 일은 호출한 쪽이 `dismiss()` 로 한다
        self.close_requested.emit()
