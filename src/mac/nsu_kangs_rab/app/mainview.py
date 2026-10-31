"""메인 창의 내용: STT 창 · AI 창(카드) · 입력창 (K-12; FR-5 · FR-7 · FR-9 · FR-11).

- 위젯은 값을 표시하고 신호로 알린다. 모델 호출 · 요청 순서는 `core.requests` 가 맡는다.
- 다른 스레드의 콜백(`RequestManager.on_card`, STT 조각)은 `UiBridge` 의 `post_*` 로 넘긴다. 이 호출은 막지 않고 반환한다
  (Qt 의 큐 연결이 주 스레드에서 처리한다, `docs/plan/technical-plan.md` 2-4절 requests 콜백 제약).
- 카드의 글은 서식 없이 글자 그대로 표시한다(AC-FR9-14, 결정 0031).
"""
from __future__ import annotations
from ..core.i18n import t as _t
from ..core import labels

from typing import Optional

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QImage, QKeySequence, QPixmap, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QStyledItemDelegate, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSpacerItem, QSplitter, QStyle, QVBoxLayout,
                               QWidget)
from PySide6.QtSvgWidgets import QSvgWidget

from ..core import appstate
from ..core import error_text
from ..core import requests as R
from ..core.diagram import can_diagram
from ..core.types import Segment

CARD_DELETE_NAME = _t("main.card_delete_name")        # AC-FR9-16 접근성 이름
DIAGRAM_BUTTON_NAME = _t("main.diagram_button_name")   # AC-FR9-6 접근성 이름 · 도움말
DIAGRAM_BUSY_TEXT = _t("ctl.activity")
DIAGRAM_RETRY_TEXT = _t("main.diagram_retry_text")
STATE_LABELS = {R.STATE_WAITING: _t("label.state_waiting"), R.STATE_ACTIVE: _t("main.state_labels_2"), R.STATE_DONE: "", R.STATE_ERROR: ""}   # 오류는 종류 알약이 말한다(D-097b)


def hhmmss(iso: str) -> str:
    """ISO 8601 → HH:MM:SS (밀리초 · 시간대 제거). 읽지 못하면 원문 일부를 그대로 둔다."""
    try:
        t = iso.split("T", 1)[1]
        return t[:8]
    except IndexError:
        return iso[:8]


def format_duration(seconds: int) -> str:
    """일시 정지 구간의 길이(NEW-26): 60초 미만 "{n}초", 1시간 미만 "{m}분 {s}초"(s 가 0 이면 "{m}분"), 1시간 이상 "{h}시간 {m}분"(m 이 0 이면 "{h}시간")."""
    sec = max(0, int(seconds))
    if sec < 60:
        return _t("pause.dur_s").format(n=sec)
    if sec < 3600:
        m, r = divmod(sec, 60)
        return _t("pause.dur_ms").format(m=m, s=r) if r else _t("pause.dur_m").format(m=m)
    h, r = divmod(sec, 3600)
    m = r // 60
    return _t("pause.dur_hm").format(h=h, m=m) if m else _t("pause.dur_h").format(h=h)


def question_html(text: str) -> str:
    """질문 줄(결정 0151)의 서식 글: 머리말만 굵게, " · " 는 mute 색, 문장은 입력한 그대로(줄바꿈 · 연속 공백 유지)."""
    import html
    from PySide6.QtWidgets import QApplication
    from . import theme
    mute = theme.tokens(QApplication.instance().property("rab_scheme") or "light")["mute"] if QApplication.instance() else "#888"
    body = html.escape(text).replace("\r\n", "\n").replace("\n", "<br>").replace("  ", "&nbsp; ")
    return '<span style="white-space:pre-wrap"><b>%s</b><span style="color:%s"> · </span>%s</span>' % (html.escape(_t("ctl.card_q")), mute, body)


def judgment_line(card: R.Card) -> Optional[str]:
    """판단 줄(AC-FR7-1). 판단이 없는 요청(`/답변` · `/고찰` 등)은 줄이 없다."""
    j = card.judgment
    if j is None:
        return None
    if j == R.JUDGMENT_UNCONFIRMED:
        return _t("main.judgment_line_169")
    if card.judgment_subject:
        if j == "질문 없음":
            return _t("main.judgment_line_170") % (labels.judgment_label(j), card.judgment_subject)
        return _t("main.judgment_line_171") % (labels.judgment_label(j), card.judgment_subject)
    return _t("main.judgment_line_172") % labels.judgment_label(j)


