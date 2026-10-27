"""세션 시작 화면 · 설정 화면 · 첫 실행 고지 · 상태 표시줄 (K-11; FR-1 · FR-3 · FR-11 · FR-13 · FR-15 · AC-NF-1).

위젯은 값을 표시하고 신호로 알릴 뿐이다. 모델 호출 · 키체인 · 파일 쓰기는 하지 않는다(호출한 쪽이 한다).
"""
from __future__ import annotations
from ..core.i18n import t as _t
from ..core import labels

import os
import re
from typing import Mapping, Optional

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QListView, QPlainTextEdit, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QStatusBar, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..core import appstate, claude_locator, resources as core_resources, settings
from .keytable import KeyTable

APP_NAME = "Prof. Kang's RAB"
APP_SUBTITLE = "Retrieval-Augmented Brain"
ABOUT_TITLE = _t("menu.mac_app_menu_text")
ABOUT_ORIGIN = (_t("screens.about_origin"))
ABOUT_IMAGE_SIZE = (240, 300)   # 이미지의 표시 크기(점). 1122 x 1402 와 비율이 같다(0.800)

MIC_UNAVAILABLE_TOOLTIP = _t("screens.mic_unavailable_tooltip")   # 결정 0064, AC-FR3-9
MIC_TOOLTIP = _t("screens.mic_tooltip")                  # 마이크 입력을 다시 켤 때 되살린다(AC-FR3-9)
EXTENSION_LABEL = _t("screens.extension_label")
EXTENSION_TOOLTIP = _t("screens.extension_tooltip")
API_FEE_TEXT = _t("screens.api_fee_text")
SAVE_DIR_PLACEHOLDER = _t("screens.save_dir_placeholder")   # 결정 0121, AC-FR13-3
EFFORT_TOOLTIP = _t("screens.effort_tooltip")
FAMILY_TOOLTIP = _t("screens.family_tooltip")

# AC-NF-1: 전사 텍스트와 캡처 · 첨부 이미지가 모델 호출을 통해 Anthropic 으로 전송된다. 시안 `FirstRun` 의 문구이다.
FIRST_RUN_HEADING = _t("screens.first_run_heading")
FIRST_RUN_INTRO = (_t("screens.first_run_intro"))
FIRST_RUN_FACTS = (
    (_t("label.tag_local"), _t("screens.first_run_facts_2")),
    (_t("screens.first_run_facts_3"), _t("screens.first_run_facts_4")),
    (_t("label.tag_local"), _t("screens.first_run_facts_5")),
    (_t("label.tag_download"), _t("newlang.new61")),                # NEW-61(결정 0167), AC-NF-1: 정보 색 태그
)
# 기능 정의 AC-NF-1 의 원문이다(고치지 않는다).
FIRST_RUN_PERMISSIONS = (
    ("screen_recording", _t("ctl.names"), _t("screens.first_run_permissions")),
    ("system_audio", _t("screens.first_run_permissions_2"), _t("screens.first_run_permissions_3")),
)
FIRST_RUN_PERMISSION_FOOT = _t("screens.first_run_permission_foot")
FIRST_RUN_UNDERSTOOD = _t("screens.first_run_understood")
FIRST_RUN_LINES = (FIRST_RUN_FACTS[1][1],)

PROVIDERS = (
    ("claude_subscription", _t("screens.providers"), True),
    ("claude_api", "Claude API", True),
    ("chatgpt_subscription", _t("screens.providers_2"), False),
    ("chatgpt_api", "ChatGPT API", False),
    ("gemini_subscription", _t("screens.providers_3"), False),
    ("gemini_api", "Gemini API", False),
)
SOURCES = (("system_sound", _t("label.source_system_sound"), True), ("system_mic", _t("label.source_system_mic"), False))   # (값, 이름, 선택 가능)
ACTIVE_SOURCES = tuple(sid for sid, _l, ok in SOURCES if ok)
KINDS = ("수업", "회의")


def source_combo(current: Optional[str]) -> QComboBox:
    """음성 소스. 비활성 항목("시스템 마이크")은 고를 수 없고 도움말을 단다(결정 0064, AC-FR3-4 · AC-FR3-9).
    설정에 비활성 항목이 남아 있으면 처음 선택은 시스템 사운드로 대체한다."""
    box = QComboBox()
    model = QStandardItemModel(box)
    for sid, label, active in SOURCES:
        it = QStandardItem(label)
        it.setData(sid, Qt.ItemDataRole.UserRole)
        if not active:
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            it.setData(MIC_UNAVAILABLE_TOOLTIP, Qt.ItemDataRole.ToolTipRole)
        model.appendRow(it)
    box.setModel(model)
    set_combo_data(box, current if current in ACTIVE_SOURCES else "system_sound")
    return box


def provider_combo(current: str) -> QComboBox:
    """여섯 항목. 비활성 네 항목은 고를 수 없고 `확장 지점` 으로 표시하며 도움말을 단다(AC-FR1-10)."""
    box = ProviderCombo()
    model = QStandardItemModel(box)
    for pid, label, active in PROVIDERS:
        it = QStandardItem(label if active else "%s (%s)" % (label, EXTENSION_LABEL))
        it.setData(pid, Qt.ItemDataRole.UserRole)
        if not active:
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            it.setData(EXTENSION_TOOLTIP, Qt.ItemDataRole.ToolTipRole)
        model.appendRow(it)
    box.setModel(model)
    set_combo_data(box, current)
    return box


def set_combo_data(box: QComboBox, data) -> bool:
    i = box.findData(data, Qt.ItemDataRole.UserRole)
    if i >= 0:
        box.setCurrentIndex(i)
        return True
    return False


def combo_data(box: QComboBox):
    return box.currentData(Qt.ItemDataRole.UserRole)


class FirstRunNotice(QWidget):
    """첫 실행 화면(시안 `FirstRun`, 결정 0068 F1~F7): 이름 · 부제 · 고지 · 필요한 권한 · 확인 상자.
    앱의 유래 문장은 없다(AC-NF-1). 확인 상자를 켜야 [동의하고 시작] 이 켜진다. 마이크 · 단축키 권한 행은 없다(결정 0063 · 0064)."""
    acknowledged = Signal()
    quit_requested = Signal()
    open_settings_requested = Signal()      # [시스템 설정 열기] (화면 기록)
    WIDTH = 700
    BOTTOM_HEIGHT = 62

    def __init__(self, parent=None):
        super().__init__(parent)
        body = QWidget()
        body.setObjectName("start_body")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(16)
        head = QVBoxLayout()
        head.setSpacing(4)
        title = QLabel(APP_NAME)
        title.setObjectName("fr_title")
        sub = QLabel(APP_SUBTITLE)
        sub.setObjectName("fr_sub")
        h2 = QLabel(FIRST_RUN_HEADING)
        h2.setObjectName("fr_h2")
        intro = QLabel(FIRST_RUN_INTRO)
        intro.setObjectName("panel_note")
        intro.setWordWrap(True)
        for w in (title, sub, h2, intro):
            head.addWidget(w)
        lay.addLayout(head)

        # 1. 데이터가 나가는 곳
        card, cl = self._card()
        cl.addWidget(_section(_t("firstrun.init___033")))
        self.fact_rows = []
        for tag, text in FIRST_RUN_FACTS:
            row = QHBoxLayout()
            row.setSpacing(10)
            pill = QLabel(tag)
            pill.setObjectName({_t("label.tag_local"): "end_pill_ok", _t("label.tag_download"): "end_pill_run"}.get(tag, "end_pill_warn"))
            pill.setFixedSize(max(54 if len(tag) <= 2 else 72, pill.fontMetrics().horizontalAdvance(tag) + 20), 20)
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t = QLabel(text)
            t.setWordWrap(True)
            row.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(t, 1)
            cl.addLayout(row)
            self.fact_rows.append((pill, t))
        lay.addWidget(card)

        # 2. 필요한 권한
        card, cl = self._card()
        cl.addWidget(_section(_t("ctl.show_permissions_035")))
        self.perm_rows = {}
        for key, name, note in FIRST_RUN_PERMISSIONS:
            row = QHBoxLayout()
            row.setSpacing(12)
            col = QVBoxLayout()
            col.setSpacing(2)
            nm = QLabel(name)
            nt = QLabel(note)
            nt.setObjectName("panel_note")
            col.addWidget(nm)
            col.addWidget(nt)
            state = QLabel("")
            state.setAlignment(Qt.AlignmentFlag.AlignCenter)
            state.setFixedHeight(22)
            btn = None
            row.addLayout(col, 1)
            row.addWidget(state, 0, Qt.AlignmentFlag.AlignVCenter)
            if key == "screen_recording":
                btn = QPushButton(_t("firstrun.btn"))
                btn.setObjectName("perm_open")
                btn.setFixedHeight(32)
                btn.clicked.connect(self.open_settings_requested.emit)
                row.addWidget(btn)
            cl.addLayout(row)
            self.perm_rows[key] = (state, btn)
        foot = QLabel(FIRST_RUN_PERMISSION_FOOT)
        foot.setObjectName("panel_note")
        foot.setWordWrap(True)
        cl.addWidget(foot)
        lay.addWidget(card)

        self.understood = QCheckBox(FIRST_RUN_UNDERSTOOD)
        lay.addWidget(self.understood)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("start_scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        self.scroll = scroll
        self.quit = QPushButton(_t("label.quit"))
        self.quit.setFixedHeight(36)
        self.ok = QPushButton(_t("firstrun.init___037"))
        self.ok.setObjectName("primary")
        self.ok.setFixedHeight(36)
        self.ok.setDefault(True)
        self.ok.setEnabled(False)
        bottom = QFrame()
        bottom.setObjectName("win_bottom")
        bottom.setFixedHeight(self.BOTTOM_HEIGHT)
        br = QHBoxLayout(bottom)
        br.setContentsMargins(28, 0, 28, 0)
        br.setSpacing(10)
        br.addStretch(1)
        br.addWidget(self.quit)
        br.addWidget(self.ok)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addWidget(bottom)
        self._review = False
        self.understood.toggled.connect(self.ok.setEnabled)
        self.ok.clicked.connect(self.acknowledged.emit)
        self.quit.clicked.connect(self.quit_requested.emit)
        self.set_permissions({})

    @staticmethod
    def _card():
        card = QFrame()
        card.setObjectName("doc_panel")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)
        return card, cl

    def content_height(self) -> int:
        return self.scroll.widget().sizeHint().height() + self.BOTTOM_HEIGHT

    def set_permissions(self, status: Mapping) -> None:
        """권한 상태(`platform.permissions.query_status` 의 값)를 행에 반영한다. 허용이 아니면 "허용 필요" 이다."""
        for key, (state, btn) in self.perm_rows.items():
            granted = status.get(key) == "허용"
            state.setText(_t("firstrun.set_permissions_038") if granted else _t("firstrun.set_permissions_039"))
            state.setObjectName("end_pill_ok" if granted else "end_pill_warn")
            state.style().unpolish(state)
            state.style().polish(state)
            state.setMinimumWidth(64)
            if btn is not None:
                btn.setVisible(not granted)

    def set_review_mode(self) -> None:
        """도움말 > 첫 실행 안내 다시 보기: 동의를 다시 받지 않는다. [종료] 와 확인 상자를 숨기고 [닫기] 만 둔다(임의)."""
        self._review = True
        self.quit.setVisible(False)
        self.understood.setVisible(False)
        self.ok.setText(_t("end.init___149"))
        self.ok.setEnabled(True)

    def all_text(self) -> str:
        """화면의 글자 전부(고지 원문을 시험이 읽는다)."""
        return "\n".join(lb.text() for lb in self.findChildren(QLabel) if lb.text())


