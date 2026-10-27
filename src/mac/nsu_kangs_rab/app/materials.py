"""사전 지식 화면 (K-19; FR-2, AC-FR2-1 · 2 · 7 · 9 · 10 · 13).

세션을 시작하기 전의 시작 화면에 놓는다(자료는 세션의 첫 요청에 실리므로 시작한 뒤에는 추가하지 않는다).
판정은 `core/materials_view.MaterialsModel`(`ContextStore` 위의 모델)이 하고 이 위젯은 표시한다.
막는 대화 상자를 쓰지 않는다: 선택 창은 `open()` 으로 열고 결과는 신호와 `notice` 문구로 알린다.
"""
from __future__ import annotations
from ..core.i18n import t as _t
from ..core.i18n import t as _t, tn

from typing import Optional, Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..core.materials_view import AddReport, MaterialsModel, RemoveReport

ROW_H = 44                      # 표의 행 높이(7-8 "40px 이상")
HEAD_H = 28                     # 머리 행 높이(7-12)
FOOT_H = 33                     # 바닥 줄 높이(표 상자 안 맨 아래)
BORDER = 2                      # 표 상자 테두리(위 · 아래 각 1)
COLS = (_t("materials.cols"), _t("materials.cols_2"), _t("materials.cols_3"), _t("materials.cols_4"))
COL_W = (64, 84, 160, 60)        # 형식 · 크기 · 문자 수 · [제거] 칸의 폭(이름 칸은 남는 폭, D-216: 문자 수 96 → 160)
COL_ALIGN = (Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignRight, Qt.AlignmentFlag.AlignRight)   # 형식 왼쪽 · 크기와 문자 수는 머리 행 포함 오른쪽
MAX_ROWS = 6                    # 6행(264px)을 넘으면 표 안에서 스크롤한다
FILE_FILTER = _t("materials.file_filter")
PASTE_NAME = _t("materials.paste_name")


