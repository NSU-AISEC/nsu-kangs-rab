"""설정 창의 키 설정 표 (결정 0141 · 0142, 시안 "6 설정" · "6-5 키 지정 중" · "6-6 키 겹침 경고").

세 행(트리거 키(앱 창 안) · 트리거 키(전역) · 액자 캡처 키(전역))에 키캡 · [변경…] · [비우기] 를 둔다. [변경…] 을 누르면 그 행이
지정 중이 되어 다음에 누른 키를 받는다. 받지 않는 키의 판별은 `keyspec.classify` 와 호출한 쪽이 주는 조회 함수가 한다.
규칙의 원본은 `docs/plan/functional-spec.md` FR-7 의 "키 설정 표" 이다.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.i18n import t as _t
from . import keyspec

# (행 번호, 이름 문구 키, 설정 키, 기본값)
ROWS = (
    ("trigger", "setform.name", "trigger_key", "F2"),
    ("global_trigger", "keyset.new11", "global_trigger_key", ""),
    ("global_capture", "keyset.new12", "global_capture_key", ""),
)
GLOBAL_ROWS = ("global_trigger", "global_capture")
SETTING_KEY = {r[0]: r[2] for r in ROWS}
DEFAULT = {r[0]: r[3] for r in ROWS}


class _Row(QFrame):
    def __init__(self, row_id: str, name_key: str, parent=None):
        super().__init__(parent)
        self.row_id = row_id
        self.setObjectName("key_row")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QFrame()
        top.setObjectName("key_row")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(12)
        self.name = QLabel(_t(name_key))
        self.cap = QLabel("")
        self.cap.setObjectName("set_keycap")
        self.cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cap.setFixedHeight(32)
        self.cap.setMinimumWidth(76)
        self.change = QPushButton(_t("start.init___044"))
        self.clear = QPushButton(_t("keyset.new15"))
        for b in (self.change, self.clear):
            b.setObjectName("set_keybtn")
            b.setFixedHeight(32)
        tl.addWidget(self.name, 1)
        tl.addWidget(self.cap, 0, Qt.AlignmentFlag.AlignVCenter)
        tl.addWidget(self.change, 0, Qt.AlignmentFlag.AlignVCenter)
        tl.addWidget(self.clear, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(top)
        self.hint = QLabel("")
        self.hint.setObjectName("key_hint")
        self.hint.setWordWrap(True)
        self.hint.setContentsMargins(14, 0, 14, 4)
        self.hint.setVisible(False)
        outer.addWidget(self.hint)


class KeyTable(QFrame):
    """키 설정 표. 값은 설정의 키 글(PortableText)이며 빈 글은 "지정 안 함" 이다."""
    key_changed = Signal(str, str)         # (행 번호, 키 글) — 사용자가 바꿨을 때만
    capturing_changed = Signal(bool)       # 지정 중이 시작 · 끝났다 (전역 키의 일시 해제에 쓴다)

    def __init__(self, values: Dict[str, str], other_menu_items: Callable[[], Dict[str, str]],
                 system_conflict: Callable[[str], Optional[str]], parent=None):
        """`other_menu_items()`: {키 글: 메뉴 항목 이름} (이 표의 두 트리거 항목은 뺀다).
        `system_conflict(키 글)`: 켜진 macOS 시스템 단축키와 겹치면 KEY-3 의 이름, 아니면 None."""
        super().__init__(parent)
        self.setObjectName("doc_panel")
        self._menu_items = other_menu_items
        self._system = system_conflict
        self._values: Dict[str, str] = {r[0]: (values.get(r[2]) if values.get(r[2]) is not None else r[3]) for r in ROWS}
        self._rows: Dict[str, _Row] = {}
        self._capturing: Optional[str] = None
        self._registered: set = set()          # 세션 중 등록에 성공한 전역 행
        self._failed: set = set()
        self._reset_notice: Dict[str, str] = {}
        self._warn: Optional[str] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for rid, name_key, _s, _d in ROWS:
            row = _Row(rid, name_key)
            row.change.clicked.connect(lambda _c=False, r=rid: self.begin_capture(r))
            row.clear.clicked.connect(lambda _c=False, r=rid: self.clear_row(r))
            lay.addWidget(row)
            self._rows[rid] = row
        self.refresh()

    # ----- 값 -----
    def value(self, row_id: str) -> str:
        return self._values[row_id]

    def set_values(self, values: Dict[str, str]) -> None:
        for rid, _n, skey, dflt in ROWS:
            if skey in values:
                self._values[rid] = values[skey] if values[skey] is not None else dflt
        self.refresh()

    def set_session_registration(self, registered: set, failed: set) -> None:
        """세션 중 등록된 전역 행과 등록에 실패한 전역 행(안내 줄의 "등록됨 · " 에 쓴다)."""
        self._registered, self._failed = set(registered), set(failed)
        self.refresh()

    def set_reset_notice(self, row_id: str, saved_key: str) -> None:
        """저장되어 있던 글자 키를 기본값으로 되돌렸다는 안내(KEY-9)를 이 행 아래에 보인다. 빈 글이면 거둔다."""
        if saved_key:
            self._reset_notice[row_id] = saved_key
        else:
            self._reset_notice.pop(row_id, None)
        self.refresh()

    def reset_notice_rows(self) -> List[str]:
        return list(self._reset_notice)

    def dismiss_reset_notices(self) -> None:
        """"처음 열 때 한 번" 보인 뒤 거둔다(호출한 쪽이 보인 사실을 설정에 기록한다)."""
        self._reset_notice.clear()
        self.refresh()

    # ----- 그리기 -----
    def refresh(self) -> None:
        for rid, row in self._rows.items():
            val = self._values[rid]
            cap_state = "capturing" if self._capturing == rid else ("empty" if not val else "set")
            row.cap.setText(_t("keyset.new14") if self._capturing == rid else (keyspec.display(val) if val else _t("keyset.new13")))
            row.cap.setProperty("state", cap_state)
            muted_other = self._capturing is not None and self._capturing != rid
            for b in (row.change, row.clear):
                b.setEnabled(not muted_other)
                b.setProperty("muted", "true" if muted_other or (b is row.clear and not val) else "false")
            hint, warn = self._hint_for(rid, val)
            row.hint.setObjectName("key_warn" if warn else "key_hint")
            row.hint.setText(hint)
            row.hint.setVisible(bool(hint))
            row.hint.setContentsMargins(*((14, 0, 14, 0) if warn else (14, 0, 14, 4)))
            for w in (row.cap, row.change, row.clear, row.hint):
                w.style().unpolish(w)
                w.style().polish(w)

    def _hint_for(self, rid: str, val: str):
        if self._capturing == rid:
            if self._warn:
                return self._warn, True
            return _t("keyset.new16"), False
        if rid in self._reset_notice:
            return _t("keyset.key9").format(key=keyspec.display(self._reset_notice[rid]) or self._reset_notice[rid]), False
        if rid in GLOBAL_ROWS and val:
            prefix = _t("keyset.key6") if rid in self._registered else ""
            return prefix + _t("keyset.key5"), False
        return "", False

    # ----- 지정 -----
    def capturing(self) -> Optional[str]:
        return self._capturing

    def begin_capture(self, row_id: str) -> bool:
        if self._capturing is not None:
            return False
        self._capturing = row_id
        self._warn = None
        QApplication.instance().installEventFilter(self)
        self.refresh()
        self.capturing_changed.emit(True)
        return True

    def end_capture(self) -> None:
        """지정을 끝낸다(키를 받았을 때 · Esc · 설정 창 닫기가 모두 이 경로이다)."""
        if self._capturing is None:
            return
        self._capturing = None
        self._warn = None
        QApplication.instance().removeEventFilter(self)
        self.refresh()
        self.capturing_changed.emit(False)

    def clear_row(self, row_id: str) -> None:
        if self._capturing is not None or not self._values[row_id]:
            return
        self._values[row_id] = ""
        self._reset_notice.pop(row_id, None)
        self.refresh()
        self.key_changed.emit(row_id, "")

    def receive(self, key: int, mods, keypad: bool = False) -> str:
        """지정 중에 키 하나를 처리한다. 반환: "cancel" | "ignore" | "accepted" | "rejected"."""
        verdict = keyspec.classify(key, mods, keypad)
        if verdict == keyspec.CANCEL:
            self.end_capture()
            return "cancel"
        if verdict == keyspec.IGNORE:
            return "ignore"
        if verdict == keyspec.TYPING:
            self._reject(_t("keyset.key4").format(key=keyspec.display(keyspec.to_text(key, mods))))
            return "rejected"
        text = keyspec.to_text(key, mods)
        shown = keyspec.display(text)
        for rid, row in self._rows.items():                       # (가) 다른 행에 지정된 키
            if rid != self._capturing and self._values[rid] == text:
                self._reject(_t("keyset.key1").format(key=shown, row=row.name.text()))
                return "rejected"
        item = self._menu_items().get(text)                       # (나) 이 앱의 메뉴 단축키
        if item:
            self._reject(_t("keyset.key2").format(key=shown, item=item))
            return "rejected"
        name = self._system(text)                                 # (다) 켜진 macOS 시스템 단축키
        if name:
            self._reject(_t("keyset.key3").format(key=shown, name=name))
            return "rejected"
        rid = self._capturing
        self._values[rid] = text
        self._reset_notice.pop(rid, None)
        self.end_capture()
        self.key_changed.emit(rid, text)
        return "accepted"

    def _reject(self, message: str) -> None:
        self._warn = message
        self.refresh()

    def eventFilter(self, obj, ev):                               # noqa: N802 (Qt)
        if self._capturing is None:
            return False
        t = ev.type()
        if t == QEvent.Type.ShortcutOverride:
            ev.accept()                                           # 메뉴 단축키가 지정 중의 키를 가져가지 않게 한다
            return False
        if t == QEvent.Type.KeyPress:
            if not ev.isAutoRepeat():
                self.receive(int(ev.key()), ev.modifiers(), bool(ev.modifiers() & Qt.KeyboardModifier.KeypadModifier))
            return True
        if t == QEvent.Type.KeyRelease:
            return True
        return False

    def hideEvent(self, e) -> None:                               # noqa: N802 (Qt)
        super().hideEvent(e)
        self.end_capture()                                        # 설정 창을 닫으면 지정을 취소한 것이다
