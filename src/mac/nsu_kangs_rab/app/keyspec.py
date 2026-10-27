"""키 설정 표의 키 값과 규칙 (결정 0141 · 0142, `docs/plan/functional-spec.md` FR-7 "키 설정 표").

키 값은 `QKeySequence` 의 PortableText 문자열로 저장한다(예: `F2`, `PgUp`, `Ctrl+Alt+K`). macOS 에서 Qt 의 `Ctrl` 은 ⌘, `Meta` 는 ⌃,
`Alt` 는 ⌥ 이다. 이 모듈은 Qt 의 키 값(`Qt.Key`) · 수식 키(`Qt.KeyboardModifier`)만 쓰며 화면 위젯은 만들지 않는다.

- `classify(key, mods)`: 지정 중에 누른 키를 "무시 / 취소 / 글자 키 / 받음" 으로 나눈다.
- `to_text` · `parse` · `display`: 저장 글 ↔ 키 ↔ 표기(⌃ ⌥ ⇧ ⌘ 순서).
- `carbon(text)`: 전역 등록에 쓰는 (macOS 가상 키 코드, Carbon 수식 키). 대응이 없으면 None.
- `typing_key_without_modifier(text)`: 저장되어 있던 글자 키를 찾는다(결정 0142, AC-FR7-31).
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

K = Qt.Key
M = Qt.KeyboardModifier

# 지정 중에 눌러도 키로 받지 않고 다음 키를 기다리는 키: 수식 키 단독, 입력 전환 키(Caps Lock · 한/영 · 한자).
_IGNORED = {
    K.Key_Shift, K.Key_Control, K.Key_Meta, K.Key_Alt, K.Key_AltGr, K.Key_Super_L, K.Key_Super_R, K.Key_CapsLock,
    K.Key_NumLock, K.Key_ScrollLock, K.Key_Mode_switch, K.Key_Hangul, K.Key_Hangul_Hanja, K.Key_Hangul_Jamo,
    K.Key_Hangul_Romaja, K.Key_Hangul_Jeonja, K.Key_Hangul_Banja, K.Key_Hangul_PreHanja, K.Key_Hangul_PostHanja,
    K.Key_Hangul_Special, K.Key_Hangul_Start, K.Key_Hangul_End, K.Key_Henkan, K.Key_Muhenkan, K.Key_Zenkaku_Hankaku,
    K.Key_Eisu_toggle, K.Key_Kana_Lock, K.Key_Kana_Shift, K.Key_unknown,
}

# 글자 입력에 쓰이는 이름 있는 키(글자 · 숫자 · 기호는 키 값이 문자 코드이므로 따로 판별한다).
_TYPING_NAMED = {K.Key_Space, K.Key_Return, K.Key_Enter, K.Key_Tab, K.Key_Backtab, K.Key_Backspace, K.Key_Delete}

# Qt 키 → macOS 가상 키 코드(ANSI 배열의 물리 위치). 표에 없는 키는 전역 등록을 하지 못한다.
_VK = {
    K.Key_A: 0, K.Key_S: 1, K.Key_D: 2, K.Key_F: 3, K.Key_H: 4, K.Key_G: 5, K.Key_Z: 6, K.Key_X: 7, K.Key_C: 8, K.Key_V: 9,
    K.Key_B: 11, K.Key_Q: 12, K.Key_W: 13, K.Key_E: 14, K.Key_R: 15, K.Key_Y: 16, K.Key_T: 17,
    K.Key_1: 18, K.Key_2: 19, K.Key_3: 20, K.Key_4: 21, K.Key_6: 22, K.Key_5: 23, K.Key_Equal: 24, K.Key_9: 25, K.Key_7: 26,
    K.Key_Minus: 27, K.Key_8: 28, K.Key_0: 29, K.Key_BracketRight: 30, K.Key_O: 31, K.Key_U: 32, K.Key_BracketLeft: 33,
    K.Key_I: 34, K.Key_P: 35, K.Key_L: 37, K.Key_J: 38, K.Key_Apostrophe: 39, K.Key_K: 40, K.Key_Semicolon: 41,
    K.Key_Backslash: 42, K.Key_Comma: 43, K.Key_Slash: 44, K.Key_N: 45, K.Key_M: 46, K.Key_Period: 47, K.Key_QuoteLeft: 50,
    K.Key_Space: 49, K.Key_Tab: 48, K.Key_Return: 36, K.Key_Backspace: 51,
    K.Key_F1: 122, K.Key_F2: 120, K.Key_F3: 99, K.Key_F4: 118, K.Key_F5: 96, K.Key_F6: 97, K.Key_F7: 98, K.Key_F8: 100,
    K.Key_F9: 101, K.Key_F10: 109, K.Key_F11: 103, K.Key_F12: 111, K.Key_F13: 105, K.Key_F14: 107, K.Key_F15: 113,
    K.Key_F16: 106, K.Key_F17: 64, K.Key_F18: 79, K.Key_F19: 80, K.Key_F20: 90,
    K.Key_Home: 115, K.Key_End: 119, K.Key_PageUp: 116, K.Key_PageDown: 121, K.Key_Delete: 117, K.Key_Help: 114,
    K.Key_Left: 123, K.Key_Right: 124, K.Key_Down: 125, K.Key_Up: 126,
}

# Carbon 수식 키(RegisterEventHotKey): ⌘ 256 · ⇧ 512 · ⌥ 2048 · ⌃ 4096. Qt 의 Ctrl 이 ⌘, Meta 가 ⌃ 이다.
CARBON_CMD, CARBON_SHIFT, CARBON_OPT, CARBON_CTRL = 256, 512, 2048, 4096

_NAMES = {
    K.Key_PageUp: "Page Up", K.Key_PageDown: "Page Down", K.Key_Home: "Home", K.Key_End: "End", K.Key_Left: "←",
    K.Key_Right: "→", K.Key_Up: "↑", K.Key_Down: "↓", K.Key_Space: "Space", K.Key_Return: "Return", K.Key_Enter: "Enter",
    K.Key_Tab: "Tab", K.Key_Backspace: "Delete", K.Key_Delete: "Forward Delete", K.Key_Help: "Help", K.Key_Insert: "Insert",
}

Verdict = str
IGNORE, CANCEL, TYPING, ACCEPT = "ignore", "cancel", "typing", "accept"


def _modifier_bits(mods) -> int:
    return int(mods.value if hasattr(mods, "value") else mods) & (
        int(M.ShiftModifier.value) | int(M.ControlModifier.value) | int(M.AltModifier.value) | int(M.MetaModifier.value))


def is_typing_key(key: int, keypad: bool = False) -> bool:
    """글자 · 숫자 · 기호 · Space · Return · Tab · Delete · 앞으로 지우기 · 키패드의 숫자 · 연산 기호 · Enter."""
    k = int(key)
    if keypad:
        return k in (int(K.Key_Enter), int(K.Key_Return)) or 0x20 <= k <= 0x7E or k < 0x01000000
    if 0 < k < 0x01000000:                  # 문자 코드 키(글자 · 숫자 · 기호)
        return True
    return any(k == int(n) for n in _TYPING_NAMED)


def classify(key: int, mods, keypad: bool = False) -> Verdict:
    """지정 중에 누른 키의 처리: Esc(수식 키를 붙여도) → 취소, 수식 키 단독 · 입력 전환 키 → 무시,
    수식 키 없이(또는 ⇧ 만 붙여) 누른 글자 키 → 글자 키(받지 않음), 그 밖 → 받음."""
    k = int(key)
    if k == int(K.Key_Escape):
        return CANCEL
    if any(k == int(i) for i in _IGNORED):
        return IGNORE
    if is_typing_key(k, keypad) and not (_modifier_bits(mods) & (int(M.ControlModifier.value) | int(M.MetaModifier.value)
                                                                  | int(M.AltModifier.value))):
        return TYPING
    return ACCEPT


def to_text(key: int, mods) -> str:
    """저장하는 글(PortableText). 수식 키는 ⇧ ⌘ ⌃ ⌥ 만 담는다(keypad · fn 은 제외)."""
    k = int(key)
    if k < 0x01000000 and chr(k).isalpha():
        k = ord(chr(k).upper())             # 글자 키는 대문자 키 값으로 정규화한다
    return QKeySequence(k | _modifier_bits(mods)).toString(QKeySequence.SequenceFormat.PortableText)


def parse(text: str) -> Optional[Tuple[int, int]]:
    """저장한 글 → (키 값, 수식 키 비트). 비었거나 읽을 수 없으면 None."""
    if not text:
        return None
    seq = QKeySequence(text, QKeySequence.SequenceFormat.PortableText)
    if seq.count() < 1:
        return None
    combo = seq[0].toCombined() if hasattr(seq[0], "toCombined") else int(seq[0])
    mods = combo & (int(M.ShiftModifier.value) | int(M.ControlModifier.value) | int(M.AltModifier.value) | int(M.MetaModifier.value))
    key = combo & ~(int(M.ShiftModifier.value) | int(M.ControlModifier.value) | int(M.AltModifier.value) | int(M.MetaModifier.value)
                    | int(M.KeypadModifier.value) | int(M.GroupSwitchModifier.value))
    if key == 0:
        return None
    return key, mods


def display(text: str) -> str:
    """표기: macOS 기호 순서(⌃ ⌥ ⇧ ⌘) + 키 이름. 비었으면 빈 글."""
    p = parse(text)
    if p is None:
        return text or ""
    key, mods = p
    out = ""
    if mods & int(M.MetaModifier.value):
        out += "⌃"
    if mods & int(M.AltModifier.value):
        out += "⌥"
    if mods & int(M.ShiftModifier.value):
        out += "⇧"
    if mods & int(M.ControlModifier.value):
        out += "⌘"
    if key in {int(k) for k in _NAMES}:
        name = next(v for k, v in _NAMES.items() if int(k) == key)
    elif 0x01000030 <= key <= 0x01000047:
        name = "F%d" % (key - 0x01000030 + 1)
    elif key < 0x01000000:
        name = chr(key).upper()
    else:
        name = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
    return out + name


def carbon(text: str) -> Optional[Tuple[int, int]]:
    """전역 등록 값 (가상 키 코드, Carbon 수식 키). 대응이 없으면 None."""
    p = parse(text)
    if p is None:
        return None
    key, mods = p
    vk = next((v for k, v in _VK.items() if int(k) == key), None)
    if vk is None:
        return None
    cm = 0
    if mods & int(M.ControlModifier.value):
        cm |= CARBON_CMD
    if mods & int(M.ShiftModifier.value):
        cm |= CARBON_SHIFT
    if mods & int(M.AltModifier.value):
        cm |= CARBON_OPT
    if mods & int(M.MetaModifier.value):
        cm |= CARBON_CTRL
    return vk, cm


def typing_key_without_modifier(text: str) -> bool:
    """저장되어 있던 키가 수식 키 없는(또는 ⇧ 만 붙은) 글자 키인가(결정 0142)."""
    p = parse(text)
    if p is None:
        return False
    key, mods = p
    return classify(key, mods) == TYPING