class SelectionDialog(QDialog):
    """보류 안내와 선택 창(AC-FR2-13).

    - 목록에는 사전 지식과 보류 자료가 함께 나온다. 하나를 골라 [빼기] 를 누르면 `ContextStore.remove` 가 호출된다.
    - 보류 자료 하나만으로 상한을 넘으면(`cancel_only`) 사실만 표시하고 [취소] 만 제공한다.
    - [취소] 는 보류를 모두 버리며 목록은 바뀌지 않는다.
    """
    removed = Signal(object)        # RemoveReport
    cancelled = Signal(int)         # 버린 보류의 수

    def __init__(self, model: MaterialsModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle(_t("materials.init___192"))
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.held_list = QListWidget()
        self.held_list.setObjectName("held_list")
        self.registered_list = QListWidget()
        self.registered_list.setObjectName("registered_list")
        self.remove_button = QPushButton(_t("materials.init___193"))
        self.cancel_button = QPushButton(_t("label.cancel"))
        lay = QVBoxLayout(self)
        lay.addWidget(self.message)
        lay.addWidget(QLabel(_t("materials.init___194")))
        lay.addWidget(self.held_list)
        lay.addWidget(QLabel(_t("materials.init___195")))
        lay.addWidget(self.registered_list)
        row = QHBoxLayout()
        row.addWidget(self.remove_button)
        row.addWidget(self.cancel_button)
        lay.addLayout(row)
        self.remove_button.clicked.connect(self._on_remove)
        self.cancel_button.clicked.connect(self._on_cancel)
        self.held_list.itemSelectionChanged.connect(lambda: self._sync(self.held_list, self.registered_list))
        self.registered_list.itemSelectionChanged.connect(lambda: self._sync(self.registered_list, self.held_list))
        self.refresh()

    def _sync(self, active: QListWidget, other: QListWidget) -> None:
        if active.selectedItems():
            other.clearSelection()
        self._update_buttons()

    def refresh(self) -> bool:
        """보류가 남아 있으면 내용을 다시 채우고 True 를 반환한다."""
        sel = self.model.selection()
        self.held_list.clear()
        self.registered_list.clear()
        if sel is None:
            self.message.setText("")
            self._update_buttons()
            return False
        self.message.setText(sel.message)
        self.cancel_only = sel.cancel_only
        for h in sel.held:
            it = QListWidgetItem(h.text)
            it.setData(Qt.UserRole, h.id)
            if h.id in sel.sole_ids and not sel.cancel_only:     # 혼합 보류: 단독 초과 자료는 빼기 대상이 아니다
                it.setFlags(it.flags() & ~Qt.ItemIsSelectable)
            self.held_list.addItem(it)
        for r in sel.registered:
            it = QListWidgetItem(r.label)
            it.setData(Qt.UserRole, r.id)
            self.registered_list.addItem(it)
        if sel.cancel_only:             # 사실만 표시한다: 빼기를 제공하지 않는다
            self.registered_list.setEnabled(False)
            self.held_list.setEnabled(False)
        else:
            self.registered_list.setEnabled(True)
            self.held_list.setEnabled(True)
        self._update_buttons()
        return True

    def _selected_id(self) -> Optional[str]:
        for lst in (self.registered_list, self.held_list):
            items = lst.selectedItems()
            if items:
                return items[0].data(Qt.UserRole)
        return None

    def _update_buttons(self) -> None:
        sel_only = getattr(self, "cancel_only", False)
        self.remove_button.setVisible(not sel_only)
        self.remove_button.setEnabled(not sel_only and self._selected_id() is not None)

    def _on_remove(self) -> None:
        mid = self._selected_id()
        if mid is None:
            return
        rep = self.model.remove(mid)
        self.removed.emit(rep)
        if not self.refresh():
            self.accept()

    def _on_cancel(self) -> None:
        n = self.model.cancel()
        self.cancelled.emit(n)
        self.reject()


class MaterialsPanel(QWidget):
    """시작 화면의 사전 지식 영역: 표(머리 행 · 행마다 [제거]) · [파일 추가…] · [글 붙여넣기…] · 바닥 줄 · 알림 문구(AC-FR2-16)."""
    changed = Signal()              # 사전 지식 목록이 바뀌었다(상태 표시줄 갱신용)

    def __init__(self, model: MaterialsModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.setAcceptDrops(True)
        self.footer = QLabel()
        self.footer.setObjectName("materials_footer")
        self.footer.setFixedHeight(FOOT_H)
        self.table = QFrame()                     # 머리 행 + 행 영역(행이 6을 넘으면 안에서 스크롤)
        self.table.setObjectName("materials_table")
        self.head = QFrame()
        self.head.setObjectName("materials_head")
        self.head.setFixedHeight(HEAD_H)
        self.rows_area = QScrollArea()
        self.rows_area.setObjectName("materials_rows")
        self.rows_area.setWidgetResizable(True)
        self.rows_area.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_host = QWidget()
        self._rows_host.setObjectName("materials_rows_host")
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(0)
        self._rows_lay.addStretch(1)
        self.rows_area.setWidget(self._rows_host)
        self._row_labels: list = []
        self.remove_buttons: list = []
        self._head_lay = hl = QHBoxLayout(self.head)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(8)
        for i, name in enumerate(COLS):
            lb = QLabel(name)
            lb.setObjectName("materials_head_cell")
            if i == 0:
                hl.addWidget(lb, 1)
            else:
                lb.setFixedWidth(COL_W[i - 1])
                lb.setAlignment(COL_ALIGN[i - 1] | Qt.AlignmentFlag.AlignVCenter)
                hl.addWidget(lb)
        pad = QLabel("")                            # [제거] 칸(행의 단추와 같은 폭)
        pad.setObjectName("materials_head_cell")   # D-154: 이름이 없으면 전역 라벨 바탕이 칠해진다
        pad.setFixedWidth(COL_W[3])
        hl.addWidget(pad)
        tl = QVBoxLayout(self.table)
        tl.setContentsMargins(0, 0, 0, 0)         # 테두리 1 은 프레임이 이미 뺀다(D-153: 여백을 더하면 바닥 줄이 마지막 행을 덮는다)
        tl.setSpacing(0)
        tl.addWidget(self.head)
        tl.addWidget(self.rows_area)
        tl.addWidget(self.footer)                 # 바닥 줄은 표 상자 안 맨 아래이고 스크롤하지 않는다
        self.notice = QLabel()
        self.notice.setObjectName("materials_notice")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)             # D-150: 문구가 없으면 공간을 차지하지 않는다
        self.add_file_button = QPushButton(_t("materials.init___196"))
        self.paste_button = QPushButton(_t("materials.init___197"))
        self.paste_edit = QPlainTextEdit()
        self.paste_edit.setObjectName("paste_edit")
        self.paste_edit.setPlaceholderText(_t("materials.init___198"))
        self.paste_edit.setMaximumHeight(80)
        self.paste_edit.setVisible(False)
        self.selection_dialog: Optional[SelectionDialog] = None
        self.empty_label = QLabel(_t("materials.init___199"))     # 0행: 상자 없이 이 한 줄만 보인다
        self.empty_label.setObjectName("materials_empty")
        for b in (self.add_file_button, self.paste_button):
            b.setFixedHeight(36)
        lay = QVBoxLayout(self)          # 시안 `Session` 5. 사전 지식: 제목 줄(오른쪽에 단추) · 목록 · 바닥 줄
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel(_t("materials.title"))
        title.setObjectName("section_title")
        head.addWidget(title, 1)
        head.setSpacing(8)
        for b in (self.add_file_button, self.paste_button):
            head.addWidget(b)
        lay.addLayout(head)
        lay.addWidget(self.table)
        lay.addWidget(self.empty_label)
        lay.addWidget(self.paste_edit)
        lay.addWidget(self.notice)
        self.add_file_button.clicked.connect(self._pick_files)
        self.paste_button.clicked.connect(self._on_paste_button)
        self.refresh()

    # ---- 표시 ----
    def _set_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def refresh(self) -> None:
        for w in self._row_widgets():
            self._rows_lay.removeWidget(w)
            w.deleteLater()
        self._row_labels = []
        self.remove_buttons = []
        rows = self.model.rows()
        locked = self.model.selection() is not None            # 보류 중(선택 창이 열려 있는 동안)에는 [제거] 를 누를 수 없다
        for i, r in enumerate(rows):
            self._rows_lay.insertWidget(i, self._make_row(r, locked))
            self._row_labels.append(r.label)
        total = sum(r.chars or 0 for r in rows)
        self.footer.setText(_t("materials.refresh_201") % (len(rows), format(total, ",")))
        # 상자 높이 = 테두리 2 + 머리 행 28 + min(44 × 행 수, 264) + 바닥 줄 33. 행이 없으면 상자 전체(머리 행 · 바닥 줄 포함)를 숨기고 "사전 지식이 없다" 한 줄만 둔다(7-12, AC-FR1-25 · AC-FR2-16)
        body = ROW_H * min(len(rows), MAX_ROWS)
        self.table.setVisible(bool(rows))
        self.empty_label.setVisible(not rows)
        self.rows_area.setFixedHeight(body)
        # D-152: 본문 영역에 세로 스크롤 막대가 보이면(행이 6을 넘을 때) 본문 행의 폭이 막대 폭만큼 줄어 오른쪽 고정 폭 칸들이 왼쪽으로 밀린다.
        # 머리 행의 오른쪽 여백을 같은 폭만큼 늘려 열 위치를 맞춘다.
        bar = self.rows_area.verticalScrollBar().sizeHint().width() if len(rows) > MAX_ROWS else 0
        self._head_lay.setContentsMargins(14, 0, 14 + bar, 0)
        self.table.setFixedHeight(BORDER + HEAD_H + body + FOOT_H)

    def _row_widgets(self) -> list:
        out = []
        for i in range(self._rows_lay.count()):
            w = self._rows_lay.itemAt(i).widget()
            if w is not None:
                out.append(w)
        return out

    @staticmethod
    def format_of(r) -> str:
        """형식 칸: 파일 확장자를 소문자로 쓴다(붙여넣은 글 등 확장자가 없으면 txt)."""
        suf = r.name.rsplit(".", 1)[1].lower() if "." in r.name.strip(".") else ""
        return suf if suf in ("md", "txt", "pdf", "png", "jpg", "jpeg", "gif", "webp") else ("png" if r.kind == "image" and not suf else "txt")

    def _make_row(self, r, locked: bool) -> QFrame:
        row = QFrame()
        row.setObjectName("materials_row")
        row.setFixedHeight(ROW_H)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 1, 14, 0)        # 위 선 1px 아래의 43 에 글을 가운데 둔다(결정 0124)
        lay.setSpacing(8)
        name = QLabel(r.name)
        name.setObjectName("materials_cell")
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(name, 1)
        chars = r.dimensions if r.kind == "image" else tn("materials.chars", r.chars or 0) % format(r.chars or 0, ",")
        for text, w, al in zip((self.format_of(r), r.size_text, chars), COL_W, COL_ALIGN):
            lb = QLabel(text)
            lb.setObjectName("materials_cell")
            lb.setFixedWidth(w)
            lb.setAlignment(al | Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(lb)
        btn = QPushButton(_t("materials.btn"))
        btn.setObjectName("materials_remove")
        btn.setAccessibleName(_t("materials.make_row_204"))
        btn.setFlat(True)
        btn.setFixedSize(COL_W[3], 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setEnabled(not locked)
        btn.clicked.connect(lambda _c=False, mid=r.id: self.remove_id(mid))
        lay.addWidget(btn)
        self.remove_buttons.append(btn)
        return row

    def row_labels(self) -> list:
        return list(self._row_labels)

    # ---- 추가 ----
    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, _t("materials.pick_files_205"), "", FILE_FILTER)
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths: Sequence) -> AddReport:
        rep = self.model.add_paths(paths)
        self._after_add(rep)
        return rep

    def _on_paste_button(self) -> None:
        """첫 클릭은 입력란을 열고, 입력란에 글이 있을 때의 클릭은 추가한다."""
        text = self.paste_edit.toPlainText()
        if self.paste_edit.isHidden():
            self.paste_edit.setVisible(True)
            self.paste_edit.setFocus()
            return
        if text.strip():
            self.add_text(text)
            self.paste_edit.clear()
            self.paste_edit.setVisible(False)

    def add_text(self, text: str, name: str = PASTE_NAME) -> AddReport:
        rep = self.model.add_text(name, text)
        self._after_add(rep)
        return rep

    def _after_add(self, rep: AddReport) -> None:
        lines = []
        for h in rep.facts:             # 파일 크기 초과의 사실은 선택 창보다 먼저 알린다(AC-FR2-10)
            lines.append(h.text)
        lines.extend(rep.unreadable)
        if rep.accepted:
            lines.append(_t("materials.after_add_206") + ", ".join(m.name for m in rep.accepted))
        self._set_notice("\n".join(lines))
        self.refresh()
        self.changed.emit()
        if rep.show_selection:
            self.open_selection()

    # ---- 빼기 · 선택 창 ----
    def remove_id(self, material_id: str) -> RemoveReport:
        rep = self.model.remove(material_id)
        self._after_remove(rep)
        return rep

    def _after_remove(self, rep: RemoveReport) -> None:
        lines = []
        if rep.resolved:
            lines.append(_t("materials.after_add_206") + ", ".join(m.name for m in rep.resolved))
        if rep.dropped:
            lines.append(_t("materials.after_remove_207") + ", ".join(rep.dropped))
        lines.extend(rep.unreadable)
        self._set_notice("\n".join(lines))
        self.refresh()
        self.changed.emit()

    def open_selection(self) -> Optional[SelectionDialog]:
        if self.model.selection() is None:
            return None
        dlg = SelectionDialog(self.model, self)
        dlg.removed.connect(self._after_remove)
        dlg.cancelled.connect(self._on_cancelled)
        self.selection_dialog = dlg
        dlg.open()
        return dlg

    def _on_cancelled(self, n: int) -> None:
        self._set_notice(tn("materials.on_cancelled_208", n) % n if n else "")
        self.refresh()
        self.changed.emit()

    # ---- 끌어 놓기 ----
    def dragEnterEvent(self, e) -> None:       # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:            # noqa: N802
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths)
            e.acceptProposedAction()