class ChoiceCards(QWidget):
    """콤보 상자 하나의 선택지를 카드가 없는 라디오 한 줄로 표시한다(시각 설계 7-3, 결정 0117 2항).
    값의 원본은 콤보 상자이며, 이 위젯은 그 항목 · 선택 · 사용 가능 여부 · 도움말을 반영한다.
    라디오를 누르면 콤보 상자의 선택이 바뀌고, 콤보 상자의 선택이 바뀌면 라디오가 따라 바뀐다.
    라디오 한 줄의 높이는 28, 선택지 사이의 가로 간격은 24, 라디오와 이름 사이는 8 이다(QSS `spacing`)."""
    ROW_H = 28
    GAP = 24

    def __init__(self, combo: QComboBox, parent=None, plain: bool = True):
        super().__init__(parent)
        self._combo = combo
        self._plain = True
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(self.GAP)
        self.setFixedHeight(self.ROW_H)
        self._buttons: list = []
        self._syncing = False
        self._group: Optional[QButtonGroup] = None
        combo.currentIndexChanged.connect(lambda _i: self._sync_checked())
        self.rebuild()

    def rebuild(self) -> None:
        for b in self._buttons:
            self._row.removeWidget(b)
            b.deleteLater()
        while self._row.count():            # D-148: 앞서 넣은 늘어나는 빈 칸도 지운다(남기면 다시 만들 때마다 쌓여 줄이 가운데에 놓인다)
            self._row.takeAt(0)
        self._buttons = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        model = self._combo.model()
        for i in range(self._combo.count()):
            b = QRadioButton(self._combo.itemText(i))
            b.setObjectName("choice_plain")
            b.setFixedHeight(self.ROW_H)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            tip = self._combo.itemData(i, Qt.ItemDataRole.ToolTipRole)
            if tip:
                b.setToolTip(str(tip))
            item = model.item(i) if hasattr(model, "item") else None
            if item is not None and not item.isEnabled():
                b.setEnabled(False)
            # D-190: 손쉬운 사용 누르기(AXPress)는 라디오를 켜지만 clicked 를 내지 않으므로 켜짐(toggled)에 연결한다
            b.toggled.connect(lambda on, idx=i: self._on_toggled(on, idx))
            self._group.addButton(b, i)
            self._row.addWidget(b, 0)
            self._buttons.append(b)
        self._row.addStretch(1)
        self._sync_checked()

    def set_tooltip_all(self, text: str) -> None:
        for b in self._buttons:
            b.setToolTip(text)

    def _on_toggled(self, on: bool, idx: int) -> None:
        if on and not self._syncing and self._combo.currentIndex() != idx:
            self._combo.setCurrentIndex(idx)

    def _sync_checked(self) -> None:
        cur = self._combo.currentIndex()
        self._syncing = True                # 선택 상자 → 라디오 동기화가 다시 선택 상자를 바꾸지 않게 한다
        try:
            for i, b in enumerate(self._buttons):
                b.setChecked(i == cur)
        finally:
            self._syncing = False

    def buttons(self) -> list:
        return list(self._buttons)


def _scheme_tokens() -> dict:
    from PySide6.QtWidgets import QApplication
    from . import theme
    app = QApplication.instance()
    return theme.tokens(str(app.property("rab_scheme") or "light") if app is not None else "light")


def _qcolor(spec: str):
    from PySide6.QtGui import QColor
    m = re.match(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)", spec.replace(" ", ""))
    if m:
        return QColor(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(float(m.group(4)) * 255))
    return QColor(spec)


