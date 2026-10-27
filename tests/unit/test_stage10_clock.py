"""단계 10: 세션 시계(결정 0164, AC-FR7-34), 시계 주입(`--dev-clock-file`), claude 경로의 적용 시점(AC-FR1-26)."""
import tempfile
import unittest
from pathlib import Path

import test_app_controller as T
from nsu_kangs_rab.core import claude_locator


class ClockTest(T.Base):
    def setUp(self):
        T.AUTO_PLAY = False
        self.addCleanup(setattr, T, "AUTO_PLAY", True)
        super().setUp()
        self.t = [1000.0]

    def _open(self):
        self.assertTrue(self.start())
        T.pump()
        self.ctl.view.set_clock_source(lambda: self.t[0])
        return self.ctl, self.ctl.view

    def _text(self, v):
        v._tick_clock()
        return v.clock.text()

    def test_before_first_play_is_zero_and_stays(self):
        ctl, v = self._open()
        self.t[0] += 5
        self.assertEqual(self._text(v), "세션 00:00:00")

    def test_counts_only_while_running_and_resumes_from_paused_value(self):
        ctl, v = self._open()
        ctl.play_capture()
        T.pump()
        self.t[0] += 5
        self.assertEqual(self._text(v), "세션 00:00:05")
        self.assertTrue(ctl.pause_capture())
        T.pump()
        self.t[0] += 30
        self.assertEqual(self._text(v), "세션 00:00:05")            # 일시 정지 동안 멈춘다
        ctl.resume_capture() if hasattr(ctl, "resume_capture") else ctl.play_capture()
        T.pump()
        self.t[0] += 3
        self.assertEqual(self._text(v), "세션 00:00:08")            # 멈춘 값에서 이어서 센다

    def test_stops_on_collection_stopped_and_continues(self):
        ctl, v = self._open()
        ctl.play_capture()
        T.pump()
        self.t[0] += 4
        ctl._on_audio_state("중단", "장치 끊김")
        T.pump()
        self.t[0] += 20
        self.assertEqual(self._text(v), "세션 00:00:04")
        ctl._on_audio_state("수집 중", "")
        T.pump()
        self.t[0] += 2
        self.assertEqual(self._text(v), "세션 00:00:06")

    def test_no_input_keeps_counting(self):
        ctl, v = self._open()
        ctl.play_capture()
        T.pump()
        self.t[0] += 3
        ctl._on_audio_state("입력 없음", "")
        T.pump()
        self.t[0] += 12
        ctl._on_audio_state("수집 중", "")
        T.pump()
        self.t[0] += 1
        self.assertEqual(self._text(v), "세션 00:00:16")

    def test_stop_dialog_keeps_counting_and_ending_stops(self):
        ctl, v = self._open()
        ctl.play_capture()
        T.pump()
        self.t[0] += 2
        ctl.request_stop()
        self.t[0] += 3
        self.assertEqual(self._text(v), "세션 00:00:05")            # 확인 창이 떠 있는 동안은 센다
        ctl._finish_quit = lambda: None
        ctl.end_session()
        T.pump()
        self.t[0] += 50
        self.assertEqual(self._text(v), "세션 00:00:05")            # 종료 처리 중에는 멈춘다

    def test_width_and_button_positions_do_not_change(self):
        ctl, v = self._open()
        ctl.play_capture()
        T.pump()
        widths, xs = set(), set()
        for sec in (0, 9, 10, 59, 599, 600, 3599, 35999, 36000):
            self.t[0] = 1000.0 + sec
            v._tick_clock()
            widths.add(v.clock.sizeHint().width())
            xs.add((v.btn_reflect.x(), v.btn_capture.x()))
        self.assertEqual(len(widths), 1)
        self.assertEqual(len(xs), 1)


class ClockFileTest(T.Base):
    def setUp(self):
        T.AUTO_PLAY = False
        self.addCleanup(setattr, T, "AUTO_PLAY", True)
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.clock_file = Path(self._d.name) / "clock.txt"
        self.clock_file.write_text("100.0")
        self.argv = ["--dev-clock-file", str(self.clock_file)]
        super().setUp()

    def test_clock_file_option_feeds_display_only(self):
        ctl = self.ctl
        self.assertTrue(self.start())
        T.pump()
        ctl.play_capture()
        T.pump()
        self.clock_file.write_text("709.0")
        ctl.view._tick_clock()
        self.assertEqual(ctl.view.clock.text(), "세션 00:10:09")
        self.assertFalse([r for r in self.records() if "clock" in str(r)])      # 사건 기록에는 영향이 없다


class ClaudePathTimingTest(T.Base):
    def setUp(self):
        super().setUp()
        self.ctl.deps.find_claude = lambda path, *a, **k: claude_locator.Found(path or "/bin/echo", False, "settings")

    def test_change_during_session_applies_next_session(self):
        self.assertTrue(self.start())
        T.pump()
        ctl = self.ctl
        self.assertEqual(T.FakeModel.instances[-1].config.claude_path, "/bin/echo")
        ctl._on_claude_path("/bin/ls")
        self.assertEqual(ctl.claude_path, "/bin/ls")                     # 설정은 저장한 경로 B 를 가리킨다
        self.assertEqual(ctl._session_claude[0], "/bin/echo")            # 이 세션은 시작 때의 경로 A 를 쓴다
        kw = ctl._make_oneshot(self.tmp.name, "cleanup")
        self.assertEqual(kw._cfg.claude_path, "/bin/echo")               # 정리 문서(일회성 프로세스)도 A
        self.assertEqual(self.ctl.data.get("claude_path"), "/bin/ls")


if __name__ == "__main__":
    unittest.main()
