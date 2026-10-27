"""결정 0154: 정리 문서 생성의 절 단위 진행 표시(계산과 종료 대화의 위젯)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app.enddialog import EndDialog
from nsu_kangs_rab.core import endflow as E

app = QApplication.instance() or QApplication([])
TEMPLATE = "# 제목\n## 가\n내용\n## 나\n## 다\n### 소절\n줄 중간 ## 아님\n"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class CountTest(unittest.TestCase):
    def test_count_rules(self):
        self.assertEqual(E.count_sections(TEMPLATE), 3)
        self.assertEqual(E.count_sections("## a\n\n## b"), 2)
        self.assertEqual(E.count_sections("### x\n  ## y\n"), 0)
        self.assertEqual(E.count_sections("```\n## 코드 안\n```"), 1)       # 코드 블록은 구분하지 않는다

    def test_format_elapsed(self):
        self.assertEqual([E.format_elapsed(x) for x in (0, 5, 65, 3599)], ["00:00", "00:05", "01:05", "59:59"])
        self.assertEqual([E.format_elapsed(x) for x in (3600, 3665, 7325)], ["1:00:00", "1:01:05", "2:02:05"])

    def test_progress_monotonic_capped_and_split_line(self):
        c = Clock()
        p = E.SectionProgress(TEMPLATE, c)
        self.assertEqual(p.snapshot()[:2], (0, 3))
        p.feed("서문\n##")
        self.assertEqual(p.snapshot()[0], 0)  # 세 글자("## ")가 도착하기 전
        p.feed(" 가")                         # 조각 경계에 걸려도 이어 붙여 센다
        self.assertEqual(p.snapshot()[0], 1)
        p.feed("\n## 나\n")
        self.assertEqual(p.snapshot()[0], 2)
        p.feed("x\n## b\n## c\n## d\n## e\n")
        self.assertEqual(p.snapshot()[0], 3)  # N 을 넘지 않는다
        c.t += 125
        self.assertAlmostEqual(p.snapshot()[2], 125)
        p.shift(3500)
        self.assertAlmostEqual(p.snapshot()[2], 3625)
        p.restart()
        self.assertEqual(p.snapshot()[:2], (0, 3))
        self.assertAlmostEqual(p.snapshot()[2], 0)


class DialogTest(unittest.TestCase):
    def setUp(self):
        self.c = Clock()
        self.p = E.SectionProgress(TEMPLATE, self.c)
        self.d = EndDialog()
        self.d.set_progress_provider(self.p.snapshot)
        self.addCleanup(self.d.dismiss)

    def read(self):
        b = self.d.bar
        return b.minimum(), b.maximum(), b.value(), self.d.progress_text.text()

    def test_stages(self):
        self.assertEqual(self.d.bar.objectName(), "end_progress")
        self.assertEqual(self.d.progress_text.objectName(), "end_progress_text")
        self.assertEqual(self.read(), (0, 0, -1, "준비 중 · 경과 00:00"))
        self.p.feed("## 가\n")
        self.c.t += 7
        self.d.refresh_progress()
        self.assertEqual(self.read(), (0, 3, 1, "1 / 3 절 · 경과 00:07"))
        self.p.feed("## 나\n## 다\n")
        self.d.refresh_progress()
        self.assertEqual(self.read(), (0, 3, 3, "3 / 3 절 · 마지막 절을 쓰는 중 · 경과 00:07"))
        self.p.shift(3600)
        self.d.refresh_progress()
        self.assertTrue(self.d.progress_text.text().endswith("경과 1:00:07"))

    def test_no_sections_in_template_shows_elapsed_only(self):
        p = E.SectionProgress("제목만", self.c)
        self.d.set_progress_provider(p.snapshot)
        p.feed("## 있어도\n")
        self.d.refresh_progress()
        self.assertEqual(self.read(), (0, 0, -1, "경과 00:00"))

    def test_hidden_when_not_working(self):
        self.d.show_done("lecture.md")
        self.assertTrue(self.d.bar_row.isHidden())
        self.d.show_failed("timeout")
        self.assertTrue(self.d.bar_row.isHidden())


if __name__ == "__main__":
    unittest.main()
