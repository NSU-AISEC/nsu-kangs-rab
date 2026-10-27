"""D-162 · D-163: [고찰] 단추의 도움말 키 표시는 키캡과 같은 표기(keyspec.display)이고, 되돌린 키를 따른다."""
import json
import unittest

from test_app_controller import Base, C, _app  # noqa: F401  (같은 조립 도구)
from nsu_kangs_rab.app import keyspec


class KeyDisplayTest(Base):
    def test_button_uses_keycap_display(self):                      # D-162
        self.ctl.data["trigger_key"] = "Ctrl+K"
        self.ctl._refresh_request_keys()
        self.assertEqual(self.ctl.view.btn_reflect.text(), keyspec.display("Ctrl+K"))
        self.assertIn("⌘K", self.ctl.view.btn_reflect.text())
        self.ctl.data["trigger_key"] = "PgDown"
        self.ctl._refresh_request_keys()
        self.assertEqual(self.ctl.view.btn_reflect.text(), keyspec.display("PgDown"))
        self.assertNotIn("PgDown", self.ctl.view.btn_reflect.text())


class IgnoredReflectInputTest(Base):
    def test_ignored_slash_reflect_clears_input(self):             # 결정 0157 3항: 무시한 /고찰 의 입력창 글은 지운다
        self.assertTrue(self.start())
        bar = self.ctl.view.input
        for text in ("/고찰", "/reflect"):
            bar.edit.setText(text)
            bar.edit.returnPressed.emit()
            self.assertEqual(bar.edit.text(), text and "")


class SanitizedKeyTest(Base):
    def setUp(self):
        super().setUp()

    def test_reset_key_shown_as_default(self):                      # D-163: 수식 키 없는 A 는 F2 로 되돌고 단추도 F2
        self.assertEqual(self.ctl.view.btn_reflect.text(), "F2")


class SanitizedStartTest(unittest.TestCase):
    def test_start_with_bad_saved_key(self):
        import tempfile
        from pathlib import Path
        import test_app_controller as T
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "cfg"
            cfg.mkdir()
            from nsu_kangs_rab.core import appstate
            (cfg / "settings.json").write_text(json.dumps({"first_run_ack": appstate.FIRST_RUN_NOTICE_VERSION, "trigger_key": "A"}))
            keys, audio = T.FakeKeys(), T.FakeAudio()
            deps = C.Deps(environ={"PATH": ""}, find_claude=lambda *a, **k: T.claude_locator.Found("/bin/echo", False, "settings"),
                          key_store_factory=lambda a: keys, model_factory=T.FakeModel, stt_helper=T.fake_stt_helper,
                          mic_factory=lambda log: audio, open_url=lambda u: True, capture_runner=lambda c, t: (1, ""))
            ctl = C.AppController(T._app, ["--dev-config-dir", str(cfg)], deps)
            try:
                self.assertEqual(ctl.view.btn_reflect.text(), "F2")
                self.assertEqual(ctl.menu.actions["request.trigger"].shortcut().toString(), "F2")
            finally:
                ctl.shutdown()
                ctl.shell.deleteLater()


if __name__ == "__main__":
    unittest.main()
