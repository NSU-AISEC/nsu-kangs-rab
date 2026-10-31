"""단계 9 일시 정지 · 수집 전 · 정지 확인 창(결정 0147 · 0149 · 0150)의 단위 시험."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import test_app_controller as T
from nsu_kangs_rab.app import mainview as mv
from nsu_kangs_rab.core import appstate
from nsu_kangs_rab.core.i18n import t as _t


def tearDownModule():
    import gc
    for _ in range(3):
        T._app.processEvents()
        T.QCoreApplication.sendPostedEvents(None, 0)
        gc.collect()


class FormatTest(unittest.TestCase):
    def test_duration(self):
        f = mv.format_duration
        self.assertEqual([f(0), f(15), f(59)], ["0초", "15초", "59초"])
        self.assertEqual([f(60), f(61), f(3599)], ["1분", "1분 1초", "59분 59초"])
        self.assertEqual([f(3600), f(3660), f(7325)], ["1시간", "1시간 1분", "2시간 2분"])

    def test_transport_table(self):
        e = appstate.transport_enabled
        self.assertEqual(e("수집 중"), (False, True, True, False))
        self.assertEqual(e("입력 없음"), (False, True, True, False))
        self.assertEqual(e("일시 정지"), (True, False, True, True))
        self.assertEqual(e("중단"), (False, False, True, False))
        self.assertEqual(e("수집 전"), (True, False, True, True))
        self.assertEqual(e("수집 중", ending=True), (False, False, False, False))


class ViewTest(unittest.TestCase):
    def test_pause_line_not_selectable_and_readable(self):
        v = mv.SessionView()
        v.transcript.add_segment(T.seg(1, 1, 2, "앞"))
        v.transcript.add_pause("10:11:25")
        self.assertEqual(v.transcript.pause_lines(), ("일시 정지 10:11:25 ~",))
        v.transcript.close_pause("10:11:25", "10:11:40", 15)
        self.assertEqual(v.transcript.pause_lines(), ("일시 정지 10:11:25 ~ 10:11:40 (15초)",))
        v.transcript.add_segment(T.seg(2, 20, 21, "뒤"))
        v.transcript.selectAll()
        self.assertEqual(v.transcript.selected_numbers(), (1, 2))
        self.assertIn("일시 정지 10:11:25 ~ 10:11:40", v.transcript.toPlainText())


class SessionTest(T.Base):
    def setUp(self):
        T.AUTO_PLAY = False
        self.addCleanup(setattr, T, "AUTO_PLAY", True)
        super().setUp()

    def jsonl(self, kind=None):
        recs = self.records()
        return [r for r in recs if kind is None or r["type"] == kind]

    def test_opens_before_collection(self):
        self.assertTrue(self.start())
        T.pump()
        ctl, v = self.ctl, self.ctl.view
        self.assertEqual(ctl.capture_state(), "수집 전")
        self.assertEqual(self.audio.starts, 0)
        self.assertFalse(v.chip_before.isHidden())
        self.assertTrue(v.chip_paused.isHidden())
        self.assertFalse(v.transcript_guide.isHidden())
        self.assertFalse(v.ai_guide.isHidden())
        self.assertTrue(v.transport.btn_play.isEnabled())
        self.assertFalse(v.transport.btn_pause.isEnabled())
        self.assertTrue(v.transport.btn_stop.isEnabled())
        self.assertTrue(v.transport.btn_play.property("emphasized"))
        self.assertIn("수집 전", ctl.shell.status.text())
        self.assertEqual(ctl.shell.status.level_cells(), 0)
        self.assertIn("수집 전", ctl.menu.status_action.text())
        self.assertTrue(ctl.menu.actions["session.play"].isEnabled())
        self.assertFalse(ctl.menu.actions["session.pause"].isEnabled())

    def test_first_play_starts_source_once(self):
        self.start()
        T.pump()
        ctl, v = self.ctl, self.ctl.view
        self.assertTrue(v.transport.btn_play.isEnabled())
        v.transport.btn_play.click()
        T.pump()
        self.assertEqual(self.audio.starts, 1)
        self.assertEqual(ctl.capture_state(), "수집 중")
        self.assertTrue(v.chip_before.isHidden())
        self.assertTrue(v.transcript_guide.isHidden())
        self.assertFalse(v.ai_guide.isHidden())             # 첫 카드가 생길 때까지 남는다
        self.assertFalse(v.transport.btn_play.isEnabled())
        self.assertTrue(v.transport.btn_pause.isEnabled())

    def test_pause_and_resume_records(self):
        self.start()
        T.pump()
        ctl, v = self.ctl, self.ctl.view
        ctl.play_capture()
        self.assertTrue(ctl.pause_capture())
        T.pump()
        self.assertEqual(ctl.capture_state(), "일시 정지")
        self.assertTrue(self.audio.paused)
        self.assertFalse(v.chip_paused.isHidden())
        self.assertIn("일시 정지", ctl.shell.status.text())
        self.assertEqual([r["state"] for r in self.jsonl("pause")], ["시작"])
        self.assertEqual(len(v.transcript.pause_lines()), 1)
        self.assertTrue(v.transport.btn_play.isEnabled() and v.transport.btn_play.property("emphasized"))
        self.assertFalse(ctl.pause_capture())                  # 일시 정지 중의 [일시 정지] 는 없다
        self.audio.on_state("입력 없음", "늦게 온 알림")          # 일시 정지 중의 수집 알림은 무시한다
        self.assertEqual(ctl.capture_state(), "일시 정지")
        self.assertTrue(ctl.play_capture())
        T.pump()
        self.assertEqual(ctl.capture_state(), "수집 중")
        self.assertEqual(self.audio.starts, 1)
        self.assertEqual(self.audio.resumes, 1)
        self.assertEqual([r["state"] for r in self.jsonl("pause")], ["시작", "끝"])
        self.assertTrue(v.chip_paused.isHidden())
        line = v.transcript.pause_lines()[0]
        self.assertRegex(line, r"^일시 정지 \d\d:\d\d:\d\d ~ \d\d:\d\d:\d\d \(\d+초\)$")
        self.assertFalse((ctl.runtime.folder / "transcript.txt").exists())      # 결정 0196: 일시 정지는 session.jsonl 의 pause 줄로만 남는다
        events = [json.loads(x)["type"] for x in Path(ctl.eventlog.path).read_text(encoding="utf-8").splitlines()] \
            if getattr(ctl.eventlog, "path", None) else []
        if events:
            self.assertIn("capture_pause", events)
            self.assertIn("capture_resume", events)

    def test_resume_failure_clears_pause(self):
        self.start()
        T.pump()
        ctl = self.ctl
        ctl.play_capture()
        ctl.pause_capture()
        self.audio.resume_ok = False
        self.assertFalse(ctl.play_capture())
        T.pump()
        self.assertEqual(ctl.capture_state(), "중단")
        self.assertEqual([r["state"] for r in self.jsonl("pause")], ["시작", "끝"])
        self.assertFalse(ctl.view.transport.btn_play.isEnabled())
        self.assertFalse(ctl.view.transport.btn_pause.isEnabled())
        self.assertTrue(ctl.view.transport.btn_stop.isEnabled())

    def test_end_while_paused_writes_pause_end_before_end(self):
        self.start()
        T.pump()
        ctl = self.ctl
        ctl.play_capture()
        ctl.pause_capture()
        folder = ctl.runtime.folder
        ctl.end_session()
        T.pump()
        recs = [json.loads(x) for x in (folder / "session.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        types = [r["type"] + (":" + r["state"] if r["type"] == "pause" else "") for r in recs]
        self.assertEqual(types[-3:], ["pause:시작", "pause:끝", "end"])

    def test_armed_start_failure(self):
        self.start()
        T.pump()
        ctl = self.ctl
        ctl._run_control(1, json.dumps({"cmd": "audio_start_failed"}))
        self.assertEqual(ctl.capture_state(), "수집 전")
        self.assertFalse(ctl.play_capture())
        T.pump()
        self.assertEqual(ctl.capture_state(), "중단")
        self.assertEqual(self.audio.starts, 0)

    def test_stop_confirm_blocks_main_window_input(self):      # FR-11 ③: 창이 떠 있는 동안 메인 창은 조작할 수 없고 닫으면 다시 된다
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.start()
        T.pump()
        ctl = self.ctl
        ctl.shell.show()
        T.pump()
        play = ctl.view.transport.btn_play
        self.assertEqual(ctl.capture_state(), "수집 전")
        ctl.request_stop()
        d = ctl._stop_dialog
        QTest.mouseClick(play, Qt.MouseButton.LeftButton)
        T.pump()
        self.assertEqual(ctl.capture_state(), "수집 전")          # 눌러도 동작하지 않는다
        QTest.keyClick(ctl.view.input.edit if hasattr(ctl.view.input, "edit") else play, Qt.Key.Key_A)
        d.btn_continue.click()
        T.pump()
        self.assertIsNone(ctl._stop_dialog)
        QTest.mouseClick(play, Qt.MouseButton.LeftButton)
        T.pump()
        self.assertEqual(ctl.capture_state(), "수집 중")          # 창이 닫히면 다시 동작한다

    def test_stop_confirm_texts_and_continue(self):
        self.start()
        T.pump()
        ctl = self.ctl
        ctl.request_stop()
        d = ctl._stop_dialog
        self.assertIsNotNone(d)
        self.assertEqual(d.body.text(), _t("stopc.new30"))       # 수집 전
        self.assertEqual((d.width(), d.height()), (560, 250))
        self.assertFalse(d.isModal())                            # 시트(창 모달)는 ⌘Q · 종료 Apple 이벤트를 막는다(b38 실기)
        d.btn_continue.click()
        T.pump()
        self.assertIsNone(ctl._stop_dialog)
        self.assertEqual(ctl.capture_state(), "수집 전")
        ctl.play_capture()
        ctl.request_stop()
        self.assertEqual(ctl._stop_dialog.body.text(), _t("stopc.new29"))
        ctl._stop_dialog.btn_continue.click()

    def test_quit_request_closes_confirm_and_ends(self):
        self.start()
        T.pump()
        ctl = self.ctl
        ctl.play_capture()
        ctl.request_stop()
        self.assertIsNotNone(ctl._stop_dialog)
        ctl.shell.request_quit()
        T.pump()
        self.assertIsNone(ctl._stop_dialog)
        self.assertIn(ctl.shell.machine.state, (appstate.State.ENDING, appstate.State.DONE))

    def test_menu_has_no_end_edit_items(self):
        titles = [t for t, _ in __import__("nsu_kangs_rab.app.menus", fromlist=["x"]).MENU_SPEC]
        self.assertNotIn(_t("menu.menu_spec_4"), titles)
        ids = [c for _t_, items in __import__("nsu_kangs_rab.app.menus", fromlist=["x"]).MENU_SPEC for c, _l, _s in items]
        self.assertNotIn("session.end", ids)
        self.assertEqual(ids[ids.index("session.rebuild_summary"):][:3], ["session.rebuild_summary", "session.pause", "session.play"])


class QuitRequestTest(T.Base):
    def setUp(self):
        T.AUTO_PLAY = False
        self.addCleanup(setattr, T, "AUTO_PLAY", True)
        super().setUp()

    def post_quit(self):
        from PySide6.QtCore import QEvent
        ev = QEvent(QEvent.Type.Quit)
        T._app.sendEvent(T._app, ev)
        T.pump()
        return ev

    def test_quit_event_with_confirm_open_goes_to_end_flow(self):
        self.start()
        T.pump()
        ctl = self.ctl
        ctl.play_capture()
        ctl.request_stop()
        self.assertIsNotNone(ctl._stop_dialog)
        ev = self.post_quit()
        self.assertFalse(ev.isAccepted())                      # 운영체제의 종료는 취소하고 앱이 스스로 끝낸다
        self.assertIsNone(ctl._stop_dialog)
        self.assertIn(ctl.shell.machine.state, (appstate.State.ENDING, appstate.State.DONE))

    def test_quit_event_before_session_quits_now(self):
        from PySide6.QtCore import QEvent
        self.assertTrue(ctl_before := self.ctl is not None)
        ev = QEvent(QEvent.Type.Quit)
        T._app.sendEvent(T._app, ev)
        T.pump()
        self.assertFalse(ev.isAccepted())
        self.assertTrue(self.ctl._ended)


class QuestionLineTest(T.Base):
    def test_free_query_card_has_question_line(self):
        self.start()
        T.pump()
        ctl = self.ctl
        ctl.play_capture()
        ctl._submit("자유질의", text="첫 줄 <b>태그</b>\n둘째  줄")
        T.pump()
        w = ctl.view.ai._cards.get(1)
        cards = [c for c in ctl.runtime.manager.cards()]
        self.assertEqual(cards[0].question, "첫 줄 <b>태그</b>\n둘째  줄")
        if w is not None:
            self.assertFalse(w.card_question.isHidden())
            html = w.card_question.text()
            self.assertIn("질문", html)
            self.assertIn("&lt;b&gt;태그&lt;/b&gt;", html)
            self.assertIn("<br>", html)
        ctl._submit("고찰")
        ctl._submit("요약")
        self.assertEqual([c.question for c in ctl.runtime.manager.cards()][1:], [None, None])


if __name__ == "__main__":
    unittest.main()
