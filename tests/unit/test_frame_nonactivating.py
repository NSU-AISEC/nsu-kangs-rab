"""액자를 앱을 활성화하지 않는 패널로 만드는 부분(결정 0112, FR-12, AC-FR12-20 의 구현 연결점).
offscreen 에서는 네이티브 창이 없으므로 헬퍼가 아무것도 하지 않는 것(no-op)과 연결점(창 형식 · 이벤트 로그 · 개발 옵션 ·
`frame_query` 의 도움말 항목)만 확인한다. 실제 동작은 화면 실기(tester)가 확인한다."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nsu_kangs_rab.app import controller as C  # noqa: E402
from nsu_kangs_rab.app import frame as F  # noqa: E402
from nsu_kangs_rab.core import appstate, claude_locator, devopts  # noqa: E402
from nsu_kangs_rab.platform import nswindow  # noqa: E402


def _fake_stt():
    return [sys.executable, str(ROOT / "tests" / "unit" / "media" / "fakes" / "fake_stt_speech.py")], []

_app = QApplication.instance() or QApplication([])
_app.setQuitOnLastWindowClosed(False)


def pump():
    for _ in range(4):
        _app.processEvents()
        QCoreApplication.sendPostedEvents(None, 0)


class NswindowTest(unittest.TestCase):
    def test_noop_when_not_cocoa(self):
        w = F.FrameWindow()
        self.addCleanup(w.deleteLater)
        info = nswindow.make_nonactivating(w, pretend_missing=False)
        self.assertEqual(info["native"], False)
        self.assertEqual((info["is_panel"], info["has_method"], info["applied"], info["pretended"]), (False, False, False, False))
        self.assertTrue(nswindow.make_nonactivating(w, pretend_missing=True)["pretended"])

    def test_background_cursor_noop_when_not_cocoa(self):                 # D-145
        self.assertFalse(nswindow.allow_background_cursor())

    def test_constants(self):
        self.assertEqual(nswindow.NONACTIVATING_PANEL, 128)
        self.assertEqual(nswindow.PREVENTS_ACTIVATION, b"_setPreventsActivation:")


class FrameWindowTest(unittest.TestCase):
    def setUp(self):
        self.w = F.FrameWindow()
        self.addCleanup(self.w.deleteLater)

    def test_panel_form_and_attributes(self):
        self.assertTrue(self.w.windowFlags() & Qt.Tool)
        self.assertTrue(self.w.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(self.w.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(self.w.testAttribute(Qt.WA_MacAlwaysShowToolWindow))
        self.assertTrue(self.w.testAttribute(Qt.WA_AlwaysShowToolTips))

    def test_native_created_callback_on_show(self):
        got = []
        self.w.on_native_created = got.append
        self.w.pretend_method_missing = True
        self.w.show()
        pump()
        self.addCleanup(self.w.hide)
        self.assertGreaterEqual(len(got), 1)
        self.assertEqual(got[0]["native"], False)
        self.assertEqual(got[0]["pretended"], True)
        self.assertEqual(self.w.native_info, got[-1])

    def test_poll_runs_only_while_shown(self):                            # D-145
        self.w.show()
        pump()
        self.assertTrue(self.w._poll.isActive())
        self.assertEqual(self.w._poll.interval(), F.POLL_MS)
        self.w.hide()
        pump()
        self.assertFalse(self.w._poll.isActive())

    def test_poll_sets_cursor_and_delayed_tooltip(self):                  # D-145
        from unittest import mock
        self.w.setGeometry(100, 100, 400, 300)
        self.w.show()
        pump()
        hp = self.w.handle_rects()[F.MOVE].center()
        gp = self.w.mapToGlobal(hp)
        clock = [1000.0]
        with mock.patch.object(F, "QCursor") as qc, mock.patch.object(F.time, "monotonic", lambda: clock[0]), \
                mock.patch.object(F.QToolTip, "showText") as show, mock.patch.object(F.QToolTip, "hideText"):
            qc.pos.return_value = gp
            self.w._poll_tick()
            self.assertEqual(self.w.cursor().shape(), Qt.OpenHandCursor)
            show.assert_not_called()                                      # 머문 시간이 모자라면 띄우지 않는다
            clock[0] += F.TIP_DELAY_S + 0.01
            self.w._poll_tick()
            self.assertEqual(show.call_count, 1)
            self.assertEqual(show.call_args[0][1], F.TIPS[F.MOVE])
            self.w._poll_tick()
            self.assertEqual(show.call_count, 1)                          # 같은 손잡이 위에서는 한 번만 띄운다

    def test_poll_ignores_pointer_outside_clickable_region(self):         # D-145: 안쪽은 아래 앱의 영역이다
        from unittest import mock
        self.w.setGeometry(100, 100, 400, 300)
        self.w.show()
        pump()
        center = self.w.mapToGlobal(self.w.rect().center())
        with mock.patch.object(F, "QCursor") as qc, mock.patch.object(self.w, "_hover") as hov:
            qc.pos.return_value = center
            for _ in range(5):
                self.w._poll_tick()
            hov.assert_not_called()

    def test_poll_hover_on_change_and_reapply_cursor(self):                       # D-145
        from unittest import mock
        self.w.setGeometry(100, 100, 400, 300)
        self.w.show()
        pump()
        gp = self.w.mapToGlobal(self.w.handle_rects()[F.MOVE].center())
        with mock.patch.object(F, "QCursor") as qc, mock.patch.object(self.w, "_hover") as hov, \
                mock.patch.object(F.nswindow, "apply_cursor") as ap:
            qc.pos.return_value = gp
            for _ in range(5):
                self.w._poll_tick()
            self.assertEqual(hov.call_count, 1)                           # 손잡이 판정 · 도움말 시간은 바뀔 때만
            self.assertEqual(ap.call_count, 4)                            # 맨 앞 앱이 되돌린 커서를 영역 안에서 매 주기 다시 적용(D-145)

    def test_hover_does_not_reset_cursor_while_pressed(self):             # D-145: 누른 동안 들어옴 사건이 쥔 손을 열린 손으로 되돌리면 안 된다
        self.w.setGeometry(100, 100, 400, 300)
        self.w.show()
        pump()
        mv = self.w.handle_rects()[F.MOVE].center()
        self.w._mode = F.MOVE
        self.w.setCursor(Qt.ClosedHandCursor)
        self.w._hover(mv)
        self.assertEqual(self.w.cursor().shape(), Qt.ClosedHandCursor)
        self.w._mode = None
        self.w._hover(mv)
        self.assertEqual(self.w.cursor().shape(), Qt.OpenHandCursor)

    def test_poll_idle_while_dragging(self):                              # D-145
        from unittest import mock
        self.w.show()
        pump()
        self.w._mode = F.MOVE
        with mock.patch.object(F, "QCursor") as qc, mock.patch.object(F.nswindow, "apply_cursor") as ap:
            self.w._poll_tick()
            qc.pos.assert_not_called()                                    # 끌기 중에는 손잡이를 다시 정하지 않고 커서만 다시 적용한다
            ap.assert_called_once()
        self.w._mode = None

    def test_tooltip_state_hidden(self):
        self.assertEqual(self.w.tooltip_state(), {"visible": False, "label": ""})

    def test_tooltip_label_survives_event_log(self):                     # D-146
        from nsu_kangs_rab.core import eventlog
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        lg = eventlog.EventLog(td.name)
        lg.emit("frame_query", tooltip={"visible": True, "label": "액자 옮기기"})
        lg.close()
        rec = json.loads(Path(lg.path).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["tooltip"], {"visible": True, "label": "액자 옮기기"})
        self.assertNotIn("dropped_fields", rec)

    def test_tooltip_texts_unchanged(self):
        self.assertEqual(set(F.TIPS.values()), {"액자 옮기기", "액자 크기 바꾸기", "액자 숨기기"})


class DevOptionTest(unittest.TestCase):
    def test_option_parse(self):
        o = devopts.parse(["--dev-frame-method-missing", "on"])
        self.assertEqual(o.get("frame_method_missing"), "on")
        self.assertEqual(o.errors, [])
        self.assertTrue(devopts.parse(["--dev-frame-method-missing", "x"]).errors)
        self.assertIsNone(devopts.parse([]).get("frame_method_missing"))


class ControllerTest(unittest.TestCase):
    def make(self, argv):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Path(self.tmp.name) / "cfg"
        self.cfg.mkdir()
        (self.cfg / "settings.json").write_text(json.dumps({"first_run_ack": appstate.FIRST_RUN_NOTICE_VERSION}))
        deps = C.Deps(environ={"PATH": ""}, stt_helper=_fake_stt,
                      find_claude=lambda *a, **k: claude_locator.Found("/bin/echo", False, "settings"))
        c = C.AppController(_app, ["--dev-config-dir", str(self.cfg)] + list(argv), deps)
        pump()
        self.addCleanup(self._cleanup, c)
        return c

    def _cleanup(self, c):
        c.shutdown()
        c.shell.deleteLater()
        for w in _app.topLevelWidgets():
            w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def events(self, c):
        return [json.loads(x) for x in Path(c.eventlog.path).read_text(encoding="utf-8").splitlines()]

    def test_event_and_query(self):
        c = self.make(["--dev-frame-method-missing", "on"])
        self.assertTrue(c.frame.pretend_method_missing)
        c.frame.show()
        pump()
        ctl = self.cfg / "control.jsonl"
        c.dev.values["control"] = str(ctl)
        ctl.write_text(json.dumps({"cmd": "frame_query"}) + "\n", encoding="utf-8")
        c._poll_control()
        ev = self.events(c)
        made = [e for e in ev if e["type"] == "frame_window_created"]
        self.assertTrue(made)
        self.assertEqual(set(made[-1]) & {"native", "window_class", "is_panel", "has_method", "applied", "pretended"},
                         {"native", "window_class", "is_panel", "has_method", "applied", "pretended"})
        self.assertTrue(made[-1]["pretended"])
        q = [e for e in ev if e["type"] == "frame_query"][-1]
        self.assertIs(q["tooltip"]["visible"], False)                    # 빈 글은 이벤트 로그가 생략한다
        self.assertEqual(q["tooltip"].get("label", ""), "")
        self.assertNotIn("dropped_fields", q)                            # D-146: `text` 이름이면 지워졌다

    def test_default_not_pretended(self):
        c = self.make([])
        self.assertFalse(c.frame.pretend_method_missing)


if __name__ == "__main__":
    unittest.main()