class StatusBanner(QFrame):
    """전사 창 위의 상태 띠(visual-design 7-5): 제목과 설명. 음성 인식 보조 프로세스가 끝나서 중단된 띠에만 오른쪽에 [다시 시도] 가
    있다(시안 3-13). 해당 상태가 아니면 숨는다."""
    retry_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)          # 시안 3: 전사 창 머리 아래의 띠(여백 10 · 14)
        outer.setSpacing(12)
        lay = QVBoxLayout()
        lay.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("banner_title")
        self.description = QLabel("")
        self.description.setObjectName("banner_text")
        self.description.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.description)
        outer.addLayout(lay, 1)
        self.retry = QPushButton(_t("card.cancelled_view_377"))
        self.retry.setObjectName("banner_retry")
        self.retry.setFixedHeight(32)
        self.retry.setVisible(False)
        self.retry.clicked.connect(lambda _c=False: self.retry_clicked.emit())
        outer.addWidget(self.retry, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setVisible(False)

    def show_banner(self, title: str, description: str, retry: bool = False, retry_enabled: bool = True, tone: str = "") -> None:
        """`tone` 가 "info" 이면 정보 색의 띠(권한 안내, 결정 0178)이고 빈 글이면 경고 색의 기본 띠이다."""
        for w in (self, self.title):
            if (w.property("tone") or "") != tone:
                w.setProperty("tone", tone)
                w.style().unpolish(w)
                w.style().polish(w)
        self.title.setText(title)
        self.description.setText(description)
        self.description.setVisible(bool(description))
        self.retry.setVisible(bool(retry))
        self.retry.setEnabled(bool(retry_enabled))
        self.setVisible(True)

    def clear_banner(self) -> None:
        self.setVisible(False)
        self.title.setText("")
        self.description.setText("")
        self.retry.setVisible(False)

    def tone(self) -> str:
        """띠의 색 종류: "info"(권한 안내) 또는 빈 글(경고 색). 시험의 판정 값이다."""
        return str(self.property("tone") or "")

    def retry_state(self) -> tuple:
        """([다시 시도] 가 보이는가, 켜져 있는가). 시험의 판정 값이다."""
        return (not self.retry.isHidden(), self.retry.isEnabled())

    def state(self) -> tuple:
        """(보임, 제목, 설명). 시험의 판정 값이다."""
        return (not self.isHidden(), self.title.text(), self.description.text())


class UiBridge(QObject):
    """다른 스레드에서 주 스레드로 값을 넘기는 연결부. `post_*` 는 잠그지 않고 즉시 반환한다."""
    card = Signal(object, str)
    segment = Signal(object)
    notice = Signal(str, object)
    capture = Signal(str, str)
    stt = Signal(str, object)           # 음성 인식 보조 프로세스의 사건(잠정 문장 · 준비 · 종료)을 주 스레드로 넘긴다

    def post_stt(self, kind: str, payload=None) -> None:
        self.stt.emit(kind, payload)

    def post_capture(self, state: str, detail: str) -> None:
        self.capture.emit(state, detail)

    def post_card(self, card, change: str) -> None:
        self.card.emit(card, change)

    def post_segment(self, seg) -> None:
        self.segment.emit(seg)

    def post_notice(self, kind: str, info) -> None:
        self.notice.emit(kind, info)


_ROLE_KIND = Qt.ItemDataRole.UserRole + 4      # 항목 종류: 조각은 None, 일시 정지 구간 줄은 "pause"
_PAUSE_ROW_H = 36                              # 위아래 여백 8 + 알약
_TIME_COL = 58          # 시안 3: 시각 칸 너비(px)
_ROW_PAD_X, _ROW_PAD_Y = 14, 7


class _SegmentDelegate(QStyledItemDelegate):
    """전사 한 줄: 시각 칸(58px)과 글 칸. 글은 창 너비에서 줄바꿈하고 가로 스크롤이 없다(시안 3, D-086)."""

    @staticmethod
    def _colors(partial: bool = False) -> tuple:
        """(시각 색, 본문 색): 앱이 적용한 화면 밝기의 토큰(D-096, 본문은 body: 7-7). 정해지지 않았으면 밝은 화면이다.
        잠정 행은 글 색이 `sub`(= `mute`)이다(결정 0167 1항, 7-7)."""
        from PySide6.QtWidgets import QApplication
        from . import theme
        app = QApplication.instance()
        tk = theme.tokens(str(app.property("rab_scheme") or "light") if app is not None else "light")
        return tk["mute"], (tk["mute"] if partial else tk["body"])

    def _doc(self, index, width: int) -> QTextDocument:
        import html
        mute, ink = self._colors(index.data(_ROLE_KIND) == "partial")
        t = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        s = index.data(Qt.ItemDataRole.UserRole + 2)
        doc = QTextDocument()
        doc.setDefaultFont(self.parent().font() if self.parent() is not None else doc.defaultFont())
        if s is None:
            doc.setPlainText(index.data(Qt.ItemDataRole.DisplayRole) or "")
        else:
            doc.setHtml('<table cellspacing="0" cellpadding="0"><tr><td width="%d" style="color:%s; font-size:12pt">%s</td>'
                        '<td style="color:%s">%s</td></tr></table>' % (_TIME_COL, mute, html.escape(t), ink, html.escape(s)))
        doc.setTextWidth(max(40, width))
        return doc

    def __init__(self, parent=None):
        super().__init__(parent)
        self._heights: dict = {}

    def sizeHint(self, option, index):  # noqa: N802 (Qt)
        width = option.rect.width() if option.rect.width() > 0 else self.parent().viewport().width()
        if index.data(_ROLE_KIND) == "pause":
            return QSize(width, _PAUSE_ROW_H)
        # 항목이 늘 때마다 모든 항목의 크기를 다시 묻는다. 같은 (글, 너비) 의 높이는 한 번만 계산한다(1000 조각 시험)
        key = (index.data(Qt.ItemDataRole.UserRole + 2), index.data(Qt.ItemDataRole.DisplayRole), width)
        h = self._heights.get(key)
        if h is None:
            if len(self._heights) > 20000:
                self._heights.clear()
            h = int(self._doc(index, width - 2 * _ROW_PAD_X).size().height()) + 2 * _ROW_PAD_Y
            self._heights[key] = h
        return QSize(width, h)

    def _paint_pause(self, painter, option, index) -> None:
        """일시 정지 구간 줄(시안 3-6): 가운데 경고색 알약과 양쪽의 가는 선. 시각 열과 맞추지 않고 너비 전체에 걸친다."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QFontMetrics
        from PySide6.QtWidgets import QApplication
        from . import theme
        tk = theme.tokens(str(QApplication.instance().property("rab_scheme") or "light"))
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        f = QFont(self.parent().font() if self.parent() is not None else painter.font())
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.DemiBold)
        f.setStyleHint(QFont.StyleHint.SansSerif)
        fm = QFontMetrics(f)
        painter.save()
        painter.setFont(f)
        r = option.rect
        pill_w = min(fm.horizontalAdvance(text) + 16, r.width() - 2 * _ROW_PAD_X)
        pill_h = fm.height() + 4
        cx, cy = r.center().x(), r.center().y()
        pill = QRectF(cx - pill_w / 2, cy - pill_h / 2, pill_w, pill_h)
        painter.setPen(QColor(tk["hairline"]))
        left, right = r.left() + _ROW_PAD_X, r.right() - _ROW_PAD_X
        if pill.left() - 10 > left:
            painter.drawLine(int(left), cy, int(pill.left() - 10), cy)
        if pill.right() + 10 < right:
            painter.drawLine(int(pill.right() + 10), cy, int(right), cy)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tk["warn-bg"]))
        painter.drawRoundedRect(pill, 4, 4)
        painter.setPen(QColor(tk["warn"]))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), fm.elidedText(text, Qt.TextElideMode.ElideRight, int(pill_w - 16)))
        painter.restore()

    def paint(self, painter, option, index):  # noqa: N802 (Qt)
        from PySide6.QtWidgets import QStyle as _S
        if index.data(_ROLE_KIND) == "pause":
            self._paint_pause(painter, option, index)
            return
        if index.data(_ROLE_KIND) == "partial":
            return                        # 항목 위젯(`_PartialRow`)이 그린다
        painter.save()
        if option.state & _S.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif getattr(self.parent(), "is_recent", None) is not None and self.parent().is_recent(index):
            from . import theme            # 마지막 30초 구간은 면 단계로만 구분한다(D-099, 시각 사양 전사 창)
            from PySide6.QtGui import QColor
            from PySide6.QtWidgets import QApplication
            tk = theme.tokens(str(QApplication.instance().property("rab_scheme") or "light"))
            painter.fillRect(option.rect, QColor(tk["surface-elevated"]))
        doc = self._doc(index, option.rect.width() - 2 * _ROW_PAD_X)
        painter.translate(option.rect.left() + _ROW_PAD_X, option.rect.top() + _ROW_PAD_Y)
        doc.drawContents(painter)
        painter.restore()


class _PartialRow(QWidget):
    """잠정 문장 행(결정 0166 · 0167 1항, 기술 계획 2-8-4 10항). 조각 행과 같은 모양(시각 열 58, 안쪽 여백 7 × 14)이며 글 색만 `sub` 이다.
    기울임 · 불투명도 변화 · 말줄임이 없다. `objectName` = `partial_row`, 속성 `rowKind` = `partial`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("partial_row")
        self.setProperty("rowKind", "partial")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(_ROW_PAD_X, _ROW_PAD_Y, _ROW_PAD_X, _ROW_PAD_Y)
        lay.setSpacing(0)
        self.time_label = QLabel("")
        self.time_label.setFixedWidth(_TIME_COL)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.text_label = QLabel("")
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.time_label)
        lay.addWidget(self.text_label, 1)
        self.apply_colors()

    def apply_colors(self) -> None:
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication
        from . import theme
        app = QApplication.instance()
        tk = theme.tokens(str(app.property("rab_scheme") or "light") if app is not None else "light")
        for lb in (self.time_label, self.text_label):
            pal = lb.palette()
            pal.setColor(QPalette.ColorRole.WindowText, QColor(tk["mute"]))
            lb.setPalette(pal)
            lb.setStyleSheet("color: %s; background: transparent;" % tk["mute"])
        f = self.time_label.font()
        f.setItalic(False)
        f.setPointSize(12)
        self.time_label.setFont(f)

    def set_text(self, start_hms: str, text: str) -> None:
        self.time_label.setText(start_hms)
        self.text_label.setText(text)