class _ProviderDelegate(QStyledItemDelegate):
    """드롭다운 목록의 항목 줄(시각 설계 7-3): 높이 32, 안쪽 여백 0 × 12, 줄 사이 선 없음, 선택된 줄 왼쪽에 ✓,
    오른쪽 상태 글(선택됨 · API 요금 · 확장 지점)."""
    ROW_H = 32

    def __init__(self, combo: QComboBox):
        super().__init__(combo)
        self._combo = combo

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt)
        return QSize(max(option.rect.width(), 200), self.ROW_H)

    def paint(self, painter, option, index) -> None:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QFont
        t = _scheme_tokens()
        active = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        on = index.row() == self._combo.currentIndex()
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver) and active
        painter.save()
        r = option.rect
        if on or hover:
            painter.fillRect(r, _qcolor(t["surface-elevated"]))
        else:
            painter.fillRect(r, _qcolor(t["surface"]))
        pid = index.data(Qt.ItemDataRole.UserRole)
        name = next((lab for p_, lab, _a in PROVIDERS if p_ == pid), str(index.data(Qt.ItemDataRole.DisplayRole)))
        ink = _qcolor(t["ink"] if active else t["mute"])
        mute = _qcolor(t["mute"])
        f = QFont(option.font)
        painter.setPen(ink)
        if on:
            painter.drawText(QRect(r.left() + 12, r.top(), 18, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "\u2713")
        f.setBold(on)
        painter.setFont(f)
        painter.drawText(QRect(r.left() + 32, r.top(), r.width() - 32 - 100, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        tag = EXTENSION_LABEL if not active else (_t("screens.tag") if on else (_t("screens.tag_2") if pid == "claude_api" else ""))
        if tag:
            f2 = QFont(option.font)
            f2.setPointSizeF(max(8.0, option.font.pointSizeF() * 0.8))
            painter.setFont(f2)
            painter.setPen(mute)
            painter.drawText(QRect(r.right() - 12 - 90, r.top(), 90, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, tag)
        painter.restore()


class _DisabledClickBlocker(QObject):
    """펼친 목록에서 비활성 항목을 눌러도 선택이 바뀌지 않고 목록이 접히지 않게 한다(AC-FR1-10). Qt 의 기본 동작은 접는다."""

    def __init__(self, view):
        super().__init__(view)
        self._view = view

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt)
        if ev.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            idx = self._view.indexAt(ev.position().toPoint())
            if idx.isValid() and not (idx.flags() & Qt.ItemFlag.ItemIsEnabled):
                return True
        return False


class ProviderCombo(QComboBox):
    """모델 제공자 드롭다운의 닫힌 상태: 높이 36, 왼쪽에 선택한 이름, 오른쪽에 아래쪽 꺾쇠(시각 설계 7-3)."""

    def paintEvent(self, ev) -> None:  # noqa: N802 (Qt)
        super().paintEvent(ev)
        from PySide6.QtGui import QPainter, QPen
        t = _scheme_tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(_qcolor(t["mute"]), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 22, self.height() / 2.0
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])
        p.end()


_ROLE_CODE = Qt.ItemDataRole.UserRole
_ROLE_OWN = Qt.ItemDataRole.UserRole + 1        # 자기 이름
_ROLE_NOTE = Qt.ItemDataRole.UserRole + 2       # 앱 언어의 이름(자기 이름과 같으면 빈 글)


class _LanguageDelegate(_ProviderDelegate):
    """언어 드롭다운의 항목 줄(시각 설계 7-3 의 언어 드롭다운): 왼쪽 자기 이름, 오른쪽 `caption` `mute` 로 앱 언어의 이름."""

    def paint(self, painter, option, index) -> None:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QFont
        t = _scheme_tokens()
        on = index.row() == self._combo.currentIndex()
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        r = option.rect
        painter.fillRect(r, _qcolor(t["surface-elevated"] if (on or hover) else t["surface"]))
        f = QFont(option.font)
        painter.setPen(_qcolor(t["ink"]))
        if on:
            painter.drawText(QRect(r.left() + 12, r.top(), 18, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "\u2713")
        f.setBold(on)
        painter.setFont(f)
        if not (index.flags() & Qt.ItemFlag.ItemIsEnabled):
            painter.setPen(_qcolor(t["mute"]))
        own = str(index.data(_ROLE_OWN) or index.data(Qt.ItemDataRole.DisplayRole))
        painter.drawText(QRect(r.left() + 32, r.top(), r.width() - 32 - 180, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, own)
        note = index.data(_ROLE_NOTE)
        if note:
            f2 = QFont(option.font)
            f2.setPointSizeF(max(8.0, option.font.pointSizeF() * 0.8))
            painter.setFont(f2)
            painter.setPen(_qcolor(t["mute"]))
            painter.drawText(QRect(r.right() - 12 - 170, r.top(), 170, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(note))
        painter.restore()


def language_combo(entries, current: str, width: int = 300) -> QComboBox:
    """언어 드롭다운(닫힌 상자 높이 36 · 너비 300, 펼친 목록은 8줄). `entries`: [(코드, 자기 이름, 앱 언어의 이름 | "", 닫힌 상자의 문구)]."""
    box = ProviderCombo()
    box.setObjectName("prov_combo")
    model = QStandardItemModel(box)
    for code, own, note, shown in entries:
        it = QStandardItem(shown)
        it.setData(code, _ROLE_CODE)
        it.setData(own, _ROLE_OWN)
        it.setData(note, _ROLE_NOTE)
        model.appendRow(it)
    box.setModel(model)
    view = QListView()
    view.setObjectName("prov_view")
    view.setItemDelegate(_LanguageDelegate(box))
    view.setMouseTracking(True)
    box.setView(view)
    box.setFixedSize(width, 36)
    box.setMaxVisibleItems(8)
    set_combo_data(box, current)
    return box


def stt_language_entries(app_lang: str):
    from ..core import languages
    out = []
    for code in languages.sorted_codes(app_lang):
        own, other = languages.self_name(code), languages.app_name(code, app_lang)
        out.append((code, own, "" if own == other else other, languages.display_text(code, app_lang)))
    return out


class ProviderList(QWidget):
    """모델 제공자 드롭다운(결정 0089, 시안 2-1): 값의 원본인 콤보 상자 `combo` 를 화면에 보이게 하고 목록 모양을 꾸민다.
    비활성 항목은 `확장 지점` 이며 고를 수 없고 눌러도 목록이 접히지 않는다. 시작 화면과 설정 창이 같은 모양이다."""

    def __init__(self, combo: QComboBox, parent=None):
        super().__init__(parent)
        self._combo = combo
        self.setObjectName("prov_list")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        combo.setObjectName("prov_combo")
        view = QListView()
        view.setObjectName("prov_view")
        view.setItemDelegate(_ProviderDelegate(combo))
        view.setMouseTracking(True)
        combo.setView(view)
        view.viewport().installEventFilter(_DisabledClickBlocker(view))
        combo.setFixedHeight(36)
        combo.setMaxVisibleItems(6)
        lay.addWidget(combo)                      # 숨은 보관 위젯에서 이 위젯으로 옮겨 보이게 한다
        self.combo = combo

    def _sync(self) -> None:
        self._combo.update()

    def row_names(self) -> list:
        m = self._combo.model()
        out = []
        for i in range(self._combo.count()):
            pid = self._combo.itemData(i, Qt.ItemDataRole.UserRole)
            out.append(next((lab for p_, lab, _a in PROVIDERS if p_ == pid), m.item(i).text()))
        return out


def combo_data_at(box: QComboBox, i: int):
    return box.itemData(i, Qt.ItemDataRole.UserRole)


def _section(title: str) -> QLabel:
    lab = QLabel(title)
    lab.setObjectName("section_title")
    return lab


class ElidedPathEdit(QLineEdit):
    """경로 입력란(AC-FR13-3): 편집하지 않을 때 경로가 폭보다 길면 가운데를 줄여 끝의 폴더 이름이 보이게 하고, 마우스를 올리면
    전체 경로를 도움말로 보인다. 편집 중(초점이 있을 때)에는 줄이지 않는다. `text()` 는 늘 전체 경로를 반환한다."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text or ""
        self._editing = False
        self.textEdited.connect(self._on_edited)
        self._refresh()

    def _on_edited(self, t: str) -> None:
        self._full = t

    def setText(self, t: str) -> None:  # noqa: N802 (Qt)
        self._full = t or ""
        self._refresh()

    def text(self) -> str:
        return self._full

    def _refresh(self) -> None:
        if self._editing:
            super().setText(self._full)
            return
        width = max(0, self.width() - 26)
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, width) if self.width() > 60 else self._full
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")
        if shown != self._full:
            self.setToolTip(self._full)

    def focusInEvent(self, e) -> None:  # noqa: N802 (Qt)
        self._editing = True
        super().setText(self._full)
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:  # noqa: N802 (Qt)
        self._editing = False
        self._refresh()
        super().focusOutEvent(e)

    def resizeEvent(self, e) -> None:  # noqa: N802 (Qt)
        super().resizeEvent(e)
        self._refresh()


class AppLanguageSection(QWidget):
    """시작 화면의 "1. 앱 언어" 절(결정 0181 1항, 시안 "2" · "2-5" · "11-1b"): 제목 18 · 아래 8 에 드롭다운(너비 300),
    고른 값이 지금 값과 다르면 그 아래 10 에 다시 시작 안내(NEW-6)를 보인다. 값은 고르는 즉시 신호로 알린다(저장은 호출한 쪽이 한다)."""
    app_language_changed = Signal(str)

    def __init__(self, data: Mapping, parent=None):
        super().__init__(parent)
        from ..core import i18n, languages
        self.setObjectName("app_language_section")
        self._running_app_lang = i18n.language()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = _section(_t("newlang.new79"))              # NEW-79 "1. 앱 언어"
        self.head.setFixedHeight(18)
        self.app_language = language_combo([(c, n, "", n) for c, n in languages.APP_LANGUAGES], languages.normalize_app(data.get("app_language")))
        self.app_language.setAccessibleName(_t("newlang.new2"))        # NEW-2: 드롭다운의 접근성 이름
        self.lang_notice = QLabel("")
        self.lang_notice.setObjectName("lang_notice")
        self.lang_notice.setWordWrap(True)
        self.lang_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.lang_notice.setVisible(False)
        self._notice_wrap = QWidget()                          # 안내 앞의 간격 10 은 안내가 보일 때만 있다
        nl = QVBoxLayout(self._notice_wrap)
        nl.setContentsMargins(0, 10, 0, 0)
        nl.addWidget(self.lang_notice)
        self._notice_wrap.setVisible(False)
        lay.addWidget(self.head)
        lay.addSpacing(8)
        lay.addWidget(self.app_language, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self._notice_wrap)
        self._update_lang_notice()
        self.app_language.currentIndexChanged.connect(lambda _i: self._on_app_language())

    def _on_app_language(self) -> None:
        self._update_lang_notice()
        self.app_language_changed.emit(combo_data(self.app_language))

    def _update_lang_notice(self) -> None:
        """고른 앱 언어가 지금 보이는 언어와 다르면 다시 시작 안내를 보인다(AC-FR16-8). 되돌리면 사라진다."""
        from ..core import languages
        chosen = combo_data(self.app_language)
        differs = chosen != self._running_app_lang
        if differs:
            names = dict(languages.APP_LANGUAGES)
            self.lang_notice.setText(_t("newlang.new6").format(chosen=names.get(chosen, chosen), current=names.get(self._running_app_lang, self._running_app_lang)))
        self.lang_notice.setVisible(differs)
        self._notice_wrap.setVisible(differs)


class ClaudeSection(QWidget):
    """시작 화면의 "5. claude 실행 파일" 절(결정 0176 3항 · 0179 · 0181 2 · 3항, 시안 "2" · "2-7" · "2-8"). 경로 칸 · [찾아보기…] · [기본 경로로 되돌리기] ·
    설명 줄과, 제공자가 Claude API 일 때만 그 아래의 번호 없는 "Claude API 키" 줄을 둔다. 절 전체는 제공자가 Claude 구독 · Claude API 일 때만 보인다.
    값은 신호로만 알린다(저장 · 키체인은 호출한 쪽이 한다). 경로 · 키는 바꾸는 즉시 저장되며 [취소] 로 되돌리지 않는다."""
    claude_path_changed = Signal(object)         # 직접 지정한 경로, 자동이면 None
    api_key_submitted = Signal(str)              # 평문 키는 이 신호로만 건넨다. 이 위젯은 저장 · 기록하지 않는다
    api_key_delete_requested = Signal()

    KEY_DOTS = "•" * 8
    CLAUDE_PROVIDERS = ("claude_subscription", "claude_api")

    @classmethod
    def provider_shows_section(cls, provider) -> bool:
        """5. claude 실행 파일 절은 제공자가 Claude 구독 · Claude API 일 때만 보인다(결정 0181 2항)."""
        return provider in cls.CLAUDE_PROVIDERS

    def __init__(self, data: Mapping, claude_auto: Optional[str], provider: str, parent=None):
        super().__init__(parent)
        self.setObjectName("claude_section")
        self._provider = provider
        self._claude_auto = claude_auto or None
        self._claude_saved = str(data.get("claude_path") or "") or None      # 저장된 값(자동이면 None)
        self._key_saved: Optional[bool] = None
        self._key_changing = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.head = _section(_t("setform.browse_claude_073"))      # UI-073 "5. claude 실행 파일"
        outer.addWidget(self.head)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        def mono_edit(text="", placeholder="") -> QLineEdit:
            e = QLineEdit(text)
            e.setObjectName("path_edit")
            e.setFixedHeight(36)
            if placeholder:
                e.setPlaceholderText(placeholder)
            return e

        def small_button(text: str, h: int = 36) -> QPushButton:
            b = QPushButton(text)
            b.setFixedHeight(h)
            b.setStyleSheet("QPushButton { min-height: %dpx; padding-top: 0px; padding-bottom: 0px; }" % (h - 2))
            b.setAutoDefault(False)
            b.setDefault(False)
            return b

        # 경로 줄
        path_group = QWidget()
        ccv = QVBoxLayout(path_group)
        ccv.setContentsMargins(0, 0, 0, 0)
        ccv.setSpacing(8)
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.claude_edit = mono_edit(placeholder=_t("setform.init___076"))
        self.claude_browse = small_button(_t("setform.init___077"))
        self.claude_restore = small_button(_t("newlang.new63"))
        prow.addWidget(self.claude_edit, 1)
        prow.addWidget(self.claude_browse)
        prow.addWidget(self.claude_restore)
        ccv.addLayout(prow)
        note_row = QHBoxLayout()
        note_row.setSpacing(8)
        note_row.setContentsMargins(0, 0, 0, 0)
        self.claude_dot = QFrame()
        self.claude_dot.setObjectName("claude_note_dot")
        self.claude_dot.setFixedSize(8, 8)
        self.claude_found = QLabel("")
        self.claude_found.setObjectName("panel_note")
        self.claude_found.setTextFormat(Qt.TextFormat.PlainText)
        self.claude_found.setWordWrap(True)
        note_row.addWidget(self.claude_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        note_row.addWidget(self.claude_found, 1)
        self.claude_note = QWidget()
        self.claude_note.setLayout(note_row)
        ccv.addWidget(self.claude_note)
        body.addWidget(path_group)
        self.claude_group = path_group
        # Claude API 키 줄: 제공자가 Claude API 인 동안에만 보인다(AC-FR1-16). 감춰도 키는 지우지 않는다
        self.key_group = QWidget()
        kg = QVBoxLayout(self.key_group)
        kg.setContentsMargins(0, 0, 0, 0)
        kg.setSpacing(8)
        self.key_label = QLabel(_t("setform.init___063"))          # UI-063 "Claude API 키" (번호 없음)
        self.key_label.setObjectName("key_label")
        kg.addWidget(self.key_label)
        krow = QHBoxLayout()
        krow.setSpacing(8)
        self.api_key = mono_edit(placeholder=_t("setform.init___063"))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.save_key = small_button(_t("start.init___044"))
        self.delete_key = small_button(_t("ctl.confirm_model_delete_064"))
        self.delete_key.setObjectName("danger")
        krow.addWidget(self.api_key, 1, Qt.AlignmentFlag.AlignVCenter)
        krow.addWidget(self.save_key, 0, Qt.AlignmentFlag.AlignVCenter)
        krow.addWidget(self.delete_key, 0, Qt.AlignmentFlag.AlignVCenter)
        kg.addLayout(krow)
        self.key_error = QLabel("")
        self.key_error.setObjectName("error")
        self.key_error.setWordWrap(True)
        self.key_error.setVisible(False)
        kg.addWidget(self.key_error)
        note = QLabel(_t("setform.note"))
        note.setObjectName("panel_note")
        note.setWordWrap(True)
        kg.addWidget(note)
        body.addWidget(self.key_group)
        outer.addLayout(body)
        self.key_group.setVisible(provider == "claude_api")
        self.set_key_saved(None)
        self._load_claude()
        self.save_key.clicked.connect(self._on_save_clicked)
        self.api_key.returnPressed.connect(self._submit_key)
        self.api_key.installEventFilter(self)
        self.delete_key.clicked.connect(lambda: self.api_key_delete_requested.emit())
        self.claude_browse.clicked.connect(self._browse_claude)
        self.claude_restore.clicked.connect(self._restore_claude)
        self.claude_edit.textChanged.connect(self._refresh_claude_state)
        self.claude_edit.editingFinished.connect(self._emit_claude_path)

    def claude_status(self) -> str:
        """저장된 값 기준의 상태 코드: auto · custom · missing · custom_missing."""
        saved = self._claude_saved
        if saved:
            return "custom" if claude_locator.is_executable(os.path.expanduser(saved)) else "custom_missing"
        return "auto" if self._claude_auto else "missing"

    def set_provider(self, provider: str) -> None:
        """제공자 드롭다운을 바꾸는 즉시 키 줄을 보이거나 감춘다(AC-FR1-16 · 0181 3항). 키체인의 키는 건드리지 않는다.
        절 전체의 표시(`provider_shows_section`)는 시작 화면이 정한다."""
        self._provider = provider
        self.key_group.setVisible(provider == "claude_api")
        if provider != "claude_api":
            self.cancel_key_edit()

    # ---- claude 실행 파일 ----
    def _load_claude(self) -> None:
        """칸에는 지정한 경로, 없으면 자동으로 찾은 경로가 들어간다(결정 0176 3항)."""
        self.claude_edit.setText(str(self._claude_saved or self._claude_auto or ""))
        self._refresh_claude_state()

    def set_claude_auto(self, auto: Optional[str]) -> None:
        """자동으로 찾은 경로가 정해지거나 바뀌었을 때 호출한다. 지정한 경로가 없고 칸이 비었거나 이전 자동 경로 그대로이면 새 자동 경로를 채운다(D-204)."""
        old = self._claude_auto
        self._claude_auto = auto or None
        text = self.claude_edit.text().strip()
        if not self._claude_saved and (not text or text == old):
            self.claude_edit.setText(self._claude_auto or "")
        self._refresh_claude_state()

    def _refresh_claude_state(self, _text=None) -> None:
        """[기본 경로로 되돌리기] 와 설명 줄(NEW-64 · 65 · 66, AC-FR1-28), 칸의 경고색 테두리를 칸의 글에 맞춘다."""
        text = self.claude_edit.text().strip()
        auto = self._claude_auto
        self.claude_restore.setVisible(bool(auto))
        usable = bool(text) and claude_locator.is_executable(os.path.expanduser(text))
        if not text and not auto:
            line, tone = _t("newlang.new65"), "warn"
        elif text and not usable:
            line, tone = _t("newlang.new66"), "warn"
        elif usable and auto and text == auto:
            line, tone = _t("newlang.new64"), "ok"
        else:
            line, tone = "", ""
        self.claude_found.setText(line)
        self.claude_note.setVisible(bool(line))
        self.claude_dot.setProperty("tone", tone or "ok")
        self.claude_dot.style().unpolish(self.claude_dot)
        self.claude_dot.style().polish(self.claude_dot)
        self._set_warn(self.claude_edit, not usable)      # 찾지 못함 · 지정 경로 없음이면 칸의 테두리가 경고색(시각 설계 7-12)

    def _browse_claude(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, _t("setform.browse_claude_073"), self.claude_edit.text())
        if path:
            self.claude_edit.setText(path)
            self._emit_claude_path()

    def _restore_claude(self) -> None:
        """[기본 경로로 되돌리기]: 칸을 자동으로 찾은 경로로 되돌리고 저장 값을 null 로 한다."""
        self.claude_edit.setText(self._claude_auto or "")
        self._emit_claude_path()

    def _emit_claude_path(self) -> None:
        """저장 값: 자동이면 None(칸이 비었거나 자동으로 찾은 경로와 같을 때), 아니면 지정한 경로. 칸이 비면 자동으로 찾은 경로를 채운다."""
        text = self.claude_edit.text().strip()
        if not text or (self._claude_auto and text == self._claude_auto):
            self.claude_edit.setText(self._claude_auto or "")
            value = None
        else:
            value = text
        self._claude_saved = value
        self._refresh_claude_state()
        self.claude_path_changed.emit(value)

    def flush_claude_path(self) -> None:
        """칸을 고친 뒤 Enter · 초점 이탈 없이 다른 단추를 눌렀을 때 먼저 저장한다(AC-FR1-28 · S11-10). 고치지 않았으면 아무것도 하지 않는다."""
        text = self.claude_edit.text().strip()
        pending = None if (not text or (self._claude_auto and text == self._claude_auto)) else text
        if pending != self._claude_saved:
            self._emit_claude_path()

    # ---- API 키 ----
    def set_key_saved(self, saved: Optional[bool]) -> None:
        """키 칸의 상태(AC-FR1-17). 저장됨: 읽기 전용 칸에 고정 점 표시(키 문자열은 넣지 않는다), [변경…] · [삭제] 활성.
        없음: 편집 가능한 칸, 자리 표시 "새 Claude API 키", [삭제] 숨김. None(확인하지 못함)은 없음과 같게 두되 [삭제] 를 켠다."""
        self._key_saved = saved
        self._key_changing = False
        self.key_error.setVisible(False)
        self.api_key.clear()
        self._set_valuebox(self.api_key, bool(saved))
        self._set_warn(self.api_key, not saved)
        if saved:
            self.save_key.setText(_t("start.init___044"))                       # [변경…]
            self.api_key.setReadOnly(True)
            self.api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self.api_key.setText(self.KEY_DOTS)
            self.api_key.setPlaceholderText("")
        else:
            self.save_key.setText(_t("setform.begin_key_change_091"))           # [저장] 하나(D-205)
            self.api_key.setReadOnly(False)
            self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.api_key.setPlaceholderText(_t("setform.begin_key_change_092"))  # UI-092 "새 Claude API 키"
        self.delete_key.setVisible(bool(saved) or saved is None)                # 키가 없으면 [삭제] 를 보이지 않는다
        self.delete_key.setEnabled(bool(saved) or saved is None)

    def _set_keywarn(self, on: bool) -> None:
        """키가 없을 때 칸의 테두리를 경고색으로 한다(시각 설계 7-12)."""
        self._set_warn(self.api_key, on)

    @staticmethod
    def _set_warn(w, on: bool) -> None:
        if bool(w.property("keywarn")) == bool(on):
            return
        w.setProperty("keywarn", bool(on))
        w.style().unpolish(w)
        w.style().polish(w)

    @staticmethod
    def _set_valuebox(w, on: bool) -> None:
        w.setProperty("valuebox", bool(on))
        w.style().unpolish(w)
        w.style().polish(w)

    def show_key_error(self, text: str) -> None:
        if self._key_changing:
            self.cancel_key_edit()
        self.key_error.setText(text)
        self.key_error.setVisible(bool(text))

    def cancel_key_edit(self) -> None:
        """[변경…] 중이면 그만둔다: 입력을 버리고 기존 키를 유지한 채 점 표시로 돌아간다."""
        if self._key_changing:
            self.set_key_saved(True)

    def _begin_key_change(self) -> None:
        self._key_changing = True
        self.save_key.setText(_t("setform.begin_key_change_091"))
        self._set_valuebox(self.api_key, False)
        self._set_warn(self.api_key, False)
        self.api_key.setReadOnly(False)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.clear()
        self.api_key.setPlaceholderText(_t("setform.begin_key_change_092"))
        self.api_key.setFocus()

    def _on_save_clicked(self) -> None:
        if self._key_saved and not self._key_changing:
            self._begin_key_change()
        elif self.api_key.text().strip():
            self._submit_key()
        else:
            self.api_key.setFocus()

    def _submit_key(self) -> None:
        key = self.api_key.text().strip()
        if not key:
            self.cancel_key_edit()
            return
        self.api_key.clear()
        self.api_key_submitted.emit(key)

    def eventFilter(self, obj, ev):  # noqa: N802 (Qt)
        if obj is self.api_key and self._key_changing:
            if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
                self.cancel_key_edit()
                return True
            if ev.type() == QEvent.Type.FocusOut and not self.save_key.underMouse():
                self.cancel_key_edit()
        return super().eventFilter(obj, ev)

    def hideEvent(self, ev) -> None:  # noqa: N802 (Qt)
        self.cancel_key_edit()
        super().hideEvent(ev)


class SessionStartForm(QWidget):
    """세션 시작 화면(FR-1 · FR-3 · FR-13, 시안 `Session`, 결정 0068). `values()` 는 시작할 때 쓸 선택을 반환한다.
    값의 원본은 콤보 상자(provider · family · effort · source · kind)이며 화면에는 카드 · 목록으로 표시한다.
    콤보 상자는 크기 0 의 보관 위젯 안에 둔다."""
    start_requested = Signal(dict)
    cancel_requested = Signal()
    content_changed = Signal()          # 내용 높이가 바뀌었다(창 높이를 다시 정한다, AC-FR1-25)
    default_prompt_saved = Signal(str)      # [기본값으로 저장](AC-FR2-5). 빈 글은 "앱 기본 문구를 쓴다" 이다(AC-FR2-3)
    app_language_changed = Signal(str)      # 1. 앱 언어 · 5. claude 실행 파일 절의 신호(값을 바꾸는 즉시 저장, 결정 0179 · 0181)
    claude_path_changed = Signal(object)
    api_key_submitted = Signal(str)
    api_key_delete_requested = Signal()

    WIDTH = 760
    LEFT_COLUMN_WIDTH = 300             # 6. 음성 소스의 열 너비(시안 "2")
    COLUMN_GAP = 24

    def __init__(self, data: Mapping, default_save_dir: str, parent=None, claude_auto: Optional[str] = None):
        super().__init__(parent)
        self._data = dict(data)
        sel = settings.resolve_selection(self._data)
        self.setObjectName("start_page")
        self._holder = QWidget(self)
        self._holder.setFixedSize(0, 0)
        self.provider = provider_combo(sel.provider)
        self.family = ProviderCombo()                 # 모델 드롭다운(결정 0117 1항): 모델 제공자 드롭다운과 모양이 같다
        self.effort = QComboBox()
        self.effort.setToolTip(EFFORT_TOOLTIP)
        self.source = source_combo(self._data.get("source"))
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(labels.doc_kind_label(k), k)
        for w in (self.provider, self.family, self.effort, self.source, self.kind):
            w.setParent(self._holder)
        self.title = QLineEdit()
        self.title.setFixedHeight(36)
        self.kind.currentIndexChanged.connect(lambda _i: self._sync_title_placeholder())     # 종류가 수업이면 과목명, 회의이면 회의명(결정 0176 1항)
        self._sync_title_placeholder()
        self.save_dir = ElidedPathEdit(self._data.get("save_dir") or "")      # 기억한 위치가 없으면 비운다(결정 0121)
        self.save_dir.setObjectName("path_edit")
        self.save_dir.setPlaceholderText(SAVE_DIR_PLACEHOLDER)
        self._default_save_dir = default_save_dir
        self.save_dir.setFixedHeight(36)
        self.change_dir = QPushButton(_t("start.init___044"))
        self.change_dir.setFixedHeight(36)
        self.session_prompt = QPlainTextEdit()
        self.session_prompt.setObjectName("session_prompt")
        self.session_prompt.setFixedHeight(96)
        self.default_prompt_btn = QPushButton(_t("start.init___045"))             # 결정 0120: 칸의 글을 설정의 기본 문구로 되돌린다
        self.default_prompt_btn.setObjectName("prompt_default_btn")
        self.default_prompt_btn.setFixedHeight(28)
        self.default_prompt_btn.setStyleSheet("QPushButton { min-height: 26px; padding-top: 0px; padding-bottom: 0px; font-size: 13px; font-weight: 500; }")   # 시각 설계 260: 글 `label` 500   # 기본 단추의 합 38 이 고정 높이 28 을 덮어쓰지 않게 한다(D-170, D-166 과 같은 구조)
        self.original_prompt_btn = QPushButton(_t("newlang.new74"))        # [처음 문구]: 칸의 글을 앱이 처음 가지고 있던 문구로 되돌린다(결정 0179 3항)
        self.save_default_btn = QPushButton(_t("newlang.new75"))           # [기본값으로 저장]: 칸의 글을 설정의 기본 문구로 즉시 저장한다
        for b, name, tip in ((self.original_prompt_btn, "prompt_original_btn", "newlang.new76"),
                             (self.save_default_btn, "prompt_save_default_btn", "newlang.new78")):
            b.setObjectName(name)
            b.setFixedHeight(28)
            b.setToolTip(_t(tip))
            b.setStyleSheet(self.default_prompt_btn.styleSheet())
        self.default_prompt_btn.setToolTip(_t("newlang.new77"))
        self._prompt_loaded = ""                                   # 마지막으로 칸에 넣은 기본 문구(사용자가 고치지 않았는지 판단)
        self._prompt_inited = False
        self.reload_default_prompt()
        self.fee = QLabel(API_FEE_TEXT)
        self.fee.setObjectName("warning")
        self.start = QPushButton(_t("start.init___046"))
        self.start.setObjectName("primary")
        self.start.setFixedHeight(36)
        self.cancel = QPushButton(_t("label.cancel"))
        self.cancel.setFixedHeight(36)
        # 시작하지 못한 사유와 조치를 본문 맨 위의 띠로 표시한다(AC-FR1-14, 시안 7-5 · D-101). 제목 = 사유, 설명 = 조치.
        self.banner = QFrame()
        self.banner.setObjectName("start_banner")
        bl = QVBoxLayout(self.banner)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(2)
        self.problem = QLabel("")             # 띠의 제목 라벨(objectName start_banner_title)
        self.problem.setObjectName("start_banner_title")
        self.problem.setWordWrap(True)
        self.problem.setTextFormat(Qt.TextFormat.PlainText)
        self.hint = QLabel("")
        self.hint.setObjectName("start_banner_hint")
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        bl.addWidget(self.problem)
        bl.addWidget(self.hint)
        self.banner.setVisible(False)
        self.problem.setVisible(False)
        # 점검 상태 줄(결정 0078, AC-FR1-23, 시각 설계 7-12): 시작 불가 띠가 없을 때만 같은 자리에 한 줄로 보인다.
        self.check_line = QWidget()
        self.check_line.setObjectName("start_check_line")
        cl = QHBoxLayout(self.check_line)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        self.check_dot = QFrame()
        self.check_dot.setObjectName("start_check_dot")
        self.check_dot.setFixedSize(8, 8)
        self.check_text = QLabel("")
        self.check_text.setObjectName("start_check_text")
        self.check_text.setTextFormat(Qt.TextFormat.PlainText)
        self.check_text.setWordWrap(True)
        cl.addWidget(self.check_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        cl.addWidget(self.check_text, 1)
        self.check_line.setVisible(False)
        self._check_text = ""
        self._blocked = False
        self._checking = False

        self.provider_list = ProviderList(self.provider)
        self.family_cards = ChoiceCards(self.family)
        self.effort_cards = ChoiceCards(self.effort)
        self.source_cards = ChoiceCards(self.source)
        self.kind_cards = ChoiceCards(self.kind)

        def group(*widgets, spacing: int = 8) -> QWidget:
            """제목 줄 아래 간격 8 로 묶은 한 요소(시각 설계 7-3). 요소 사이의 간격 18 은 본문 배치가 둔다."""
            g = QWidget()
            gl = QVBoxLayout(g)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(spacing)
            for w in widgets:
                gl.addWidget(w) if isinstance(w, QWidget) else gl.addLayout(w)
            return g

        self.provider_section = group(_section(_t("start.init___047")), self.provider_list, self.fee)
        self.family_section = group(_section(_t("start.init___048")), self.family_cards)
        self.effort_section = group(_section(_t("newlang.new81")), self.effort_cards)      # NEW-81 "4. effort"(번역 표에서 읽는다, R12-8)
        self.source_section = group(_section(_t("start.init___049")), self.source_cards)
        # 7. 음성 인식 언어(결정 0179 1항 · 0181 1항): 6. 음성 소스의 오른쪽 열. 제목 · 드롭다운 · 설명 줄 NEW-71, 아홉 밖의 저장 값이면 경고 줄 NEW-59
        from ..core import i18n, languages
        self.stt_language = language_combo(stt_language_entries(i18n.language()), languages.normalize_stt(self._data.get("stt_language")))
        self.stt_language.setMinimumWidth(self.LEFT_COLUMN_WIDTH)
        self.stt_language.setMaximumWidth(16777215)
        self.stt_language.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.stt_language.setToolTip("")
        stt_note = QLabel(_t("newlang.new71"))
        stt_note.setObjectName("mute")
        stt_note.setWordWrap(True)
        stt_note.setTextFormat(Qt.TextFormat.PlainText)
        self.stt_note = stt_note
        self.stt_head = _section(_t("newlang.new80"))                # NEW-80 "7. 음성 인식 언어"
        self.stt_language.setAccessibleName(_t("newlang.new3"))      # NEW-3: 드롭다운의 접근성 이름
        self.stt_head.setFixedHeight(18)                       # 시각 설계 266 ①: 제목 18 · 아래 8 · 드롭다운 36 · 아래 6 · 설명 줄 18 (D-207)
        self.stt_section = group(self.stt_head, self.stt_language, stt_note, spacing=0)
        self.stt_section.layout().insertSpacing(1, 8)
        self.stt_section.layout().insertSpacing(3, 6)
        self.stt_section.setObjectName("stt_section")
        self.stt_fallback_notice = QLabel("")         # NEW-59 · 59N(결정 0167 7항)
        self.stt_fallback_notice.setObjectName("lang_notice")
        self.stt_fallback_notice.setWordWrap(True)
        self.stt_fallback_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.stt_fallback_notice.setVisible(False)
        self.source_row = QWidget()
        self.source_row.setObjectName("source_stt_row")
        sr = QHBoxLayout(self.source_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(self.COLUMN_GAP)
        self.source_section.setFixedWidth(self.LEFT_COLUMN_WIDTH)
        sr.addWidget(self.source_section, 0, Qt.AlignmentFlag.AlignTop)
        sr.addWidget(self.stt_section, 1, Qt.AlignmentFlag.AlignTop)
        self.source_block = group(self.source_row, self.stt_fallback_notice, spacing=10)
        self.source_block.setObjectName("source_block")
        self.app_language_section = AppLanguageSection(self._data)
        self.claude_section = ClaudeSection(self._data, claude_auto, sel.provider)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(self.title, 1)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        dir_row.addWidget(self.save_dir, 1)
        dir_row.addWidget(self.change_dir)
        self.doc_section = group(_section(_t("start.init___050")), self.kind_cards, name_row, dir_row)   # 카드 안의 카드를 쓰지 않는다
        prompt_head = QHBoxLayout()
        prompt_head.setSpacing(8)
        prompt_head.addWidget(_section(_t("start.init___051")), 1)
        prompt_head.addWidget(self.original_prompt_btn)
        prompt_head.addWidget(self.default_prompt_btn)
        prompt_head.addWidget(self.save_default_btn)
        self.prompt_section = group(prompt_head, self.session_prompt)

        body = QWidget()
        body.setObjectName("start_body")
        self._lay = QVBoxLayout(body)
        self._lay.setContentsMargins(24, 20, 24, 20)
        self._lay.setSpacing(18)
        self._lay.addWidget(self.banner)
        self._lay.addWidget(self.check_line)
        self._lay.addWidget(self.app_language_section)
        self._lay.addWidget(self.provider_section)
        self._lay.addWidget(self.family_section)
        self._lay.addWidget(self.effort_section)
        self._lay.addWidget(self.claude_section)
        self._lay.addWidget(self.source_block)
        self._material_index = self._lay.count()      # 사전 지식 구역이 들어갈 자리(add_section)
        self._lay.addWidget(self.doc_section)
        self._lay.addWidget(self.prompt_section)
        self.claude_section.setVisible(ClaudeSection.provider_shows_section(sel.provider))
        self._pending_reveal: Optional[str] = None
        self._body = body
        body.installEventFilter(self)                 # 내용 높이가 바뀌면 창 높이를 다시 정한다(AC-FR1-25)
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(0)
        self._relayout_timer.timeout.connect(self.content_changed.emit)

        scroll = QScrollArea()
        scroll.setObjectName("start_scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        self.scroll = scroll
        bottom = QFrame()
        bottom.setObjectName("win_bottom")
        bottom.setFixedHeight(64)
        br = QHBoxLayout(bottom)
        br.setContentsMargins(24, 0, 24, 0)
        br.setSpacing(10)
        br.addStretch(1)
        br.addWidget(self.cancel)
        br.addWidget(self.start)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addWidget(bottom)

        self._reload_models(sel.family, sel.effort)
        self.provider.currentIndexChanged.connect(lambda _i: self._on_provider())
        self.family.currentIndexChanged.connect(lambda _i: self._on_family())
        self.start.clicked.connect(self._on_start_clicked)
        self.cancel.clicked.connect(self._on_cancel_clicked)
        self.change_dir.clicked.connect(self._browse_dir)
        self.default_prompt_btn.clicked.connect(self.reset_prompt_to_default)
        self.original_prompt_btn.clicked.connect(self.reset_prompt_to_original)
        self.save_default_btn.clicked.connect(self._save_prompt_default)
        self.session_prompt.textChanged.connect(self._sync_prompt_buttons)
        self._sync_prompt_buttons()
        self.provider.currentIndexChanged.connect(lambda _i: self._on_provider_for_claude_section())
        self.app_language_section.app_language_changed.connect(self.app_language_changed.emit)
        self.claude_section.claude_path_changed.connect(self.claude_path_changed.emit)
        self.claude_section.api_key_submitted.connect(self.api_key_submitted.emit)
        self.claude_section.api_key_delete_requested.connect(self.api_key_delete_requested.emit)
        self.start.setDefault(True)

    # ----- 1. 앱 언어 · 5. claude 실행 파일 · 7. 음성 인식 언어 (결정 0179 · 0181) -----
    def _on_provider_for_claude_section(self) -> None:
        provider = combo_data(self.provider)
        self.claude_section.set_provider(provider)
        self.claude_section.setVisible(ClaudeSection.provider_shows_section(provider))

    def _on_start_clicked(self) -> None:
        self.claude_section.flush_claude_path()          # 경로 칸을 고치고 Enter 없이 누른 경우 먼저 저장하고 띠를 다시 평가한다(S11-10)
        if self._blocked or self._checking:
            return
        self.start_requested.emit(self.values())

    def _on_cancel_clicked(self) -> None:
        self.claude_section.flush_claude_path()
        self.cancel_requested.emit()

    def set_key_saved(self, saved: Optional[bool]) -> None:
        self.claude_section.set_key_saved(saved)

    def show_key_error(self, text: str) -> None:
        self.claude_section.show_key_error(text)

    def set_claude_auto(self, auto: Optional[str]) -> None:
        self.claude_section.set_claude_auto(auto)

    def reveal_banner_target(self, kind: str) -> None:
        """조치가 5. claude 실행 파일 절 안에 있는 띠(API 키 없음 · claude 없음 · 지정 경로 없음)가 나타날 때 한 번 호출한다(AC-FR1-32).
        본문을 그 절이 완전히 보이는 최소 거리만큼 스크롤하고(이미 보이면 움직이지 않는다) 초점을 키 없음이면 API 키 칸에, 나머지는 경로 칸에 둔다.
        창이 아직 보이지 않으면 처음 보일 때 한 번 한다."""
        self._pending_reveal = kind
        QTimer.singleShot(0, self._apply_reveal)

    def _apply_reveal(self) -> None:
        kind = self._pending_reveal
        if not kind or not self.isVisible():
            return                                  # 보이지 않으면 showEvent 가 다시 시도한다
        self._pending_reveal = None
        section = self.claude_section
        if section.isHidden():
            return
        # 같은 호출 안에서 바뀐 안쪽 위젯(설명 줄 등)의 배치 요청을 먼저 처리한 뒤 본문 배치를 확정해야 절의 높이가 최신이다(D-212).
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        for w in [section] + section.findChildren(QWidget):
            if w.layout() is not None:
                w.layout().activate()
        lay = self._body.layout()
        if lay is not None:
            lay.activate()
        self.scroll.ensureWidgetVisible(section, 0, 0)
        target = section.api_key if kind == "key" else section.claude_edit
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def showEvent(self, ev) -> None:  # noqa: N802 (Qt)
        super().showEvent(ev)
        if self._pending_reveal:
            QTimer.singleShot(0, self._apply_reveal)

    def set_stt_fallback_notice(self, text: str) -> None:
        """저장된 음성 인식 언어가 표 밖이어서 한국어로 바꾼 안내 줄(NEW-59 · 59N). 빈 글이면 감춘다."""
        self.stt_fallback_notice.setText(text or "")
        self.stt_fallback_notice.setVisible(bool(text))

    def set_unsupported_locales(self, unsupported) -> None:
        """이 macOS 가 지원하지 않는 언어 코드를 회색 항목으로 바꾼다(NEW-58, 선택할 수 없다). 빈 집합이면 모두 선택할 수 있다."""
        model = self.stt_language.model()
        bad = set(unsupported or ())
        note58 = _t("newlang.new58")
        for i in range(model.rowCount()):
            it = model.item(i)
            code = it.data(_ROLE_CODE)
            if code in bad:
                it.setData(note58, _ROLE_NOTE)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            else:
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self._unsupported = bad

    def unsupported_locale_codes(self) -> set:
        return set(getattr(self, "_unsupported", ()))

    def reset_prompt_to_original(self) -> None:
        """[처음 문구]: 칸의 글을 실행 중인 앱 언어 판의 처음 문구로 되돌린다(AC-FR2-5)."""
        self.session_prompt.setPlainText(self._original_prompt())

    def _original_prompt(self) -> str:
        from ..core import i18n
        return core_resources.default_session_prompt(i18n.language())

    def _save_prompt_default(self) -> None:
        """[기본값으로 저장]: 칸의 글을 즉시 설정의 기본 문구로 기록한다. 처음 문구와 같으면 빈 글(앱 기본 문구를 쓴다)이다."""
        text = self.session_prompt.toPlainText()
        if not text.strip():
            return
        same = text.strip() == self._original_prompt().strip()
        self.default_prompt_saved.emit("" if same else text)

    def _sync_prompt_buttons(self) -> None:
        text = self.session_prompt.toPlainText()
        self.original_prompt_btn.setEnabled(text != self._original_prompt())
        self.save_default_btn.setEnabled(bool(text.strip()))

    def content_height(self) -> int:
        """스크롤 없이 내용을 모두 보이는 창 높이(아래 줄 포함). 본문의 높이는 줄 바꿈 글 때문에 폭에 따라 달라지므로
        `sizeHint`(힌트 폭의 높이)가 아니라 본문의 실제 폭에서의 선호 높이(`heightForWidth`)로 센다(D-151, AC-FR1-25)."""
        body = self.scroll.widget()
        w = self.scroll.viewport().width()
        if w <= 0 or not self.isVisible():
            w = self.WIDTH
        w = max(w, body.minimumSizeHint().width())      # 본문은 최소 폭(두 열 4 · 5 의 합)보다 좁아지지 않는다
        lay = body.layout()
        h = lay.heightForWidth(w) if lay is not None and lay.hasHeightForWidth() else body.sizeHint().height()
        return max(h, 0) + 64

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, _t("start.path"), self.save_dir.text())
        if path:
            self.save_dir.setText(path)

    def show_checking(self, on: bool) -> None:
        """인증 출처 확인 중(결정 0056): 단추를 막고 "확인 중" 을 표시한다."""
        self._checking = on
        self.start.setText(_t("start.show_checking_053") if on else _t("start.init___046"))
        self._update_start_enabled()
        if on:
            self.show_problem("")

    def _update_start_enabled(self) -> None:
        self.start.setEnabled(not (self._checking or self._blocked))

    def show_problem(self, text: str, hint: str = "", blocking: bool = False) -> None:
        """시작 화면 맨 위의 띠. `blocking` 이면 [세션 시작] 을 끈다(키 없음 · claude 없음처럼 설정에서만 해소되는 경우).
        빈 글이면 띠를 숨기고 단추를 다시 켠다."""
        self.problem.setText(text)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        self.problem.setVisible(bool(text))
        self.banner.setVisible(bool(text))
        self._blocked = bool(text) and blocking
        self._update_start_enabled()
        self._sync_check_line()

    def show_check_line(self, text: str) -> None:
        """점검 상태 줄의 글(빈 글이면 숨긴다). 시작 불가 띠가 보이는 동안에는 글을 두어도 보이지 않는다."""
        self._check_text = text
        self.check_text.setText(text)
        self._sync_check_line()

    def _sync_check_line(self) -> None:
        self.check_line.setVisible(bool(self._check_text) and not self.problem.text())

    @property
    def blocked(self) -> bool:
        return self._blocked

    def add_section(self, widget: QWidget) -> None:
        """사전 지식 구역(5)을 음성 소스와 세션 문서 사이에 더한다."""
        self._lay.insertWidget(self._material_index, widget)

    def eventFilter(self, obj, ev) -> bool:      # noqa: N802 (Qt)
        if obj is self._body and ev.type() == QEvent.Type.LayoutRequest:
            self._relayout_timer.start()          # 본문의 요소가 바뀌었다
        return False

    def layout_elements(self) -> list:
        """본문의 보이는 요소(위에서 아래)와 표시 높이. 내용 높이 = 위 여백 20 + 높이의 합 + 간격 18 × (요소 수 − 1) + 아래 여백 20 + 하단 행 64
        (AC-FR1-25). 시험이 이 값으로 `content_height()` 를 대조한다."""
        out = []
        for i in range(self._lay.count()):
            w = self._lay.itemAt(i).widget()
            if w is not None and not w.isHidden():
                ew = w.width()                       # 요소의 실제 폭에서의 선호 높이(남는 높이는 배분하지 않는다)
                h = w.heightForWidth(ew) if w.hasHeightForWidth() else w.sizeHint().height()
                out.append((w.objectName() or type(w).__name__, h))
        return out

    # ----- 세션 프롬프트 칸 (결정 0120) -----
    def effective_default_prompt(self) -> str:
        """설정의 기본 문구(비었으면 앱의 기본 문구) 전문."""
        return settings.resolve_session_prompt(self._data, None, core_resources.default_session_prompt())[1]

    def reload_default_prompt(self, data: Optional[Mapping] = None) -> None:
        """칸에 설정의 기본 문구를 넣는다. 사용자가 칸을 고쳤으면(마지막으로 넣은 기본 문구와 다르면) 덮어쓰지 않는다."""
        if data is not None:
            self._data = dict(data)
        new = self.effective_default_prompt()
        cur = self.session_prompt.toPlainText()
        if cur == self._prompt_loaded or not self._prompt_inited:
            self.session_prompt.setPlainText(new)
        self._prompt_loaded = new
        self._prompt_inited = True

    def reset_prompt_to_default(self) -> None:
        """[기본값]: 칸의 글을 설정의 기본 문구로 되돌린다(칸의 글이 이미 같아도 단추는 켜져 있다)."""
        new = self.effective_default_prompt()
        self.session_prompt.setPlainText(new)
        self._prompt_loaded = new

    def _reload_models(self, family: Optional[str], effort: Optional[str]) -> None:
        provider = combo_data(self.provider)
        self.family.blockSignals(True)
        self.family.clear()
        for f in settings.families(self._data, provider):
            self.family.addItem(appstate.FAMILY_LABELS.get(f, f), f)
        set_combo_data(self.family, family)
        self.family.blockSignals(False)
        self.family.setToolTip(FAMILY_TOOLTIP)
        self.family_cards.rebuild()                 # 결정 0143: 모델은 effort 와 같은 카드 없는 라디오 줄이다
        self.family_cards.set_tooltip_all(FAMILY_TOOLTIP)
        self._reload_effort(effort)
        self.fee.setVisible(provider == "claude_api")

    def _reload_effort(self, effort: Optional[str]) -> None:
        tbl = settings.effort_table(self._data, combo_data(self.provider), combo_data(self.family))
        self.effort.clear()
        for e in tbl.options:
            self.effort.addItem(e, e)
        if tbl.options:
            set_combo_data(self.effort, effort if effort in tbl.options else tbl.default)
        self.effort.setVisible(bool(tbl.options))   # 단계가 없는 계열은 입력을 숨긴다(AC-FR1-9)
        self.effort_cards.rebuild()
        self.effort_cards.set_tooltip_all(EFFORT_TOOLTIP)
        self.effort_section.setVisible(bool(tbl.options))

    def _on_provider(self) -> None:
        self._reload_models(combo_data(self.family) if self.family.count() else None, None)
        # 제공자를 바꾸면 계열 목록도 다시 읽는다(표가 다를 수 있다)
        if combo_data(self.family) is None and self.family.count():
            self.family.setCurrentIndex(0)

    def _sync_title_placeholder(self) -> None:
        self.title.setPlaceholderText(_t("newlang.new62") if combo_data(self.kind) == "회의" else _t("start.init___042"))

    def _on_family(self) -> None:
        self._reload_effort(None)

    def effort_value(self) -> Optional[str]:
        return combo_data(self.effort) if self.effort.count() else None

    def values(self) -> dict:
        return {
            "provider": combo_data(self.provider), "model": combo_data(self.family), "effort": self.effort_value(),
            "source": combo_data(self.source), "kind": combo_data(self.kind),
            "stt_language": combo_data(self.stt_language),
            "title": self.title.text().strip(),
            "save_dir": self.save_dir.text().strip(),
            "session_prompt": self.session_prompt.toPlainText(),
        }


class _PromptEdit(QPlainTextEdit):
    """입력란을 떠날 때 `focus_lost` 를 알리는 글 상자(설정의 기본 프롬프트 · 템플릿은 입력을 마친 때 저장한다).
    `focus_changed(bool)` 은 초점을 얻거나 잃을 때마다 알린다(템플릿 칸의 초점 표시)."""
    focus_lost = Signal()
    focus_changed = Signal(bool)

    def focusInEvent(self, e) -> None:        # noqa: N802 (Qt)
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e) -> None:       # noqa: N802 (Qt)
        super().focusOutEvent(e)
        self.focus_changed.emit(False)
        self.focus_lost.emit()


class SettingsForm(QWidget):
    """설정 화면(FR-1 · FR-15, 시안 `Settings`, 결정 0068 · 0179). 구역: 테마 · 단축키 표 · 정리 문서 템플릿. 값은 신호로만 알린다.
    모델 제공자 · 음성 소스 · 언어 · claude 실행 파일 · API 키 · 기본 프롬프트는 시작 화면으로 옮겼다(결정 0179).
    선택지의 원본은 콤보 상자이며(크기 0 의 보관 위젯), 화면에는 카드 · 목록으로 표시한다."""
    appearance_changed = Signal(str)
    template_changed = Signal(str, str)      # (수업 | 회의, 본문). 빈 글은 앱 기본 템플릿이다(AC-FR13-9)
    key_row_changed = Signal(str, str)      # (행 번호, 키 글) 키 설정 표의 변경(결정 0141)
    close_requested = Signal()

    WIDTH = 760

    def __init__(self, data: Mapping, parent=None, *, other_menu_items=None, system_conflict=None):
        super().__init__(parent)
        from ..core import resources
        self._resources = resources
        self._holder = QWidget(self)
        self._holder.setFixedSize(0, 0)
        self.appearance = QComboBox(self._holder)
        for value, label in appstate.APPEARANCE_CHOICES:
            self.appearance.addItem(label, value)
        set_combo_data(self.appearance, appstate.normalize_appearance(data.get("appearance")))

        def card() -> tuple:
            f = QFrame()
            f.setObjectName("doc_panel")
            v = QVBoxLayout(f)
            v.setContentsMargins(14, 12, 14, 12)
            v.setSpacing(10)
            return f, v

        def small_button(text: str, h: int = 36) -> QPushButton:
            b = QPushButton(text)
            b.setFixedHeight(h)
            side = " padding-left: 12px; padding-right: 12px; font-size: 13px; font-weight: 500;" if h <= 28 else ""        # 시각 설계 268: 되돌리기 단추(높이 28)의 좌우 여백 12 · 글 13px(`label`) 500(D-169)
            b.setStyleSheet("QPushButton { min-height: %dpx; padding-top: 0px; padding-bottom: 0px;%s }" % (h - 2, side))   # 기본 단추의 min-height 20 + 여백 + 테두리 = 38 이 고정 높이를 덮어쓰지 않게 한다(D-166)
            return b

        body = QWidget()
        body.setObjectName("start_body")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(16)

        # 테마(결정 0158)
        lay.addWidget(_section(_t("setform.init___069")))
        self.appearance_cards = ChoiceCards(self.appearance)
        notes = {appstate.APPEARANCE_SYSTEM: _t("setform.notes"),
                 appstate.APPEARANCE_LIGHT: _t("setform.notes_2"), appstate.APPEARANCE_DARK: _t("setform.notes_3")}
        for i, b in enumerate(self.appearance_cards.buttons()):
            b.setToolTip(notes.get(self.appearance.itemData(i), ""))
        lay.addWidget(self.appearance_cards)

        # 단축키
        lay.addWidget(_section(_t("setform.init___057")))
        self.key_table = KeyTable(data, other_menu_items or (lambda: {}), system_conflict or (lambda _t: None))
        self.key_table.key_changed.connect(self._on_key_row_changed)
        self.trigger_key = self.key_table._rows["trigger"].cap          # 앞선 판의 이름(시험이 읽는다)
        self.trigger_change = self.key_table._rows["trigger"].change
        lay.addWidget(self.key_table)

        # 정리 문서 템플릿
        lay.addWidget(_section(_t("setform.init___083")))
        # 절 카드 하나(결정 0181 5항, 시각 설계 7-12 "설정의 정리 문서 템플릿 절"): 카드 안에 따로 테두리 · 바탕 · 모서리를 가진 상자를 두지 않는다.
        # 위에서 아래로 수업 · 회의 두 구역과 단추 구역이고 구역 사이는 hairline 1px 가로선 하나이다. 편집 칸은 테두리 · 바탕이 없다.
        tc = QFrame()
        tc.setObjectName("template_card")
        tcv = QVBoxLayout(tc)
        tcv.setContentsMargins(0, 0, 0, 0)          # 테두리 1px 는 스타일시트가 안쪽에 더한다
        tcv.setSpacing(0)
        self.template_edits = {}
        self.template_caps = {}
        self.template_dividers = {}
        for kind, label in (("수업", _t("setform.init___084")), ("회의", _t("setform.init___085"))):
            zone = QWidget()
            zone.setObjectName("template_zone")
            zl = QVBoxLayout(zone)
            zl.setContentsMargins(14, 10, 14, 12)
            zl.setSpacing(4)
            cap = QLabel(label)
            cap.setObjectName("template_cap")
            cap.setFixedHeight(18)
            ed = _PromptEdit()
            ed.setObjectName("template_edit")
            ed.setFixedHeight(92)
            ed.setAccessibleName(label)
            ed.setFrameShape(QFrame.Shape.NoFrame)
            self.template_edits[kind] = ed
            self.template_caps[kind] = cap
            zl.addWidget(cap)
            zl.addWidget(ed)
            tcv.addWidget(zone)
            line = QFrame()
            line.setObjectName("template_divider")
            line.setFixedHeight(1)
            self.template_dividers[kind] = line
            tcv.addWidget(line)
            ed.focus_changed.connect(lambda on, k=kind: self._sync_template_focus(k, on))
        bz = QWidget()
        bz.setObjectName("template_buttons")
        bzl = QHBoxLayout(bz)
        bzl.setContentsMargins(14, 10, 14, 10)
        self.templates_reset = small_button(_t("setform.init___086"), 28)
        bzl.addStretch(1)
        bzl.addWidget(self.templates_reset)
        tcv.addWidget(bz)
        lay.addWidget(tc)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("start_scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        self.scroll = scroll
        bottom = QFrame()
        bottom.setObjectName("win_bottom")
        bottom.setFixedHeight(56)
        br = QHBoxLayout(bottom)
        br.setContentsMargins(24, 0, 24, 0)
        br.addStretch(1)
        self.close_button = small_button(_t("end.init___149"))
        self.close_button.setObjectName("primary")
        br.addWidget(self.close_button)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addWidget(bottom)

        self._load_texts(data)
        self.appearance.currentIndexChanged.connect(lambda _i: self.appearance_changed.emit(combo_data(self.appearance)))
        self._no_default_buttons()
        for kind, ed in self.template_edits.items():
            ed.focus_lost.connect(lambda k=kind: self._emit_template(k))
        self.templates_reset.clicked.connect(self._reset_templates)
        self.close_button.clicked.connect(self._on_close)

    # ---- 값 읽기 · 맞추기 ----
    def content_height(self) -> int:
        return self.scroll.widget().sizeHint().height() + 56

    def _load_texts(self, data: Mapping) -> None:
        tpl = data.get("templates") or {}
        defaults = {"수업": self._resources.lecture_template(), "회의": self._resources.meeting_template()}
        for kind, key in (("수업", "lecture"), ("회의", "meeting")):
            v = tpl.get(key)
            self.template_edits[kind].setPlainText(v if isinstance(v, str) and v.strip() else defaults[kind])

    def sync(self, data: Mapping) -> None:
        """창을 다시 열 때 현재 설정으로 선택을 맞춘다(D-077). 신호를 막아 저장을 다시 일으키지 않는다."""
        self.appearance.blockSignals(True)
        try:
            set_combo_data(self.appearance, appstate.normalize_appearance(data.get("appearance")))
        finally:
            self.appearance.blockSignals(False)
        self.appearance_cards._sync_checked()
        self.key_table.set_values(dict(data))
        self._load_texts(data)

    def _no_default_buttons(self) -> None:
        """설정 창은 기본 단추가 없다(D-104): 입력 칸의 Enter 가 `QDialog` 의 기본 단추(첫 단추)를 누르지 않게 한다."""
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)
            b.setDefault(False)

    def showEvent(self, ev) -> None:  # noqa: N802 (Qt)
        self._no_default_buttons()
        super().showEvent(ev)

    # ---- 템플릿 ----
    def _template_default(self, kind: str) -> str:
        return self._resources.lecture_template() if kind == "수업" else self._resources.meeting_template()

    def _sync_template_focus(self, kind: str, on: bool) -> None:
        """초점 표시(시각 설계 7-12): 초점이 있는 칸의 이름 줄은 `text` 색, 그 구역 아래 구분선은 `hairline-strong` 이고 다른 칸은 그대로이다."""
        for w in (self.template_caps[kind], self.template_dividers[kind]):
            w.setProperty("focused", bool(on))
            w.style().unpolish(w)
            w.style().polish(w)

    def _emit_template(self, kind: str) -> None:
        text = self.template_edits[kind].toPlainText()
        same = text.strip() == self._template_default(kind).strip()
        self.template_changed.emit(kind, "" if same or not text.strip() else text)

    def _reset_templates(self) -> None:
        for kind, ed in self.template_edits.items():
            ed.setPlainText(self._template_default(kind))
            self.template_changed.emit(kind, "")

    def flush(self) -> None:
        """창을 닫기 전에 입력 중이던 글을 저장 신호로 낸다."""
        for kind in self.template_edits:
            self._emit_template(kind)

    def _on_close(self) -> None:
        self.flush()
        self.close_requested.emit()

    # ---- 단축키 ----
    def _on_key_row_changed(self, row_id: str, text: str) -> None:
        self.key_row_changed.emit(row_id, text)




class AboutView(QWidget):
    """앱 정보 창의 내용(AC-NF-4, 시안 `8 앱 정보`): 왼쪽에 이미지(결정 0043), 오른쪽에 이름 · 부제 · 유래 두 문장.
    수치는 design 이 시안 원문에서 옮긴 값이다(점 단위): 안쪽 여백 위아래 24 · 좌우 28, 열 간격 24,
    이미지 240 x 300(원본 1122 x 1402 와 같은 비율), 글 묶음 항목 간격 6."""
    WIDTH = 640
    HEIGHT = 420             # 결정 0068 5항(design 값): 창 높이 420 고정, 내용은 세로 가운데에 둔다

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(28, 24, 28, 24)
        row.setSpacing(24)
        self.image = QLabel()
        self.image.setObjectName("about_image")
        self.image.setFixedSize(ABOUT_IMAGE_SIZE[0], ABOUT_IMAGE_SIZE[1])
        self.image.setAlignment(Qt.AlignCenter)
        pm = QPixmap(str(image_path))
        self.source_size = (pm.width(), pm.height())
        if not pm.isNull():
            self.image.setPixmap(pm.scaled(ABOUT_IMAGE_SIZE[0], ABOUT_IMAGE_SIZE[1], Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))
        col = QVBoxLayout()
        col.setSpacing(6)
        col.setAlignment(Qt.AlignVCenter)
        self.title = QLabel(APP_NAME)
        self.title.setObjectName("about_title")
        self.subtitle = QLabel(APP_SUBTITLE)
        self.subtitle.setObjectName("about_subtitle")
        self.card = QFrame()
        self.card.setObjectName("about_card")
        inner = QVBoxLayout(self.card)
        inner.setContentsMargins(14, 12, 14, 12)
        self.origin = QLabel(ABOUT_ORIGIN)
        self.origin.setObjectName("about_origin")
        self.origin.setWordWrap(True)
        # 글 묶음 폭 = 창 폭 - 좌우 여백 56 - 이미지 240 - 열 간격 24, 카드 안쪽 = 테두리 2 + 좌우 여백 28.
        # 줄바꿈 글의 높이는 폭이 정해져야 계산되므로 폭을 고정하고 높이를 맞춘다(안 그러면 카드 안에서 잘린다).
        text_w = self.WIDTH - 56 - ABOUT_IMAGE_SIZE[0] - 24 - 2 - 28
        self.origin.setFixedWidth(text_w)
        self.origin.setMinimumHeight(self.origin.heightForWidth(text_w))
        inner.addWidget(self.origin)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        col.addSpacing(12)
        col.addWidget(self.card)
        row.addWidget(self.image, 0, Qt.AlignVCenter)
        row.addLayout(col, 1)


class LevelBar(QWidget):
    """입력 레벨 막대: 6칸, 칸 폭 3px · 간격 2px · 최대 높이 14px. 채운 칸은 `ok`, 빈 칸은 `hairline`,
    수집 중단이면 3px 높이의 회색(`docs/visual-design.md` 8절)."""
    CELL_W, GAP, MAX_H, STOPPED_H = 3, 2, 14, 3

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self.GAP)
        self._cells = []
        for i in range(appstate.LEVEL_CELLS):
            c = QFrame(self)
            c.setFixedWidth(self.CELL_W)
            lay.addWidget(c, 0, Qt.AlignVCenter)
            self._cells.append(c)
        self.setFixedHeight(self.MAX_H)
        self._count, self._stopped = 0, False
        self.set_cells(0, False)

    def _height(self, i: int) -> int:
        return 4 + round((self.MAX_H - 4) * i / (len(self._cells) - 1))

    def set_cells(self, count: int, stopped: bool) -> None:
        self._count, self._stopped = max(0, min(len(self._cells), int(count))), bool(stopped)
        for i, c in enumerate(self._cells):
            if self._stopped:
                c.setObjectName("level_stopped")
                c.setFixedHeight(self.STOPPED_H)
            else:
                c.setObjectName("level_on" if i < self._count else "level_off")
                c.setFixedHeight(self._height(i))
            c.style().unpolish(c)
            c.style().polish(c)

    def cells(self) -> int:
        """채운 칸 수(AC-FR3-10 의 판정 값). 수집 중단이면 0 이다."""
        return 0 if self._stopped else self._count


PILL_H = 20                                      # 시각 설계 7-4 알약 높이


class StatusBar(QStatusBar):
    """상태 표시줄(FR-11). `show_inputs` 로 `appstate.status_items` 의 값을 그대로 표시한다.
    수집 상태 옆에 입력 레벨 막대를 둔다(AC-FR3-10)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self.setFixedHeight(32)                     # 시안 3: 높이 32, 좌우 여백 14, 항목 간격 18 (D-086 · D-089)
        self._text = ""
        self._box = QWidget()
        self._box.setObjectName("status_box")
        self._row = QHBoxLayout(self._box)
        self._row.setContentsMargins(14, 0, 14, 0)
        self._row.setSpacing(18)
        self._labels: list = []
        self._names: list = []
        self._prep_shown = False
        self._chip_shows = 0
        self.more = QLabel("…")                      # 감춘 항목이 있을 때 오른쪽 끝에 둔다
        self.more.setObjectName("status_item")
        self.more.setVisible(False)
        self._row.addStretch(1)
        self._row.addWidget(self.more)                      # 항목은 이 늘어나는 칸 앞에 넣는다
        self.level = LevelBar(self._box)
        self.level.setToolTip(_t("screens.init___093"))
        self._box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # 항목의 폭 합이 창의 최소 폭이 되지 않게 한다(D-098)
        self.addWidget(self._box, 1)

    def minimumSizeHint(self):  # noqa: N802 (Qt)
        return QSize(0, self.height())

    def level_cells(self) -> int:
        """입력 레벨 막대의 칸 수(0 ~ 6). 기술 계획 5절의 연결점이다."""
        return self.level.cells()

    def set_level(self, rms_dbfs: Optional[float], capture_state: Optional[str]) -> int:
        n = appstate.level_to_cells(rms_dbfs, capture_state == "수집 중")
        self.level.set_cells(n, capture_state in ("중단", "일시 정지", "수집 전"))      # 3px 회색(수집 중단 · 일시 정지 · 수집 전)
        return n

    def show_inputs(self, s: appstate.StatusInputs) -> str:
        items = appstate.status_items(s)
        text = " · ".join(v for _, v in items)
        for lb in self._labels:
            self._row.removeWidget(lb)
            lb.hide()                            # deleteLater 는 이벤트 루프가 돌아야 삭제하므로, 그 사이 이전 라벨이 보이지 않게 한다
            lb.setParent(None)
            lb.deleteLater()
        self._labels = []
        self._names = []
        self._row.removeWidget(self.level)
        for name, value in items:
            lb = QLabel(value)
            if name in ("activity", "stt_prep"):      # FR-11: 요청 진행 중 · 모델 준비 중은 해당할 때만 알약으로 표시한다
                lb.setObjectName("status_pill")
            elif name == "capture_state" and s.capture_state in (appstate.COLLECT_PAUSED, appstate.COLLECT_BEFORE):
                lb.setObjectName("status_item_warn" if s.capture_state == appstate.COLLECT_PAUSED else "status_item_info")
            else:
                lb.setObjectName("status_item")
            if lb.objectName() == "status_pill":      # 시각 설계 7-4: 알약 높이 20px(표시줄 높이까지 늘리지 않고 세로 가운데, D-221)
                lb.setFixedHeight(PILL_H)
                self._row.insertWidget(self._row.count() - 2, lb, 0, Qt.AlignmentFlag.AlignVCenter)
            else:
                self._row.insertWidget(self._row.count() - 2, lb)
            self._labels.append(lb)
            self._names.append(name)
            if name == "capture_state":               # FR-11: 수집 상태 바로 옆에 입력 레벨 막대
                self._row.insertWidget(self._row.count() - 2, self.level)
        if self._row.indexOf(self.level) < 0:
            self._row.insertWidget(self._row.count() - 2, self.level)
        self._text = text
        shown = "stt_prep" in self._names
        if shown and not self._prep_shown:
            self._chip_shows += 1                     # 시험 수단: 칩이 새로 나타난 횟수(AC-FR4-18 ⑥)
        self._prep_shown = shown
        self._fit()
        return text

    def chip_show_count(self) -> int:
        """모델 준비 칩이 나타난 횟수(숨겼다가 다시 나타나면 더한다). 시험이 읽는다(5-1절, AC-FR4-18)."""
        return self._chip_shows

    # 표시줄이 폭에 맞지 않으면 우선순위가 낮은 항목부터 통째로 감추고 오른쪽 끝에 "…" 를 둔다(D-098, 시안 판 1791811345-6cdc).
    # 우선순위(높음 → 낮음): 수집 상태 · 현재 상태 · 전사 오류 · 전사 처리 대기 · 요청 대기열 · 음성 소스 · 제공자 · 모델 · 사전 지식 · 캡처 수.
    PRIORITY = ("capture_state", "stt_prep", "activity", "stt_errors", "queue", "source", "provider", "model", "materials", "captures")

    def _fit(self) -> None:
        names = getattr(self, "_names", [])
        for lb in self._labels:
            lb.setVisible(True)
            lb.ensurePolished()                  # 스타일시트가 적용된 글꼴로 폭을 잰다(적용 전 폭으로 재면 실제보다 좁게 계산한다)
        if not names:
            self.more.setVisible(False)
            return
        avail = self.width() - 28
        spacing = self._row.spacing()

        def total(visible: list) -> int:
            w = 0
            for lb, shown in zip(self._labels, visible):
                if shown:
                    w += lb.sizeHint().width() + spacing
            return w + self.level.sizeHint().width() + spacing
        visible = [True] * len(names)
        order = sorted(range(len(names)), key=lambda i: self.PRIORITY.index(names[i]) if names[i] in self.PRIORITY else -1,
                       reverse=True)
        hidden = []
        for i in order:
            if total(visible) <= avail - (self.more.sizeHint().width() + spacing if hidden else 0) or avail <= 0:
                break
            visible[i] = False
            hidden.append(i)
        for lb, shown in zip(self._labels, visible):
            lb.setVisible(shown)
        self.more.setVisible(bool(hidden))
        if hidden:
            self.more.setToolTip("\n".join(self._labels[i].text() for i in sorted(hidden)))

    def resizeEvent(self, e) -> None:       # noqa: N802 (Qt)
        super().resizeEvent(e)
        self._fit()

    def text(self) -> str:
        return self._text
