"""결정 0144: AI 창의 따라가기(새 카드 · 스트리밍으로 늘어나는 글 · 위로 스크롤하면 멈춤 · 요청 카드는 맨 아래로)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app.mainview import AIView
from nsu_kangs_rab.core import requests as R

app = QApplication.instance() or QApplication([])


def card(n, text, state=R.STATE_WAITING):
    return R.Card(n, "자유질의", state, text=text)


class FollowTest(unittest.TestCase):
    def make(self):
        v = AIView()
        v.resize(420, 300)
        v.show()
        app.processEvents()
        return v

    def bottom(self, v):
        bar = v.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def test_follows_new_cards_and_streaming(self):
        v = self.make()
        for n in range(1, 6):
            v.apply_card(card(n, "줄\n" * 8), "new")
            app.processEvents()
        self.assertGreater(v.verticalScrollBar().maximum(), 0)
        self.assertTrue(self.bottom(v))
        v.apply_card(card(5, "줄\n" * 60), "update")             # 스트리밍으로 글이 크게 늘어난다
        app.processEvents()
        self.assertTrue(self.bottom(v))

    def test_stops_when_scrolled_up_and_resumes_at_bottom(self):
        v = self.make()
        for n in range(1, 6):
            v.apply_card(card(n, "줄\n" * 8), "new")
            app.processEvents()
        bar = v.verticalScrollBar()
        bar.setValue(0)
        self.assertFalse(v.following())
        v.apply_card(card(5, "줄\n" * 60), "update")
        app.processEvents()
        self.assertEqual(bar.value(), 0)
        bar.setValue(bar.maximum())
        self.assertTrue(v.following())
        v.apply_card(card(5, "줄\n" * 90), "update")
        app.processEvents()
        self.assertTrue(self.bottom(v))

    def test_new_request_card_jumps_to_bottom_even_when_scrolled_up(self):
        v = self.make()
        for n in range(1, 6):
            v.apply_card(card(n, "줄\n" * 8), "new")
            app.processEvents()
        v.verticalScrollBar().setValue(0)
        v.apply_card(card(6, "줄\n" * 8), "new")
        app.processEvents()
        self.assertTrue(self.bottom(v))
        self.assertTrue(v.following())


if __name__ == "__main__":
    unittest.main()