class TranscriptView(QListWidget):
    """STT 창. 조각마다 한 항목(시각은 첫 줄에만, 줄바꿈은 창 너비)이고 자동 이동은 맨 아래일 때만 따라간다(AC-FR5-2)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transcript")
        self.setWordWrap(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setItemDelegate(_SegmentDelegate(self))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self._count = 0
        self._pause_item = None
        self._partial_widget = None
        self._partial_item = None                     # 잠정 문장 행(최대 하나, 맨 아래, 결정 0166 · 0167)
        self._recent_timer = QTimer(self)             # 30초 구간의 경계가 지나가면 면을 다시 그린다
        self._recent_timer.setInterval(1000)
        self._recent_timer.timeout.connect(self.viewport().update)
        self._recent_timer.start()

    RECENT_SECONDS = 30
    now_fn = None            # 시험용: 현재 시각을 돌려주는 함수(없으면 시스템 시각)

    def is_recent(self, index) -> bool:
        """조각의 시작이 지금부터 30초 안인가(마지막 30초 구간, 7-7)."""
        from datetime import datetime
        iso = index.data(Qt.ItemDataRole.UserRole + 3)
        if not iso:
            return False
        try:
            t = datetime.fromisoformat(str(iso))
        except ValueError:
            return False
        now = self.now_fn() if self.now_fn is not None else datetime.now(t.tzinfo)
        if (now.tzinfo is None) != (t.tzinfo is None):
            now = now.replace(tzinfo=t.tzinfo)
        return 0 <= (now - t).total_seconds() <= self.RECENT_SECONDS

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def add_segment(self, seg: Segment) -> None:
        follow = self._at_bottom()
        self.clear_partial()               # 확정이 도착하면 그 구간의 잠정 행이 같은 위치에서 조각 행이 된다(AC-FR4-15 ③)
        it = QListWidgetItem("%s  %s" % (hhmmss(seg.start_wall), seg.text))
        it.setData(Qt.ItemDataRole.UserRole, seg.n)
        it.setData(Qt.ItemDataRole.UserRole + 1, hhmmss(seg.start_wall))
        it.setData(Qt.ItemDataRole.UserRole + 2, seg.text)
        it.setData(Qt.ItemDataRole.UserRole + 3, seg.start_wall)
        self.addItem(it)
        self._count += 1
        if follow:
            self.scrollToBottom()

    # ----- 잠정 문장 행 (결정 0166 · 0167 1항, FR-4) -----
    def set_partial(self, text: str, start_hms: str) -> None:
        """잠정 문장을 맨 아래 행 하나에 보인다. 이미 있으면 글을 대체한다(행은 둘이 되지 않는다). 번호가 없고 선택할 수 없다."""
        follow = self._at_bottom()
        it = self._partial_item
        if it is None:
            it = QListWidgetItem("")
            it.setData(_ROLE_KIND, "partial")
            it.setData(Qt.ItemDataRole.UserRole, None)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.addItem(it)
            self._partial_item = it
            self._partial_widget = _PartialRow(self.viewport())
            self.setItemWidget(it, self._partial_widget)
        it.setData(Qt.ItemDataRole.UserRole + 1, start_hms)
        it.setData(Qt.ItemDataRole.UserRole + 2, text)          # 항목 높이는 델리게이트가 이 글로 계산한다(조각 행과 같은 방식)
        it.setText("%s  %s" % (start_hms, text))
        self._partial_widget.set_text(start_hms, text)
        self.scheduleDelayedItemsLayout()
        if follow:
            self.scrollToBottom()

    def clear_partial(self) -> None:
        it, self._partial_item = self._partial_item, None
        if it is not None:
            row = self.row(it)
            if row >= 0:
                self.removeItemWidget(it)
                self.takeItem(row)
            w, self._partial_widget = self._partial_widget, None
            if w is not None:
                w.hide()
                w.deleteLater()

    def partial_widget(self):
        """잠정 행 위젯(없으면 None). 글자색 · 글꼴을 시험이 읽는다."""
        return self._partial_widget

    def partial_text(self) -> Optional[str]:
        it = self._partial_item
        return None if it is None else str(it.data(Qt.ItemDataRole.UserRole + 2))

    def row_kinds(self) -> tuple:
        """행 종류의 목록(위에서 아래): `segment` · `pause` · `partial`. 시험이 읽는다."""
        return tuple(self.item(i).data(_ROLE_KIND) or "segment" for i in range(self.count()))

    # ----- 일시 정지 구간 줄 (결정 0147, FR-5) -----
    def _pause_text(self, start: str, end: Optional[str], seconds: Optional[int]) -> str:
        if end is None:
            return _t("pause.new25").format(start=start)
        return _t("pause.new24").format(start=start, end=end, duration=format_duration(seconds or 0))

    def add_pause(self, start: str, end: Optional[str] = None, seconds: Optional[int] = None) -> None:
        """구간 줄을 끝에 더한다(진행 중이면 `end` 가 None). 번호가 없고 선택할 수 없다. 시각 순서는 호출 순서가 만든다."""
        self.clear_partial()
        follow = self._at_bottom()
        it = QListWidgetItem(self._pause_text(start, end, seconds))
        it.setData(_ROLE_KIND, "pause")
        it.setData(Qt.ItemDataRole.UserRole, None)
        it.setFlags(Qt.ItemFlag.ItemIsEnabled)                    # 선택 대상이 아니다(`/답변` 의 입력에서 제외)
        self.addItem(it)
        if end is None:
            self._pause_item = it
        if follow:
            self.scrollToBottom()

    def close_pause(self, start: str, end: str, seconds: int) -> None:
        """진행 중인 구간 줄을 끝 시각이 붙은 모양으로 바꾼다."""
        it = getattr(self, "_pause_item", None)
        if it is None:
            return
        it.setText(self._pause_text(start, end, seconds))
        self._pause_item = None
        self.viewport().update()

    def pause_lines(self) -> tuple:
        return tuple(self.item(i).text() for i in range(self.count()) if self.item(i).data(_ROLE_KIND) == "pause")

    def toPlainText(self) -> str:  # noqa: N802 (Qt 스타일: 시험이 전사 창의 글을 한 번에 읽는다)
        return "\n".join(self.item(i).text() for i in range(self.count()))

    def resizeEvent(self, ev) -> None:  # noqa: N802 (Qt)
        super().resizeEvent(ev)
        self.doItemsLayout()                # 너비가 바뀌면 줄바꿈이 달라지므로 항목 높이를 다시 정한다

    def count_segments(self) -> int:
        return self._count

    def selected_numbers(self) -> tuple:
        """선택한 조각의 번호(오름차순). `/답변` 요청의 입력이다(FR-5 표시 선택)."""
        return tuple(sorted(i.data(Qt.ItemDataRole.UserRole) for i in self.selectedItems()
                            if i.data(_ROLE_KIND) not in ("pause", "partial")))

    def last_text(self) -> Optional[str]:
        n = self.count()
        return self.item(n - 1).text() if n else None


class _SvgBox(QSvgWidget):
    """카드 안의 SVG. 누르면 `clicked` 를 보낸다(AC-FR9-8)."""
    clicked = Signal()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 (Qt)
        self.clicked.emit()
        super().mouseReleaseEvent(ev)

    def load_file(self, path: str) -> bool:
        self.load(path)
        r = self.renderer()
        ok = r.isValid()
        if ok:
            sz = r.defaultSize()
            w = 320
            h = int(w * sz.height() / sz.width()) if sz.width() > 0 and sz.height() > 0 else 200
            self.setFixedSize(w, max(40, min(h, 240)))
        return ok


class CardWidget(QFrame):
    delete_requested = Signal(int)
    diagram_requested = Signal(int)
    diagram_open_requested = Signal(int)

    def __init__(self, card: R.Card, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.n = card.n
        self.image_labels: list = []
        head = QHBoxLayout()
        self.kind_label = QLabel("")
        self.kind_label.setObjectName("badge")
        self.time_label = QLabel("")
        self.time_label.setObjectName("mute")
        self.state_label = QLabel("")
        self.state_label.setObjectName("mute")
        self.delete = QPushButton("x")
        self.delete.setAccessibleName(CARD_DELETE_NAME)
        self.delete.setObjectName("card_delete")
        self.delete.setText("\u00d7")
        self.delete.setFixedSize(22, 22)
        self.delete.clicked.connect(lambda: self.delete_requested.emit(self.n))
        for w in (self.kind_label, self.time_label, self.state_label):
            head.addWidget(w)
        head.addStretch(1)
        head.addWidget(self.delete)
        self.judgment = QLabel("")
        self.judgment.setWordWrap(True)
        self.judgment.setTextFormat(Qt.TextFormat.PlainText)  # 판단 대상은 모델이 쓴 글이므로 서식으로 해석하지 않는다 (D-038)
        self.card_question = QLabel("")     # 자유 질의 카드의 질문 줄(결정 0151): "질문 · <문장>". 줄이거나 자르지 않는다
        self.card_question.setObjectName("card_question")
        self.card_question.setWordWrap(True)
        self.card_question.setTextFormat(Qt.TextFormat.RichText)     # 머리말만 굵게 하려고 쓴다. 입력한 문장은 이스케이프해 넣는다
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.PlainText)       # 마크다운 · HTML 로 해석하지 않는다(AC-FR9-14)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.partial_line = QLabel("")      # 확정 대기 상한을 넘겨 잠정 문장을 포함한 요청의 한 줄(NEW-60, AC-FR7-14)
        self.partial_line.setObjectName("mute")
        self.partial_line.setWordWrap(True)
        self.partial_line.setTextFormat(Qt.TextFormat.PlainText)
        self.image_rows = QVBoxLayout()     # 이미지 카드(AC-FR12-14): 썸네일 · 크기 · 출처. 시각과 x 는 머리에 있다
        self.image_rows.setSpacing(8)
        self.dropped = QLabel("")           # 요청 합계 상한으로 싣지 못한 첨부의 이름과 사유 (AC-FR7-23)
        self.dropped.setObjectName("mute")
        self.dropped.setWordWrap(True)
        self.dropped.setTextFormat(Qt.TextFormat.PlainText)
        # 다이어그램(FR-9): 오른쪽 아래의 이미지 버튼, 진행 · 실패 표시, [다시 만들기], 완료한 SVG
        self.diagram_button = QPushButton()                   # 그린 그림(둥근 사각 노드 둘과 잇는 선, 시각 설계 7-1). 글자 "▦" 를 쓰지 않는다
        self.diagram_button.setIconSize(QSize(16, 16))
        self.diagram_button.setAccessibleName(DIAGRAM_BUTTON_NAME)
        self.diagram_button.setToolTip(DIAGRAM_BUTTON_NAME)
        self.diagram_button.setObjectName("iconbtn")
        self._set_diagram_icon(False)
        self.diagram_button.setFixedSize(28, 28)
        self.diagram_status = QLabel("")
        self.diagram_status.setObjectName("mute")
        self.diagram_status.setWordWrap(True)
        self.diagram_status.setTextFormat(Qt.TextFormat.PlainText)
        self.diagram_retry = QPushButton(DIAGRAM_RETRY_TEXT)
        self.diagram_view = _SvgBox()
        self.diagram_view.setVisible(False)
        self.diagram_view.setCursor(Qt.CursorShape.PointingHandCursor)
        self._diagram_busy = False
        self._diagram_gate = (True, "")
        self._diagram_allowed = False
        foot = QHBoxLayout()
        foot.addWidget(self.diagram_status, 1)
        # 문구 · [다시 만들기] 가 숨겨져도 버튼이 오른쪽 아래에 있게 한다(D-048, AC-FR9-6). 늘어나는 칸이 보이면 그 칸이 먼저 늘어난다
        foot.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        foot.addWidget(self.diagram_retry)
        foot.addWidget(self.diagram_button)
        self.diagram_button.clicked.connect(lambda: self.diagram_requested.emit(self.n))
        self.diagram_retry.clicked.connect(lambda: self.diagram_requested.emit(self.n))
        self.diagram_view.clicked.connect(lambda: self.diagram_open_requested.emit(self.n))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)       # 시안 3: 카드 여백 16 · 요소 간격 8
        lay.setSpacing(8)
        lay.addLayout(head)
        lay.addWidget(self.card_question)      # 머리 바로 아래, 이미지 줄 위(결정 0151)
        lay.addLayout(self.image_rows)         # 머리 바로 아래, 판단 줄이 있으면 그 위(7-6)
        for w in (self.judgment, self.partial_line, self.body, self.dropped, self.error, self.diagram_view):
            lay.addWidget(w)
        lay.addLayout(foot)
        self.diagram_retry.setVisible(False)
        self.diagram_status.setVisible(False)
        self.update_card(card)

    def _set_diagram_icon(self, enabled: bool) -> None:
        from PySide6.QtWidgets import QApplication
        from . import theme
        app = QApplication.instance()
        tk = theme.tokens(str(app.property("rab_scheme") or "light") if app is not None else "light")
        self.diagram_button.setIcon(line_icon("diagram", tk["body"] if enabled else tk["ash"]))

    def update_card(self, card: R.Card) -> None:
        self.kind_label.setText(labels.kind_label("오류" if card.error else card.kind))
        # [고찰] 요청(종류 트리거)의 카드에는 모든 경로 · 모든 상태에서 종류 알약이 없다. 기준은 요청 종류이며 판단 줄이 아니다
        # (응답 대기 · 첫 줄 전 · "미확인" 포함, 결정 0157 5항). 오류 카드는 "오류" 알약을 둔다.
        self.kind_label.setVisible(bool(card.error) or card.kind != "트리거")
        name = "badge_error" if card.error else "badge"          # 오류 카드의 종류 알약은 오류색이다(D-097)
        if self.kind_label.objectName() != name:
            self.kind_label.setObjectName(name)
            self.kind_label.style().unpolish(self.kind_label)
            self.kind_label.style().polish(self.kind_label)
        self.time_label.setText(hhmmss(card.t_wall) if card.t_wall else "")     # 요청 시각(AC-FR9-5)
        self.state_label.setText(STATE_LABELS.get(card.state, card.state))
        jl = judgment_line(card)
        if card.error and card.n > 0:        # 요청에 대한 오류만 요청 종류 줄을 남긴다. 요청이 없는 오류(n <= 0: 수집 · 전사 · 권한)에는 두지 않는다(W-43, 시각 설계 7-12)
            jl = _t("main.jl") % labels.kind_label(card.kind) + (" · " + jl if jl else "")
        self.judgment.setText(jl or "")
        self.judgment.setVisible(jl is not None)
        q = getattr(card, "question", None)
        self.card_question.setVisible(bool(q) and not card.error)
        if q and not card.error:
            self.card_question.setText(question_html(q))
        self.body.setText(card.text)
        self.body.setVisible(bool(card.text))
        pr = getattr(card, "partial", None)
        self.partial_line.setText(_t("newlang.new60").format(range="%s ~ %s" % (pr[0], pr[1])) if pr else "")
        self.partial_line.setVisible(bool(pr))
        names = tuple(getattr(card, "dropped", ()) or ())
        self.dropped.setText(_t("main.update_card_176") % (R.DROPPED_REASON, ", ".join(names)) if names else "")
        self.dropped.setVisible(bool(names))
        if card.error:
            self.error.setText(error_text.card_text(str(card.error[0]), card.error[1] or None, len(card.error) > 2 and card.error[2] == "guided"))   # AC-FR9-21: 사유 + 조치
        self.error.setVisible(bool(card.error))
        self._diagram_allowed = (can_diagram(card.kind, card.judgment) and card.state == R.STATE_DONE
                                 and bool(card.text) and not card.error)
        self._sync_diagram()

    def set_images(self, infos) -> None:
        """이미지 카드의 썸네일 · 크기 · 출처 줄. `infos`: (이미지 바이트, 출처 이름) 의 열."""
        while self.image_rows.count():
            it = self.image_rows.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self.image_labels = []
        for data, source in infos or ():
            row = QHBoxLayout()
            row.setSpacing(10)
            row.setContentsMargins(0, 0, 0, 0)
            thumb = QLabel("")
            thumb.setObjectName("card_thumb")
            pm = _thumbnail(data, CARD_THUMB_W, CARD_THUMB_H)
            if pm is not None:
                thumb.setPixmap(pm)
            thumb.setFixedSize(CARD_THUMB_W + 2, CARD_THUMB_H + 2)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info = QLabel(image_info_text(data, source))
            info.setObjectName("card_caption")      # caption 12px mute
            info.setTextFormat(Qt.TextFormat.PlainText)
            row.addWidget(thumb, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(info, 1, Qt.AlignmentFlag.AlignVCenter)
            holder = QWidget()
            holder.setObjectName("card_imgrow")
            holder.setLayout(row)
            self.image_rows.addWidget(holder)
            self.image_labels.append((thumb, info))
        self.layout().invalidate()
        self.updateGeometry()

    # ---- 다이어그램 ----
    def _sync_diagram(self) -> None:
        self.diagram_button.setVisible(self._diagram_allowed)
        ok, why = self._diagram_gate
        on = self._diagram_allowed and ok and not self._diagram_busy
        self.diagram_button.setEnabled(on)
        self._set_diagram_icon(on)
        self.diagram_button.setToolTip(DIAGRAM_BUTTON_NAME if (ok or self._diagram_busy) else why)
        self.diagram_retry.setEnabled(ok and not self._diagram_busy)

    def set_diagram_gate(self, enabled: bool, reason: str = "") -> None:
        self._diagram_gate = (bool(enabled), reason)
        self._sync_diagram()

    def diagram_progress(self) -> None:
        self._diagram_busy = True
        self.diagram_status.setText(DIAGRAM_BUSY_TEXT)
        self.diagram_status.setVisible(True)
        self.diagram_retry.setVisible(False)
        self._sync_diagram()

    def diagram_done(self, svg_path: str) -> bool:
        self._diagram_busy = False
        ok = self.diagram_view.load_file(str(svg_path))
        self.diagram_view.setVisible(ok)
        self.diagram_status.setText("" if ok else _t("main.diagram_done_177"))
        self.diagram_status.setVisible(not ok)
        self.diagram_retry.setVisible(not ok)
        self._sync_diagram()
        return ok

    def diagram_failed(self, reason: str) -> None:
        self._diagram_busy = False
        self.diagram_view.setVisible(False)
        self.diagram_status.setText(reason)
        self.diagram_status.setVisible(True)
        self.diagram_retry.setVisible(True)
        self._sync_diagram()

    def diagram_idle(self) -> None:
        """취소한 뒤: 진행 표시를 지우고 버튼을 다시 쓸 수 있게 한다."""
        self._diagram_busy = False
        self.diagram_status.setVisible(False)
        self.diagram_retry.setVisible(False)
        self._sync_diagram()

    @property
    def diagram_busy(self) -> bool:
        return self._diagram_busy


class AIView(QScrollArea):
    """AI 창. 카드의 생성 · 갱신 · 삭제와 자동 이동(맨 아래일 때만). 숨김 상태의 카드는 표시하지 않는다."""
    card_delete_requested = Signal(int)
    diagram_requested = Signal(int)
    diagram_open_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gate_provider = None       # (n) -> (활성 여부, 사유). 컨트롤러가 둔다
        self.setObjectName("ai_view")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # 카드 글은 줄바꿈한다(시안 3)
        inner = QWidget()
        inner.setObjectName("ai_inner")
        self._lay = QVBoxLayout(inner)
        self._lay.setContentsMargins(16, 16, 16, 16)    # 시안 3: AI 창 본문 여백 16 · 카드 간격 12
        self._lay.setSpacing(12)
        self._lay.addStretch(1)
        self.setWidget(inner)
        self._cards: dict = {}
        self._card_images: dict = {}
        self._gone: set = set()      # 지운 · 숨긴 카드의 번호. 이후의 갱신이 와도 다시 나타나지 않는다(AC-FR9-2 ⑤)
        # 결정 0144: 따라가기. 사용자가 위로 스크롤하면 멈추고 맨 아래로 돌아오면 다시 시작한다.
        # 카드의 글이 늘면 레이아웃이 나중에 갱신되므로 스크롤 범위가 바뀔 때(rangeChanged) 따라간다.
        self._stick = True
        self._programmatic = False
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(self._on_range)
        bar.valueChanged.connect(self._on_value)

    FOLLOW_SLACK = 24                  # 판정 여유(px): 보이는 끝이 맨 아래에서 이 안에 있으면 따라가는 중이다(결정 0144 ①, D-167)

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - self.FOLLOW_SLACK

    def _to_bottom(self) -> None:
        try:
            bar = self.verticalScrollBar()
        except RuntimeError:          # 지연 호출이 오기 전에 창이 지워졌다
            return
        self._programmatic = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._programmatic = False

    def _on_range(self, _lo: int, _hi: int) -> None:
        if self._stick:
            self._to_bottom()

    def _on_value(self, _v: int) -> None:
        if not self._programmatic:
            self._stick = self._at_bottom()

    def following(self) -> bool:
        return self._stick

    def jump_to_bottom(self) -> None:
        """사용자가 보낸 요청으로 생긴 카드는 맨 아래로 이동하고 따라가기를 다시 시작한다."""
        self._stick = True
        self._to_bottom()

    def set_card_images(self, n: int, infos) -> None:
        """카드 `n` 의 이미지 정보를 저장하고, 카드 위젯이 있으면 바로 반영한다(위젯이 나중에 생겨도 반영된다)."""
        self._card_images[n] = list(infos)
        w = self._cards.get(n)
        if w is not None:
            w.set_images(self._card_images[n])

    def apply_card(self, card: R.Card, change: str) -> None:
        w = self._cards.get(card.n)
        if change == "removed" or card.state == R.STATE_HIDDEN:
            self._gone.add(card.n)
            if w is not None:
                self._lay.removeWidget(w)
                w.deleteLater()
                del self._cards[card.n]
            return
        if card.n in self._gone:
            return
        if w is None:
            w = CardWidget(card)
            if card.n in self._card_images:
                w.set_images(self._card_images[card.n])
            w.delete_requested.connect(self.card_delete_requested.emit)
            w.diagram_requested.connect(self.diagram_requested.emit)
            w.diagram_open_requested.connect(self.diagram_open_requested.emit)
            self._lay.insertWidget(self._lay.count() - 1, w)
            self._cards[card.n] = w
        else:
            w.update_card(card)
        self._apply_gate(w)
        if change == "new":                            # 사용자가 보낸 요청의 카드: 맨 아래로 이동(결정 0144 ②)
            self.jump_to_bottom()
            QTimer.singleShot(0, self.jump_to_bottom)      # 새 카드의 크기가 정해진 뒤에도 맨 아래에 둔다
        elif self._stick:                              # "new_app"(앱이 만든 오류 카드 등)도 따라가는 중일 때만 맨 아래로 간다(결정 0144 ③, D-168)
            self._to_bottom()
            QTimer.singleShot(0, lambda: self._stick and self._to_bottom())

    def _apply_gate(self, w: "CardWidget") -> None:
        if self.gate_provider is not None:
            ok, why = self.gate_provider(w.n)
            w.set_diagram_gate(ok, why)

    def refresh_gates(self) -> None:
        for w in self._cards.values():
            self._apply_gate(w)

    def card_numbers(self) -> tuple:
        return tuple(self._cards)

    def card(self, n: int) -> Optional[CardWidget]:
        return self._cards.get(n)


_THUMB = 32
CARD_THUMB_W, CARD_THUMB_H = 144, 96         # 이미지 카드 썸네일의 최대 크기(시각 설계 7-6, 비율을 유지하고 이 안에 맞춘다)


def image_info_text(data, source: str) -> str:
    """이미지 카드의 캡션 `<가로>×<세로> px · <용량> · <출처>` (시각 설계 7-6, AC-FR7-27). 용량은 1 KB = 1024 바이트이고
    1 MB 미만이면 `NNN KB`(정수로 반올림, 1 KB 미만은 `1 KB`), 이상이면 `N.N MB`(소수 한 자리로 반올림)이다."""
    img = QImage()
    if isinstance(data, (bytes, bytearray)):
        img.loadFromData(bytes(data))
    size = len(data) if isinstance(data, (bytes, bytearray)) else 0
    parts = []
    if not img.isNull():
        parts.append("%d×%d px" % (img.width(), img.height()))
    if size:
        kb = (size + 512) // 1024                    # 정수 반올림(0.5 올림)
        if kb < 1024:
            parts.append("%d KB" % max(1, kb))
        else:                                         # KB 로 반올림한 값이 1024 이상이면 MB (master 판정, D-128)
            tenths = (size * 10 + 524288) // 1048576     # 소수 한 자리, 0.5 올림(짝수 반올림 아님)
            parts.append("%d.%d MB" % (tenths // 10, tenths % 10))
    parts.append(labels.source_label(source))
    return " · ".join(parts)


def _thumbnail(image, w: int = _THUMB, h: int = _THUMB):
    if image is None:
        return None
    pm = QPixmap()
    if isinstance(image, (bytes, bytearray)):
        pm.loadFromData(bytes(image))
    elif isinstance(image, QPixmap):
        pm = image
    elif isinstance(image, QImage):
        pm = QPixmap.fromImage(image)
    if pm.isNull():
        return None
    return pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class InputBar(QWidget):
    """입력창과 버튼. 입력은 Qt 의 입력기 처리에 맡기고(AC-FR7-2) 확정한 글만 신호로 내보낸다."""
    submitted = Signal(str)
    chip_removed = Signal(object)
    files_dropped = Signal(list)       # 끌어다 놓은 파일의 경로 목록(AC-FR7-15). 읽기 · 판정은 호출한 쪽이 한다
    image_pasted = Signal(bytes)       # 클립보드의 이미지(png 바이트)
    files_pasted = Signal(list)        # 클립보드의 파일 URL 의 경로 목록(AC-FR7-26 ⒜). 출처는 붙여넣기이다(D-133)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._chips: dict = {}
        self.chip_row = QHBoxLayout()
        self.chip_row.addStretch(1)
        self.edit = QLineEdit()
        self.setObjectName("input_area")
        self.edit.setFixedHeight(36)
        self.edit.setPlaceholderText(_t("main.init___180"))
        row = QHBoxLayout()           # 입력 칸뿐이다: [고찰] · 카메라 단추는 AI 창 머리 행에 있다(결정 0156 · 0157)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(8)
        row.addWidget(self.edit, 1)
        self.chip_row.setContentsMargins(14, 10, 14, 0)     # 시안 3: 칩 행은 칩이 있을 때만(위 여백 10)
        self.chip_row.setSpacing(10)
        self._chip_box = QWidget()
        self._chip_box.setObjectName("chip_box")
        self._chip_box.setLayout(self.chip_row)
        self._chip_box.setVisible(False)
        edit_box = QWidget()
        edit_box.setObjectName("edit_box")
        edit_box.setFixedHeight(58)
        edit_box.setLayout(row)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._chip_box)
        lay.addWidget(edit_box)
        self.edit.handle_paste = self.handle_paste       # 메뉴 막대의 붙여넣기도 같은 처리를 쓴다(D-076)
        self.edit.returnPressed.connect(self._submit)
        self.edit.installEventFilter(self)

    # 붙여넣기(AC-FR7-26): 파일 URL 을 먼저 본다. 파일 URL 이 있으면 그 파일만 첨부 판정으로 넘기고
    # (이미지 데이터 · 글은 무시, 이미지가 아닌 파일은 판정이 형식 사유로 거부한다), 입력창의 글은 바뀌지 않는다.
    # 파일 URL 이 없고 이미지 데이터가 있으면 글이 함께 있어도 이미지만 넘긴다. 글만 있으면 입력기에 맡긴다.
    def handle_paste(self) -> bool:
        """클립보드를 첨부로 처리한다. 처리했으면 True(입력란 기본 붙여넣기를 하지 않는다). ⌘V 와 메뉴 막대의 붙여넣기가 같이 쓴다."""
        md = QGuiApplication.clipboard().mimeData()
        if md is None:
            return False
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []
        if paths:
            self.files_pasted.emit(paths)
            return True
        if md.hasImage():
            img = QGuiApplication.clipboard().image()
            if not img.isNull():
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img.save(buf, "PNG")
                self.image_pasted.emit(bytes(ba))
                return True
        return False

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt)
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress and ev.matches(QKeySequence.StandardKey.Paste):
            if self.handle_paste():
                return True
        return super().eventFilter(obj, ev)

    def dragEnterEvent(self, ev) -> None:  # noqa: N802 (Qt)
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:  # noqa: N802 (Qt)
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths:
            ev.acceptProposedAction()
            self.files_dropped.emit(paths)

    def _submit(self) -> None:
        text = self.edit.text()
        if text.strip() or self._chips:       # D-125: 글 없이 이미지만 있어도 보낸다(FR-7 이미지 첨부 행)
            self.edit.clear()
            self.submitted.emit(text)

    # 첨부 이미지 칩(AC-FR7-16). 첨부 판정 · 축소는 K-14 이며 여기서는 표시와 제거만 한다.
    def add_chip(self, key, label: str, image=None) -> None:
        """image 는 축소를 마친 이미지 바이트 또는 QPixmap/QImage. 주어지면 칩에 썸네일 아이콘으로 표시한다 (AC-FR7-16)."""
        if key in self._chips:
            return
        b = QPushButton("%s  x" % label)
        pm = _thumbnail(image)
        if pm is not None:
            b.setIcon(QIcon(pm))
            b.setIconSize(QSize(_THUMB, _THUMB))
        b.setAccessibleName(_t("main.add_chip_181") % label)
        b.clicked.connect(lambda: self.remove_chip(key, notify=True))
        self._chips[key] = b
        self.chip_row.insertWidget(self.chip_row.count() - 1, b)
        self._chip_box.setVisible(True)

    def remove_chip(self, key, notify: bool = False) -> None:
        b = self._chips.pop(key, None)
        if b is None:
            return
        self.chip_row.removeWidget(b)
        b.deleteLater()
        self._chip_box.setVisible(bool(self._chips))
        if notify:
            self.chip_removed.emit(key)

    def clear_chips(self) -> None:
        """요청을 보낸 뒤 칩을 모두 지운다(뺀 첨부의 칩도 사라진다, AC-FR7-23). `chip_removed` 는 내지 않는다."""
        for key in list(self._chips):
            self.remove_chip(key)

    def chips(self) -> tuple:
        return tuple(self._chips)


MIN_TRANSCRIPT_WIDTH = 360     # design 의 layout-values 회신(D-086): 전사 창 · AI 창의 최소 너비
MIN_AI_WIDTH = 400
SPLIT_RATIO = (10, 11)         # 시안 3: 전사 flex 1 : AI flex 1.1


class _ElideLabel(QLabel):
    """창 머리의 보조 글. 폭이 모자라면 끝을 줄임표로 줄이고(영어 문구는 한국어보다 길다, AC-FR16-15) 전체 글은 풍선 도움말로 보인다."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setText(text)                   # D-159: 생성자에 글을 넘기면 다시 정의한 setText 가 호출되지 않는다

    def sizeHint(self):  # noqa: N802 (Qt)
        return QLabel.sizeHint(self)

    def minimumSizeHint(self):  # noqa: N802 (Qt)
        h = QLabel.minimumSizeHint(self)
        h.setWidth(0)
        return h

    def setText(self, text: str) -> None:  # noqa: N802 (Qt)
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, e) -> None:  # noqa: N802 (Qt)
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        p.drawText(self.rect(), int(self.alignment()), self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width()))


