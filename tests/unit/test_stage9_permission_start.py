"""결정 0161: 세션 시작 때 권한이 "허용되지 않음" 이어도 수집 전 상태를 유지하고 [재생] 을 끄지 않는다."""
import unittest

import test_app_controller as T


class PermissionAtStartTest(T.Base):
    def setUp(self):
        T.AUTO_PLAY = False
        self.addCleanup(setattr, T, "AUTO_PLAY", True)
        super().setUp()

    def _open(self, status, source):
        self.ctl.deps.permission_status = lambda: status
        self.assertTrue(self.start(source=source))
        T.pump()

    def _assert_before_and_play_enabled(self):
        v = self.ctl.view
        self.assertEqual(self.ctl.capture_state(), "수집 전")           # "중단" 이 아니다
        self.assertTrue(v.transport.btn_play.isEnabled())
        self.assertEqual(self.audio.starts, 0)                          # 시작 때는 장치도 보조 프로그램도 열지 않는다
        self.assertFalse([r for r in self.records() if r["type"] == "request" and r.get("kind") == "오류"])

    def test_screen_recording_denied_keeps_before_state(self):
        self._open({"screen_recording": "허용되지 않음", "system_audio": "허용"}, "system_mic")
        self.ctl.deps.permission_status = lambda: {"screen_recording": "허용되지 않음"}
        self.ctl._check_permission_at_start("system_sound", None)
        self._assert_before_and_play_enabled()
        self.assertEqual(self.ctl.permission_hint, "screen_recording")

    def test_microphone_denied_keeps_play_enabled(self):
        self._open({"microphone": "허용되지 않음"}, "system_mic")
        self._assert_before_and_play_enabled()
        self.assertEqual(self.ctl.permission_hint, "microphone")

    def test_allowed_has_no_hint(self):
        self._open({"microphone": "허용", "screen_recording": "허용"}, "system_mic")
        self._assert_before_and_play_enabled()
        self.assertIsNone(self.ctl.permission_hint)

    def test_first_play_starts_source_even_if_denied(self):
        self._open({"microphone": "허용되지 않음"}, "system_mic")
        self.ctl.view.transport.btn_play.click()
        T.pump()
        self.assertEqual(self.audio.starts, 1)                          # 처음 [재생] 에서 소스를 연다

    # ---- 결정 0161: 안내 줄 · 액자 캡처 카드 · 사건 ----
    def _events(self, kind):
        import json
        from pathlib import Path
        rows = [json.loads(x) for x in Path(self.ctl.eventlog.path).read_text(encoding="utf-8").splitlines()]
        return [e for e in rows if e["type"] == kind]

    def _guide(self):
        g = self.ctl.view.transcript_guide_permission
        return g.text() if not g.isHidden() else ""

    def test_guide_line_screen_and_event(self):
        self._open({"screen_recording": "허용되지 않음"}, "system_mic")
        self.ctl.deps.permission_status = lambda: {"screen_recording": "허용되지 않음"}
        self.ctl._check_permission_at_start("system_sound", None)
        self.assertEqual(self._guide(), "[재생] 을 누르면 운영체제가 화면 기록 권한을 물을 수 있습니다.")
        ev = self._events("permission_guide")
        self.assertEqual([(e["permission"], e["check"]) for e in ev][-1], ("screen_recording", "denied"))

    def test_guide_line_microphone(self):
        self._open({"microphone": "허용되지 않음"}, "system_mic")
        self.assertIn("마이크 권한이 허용되지 않았습니다", self._guide())
        self.assertEqual(self._events("permission_guide")[-1]["permission"], "microphone")

    def test_no_guide_when_allowed(self):
        self._open({"microphone": "허용", "screen_recording": "허용"}, "system_mic")
        self.assertEqual(self._guide(), "")
        self.assertEqual(self._events("permission_guide"), [])

    def test_no_guide_when_not_determined(self):
        self._open({"microphone": "묻지 않음"}, "system_mic")
        self.assertEqual(self._guide(), "")
        self.assertEqual(self._events("permission_guide"), [])

    def test_capture_card_before_first_play_has_new45_and_event(self):
        self._open({"screen_recording": "허용되지 않음"}, "system_mic")
        self.ctl._permission_values = lambda: {"screen_recording": "허용되지 않음"}
        self.ctl.capture_frame()
        T.pump()
        texts = [w.error.text() for w in self.ctl.view.ai._cards.values()]
        self.assertTrue(any("운영체제가 화면 기록 권한을 물을 수 있습니다" in x for x in texts))
        e = self._events("permission_card")[-1]
        self.assertEqual((e["permission"], e["source"], e["guided"]), ("screen_recording", "capture", True))

    def test_capture_card_after_first_play_has_no_new45(self):
        self._open({"screen_recording": "허용되지 않음"}, "system_mic")
        self.ctl.view.transport.btn_play.click()
        T.pump()
        self.ctl._permission_values = lambda: {"screen_recording": "허용되지 않음"}
        self.ctl.capture_frame()
        T.pump()
        e = self._events("permission_card")[-1]
        self.assertEqual((e["source"], e["guided"]), ("capture", False))
        texts = [w.error.text() for w in self.ctl.view.ai._cards.values()]
        self.assertFalse(any("물을 수 있다" in x for x in texts))

    def test_no_permission_from_helper_posts_play_event(self):
        from nsu_kangs_rab.platform.audio.system_sound import REASON_TEXT
        self._open({"microphone": "허용"}, "system_mic")
        self.ctl.view.transport.btn_play.click()
        T.pump()
        self.ctl._attempt_pending = False                               # 첫 음성 블록 뒤의 권한 회수는 옛 처리이다(결정 0178 6항)
        self.ctl._on_audio_state("중단", REASON_TEXT["no_permission"])
        T.pump()
        e = self._events("permission_card")[-1]
        self.assertEqual((e["permission"], e["source"], e["guided"]), ("microphone", "play", False))


if __name__ == "__main__":
    unittest.main()
