"""단계 16 (결정 0191): D-227 다시 보기로 연 첫 실행 고지 창의 높이. 표시 전후의 내용 높이가 같고, 높이 = max(420, min(내용, 가용 − 80))."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_app_controller as TC  # noqa: E402
from nsu_kangs_rab.app import screens, shell  # noqa: E402
from test_start_screen_stage6 import _Screen  # noqa: E402


class ReviewNoticeHeightTest(TC.Base):
    def _open(self, avail=None):
        if avail is not None:
            self.ctl.shell.screen = lambda: _Screen(avail)
        self.ctl._show_first_run_notice()
        TC.pump(10)
        dlg = self.ctl._notice_dialog
        self.addCleanup(dlg.close)
        return dlg, dlg.findChild(screens.FirstRunNotice)

    def test_content_height_same_before_and_after_show_d227(self):
        page = screens.FirstRunNotice()
        self.addCleanup(page.deleteLater)
        before = page.content_height()
        page.resize(page.WIDTH, 2000)
        page.show()
        TC.pump(5)
        self.assertEqual(page.content_height(), before)
        page.close()

    def test_dialog_height_equals_content_when_room_d227(self):
        dlg, page = self._open(avail=5000)
        self.assertEqual(dlg.height(), page.content_height())
        self.assertEqual(page.scroll.verticalScrollBar().maximum(), 0)

    def test_dialog_height_uses_fit_to_screen_limit(self):
        """상한은 `fit_to_screen` 의 값(가용 − 80, 하한 MIN_WINDOW 높이 560)이다. 내용(550)이 그 하한보다 낮아 이 화면에서는 상한이 걸리지 않는다."""
        dlg, page = self._open(avail=500)
        self.assertEqual(dlg.height(), max(shell.DIALOG_MIN_HEIGHT, min(page.content_height(), shell.fit_to_screen((page.WIDTH, 100000), screen=_Screen(500))[1])))

    def test_boundary_equal_content(self):
        base, page = self._open(avail=5000)
        c = page.content_height()
        base.close()
        dlg, page = self._open(avail=c + 80)
        self.assertEqual(dlg.height(), c)
        self.assertEqual(page.scroll.verticalScrollBar().maximum(), 0)


def tearDownModule():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