def _transport_icon(kind: str, color: str) -> QIcon:
    """채운 14 × 14 아이콘(▶ · ❚❚ · ■)을 그린다."""
    from PySide6.QtGui import QColor, QPainter, QPolygonF
    from PySide6.QtCore import QPointF, QRectF
    scale = 2
    pm = QPixmap(14 * scale, 14 * scale)
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.GlobalColor.transparent)
    pt = QPainter(pm)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    pt.setPen(Qt.PenStyle.NoPen)
    pt.setBrush(QColor(color))
    if kind == "play":
        pt.drawPolygon(QPolygonF([QPointF(3, 1.5), QPointF(12, 7), QPointF(3, 12.5)]))
    elif kind == "pause":
        pt.drawRoundedRect(QRectF(2.5, 2, 3.2, 10), 0.8, 0.8)
        pt.drawRoundedRect(QRectF(8.3, 2, 3.2, 10), 0.8, 0.8)
    else:
        pt.drawRoundedRect(QRectF(2.5, 2.5, 9, 9), 1.5, 1.5)
    pt.end()
    return QIcon(pm)


class Transport(QWidget):
    """전사 창 머리줄의 조작 단추 셋(결정 0147, 시안 3-1): [재생] ▶ · [일시 정지] ❚❚ · [정지] ■, 각 28 × 28."""
    play_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transport")
        self.setAccessibleName(_t("pause.new22"))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.btn_play = self._make("btn_play", "play", "pause.new19", self.play_clicked)
        self.btn_pause = self._make("btn_pause", "pause", "pause.new20", self.pause_clicked)
        self.btn_stop = self._make("btn_stop", "stop", "pause.new21", self.stop_clicked)
        for b in (self.btn_play, self.btn_pause, self.btn_stop):
            lay.addWidget(b)
        self._ending = False
        self._play_blocked = False
        self._last_state = None
        self.set_state(None)

    def play_blocked(self) -> bool:
        return self._play_blocked

    def set_play_blocked(self, blocked: bool) -> None:
        """모델을 준비하는 동안과 준비 실패 · 보조 프로세스 종료 중에는 [재생] 을 끈다(결정 0167)."""
        self._play_blocked = bool(blocked)
        self.set_state(self._last_state)

    def _make(self, name: str, kind: str, key: str, sig) -> QPushButton:
        b = QPushButton()
        b.setObjectName(name)
        b.setProperty("kind", kind)
        b.setFixedSize(28, 28)
        b.setIconSize(QSize(14, 14))
        b.setToolTip(_t(key))
        b.setAccessibleName(_t(key))
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)       # 전체 키보드 접근을 켠 상태에서 Tab 으로 초점을 옮긴다
        b.clicked.connect(lambda _c=False: sig.emit())
        b.setStyleSheet("")                             # 모양은 앱 스타일시트(QPushButton#transport_btn)가 맡는다
        b.setProperty("transport", True)
        return b

    def set_state(self, capture_state: Optional[str], ending: Optional[bool] = None) -> None:
        if ending is not None:
            self._ending = bool(ending)
        self._last_state = capture_state
        play, pause, stop, emph = appstate.transport_enabled(capture_state, self._ending)
        if self._play_blocked:
            play = False
        from PySide6.QtWidgets import QApplication
        from . import theme
        app = QApplication.instance()
        tk = theme.tokens(str(app.property("rab_scheme") or "light") if app is not None else "light")
        for b, on in ((self.btn_play, play), (self.btn_pause, pause), (self.btn_stop, stop)):
            e = bool(emph and b is self.btn_play)
            b.setEnabled(on)
            b.setProperty("emphasized", e)
            color = tk["on-primary"] if e and on else (tk["ink"] if on else tk["mute"])
            b.setIcon(_transport_icon(b.property("kind"), color))
            b.style().unpolish(b)
            b.style().polish(b)


