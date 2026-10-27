"""D-120: 액자 창의 macOS 기본 크기 조절(Resizable)을 끈다. offscreen 에서는 대상이 아니므로 False 를 반환하는지 본다."""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "mac"))

from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.platform import nswindow

_app = QApplication.instance() or QApplication([])


class NSWindowTest(unittest.TestCase):
    def test_mask_drops_only_resizable(self):
        self.assertEqual(nswindow.without_resizable(14), 6)       # 실측 styleMask 14 = Closable | Miniaturizable | Resizable
        self.assertEqual(nswindow.without_resizable(6), 6)
        self.assertEqual(nswindow.without_resizable(0), 0)

    def test_not_cocoa_does_nothing(self):
        from nsu_kangs_rab.app.frame import FrameWindow
        f = FrameWindow()
        self.assertFalse(nswindow.disable_native_resize(f))
        self.assertIsNone(nswindow.style_mask(f))
        f.deleteLater()


if __name__ == "__main__":
    unittest.main()


class CursorApplyTest(unittest.TestCase):
    def test_apply_cursor_is_noop_off_cocoa_and_hover_still_sets_qt_cursor(self):  # D-123
        from PySide6.QtCore import QPoint, Qt
        from nsu_kangs_rab.app.frame import FrameWindow
        from nsu_kangs_rab.core import framegeom as G
        f = FrameWindow()
        f.set_frame(G.Rect(0, 0, 400, 300))
        self.assertFalse(nswindow.apply_cursor(f))
        self.assertFalse(nswindow.allow_background_cursor())      # D-145: 비공개 속성은 cocoa 가 아니면 호출하지 않는다(결정 0086 4항 수정은 master 가 기록한다)
        f._hover(QPoint(5, 5))
        self.assertEqual(f.cursor().shape(), Qt.OpenHandCursor)
        f._hover(QPoint(200, 1))
        self.assertEqual(f.cursor().shape(), Qt.ArrowCursor)
        f.deleteLater()


class ShadowTest(unittest.TestCase):
    def test_frame_has_no_drop_shadow_d124(self):
        """고리 모양 투명 창의 그림자가 구멍(캡처 영역) 가장자리를 어둡게 했다(D-124). cocoa 의 hasShadow 는 NoDropShadowWindowHint 가 끈다."""
        from PySide6.QtCore import Qt
        from nsu_kangs_rab.app.frame import FrameWindow
        f = FrameWindow()
        self.assertTrue(f.windowFlags() & Qt.NoDropShadowWindowHint)
        f.deleteLater()
