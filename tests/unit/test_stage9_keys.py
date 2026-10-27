"""단계 9 키 설정 표(결정 0141 · 0142)의 단위 시험: 키 규칙 · 표 위젯 · 전역 키 등록기. 실제 Carbon 등록은 하지 않는다."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app import keyspec as ks
from nsu_kangs_rab.app.keytable import KeyTable
from nsu_kangs_rab.core.i18n import t as _t
from nsu_kangs_rab.platform import hotkeys

K, M = Qt.Key, Qt.KeyboardModifier
NO = M.NoModifier
app = QApplication.instance() or QApplication([])


class KeySpecTest(unittest.TestCase):
    def test_classify(self):
        c = lambda k, m=NO: ks.classify(int(k.value), m)               # noqa: E731
        self.assertEqual(c(K.Key_PageUp), ks.ACCEPT)
        self.assertEqual(c(K.Key_F2), ks.ACCEPT)
        self.assertEqual(c(K.Key_Up), ks.ACCEPT)
        self.assertEqual(c(K.Key_A), ks.TYPING)
        self.assertEqual(c(K.Key_A, M.ShiftModifier), ks.TYPING)          # ⇧ 만 붙인 글자 키
        self.assertEqual(c(K.Key_1, M.ShiftModifier), ks.TYPING)
        self.assertEqual(c(K.Key_Space), ks.TYPING)
        self.assertEqual(c(K.Key_A, M.MetaModifier), ks.ACCEPT)           # ⌃A
        self.assertEqual(c(K.Key_A, M.AltModifier), ks.ACCEPT)            # ⌥A
        self.assertEqual(c(K.Key_Escape), ks.CANCEL)
        self.assertEqual(c(K.Key_Escape, M.AltModifier), ks.CANCEL)       # ⌥Esc 도 취소
        for k in (K.Key_Shift, K.Key_Control, K.Key_Alt, K.Key_Meta, K.Key_CapsLock, K.Key_Hangul):
            self.assertEqual(c(k), ks.IGNORE)
        self.assertEqual(ks.classify(int(K.Key_5.value), NO, keypad=True), ks.TYPING)

    def test_text_roundtrip_and_display(self):
        t = ks.to_text(int(K.Key_K.value), M.ControlModifier | M.ShiftModifier | M.AltModifier)
        self.assertEqual(ks.parse(t), (int(K.Key_K.value), int((M.ControlModifier | M.ShiftModifier | M.AltModifier).value)))
        self.assertEqual(ks.display(t), "⌥⇧⌘K")
        self.assertEqual(ks.display(ks.to_text(int(K.Key_PageUp.value), NO)), "Page Up")
        self.assertEqual(ks.display("F2"), "F2")
        self.assertEqual(ks.display(ks.to_text(int(K.Key_A.value), M.MetaModifier)), "⌃A")

    def test_carbon(self):
        self.assertEqual(ks.carbon("PgUp"), (116, 0))
        self.assertEqual(ks.carbon("PgDown"), (121, 0))
        self.assertEqual(ks.carbon("F2"), (120, 0))
        self.assertEqual(ks.carbon("Ctrl+Alt+Shift+K"), (40, ks.CARBON_CMD | ks.CARBON_OPT | ks.CARBON_SHIFT))
        self.assertEqual(ks.carbon("Meta+A"), (0, ks.CARBON_CTRL))
        self.assertIsNone(ks.carbon(""))

    def test_saved_typing_key(self):
        self.assertTrue(ks.typing_key_without_modifier("A"))
        self.assertFalse(ks.typing_key_without_modifier("F2"))
        self.assertFalse(ks.typing_key_without_modifier("Ctrl+A"))
        self.assertFalse(ks.typing_key_without_modifier(""))


class KeyTableTest(unittest.TestCase):
    def make(self, menu=None, system=None, values=None):
        return KeyTable(values or {}, lambda: dict(menu or {}), lambda text: (system or {}).get(text))

    def press(self, tbl, key, mods=NO):
        return tbl.receive(int(key.value), mods)

    def test_defaults(self):
        tbl = self.make()
        self.assertEqual(tbl.value("trigger"), "F2")
        self.assertEqual(tbl.value("global_trigger"), "")
        self.assertEqual(tbl._rows["global_trigger"].cap.text(), _t("keyset.new13"))

    def test_capture_page_up_and_esc(self):
        tbl = self.make()
        got = []
        tbl.key_changed.connect(lambda r, t: got.append((r, t)))
        tbl.begin_capture("global_trigger")
        self.assertEqual(tbl._rows["global_trigger"].cap.text(), _t("keyset.new14"))
        self.assertFalse(tbl._rows["trigger"].change.isEnabled())          # 다른 행의 단추는 지정 중에 동작하지 않는다
        self.assertEqual(self.press(tbl, K.Key_PageUp), "accepted")
        self.assertEqual(got, [("global_trigger", "PgUp")])
        self.assertIsNone(tbl.capturing())
        tbl.begin_capture("trigger")
        self.assertEqual(self.press(tbl, K.Key_Escape), "cancel")
        self.assertEqual(tbl.value("trigger"), "F2")

    def test_rejections_keep_capturing(self):
        tbl = self.make(menu={"Ctrl+,": "설정"}, system={"Ctrl+Space": "Spotlight"})
        tbl.begin_capture("global_capture")
        self.assertEqual(self.press(tbl, K.Key_F2), "rejected")                      # 다른 행(F2)
        self.assertIn("F2", tbl._rows["global_capture"].hint.text())
        self.assertEqual(tbl._rows["global_capture"].hint.objectName(), "key_warn")
        self.assertEqual(self.press(tbl, K.Key_Comma, M.ControlModifier), "rejected")  # 메뉴
        self.assertIn("설정", tbl._rows["global_capture"].hint.text())
        self.assertEqual(self.press(tbl, K.Key_Space, M.ControlModifier), "rejected")  # 시스템
        self.assertEqual(self.press(tbl, K.Key_A), "rejected")                       # 글자 키
        self.assertEqual(self.press(tbl, K.Key_Shift), "ignore")
        self.assertEqual(tbl.capturing(), "global_capture")
        self.assertEqual(self.press(tbl, K.Key_A, M.MetaModifier), "accepted")
        self.assertEqual(tbl.value("global_capture"), "Meta+A")

    def test_clear(self):
        tbl = self.make(values={"global_trigger_key": "PgUp"})
        got = []
        tbl.key_changed.connect(lambda r, t: got.append((r, t)))
        tbl.clear_row("global_trigger")
        tbl.clear_row("global_trigger")                                            # 빈 행의 비우기는 아무 일이 없다
        self.assertEqual(got, [("global_trigger", "")])

    def test_hint_registered_prefix(self):
        tbl = self.make(values={"global_trigger_key": "PgUp"})
        self.assertEqual(tbl._rows["global_trigger"].hint.text(), _t("keyset.key5"))
        tbl.set_session_registration({"global_trigger"}, set())
        self.assertEqual(tbl._rows["global_trigger"].hint.text(), _t("keyset.key6") + _t("keyset.key5"))

    def test_reset_notice(self):
        tbl = self.make()
        tbl.set_reset_notice("trigger", "A")
        self.assertIn("A", tbl._rows["trigger"].hint.text())
        tbl.dismiss_reset_notices()
        self.assertEqual(tbl._rows["trigger"].hint.text(), "")


class _FakeBackend:
    def __init__(self, fail=()):
        self.regs, self.fail = {}, set(fail)

    def register(self, ident, vk, mods):
        if vk in self.fail:
            return -9878
        self.regs[ident] = (vk, mods)
        return 0

    def unregister(self, ident):
        self.regs.pop(ident, None)


class GlobalHotkeysTest(unittest.TestCase):
    def test_register_fire_clear(self):
        got = []
        be = _FakeBackend(fail={40})
        hk = hotkeys.GlobalHotkeys(got.append, backend=be)
        self.assertEqual(hk.set("a", 116, 0), 0)
        self.assertNotEqual(hk.set("b", 40, 0), 0)
        self.assertTrue(hk.registered("a"))
        self.assertFalse(hk.registered("b"))
        hk._fired(next(iter(be.regs)))
        self.assertEqual(got, ["a"])
        hk.set("a", 121, 0)                                                         # 같은 이름은 먼저 해제하고 다시 등록한다
        self.assertEqual(list(be.regs.values()), [(121, 0)])
        hk.clear_all()
        self.assertEqual(be.regs, {})


if __name__ == "__main__":
    unittest.main()