def line_icon(kind: str, color: str, size: int = 16, width: float = 1.4) -> QIcon:
    """그린 선 아이콘(시각 설계 7-1): `brain` = 고찰(좌우 두 엽과 가운데 선), `camera` = 액자 캡처, `diagram` = 둥근 사각 노드 둘과 이를 잇는 선. 크기 16, 선 굵기 1.4."""
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtCore import QPointF, QRectF
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.GlobalColor.transparent)
    pt = QPainter(pm)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pt.setPen(pen)
    pt.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "brain":
        from PySide6.QtGui import QPainterPath
        left = QPainterPath()                     # 왼쪽 엽: 가운데 선에서 시작해 바깥으로 두 번 부푼다
        left.moveTo(8.0, 2.6)
        left.cubicTo(6.8, 1.4, 4.4, 1.8, 4.0, 3.8)
        left.cubicTo(2.2, 4.0, 1.6, 6.2, 2.6, 7.4)
        left.cubicTo(1.4, 8.6, 1.8, 10.8, 3.4, 11.2)
        left.cubicTo(3.6, 13.0, 6.0, 14.0, 8.0, 12.8)
        pt.drawPath(left)
        right = QPainterPath()                    # 오른쪽 엽: 왼쪽 엽의 좌우 대칭
        right.moveTo(8.0, 2.6)
        right.cubicTo(9.2, 1.4, 11.6, 1.8, 12.0, 3.8)
        right.cubicTo(13.8, 4.0, 14.4, 6.2, 13.4, 7.4)
        right.cubicTo(14.6, 8.6, 14.2, 10.8, 12.6, 11.2)
        right.cubicTo(12.4, 13.0, 10.0, 14.0, 8.0, 12.8)
        pt.drawPath(right)
        pt.drawLine(QPointF(8.0, 2.6), QPointF(8.0, 12.8))           # 가운데 선
    elif kind == "camera":
        from PySide6.QtGui import QPainterPath
        body = QPainterPath()
        body.addRoundedRect(QRectF(1.7, 4.6, 12.6, 9.0), 2.0, 2.0)
        pt.drawPath(body)
        top = QPainterPath()                      # 윗면의 돌출부
        top.moveTo(5.3, 4.6)
        top.lineTo(6.4, 2.6)
        top.lineTo(9.6, 2.6)
        top.lineTo(10.7, 4.6)
        pt.drawPath(top)
        pt.drawEllipse(QRectF(5.6, 6.6, 4.8, 4.8))   # 렌즈
    else:
        pt.drawRoundedRect(QRectF(1.5, 2.0, 5.0, 4.5), 1.2, 1.2)      # 위 노드
        pt.drawRoundedRect(QRectF(9.5, 9.5, 5.0, 4.5), 1.2, 1.2)      # 아래 노드
        pt.drawLine(QPointF(4.0, 6.5), QPointF(4.0, 11.7))            # 잇는 선: 위 노드 아래 → 꺾어서 아래 노드 왼쪽
        pt.drawLine(QPointF(4.0, 11.7), QPointF(9.5, 11.7))
    pt.end()
    return QIcon(pm)


