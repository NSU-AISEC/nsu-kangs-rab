"""결정 0153: 편집 메뉴가 없어도 입력 칸 · 전사 창의 ⌘Z · ⇧⌘Z · ⌘X · ⌘C · ⌘V · ⌘A 가 위젯의 기본 동작으로 동작한다 (offscreen)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit

import test_app_controller as T
from nsu_kangs_rab.app import mainview as mv

app = QApplication.instance() or QApplication([])
SK = QKeySequence.StandardKey


def press(w, std):
    QTest.keySequence(w, QKeySequence(std))


class InputShortcutTest(unittest.TestCase):
    def check_edit(self, w, get, set_):
        w.show()
        w.setFocus()
        app.processEvents()
        set_("abc def")
        press(w, SK.SelectAll)
        press(w, SK.Cut)
        self.assertEqual(get(), "")
        self.assertEqual(QGuiApplication.clipboard().text(), "abc def")
        press(w, SK.Paste)
        self.assertEqual(get(), "abc def")
        press(w, SK.Undo)
        self.assertNotEqual(get(), "abc def")
        press(w, SK.Redo)
        self.assertEqual(get(), "abc def")
        w.close()

    def test_line_edit(self):
        w = QLineEdit()
        self.check_edit(w, w.text, w.setText)

    def test_plain_text_edit(self):
        w = QPlainTextEdit()
        self.check_edit(w, w.toPlainText, w.setPlainText)


class TranscriptShortcutTest(unittest.TestCase):
    def test_select_all_and_copy_current_line(self):
        v = mv.SessionView()
        v.resize(700, 500)
        v.show()
        for i in range(1, 4):
            v.transcript.add_segment(T.seg(i, i, i + 1, "조각 %d" % i))
        v.transcript.setFocus()
        app.processEvents()
        press(v.transcript, SK.SelectAll)
        self.assertEqual(v.transcript.selected_numbers(), (1, 2, 3))
        QGuiApplication.clipboard().setText("")
        v.transcript.setCurrentRow(1)
        press(v.transcript, SK.Copy)
        self.assertIn("조각 2", QGuiApplication.clipboard().text())
        self.assertNotIn("조각 1", QGuiApplication.clipboard().text())
        v.close()


if __name__ == "__main__":
    unittest.main()
