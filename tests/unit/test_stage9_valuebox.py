"""결정 0145: 설정 창의 값 표시 상자(키캡 · 저장된 키 점 표시 · 모델 위치)와 단추의 높이 · 세로 정렬."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app import screens
from nsu_kangs_rab.core import settings

app = QApplication.instance() or QApplication([])


class ValueBoxTest(unittest.TestCase):
    def setUp(self):
        app.setStyleSheet("")                                    # 다른 시험 모듈이 남긴 스타일에 영향받지 않게 비운다
        self.addCleanup(app.setStyleSheet, "")

    def form(self):
        f = screens.SettingsForm(settings.load_defaults())
        f.resize(640, 900)
        f.show()
        app.processEvents()
        return f

    def card(self):                                              # 결정 0179: 저장된 키의 값 표시 상자는 시작 화면의 5. claude 실행 파일 절의 키 줄에 있다
        c = screens.ClaudeSection(settings.load_defaults(), "/usr/bin/claude", "claude_api")
        c.resize(640, 400)
        c.show()
        app.processEvents()
        self.addCleanup(self._dispose, c)
        return c

    @staticmethod
    def _dispose(w):          # 부모 없는 위젯을 종료 전에 지운다
        from PySide6.QtCore import QCoreApplication, QEvent
        w.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_model_section_is_removed(self):                  # 결정 0162 · 0167: 앱이 내려받는 모델이 없다
        f = self.form()
        for name in ("model_section", "model_path", "model_open", "model_delete", "model_state", "set_model_state"):
            self.assertFalse(hasattr(f, name), name)
        f.close()

    def test_saved_key_is_value_box_36_and_editing_restores_input(self):
        f = self.card()
        f.set_key_saved(True)
        self.assertTrue(f.api_key.property("valuebox"))
        self.assertEqual(f.api_key.height(), 36)
        self.assertEqual(f.save_key.height(), 36)
        f.set_key_saved(False)
        self.assertFalse(f.api_key.property("valuebox"))
        f.set_key_saved(True)
        f._begin_key_change()
        self.assertFalse(f.api_key.property("valuebox"))
        f.close()

    def test_keycap_and_buttons_same_height(self):
        f = self.form()
        for row in f.key_table._rows.values():
            self.assertEqual(row.cap.height(), 32)
            self.assertEqual(row.change.height(), 32)
            self.assertEqual(row.clear.height(), 32)
            self.assertEqual(row.cap.geometry().center().y(), row.change.geometry().center().y())
        f.close()


def tearDownModule():          # 부모 없는 위젯(카드 · 폼)을 인터프리터 종료 전에 지운다(종료 때의 비정상 종료 방지)
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
