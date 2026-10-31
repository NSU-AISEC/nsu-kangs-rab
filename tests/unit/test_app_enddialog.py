"""종료 창(시안 `EndDialog`, 결정 0068 E1~E4): 폭 · 상태별 버튼 · 닫기 규칙."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app import enddialog

_app = QApplication.instance() or QApplication([])


def tearDownModule():
    import gc
    for _ in range(3):
        _app.processEvents()
        gc.collect()


def visible(d):
    return {n: not b.isHidden() for n, b in (("cancel", d.cancel_button), ("close", d.close_button),
                                              ("folder", d.folder_button), ("retry", d.retry_button))}


class EndDialogTest(unittest.TestCase):
    def setUp(self):
        self.d = enddialog.EndDialog()
        self.d.set_info(segments=128, captures=4, qa=4, folder="~/Documents/ProfKangRAB/2026-10-09/", doc_name="lecture.md")
        self.addCleanup(self.d.dismiss)

    def test_size_and_modality(self):
        self.assertEqual(self.d.minimumWidth(), 640)
        self.assertEqual(self.d.maximumWidth(), 640)
        self.assertGreaterEqual(self.d.minimumHeight(), 420)
        self.assertEqual(self.d.windowModality(), Qt.WindowModality.NonModal)      # 결정 0172 1항: 종료 요청이 도착해야 한다

    def test_working_state(self):
        d = self.d
        self.assertEqual(visible(d), dict(cancel=True, close=False, folder=True, retry=False))
        self.assertFalse(d.folder_button.isEnabled())
        self.assertEqual(d.row_transcript.pill.text(), "완료")
        self.assertEqual(d.row_doc.pill.text(), "진행 중")
        self.assertIn("조각 128개", d.row_transcript.note.text())
        self.assertFalse(d.bar_row.isHidden())
        self.assertIn("2026-10-09", d.path_label.text())

    def test_done_state_primary_is_folder(self):
        d = self.d
        d.show_done("lecture.md")
        self.assertEqual(visible(d), dict(cancel=False, close=True, folder=True, retry=False))
        self.assertTrue(d.folder_button.isEnabled())
        self.assertEqual(d.folder_button.objectName(), "primary")
        self.assertTrue(d.bar_row.isHidden())
        self.assertEqual(d.title.text(), "문서를 만들었습니다")

    def test_failed_state_primary_is_retry_and_reason(self):
        d = self.d
        d.show_failed("rate_limit")
        self.assertEqual(visible(d), dict(cancel=False, close=False, folder=True, retry=True))
        self.assertEqual(d.retry_button.objectName(), "primary")
        self.assertEqual(d.row_doc.pill.text(), "실패")
        self.assertIn("한도 초과", d.message.text())
        self.assertIn("session.jsonl", d.message.text())

    def test_unknown_failure_kind_has_no_english_code(self):  # D-102
        self.d.show_failed("unknown")
        self.assertNotIn("unknown", self.d.message.text())
        self.d.show_failed("weird_kind")
        self.assertNotIn("weird_kind", self.d.message.text())
        self.d.show_failed("no_claude")
        self.assertIn("claude", self.d.message.text())

    def test_retry_returns_to_working(self):
        d = self.d
        got = []
        d.retry_requested.connect(lambda: got.append(1))
        d.show_failed("io")
        d.retry_button.click()
        self.assertEqual(got, [1])
        self.assertEqual(d.state, "working")

    def test_window_close_rules(self):
        d = self.d
        got = []
        d.close_requested.connect(lambda: got.append(1))
        d.close()                       # 진행 중에는 닫히지 않는다
        self.assertEqual(got, [])
        d.show_failed("io")
        d.close()                       # 실패 상태: 닫기 단추가 없으므로 창 닫기가 닫기 요청이다
        self.assertEqual(got, [1])
        d.dismiss()                     # 호출한 쪽의 닫기는 요청을 내지 않는다
        self.assertEqual(got, [1])

    def test_esc_while_working_is_cancel_vd261(self):
        d = self.d
        cancel, close = [], []
        d.cancel_requested.connect(lambda: cancel.append(1))
        d.close_requested.connect(lambda: close.append(1))
        d.reject()                      # 정리 문서를 만드는 중의 Esc = [취소]
        self.assertEqual((cancel, close), ([1], []))
        d.reject()                      # 이미 취소를 요청했으면 되풀이하지 않는다
        self.assertEqual(cancel, [1])
        d.show_done("x.md")
        d.reject()                      # 완료 화면의 Esc = [닫기]
        self.assertEqual(close, [1])

    def test_raises_after_other_window_activates_d186(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication, QWidget
        host = QWidget()
        d = enddialog.EndDialog(host)
        host.show()
        d.open()
        calls = []
        from PySide6.QtCore import Qt
        app_state = [Qt.ApplicationState.ApplicationActive]
        orig_state = QApplication.applicationState
        QApplication.applicationState = staticmethod(lambda: app_state[0])
        self.addCleanup(lambda: setattr(QApplication, "applicationState", orig_state))
        d.raise_ = lambda: calls.append(1)
        d.activateWindow = lambda: None
        other = QWidget()
        QApplication.sendEvent(other, QEvent(QEvent.Type.WindowActivate))
        QApplication.sendEvent(QApplication.instance(), QEvent(QEvent.Type.ApplicationActivate))
        deadline = 50
        while len(calls) < 2 and deadline:
            QApplication.processEvents()
            deadline -= 1
        self.assertGreaterEqual(len(calls), 2)
        n = len(calls)
        app_state[0] = Qt.ApplicationState.ApplicationInactive          # 다른 앱이 앞이면 올리지 않는다
        QApplication.sendEvent(other, QEvent(QEvent.Type.WindowActivate))
        for _ in range(20):
            QApplication.processEvents()
        self.assertEqual(len(calls), n)
        d.dismiss()
        host.close()


if __name__ == "__main__":
    unittest.main()
