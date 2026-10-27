"""앱 정보 창(AC-NF-4, 결정 0043)과 앱 자원의 해시 기록."""
import hashlib
import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app import screens
from nsu_kangs_rab.core import resources

_app = QApplication.instance() or QApplication([])


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


class AssetsTest(unittest.TestCase):
    def test_recorded_hashes_match(self):
        rec = json.load(open(resources._DIR / "ASSETS.json", encoding="utf-8"))
        for name in ("about_image.png", "app_icon_source.png"):
            self.assertEqual(_sha(resources._DIR / name), rec[name]["자원_sha256"])
            self.assertEqual(rec[name]["원본_sha256"], rec[name]["자원_sha256"])
        self.assertTrue(rec["about_image.png"]["자원_sha256"].startswith("df75fe747562948d"))
        self.assertTrue(rec["app_icon_source.png"]["자원_sha256"].startswith("a9b6906af4e4472f"))


class AboutViewTest(unittest.TestCase):
    def test_contents(self):
        v = screens.AboutView(resources.about_image_path())
        self.assertEqual(v.title.text(), "Prof. Kang's RAB")
        self.assertEqual(v.subtitle.text(), "Retrieval-Augmented Brain")
        self.assertIn("2026년 9월 19일 강의에서 소개한 회의 방식에서 출발했습니다.", v.origin.text())
        self.assertIn("사용자의 두뇌와 지식을 증강합니다.", v.origin.text())
        pm = v.image.pixmap()
        self.assertFalse(pm.isNull())
        self.assertEqual(v.source_size, (1122, 1402))
        self.assertLess(abs(pm.width() / pm.height() - 1122 / 1402) / (1122 / 1402), 0.01)

    def test_layout_not_clipped(self):
        v = screens.AboutView(resources.about_image_path())
        v.show()
        _app.processEvents()
        self.assertEqual((v.width(), v.height()), (640, 420))
        self.assertEqual((v.image.width(), v.image.height()), (240, 300))
        self.assertLess(v.image.x(), v.title.x())       # 이미지가 왼쪽, 글이 오른쪽
        self.assertGreaterEqual(v.origin.height(), v.origin.heightForWidth(v.origin.width()))
        v.close()

    def test_window_title(self):
        self.assertEqual(screens.ABOUT_TITLE, "앱 정보")


if __name__ == "__main__":
    unittest.main()