class _HeaderBar(QFrame):
    """AI 창 머리 행. 폭이 모자라면 카메라 → [고찰] 단추의 키 표기 순으로 감춘다(`fit`)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_resize = None

    def resizeEvent(self, ev) -> None:  # noqa: N802 (Qt)
        super().resizeEvent(ev)
        if self.on_resize is not None:
            self.on_resize()


def _pane_header(title: str, note: str, cls=QFrame):
    """창 머리 행(시안 3): 높이 40, 좌우 여백 14, 아래 hairline. 제목은 굵게, 오른쪽에 보조 글."""
    head = cls()
    head.setObjectName("pane_header")
    head.setFixedHeight(40)
    lay = QHBoxLayout(head)
    lay.setContentsMargins(14, 0, 14, 0)
    lay.setSpacing(12)
    t = QLabel(title)
    t.setObjectName("pane_title")
    n = _ElideLabel(note)
    n.setObjectName("pane_note")
    lay.addWidget(t)
    lay.addStretch(1)
    lay.addWidget(n)
    return head, t, n, lay



class _ClockLabel(QLabel):
    """세션 시계 라벨: 숫자를 고정폭(OpenType `tnum`)으로 그리고, 폭을 가장 넓은 숫자의 글 폭으로 고정해 값이 바뀌어도 머리 행의 단추가
    움직이지 않게 한다(D-174, AC-FR7-34 ⑤). 글꼴이 `tnum` 을 지원하지 않아도 폭은 같다."""

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self._w = 0
        self._set_tabular()

    def _set_tabular(self) -> None:
        f = self.font()
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
            self.setFont(f)
        except Exception:  # noqa: BLE001  (Qt 6.7 미만에는 없다)
            pass

    def _fixed_width(self) -> int:
        self.ensurePolished()
        fm = self.fontMetrics()
        fmt = _t("main.tick_clock_185")
        w = max(fm.horizontalAdvance(fmt.replace("%02d", str(d) * 2)) for d in range(10))
        return w + self.contentsMargins().left() + self.contentsMargins().right() + 2

    def sizeHint(self) -> QSize:
        if not self._w:
            self._w = self._fixed_width()
        return QSize(self._w, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def changeEvent(self, e) -> None:
        # 글꼴 · 스타일이 바뀌면(테마 전환 · 앱 언어 전환) 캐시한 폭이 낡으므로 다시 잰다(권고 47)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and self._w:
            self._w = 0
            self.updateGeometry()
        super().changeEvent(e)


class SessionView(QWidget):
    """메인 창의 세션 화면: 왼쪽 STT 창, 오른쪽 AI 창, 아래 입력창(2-1절). 배치는 시안 3 (D-086)."""

    reflect_clicked = Signal()          # AI 창 머리 행의 [고찰] 단추(결정 0157)
    capture_clicked = Signal()          # 카메라 단추 = 액자 캡처
    guide_retry_clicked = Signal()      # 수집 전 안내 상자(준비 실패)의 [다시 시도]

    def __init__(self, trigger_key: str = "F2", parent=None):
        super().__init__(parent)
        self.transcript = TranscriptView()
        self.ai = AIView()
        self.input = InputBar()
        self._trigger_key, self._global_trigger, self._global_capture = trigger_key, "", ""
        self._reflect_enabled = self._capture_enabled = True
        self.bridge = UiBridge(self)
        self.banner = StatusBanner()
        self.key_banner = StatusBanner()        # 전역 키 등록 실패(결정 0141, KEY-7 · KEY-8): AI 창 위의 띠
        # 왼쪽: 머리 행 · 띠 · 전사 (바탕 surface)
        left = QWidget()
        left.setObjectName("pane_left")
        left.setMinimumWidth(MIN_TRANSCRIPT_WIDTH)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        head_l, _title_unused, self.transcript_note, head_lay = _pane_header(_t("main.init___183"), "")
        self.chip_paused = QLabel(_t("pause.new23"))          # 일시 정지 중에만 보이는 경고색 칩(결정 0147)
        self.chip_paused.setObjectName("chip_paused")
        self.chip_before = QLabel(_t("before.new33"))         # 수집 전에만 보이는 정보색 칩(결정 0150)
        self.chip_before.setObjectName("chip_before")
        for i, chip in enumerate((self.chip_paused, self.chip_before)):
            chip.setVisible(False)
            head_lay.insertWidget(1 + i, chip)
            head_lay.setAlignment(chip, Qt.AlignmentFlag.AlignVCenter)
        head_lay.setSpacing(8)
        self.transport = Transport()
        head_lay.addSpacing(4)
        head_lay.addWidget(self.transport)
        left_lay.addWidget(head_l)
        left_lay.addWidget(self.banner)
        self.transcript_guide = self._make_transcript_guide()   # 수집 전의 빈 안내 상자(결정 0150, 시안 3-7)
        self.transcript_guide.setVisible(False)
        left_lay.addWidget(self.transcript_guide)
        left_lay.addWidget(self.transcript, 1)
        # 오른쪽: 머리 행(보조 글 · 세션 시계) · 카드 (바탕 canvas)
        right = QWidget()
        right.setObjectName("pane_right")
        right.setMinimumWidth(MIN_AI_WIDTH)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        head_r, self.ai_title, self.ai_note, hl = _pane_header(_t("main.init___184"), "", _HeaderBar)    # 보조 글이 없는 머리 행(결정 0157)
        self.ai_note.setVisible(False)
        hl.removeWidget(self.ai_note)
        self.btn_reflect = QPushButton()
        self.btn_reflect.setObjectName("btn_reflect")
        self.btn_reflect.setProperty("keybtn", True)
        self.btn_reflect.setFixedHeight(28)
        self.btn_reflect.setIconSize(QSize(16, 16))
        self.btn_reflect.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_capture = QPushButton()
        self.btn_capture.setObjectName("btn_capture")
        self.btn_capture.setProperty("transport", True)
        self.btn_capture.setFixedSize(28, 28)
        self.btn_capture.setIconSize(QSize(16, 16))
        self.btn_capture.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_reflect.clicked.connect(lambda _c=False: self.reflect_clicked.emit())
        self.btn_capture.clicked.connect(lambda _c=False: self.capture_clicked.emit())
        self.clock = _ClockLabel()
        self.clock.setObjectName("pane_note")
        self.clock.setVisible(False)
        hl.addWidget(self.btn_reflect)
        hl.addSpacing(-4)                       # 간격 12 → 단추 사이 8
        hl.addWidget(self.btn_capture)
        hl.addSpacing(2)                        # 단추 묶음과 시계 사이 14
        hl.addWidget(self.clock)
        self.ai_head = head_r
        head_r.on_resize = self._fit_request_buttons
        self._apply_request_texts()
        right_lay.addWidget(head_r)
        right_lay.addWidget(self.key_banner)
        self.ai_guide = QLabel(_t("before.new36"))             # 첫 카드가 생기면 사라지는 안내 한 줄(결정 0150)
        self.ai_guide.setObjectName("ai_guide")
        self.ai_guide.setWordWrap(True)
        self.ai_guide.setContentsMargins(14, 10, 14, 0)
        right_lay.addWidget(self.ai_guide)
        self._ai_guide_done = False
        right_lay.addWidget(self.ai, 1)
        import time as _time
        self._clock_acc = 0.0                 # 멈춘 동안 쌓인 초
        self._clock_since = None              # 세고 있는 구간의 시작(원천의 값), 멈춘 동안 None
        self._clock_src = _time.monotonic
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(200)
        self._clock_timer.timeout.connect(self._tick_clock)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("main_split")
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, SPLIT_RATIO[0])
        split.setStretchFactor(1, SPLIT_RATIO[1])
        split.setSizes([SPLIT_RATIO[0] * 100, SPLIT_RATIO[1] * 100])
        self.split = split
        for i in range(1, split.count()):
            split.handle(i).setEnabled(False)      # 분할선을 끌어 옮기는 기능은 없다(design 회신)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(split, 1)
        lay.addWidget(self.input)
        self.bridge.card.connect(self.ai.apply_card)
        self.bridge.card.connect(self._hide_ai_guide)
        self.bridge.segment.connect(self.transcript.add_segment)

    def _make_transcript_guide(self) -> QFrame:
        box = QFrame()
        box.setObjectName("transcript_guide")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        title = QLabel(_t("before.new34"))
        title.setObjectName("transcript_guide_title")
        body = QLabel(_t("before.new35"))
        body.setObjectName("transcript_guide_body")
        body.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(body)
        retry = QPushButton(_t("card.cancelled_view_377"))      # 준비 실패의 [다시 시도] (시안 3-11, 높이 32)
        retry.setObjectName("transcript_guide_retry")
        retry.setFixedHeight(32)
        retry.setVisible(False)
        retry.clicked.connect(lambda _c=False: self.guide_retry_clicked.emit())
        lay.addWidget(retry, 0, Qt.AlignmentFlag.AlignLeft)
        self.transcript_guide_retry = retry
        perm = QLabel("")                      # 권한 안내 줄(결정 0161, NEW-45 · NEW-46). 오류 카드 · 띠가 아니다
        perm.setObjectName("transcript_guide_permission")
        perm.setWordWrap(True)
        perm.setTextFormat(Qt.TextFormat.PlainText)
        perm.setVisible(False)
        lay.addSpacing(-2)                     # 내부 간격 6 + 위 간격 4 = 10 이 되도록 한다(VD 197)
        lay.addWidget(perm)
        self.transcript_guide_title, self.transcript_guide_body, self.transcript_guide_permission = title, body, perm
        return box

    def set_stt_guide(self, mode: str, title: str = "", body: str = "", retry: bool = False, retry_enabled: bool = True) -> None:
        """수집 전 안내 상자의 상태. `normal`(NEW-34 · 35), `preparing`(본문 NEW-49), `error`(사유 `title` · 조치 `body` · [다시 시도])."""
        if mode == "error":
            self.transcript_guide_title.setText(title)
            self.transcript_guide_body.setText(body)
        else:
            self.transcript_guide_title.setText(_t("before.new34"))
            self.transcript_guide_body.setText(_t("newlang.new49") if mode == "preparing" else _t("before.new35"))
        self.transcript_guide.setProperty("state", "error" if mode == "error" else "")
        self.transcript_guide.style().unpolish(self.transcript_guide)
        self.transcript_guide.style().polish(self.transcript_guide)
        self.transcript_guide_retry.setVisible(bool(retry) and mode == "error")
        self.transcript_guide_retry.setEnabled(bool(retry_enabled))
        self._stt_guide_mode = mode

    def stt_guide_state(self) -> tuple:
        """(모드, 제목, 본문, [다시 시도] 보임, [다시 시도] 켜짐). 시험의 판정 값이다."""
        return (getattr(self, "_stt_guide_mode", "normal"), self.transcript_guide_title.text(), self.transcript_guide_body.text(),
                not self.transcript_guide_retry.isHidden(), self.transcript_guide_retry.isEnabled())

    def set_play_blocked(self, blocked: bool) -> None:
        self.transport.set_play_blocked(blocked)

    def set_permission_guide(self, text: str) -> None:
        """수집 전 안내 상자의 본문 아래 안내 줄. 빈 글이면 감춘다. 상자가 사라지면(처음 [재생]) 줄도 함께 사라진다."""
        self.transcript_guide_permission.setText(text or "")
        self.transcript_guide_permission.setVisible(bool(text))

    def _hide_ai_guide(self, *_a) -> None:
        self._ai_guide_done = True
        self.ai_guide.setVisible(False)

    # ---- [고찰] · 카메라 단추(결정 0156 · 0157) ----
    def set_request_keys(self, trigger_key: Optional[str] = None, global_trigger: Optional[str] = None,
                         global_capture: Optional[str] = None) -> None:
        """단추의 글 · 도움말에 보이는 키(표시용 글). 주지 않은 값은 그대로 둔다."""
        if trigger_key is not None:
            self._trigger_key = trigger_key
        if global_trigger is not None:
            self._global_trigger = global_trigger
        if global_capture is not None:
            self._global_capture = global_capture
        self._apply_request_texts()

    def _apply_request_texts(self) -> None:
        """[고찰] · 카메라 단추: 그림 + 키 표기(키가 비면 그림만). 도움말은 기능 이름만이다(결정 0176 2항)."""
        name = _t("newlang.new42")
        cam = _t("newlang.new44")
        self.btn_reflect.setToolTip(name)
        self.btn_reflect.setAccessibleName(name)
        self.btn_capture.setToolTip(cam)
        self.btn_capture.setAccessibleName(cam)
        self._fit_request_buttons()
        self._refresh_header_icons()

    def _fit_request_buttons(self) -> None:
        """폭이 모자라면 카메라 단추의 키 표기를 먼저 감추고, 그래도 모자라면 [고찰] 단추의 키 표기를 감춘다(결정 0176, FS 373)."""
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont(self.btn_reflect.font())
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.Medium)
        fm = QFontMetrics(f)

        def width(key: str) -> int:
            return 28 if not key else 2 + 20 + 16 + 6 + fm.horizontalAdvance(key)
        head = getattr(self, "ai_head", None)
        avail = head.width() if head is not None and head.width() > 0 else 390
        clock_w = max(self.clock.sizeHint().width(), 64) if hasattr(self, "clock") else 64
        title_w = QFontMetrics(self.ai_title.font()).horizontalAdvance(self.ai_title.text()) + 8 if hasattr(self, "ai_title") else 60
        base = 28 + title_w + 8 + 14 + clock_w + 12 * 2 + 12 + 8                # 여백 · 제목 · 간격 · 시계 · 두 단추 사이
        rk, ck = self._global_trigger or self._trigger_key or "", self._global_capture or ""
        if avail < base + width(rk) + width(ck):
            ck = ""
        if avail < base + width(rk) + width(ck):
            rk = ""
        for btn, key in ((self.btn_reflect, rk), (self.btn_capture, ck)):
            if btn.text() != key:
                btn.setText(key)
            btn.setProperty("keybtn", bool(key))
            btn.setProperty("transport", not key)
            btn.setFixedWidth(width(key))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _refresh_header_icons(self) -> None:
        from PySide6.QtWidgets import QApplication
        from . import theme
        app = QApplication.instance()
        tk = theme.tokens(str(app.property("rab_scheme") or "light") if app is not None else "light")
        self.btn_capture.setIcon(line_icon("camera", tk["ink"] if self._capture_enabled else tk["ash"]))
        self.btn_reflect.setIcon(line_icon("brain", tk["ink"] if self._reflect_enabled else tk["ash"]))

    def set_request_buttons_enabled(self, enabled: bool) -> None:
        """세션 중(수집 전 포함)에만 활성이고 종료 처리 중에는 비활성이다(FR-14 의 표). 응답 중에도 활성이다."""
        self._reflect_enabled = self._capture_enabled = bool(enabled)
        for b in (self.btn_reflect, self.btn_capture):
            b.setEnabled(bool(enabled))
        self._refresh_header_icons()

    def set_capture_state(self, state: Optional[str], ending: bool = False) -> None:
        """수집 상태에 맞춰 머리줄의 칩 · 조작 단추 · 안내 상자를 정한다(FR-11)."""
        self.chip_paused.setVisible(state == appstate.COLLECT_PAUSED)
        self.chip_before.setVisible(state == appstate.COLLECT_BEFORE)
        self.transcript_guide.setVisible(state == appstate.COLLECT_BEFORE)
        self.ai_guide.setVisible(not self._ai_guide_done)
        self.transport.set_state(state, ending)
        self.set_request_buttons_enabled(not ending)

    # 세션 시계(시안 3 의 "세션 01:12:30")
    def start_clock(self) -> None:
        """시계를 보이고 00:00:00 에서 멈춘 채 둔다. 세기 시작은 `set_clock_running(True)`(수집 중)이다."""
        self._clock_acc, self._clock_since = 0.0, None
        self.clock.setVisible(True)
        self._tick_clock()
        self._clock_timer.start()

    def stop_clock(self) -> None:
        self._clock_timer.stop()

    def set_clock_source(self, src) -> None:
        """시각 원천(인자 없는 호출, 단조 시계 초). 화면 시계에만 쓴다(시험의 세션 시계 주입)."""
        now = self._clock_src()
        if self._clock_since is not None:                  # 세는 중에 바꾸면 지금까지의 값을 보존한다
            self._clock_acc += max(0.0, now - self._clock_since)
            self._clock_src = src
            self._clock_since = src()
        else:
            self._clock_src = src
        self._tick_clock()

    def set_clock_running(self, running: bool) -> None:
        if running and self._clock_since is None:
            self._clock_since = self._clock_src()
        elif not running and self._clock_since is not None:
            self._clock_acc += max(0.0, self._clock_src() - self._clock_since)
            self._clock_since = None
        self._tick_clock()

    def clock_seconds(self) -> float:
        extra = max(0.0, self._clock_src() - self._clock_since) if self._clock_since is not None else 0.0
        return self._clock_acc + extra

    def _tick_clock(self) -> None:
        sec = int(self.clock_seconds())
        text = _t("main.tick_clock_185") % (sec // 3600, sec % 3600 // 60, sec % 60)
        if text != self.clock.text():
            self.clock.setText(text)

    def set_source_note(self, text: str) -> None:
        self.transcript_note.setText(text)
