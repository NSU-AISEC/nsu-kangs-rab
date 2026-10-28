"""단계 17 (결정 0192): 정리 문서 다시 만들기 창이 떠 있을 때의 종료 요청 (D-229, AC-FR13-14 · AC-FR13-18)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_app_controller as TC  # noqa: E402
from test_app_controller import FakeModel, pump  # noqa: E402
from nsu_kangs_rab.core import endflow  # noqa: E402


class RebuildQuitTest(TC.Base):
    def _rebuild(self, reply):
        folder = Path(tempfile.mkdtemp(prefix="s17-rq-"))
        self.addCleanup(shutil.rmtree, folder, True)
        ev = [{"type": "header", "v": 1, "date": "2026-10-09", "provider": "claude_subscription", "model": "sonnet",
               "effort": "medium", "source": "시스템 사운드", "materials": [], "kind": "수업", "title": "종료 시험",
               "number": "01", "mode": "대면", "start": "13:15:02"},
              {"type": "segment", "n": 1, "start": "13:15:05", "end": "13:15:09", "text": "첫 조각"},
              {"type": "segment", "n": 2, "start": "13:16:00", "end": "13:16:04", "text": "둘째 조각"}]
        (folder / "session.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in ev), encoding="utf-8")
        self.assertIsNone(self.ctl.runtime)                        # 세션을 시작하기 전(②)이다
        orig = FakeModel.__init__

        def init(self_, *a, **k):
            orig(self_, *a, **k)
            self_.auto_reply = reply
        FakeModel.__init__ = init
        self.addCleanup(setattr, FakeModel, "__init__", orig)
        self.assertTrue(self.ctl.rebuild_summary(folder))
        pump(10)
        return folder

    def _wait_ended(self):
        for _ in range(100):
            pump(1)
            if self.ctl._ended:
                break

    def test_quit_while_generating_cancels_and_ends(self):        # 갈래 1: 생성 중
        folder = self._rebuild(False)
        self.assertFalse(self.ctl._cleanup_finished)
        self.ctl.shell.request_quit()
        self.assertFalse(self.ctl._ended)                          # 취소 결과를 기다린다
        self.assertTrue(self.ctl._quit_after_rebuild)
        self._wait_ended()
        self.assertTrue(self.ctl._ended)
        self.assertIsNone(self.ctl._end_dialog)
        self.assertFalse((folder / "lecture.md").exists())         # 문서가 남지 않는다

    def test_quit_on_done_screen_ends_at_once(self):               # 갈래 2: 완료 화면
        folder = self._rebuild(True)
        for _ in range(100):
            pump(1)
            if self.ctl._cleanup_finished:
                break
        self.assertTrue((folder / "lecture.md").exists())
        self.ctl.shell.request_quit()
        self.assertTrue(self.ctl._ended)
        self.assertIsNone(self.ctl._end_dialog)

    def test_quit_without_rebuild_ends_at_once(self):              # 갈래 3: 다시 만들기 없음
        self.ctl.shell.request_quit()
        self.assertTrue(self.ctl._ended)
        self.assertFalse(self.ctl._quit_after_rebuild)

    def test_repeated_quit_requests_are_harmless(self):
        self._rebuild(False)
        self.ctl.shell.request_quit()
        self.ctl.shell.request_quit()
        self._wait_ended()
        self.assertTrue(self.ctl._ended)

    def test_sigterm_while_rebuilding_cancels_and_ends(self):      # AC-FR13-18 ⓑ
        self._rebuild(False)
        self.ctl.terminate_by_signal("sigterm")
        self.assertFalse(self.ctl._ended)
        self.ctl.terminate_by_signal("sigterm")                    # 두 번째는 아무 일도 하지 않는다
        self._wait_ended()
        self.assertTrue(self.ctl._ended)
        self.assertIsNone(self.ctl._end_dialog)

    def _late_result(self, result):
        """종료 요청 뒤 취소가 적용되기 전에 다른 결과가 온 경우(D-230)."""
        self._rebuild(False)
        self.ctl.shell.request_quit()
        self.assertTrue(self.ctl._quit_after_rebuild)
        self.assertFalse(self.ctl._ended)
        self.ctl._end_bridge.done.emit(result)
        self._wait_ended()
        self.assertTrue(self.ctl._ended)
        self.assertIsNone(self.ctl._end_dialog)

    def test_quit_then_done_result_still_ends_d230(self):
        self._late_result(endflow.EndResult(endflow.DONE, path=Path("lecture.md")))

    def test_quit_then_failed_result_still_ends_d230(self):
        self._late_result(endflow.EndResult(endflow.FAILED, kind="timeout"))

    def test_sigterm_then_done_result_still_ends_d230(self):
        self._rebuild(False)
        self.ctl.terminate_by_signal("sigterm")
        self.ctl._end_bridge.done.emit(endflow.EndResult(endflow.DONE, path=Path("lecture.md")))
        self._wait_ended()
        self.assertTrue(self.ctl._ended)

    def test_shutdown_dismisses_leftover_dialog(self):
        self._rebuild(False)
        d = self.ctl._end_dialog
        self.assertTrue(d.isVisible())
        self.ctl.shutdown()
        self.assertIsNone(self.ctl._end_dialog)
        self.assertFalse(d.isVisible())


def tearDownModule():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
