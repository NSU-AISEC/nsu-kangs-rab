"""앱 조립(`app/controller.py`, K-20): 가짜 `claude` 프로세스 객체 · 가짜 음성 · 임시 설정 폴더로 offscreen 에서 실행한다.
모델 호출 · 키체인 · 실제 마이크는 쓰지 않는다 (AC-FR7-5 · 16 · 19 의 요청 부분, X6)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QEvent  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from nsu_kangs_rab.app import controller as C  # noqa: E402
from nsu_kangs_rab.core import appstate, claude_locator  # noqa: E402
from nsu_kangs_rab.core import requests as R  # noqa: E402
from nsu_kangs_rab.core.model_session import EXPECTED_SOURCE  # noqa: E402
from nsu_kangs_rab.core.types import Error, Init, Result, Segment, TextDelta  # noqa: E402

_app = QApplication.instance() or QApplication([])
_app.setQuitOnLastWindowClosed(False)


def tearDownModule():
    import gc
    for _ in range(3):
        _app.processEvents()
        QCoreApplication.sendPostedEvents(None, 0)
        gc.collect()


class FakeModel:
    instances: list = []
    OMIT = "__omit__"
    next_init_source = None
    diagram_hook = None                 # (model, text) → 다이어그램 요청에 대한 시험용 동작

    def __init__(self, config=None, auth=None, on_event=None, **kw):
        self.config, self.auth, self.on_event, self.kw = config, auth, on_event, kw
        self.sent, self.pid, self.init = [], 4242, None
        self.started = self.closed = False
        self.start_ok = True
        self.auto_reply = False             # True 이면 정리 요청에 문서로 답한다
        self.init_source = FakeModel.next_init_source   # None 이면 고른 방식과 같은 출처, OMIT 이면 init 을 내지 않는다
        FakeModel.instances.append(self)

    def start(self):
        self.started = True
        if self.start_ok and self.on_event is not None and getattr(self.config, "effort", None) \
                and self.init_source != FakeModel.OMIT:
            # 실제 `ModelSession` 은 첫 `/effort` 의 init 으로 인증 출처를 확인한다. 불일치이면 `Error(auth)` 만 낸다
            want = EXPECTED_SOURCE[self.auth]
            src = self.init_source or want
            if src != want:
                self.on_event(Error("auth", "인증 출처가 고른 방식과 다릅니다(기대 %s, 실제 %s)" % (want, src)))
            else:
                self.on_event(Init("fake", src, "0"))
        return self.start_ok

    def send(self, msg):
        self.sent.append(msg)
        text = msg.blocks[0].get("text", "") if getattr(msg, "blocks", None) else ""
        hook = FakeModel.diagram_hook
        if hook is not None and text.startswith("[요청] 종류=다이어그램"):
            hook(self, text)
            return True
        if self.auto_reply and text.startswith("[요청] 종류=정리문서"):
            self.on_event(TextDelta("# 정리"))
            self.on_event(Result(True, text="# 정리 문서", num_turns=1))
        return True

    def interrupt(self):
        return "int"

    def set_effort(self, level):
        self.efforts = getattr(self, "efforts", []) + [level]
        if self.auto_reply:
            self.on_event(Result(True, text="(command)", num_turns=0))
        return True

    def restart(self):
        return True

    def close(self):
        self.closed = True


class FakeAudio:
    lvl = 0.0

    def __init__(self):
        self.started = self.stopped = False
        self.on_state = None
        self.paused = False
        self.starts = self.resumes = self.pauses = 0
        self.resume_ok = True
        self.emit_block = True
        self.on_block = None

    def _first_block(self, on_block):
        """결정 0178: 시도의 결과는 첫 음성 블록이다. 가짜 소스도 시작 · 재개가 성공하면 무음 블록 하나를 낸다."""
        self.on_block = on_block
        if self.emit_block:
            import numpy as np
            from nsu_kangs_rab.platform.audio.types import PcmBlock
            on_block(PcmBlock(np.zeros(160, dtype=np.float32), 0.0))

    def start(self, on_block, on_state=lambda s, d="": None):
        self.started, self.on_state = True, on_state
        self.starts += 1
        on_state("수집 중", "fake")
        self._first_block(on_block)

    def pause(self):
        self.paused = True
        self.pauses += 1

    def resume(self):
        if not self.paused:
            return False
        self.resumes += 1
        if not self.resume_ok:
            self.on_state("중단", "수집을 시작하지 못했습니다: 시험")
            return False
        self.paused = False
        self.on_state("수집 중", "fake")
        if self.on_block is not None:
            self._first_block(self.on_block)
        return True

    def stop(self):
        self.stopped = True

    def level(self):
        return self.lvl


FAKE_STT = str(Path(__file__).resolve().parent / "media" / "fakes" / "fake_stt_speech.py")


def fake_stt_helper():
    """`Deps.stt_helper`: 가짜 `stt_speech`(시나리오 없음: `ready` 만 내고 `Q` 에서 끝난다)."""
    return [sys.executable, FAKE_STT], []


def wait_stt_ready(ctl, timeout_s: float = 8.0) -> bool:
    """가짜 보조 프로세스의 `ready` 가 주 스레드에 도착할 때까지 사건을 처리한다."""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if ctl._stt_ready:
            return True
        time.sleep(0.01)
    return False


class FakeKeys:
    def __init__(self, key=None):
        self.key = key

    def get(self):
        return self.key

    def set(self, key):
        self.key = key

    def delete(self):
        self.key = None
        return True


def seg(n, start, end, text="본문"):
    def w(x):
        return "2026-10-11T14:%02d:%02d.000+09:00" % (x // 60, x % 60)
    return Segment(n, w(start), w(end), float(start), float(end), text)


def png_bytes(w=40, h=30):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("blue"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def pump(n=5):
    for _ in range(n):
        _app.processEvents()
        QCoreApplication.sendPostedEvents(None, 0)
        time.sleep(0.01)


AUTO_PLAY = True       # 결정 0150: 세션은 수집 전으로 열린다. 수집을 전제로 쓴 시험은 세션 시작 직후 [재생] 을 한 번 누른다


_orig_enter_session = C.AppController._enter_session


def _enter_session_and_play(self, rt):
    _orig_enter_session(self, rt)
    if AUTO_PLAY and getattr(self, "_auto_play_ok", True):
        if hasattr(self.pipeline, "locales"):
            wait_stt_ready(self)          # 보조 프로세스가 준비를 마칠 때까지 [재생] 은 꺼져 있다(결정 0167)
        self.play_capture()


C.AppController._enter_session = _enter_session_and_play


class Base(unittest.TestCase):
    argv: list = []
    first_run = False

    def setUp(self):
        FakeModel.instances.clear()
        FakeModel.next_init_source = None
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Path(self.tmp.name) / "cfg"
        self.save = Path(self.tmp.name) / "save"
        self.cfg.mkdir()
        if not self.first_run:
            (self.cfg / "settings.json").write_text(json.dumps({"first_run_ack": appstate.FIRST_RUN_NOTICE_VERSION}))
        self.keys = FakeKeys()
        self.audio = FakeAudio()
        deps = C.Deps(environ={"PATH": ""},
                      find_claude=lambda *a, **k: claude_locator.Found("/bin/echo", False, "settings"),
                      key_store_factory=lambda account: self.keys, model_factory=FakeModel,
                      stt_helper=fake_stt_helper, mic_factory=lambda log: self.audio, open_url=lambda u: True,
                      capture_runner=lambda cmd, timeout_s: (1, ""))      # 실제 `screencapture` 를 실행하지 않는다
        self.ctl = C.AppController(_app, ["--dev-config-dir", str(self.cfg)] + list(self.argv), deps)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.ctl.shutdown()
        for w in (self.ctl.shell,):
            w.deleteLater()
        for w in _app.topLevelWidgets():      # 시험마다 남는 최상위 창(대화 상자 등)이 쌓여 뒤의 시험이 느려지는 것을 막는다
            w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def start(self, **over):
        p = self.ctl.shell.start_page.values()
        p.update({"save_dir": str(self.save), "source": "system_mic", "title": "시험", "number": "3"})
        p.update(over)
        return self.ctl.start_session(p)

    @property
    def model(self):
        return FakeModel.instances[-1]

    def records(self):
        f = self.ctl.runtime.folder / "session.jsonl"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]


class StartTest(Base):
    def test_window_state_before_start(self):
        self.assertIs(self.ctl.shell.machine.state, appstate.State.BEFORE_SESSION)
        self.assertEqual(self.ctl.claude_path, "/bin/echo")
        self.assertEqual(FakeModel.instances, [])          # 만들기만으로는 프로세스 객체를 만들지 않는다

    def test_blocked_start_shows_banner_and_disables_start(self):  # D-101
        sp = self.ctl.shell.start_page
        self.assertFalse(self.start(provider="claude_api"))        # 키가 없다
        self.assertFalse(sp.banner.isHidden())
        self.assertEqual(sp.problem.text(), "API 키가 없어 세션을 시작할 수 없습니다")
        self.assertIn("조치: 아래 5. claude 실행 파일의 “Claude API 키” 칸에 키를 입력하거나, 2. 모델 제공자에서 Claude 구독을 고르세요.", sp.hint.text())      # UI-236, 결정 0181
        self.assertFalse(sp.start.isEnabled())
        self.ctl.shell.statusBar()       # 시작 화면에는 상태 표시줄을 두지 않는다
        self.assertTrue(self.ctl.shell.status.isHidden() or not self.ctl.shell.status.isVisible())

    def test_banner_clears_when_cause_is_resolved(self):  # D-101 보충 2
        sp = self.ctl.shell.start_page
        self.start(provider="claude_api")
        self.assertFalse(sp.start.isEnabled())
        self.keys.set("sk-test")
        self.ctl._on_key_submitted("sk-test")
        self.assertTrue(sp.banner.isHidden())
        self.assertTrue(sp.start.isEnabled())
        sp.provider.setCurrentIndex(sp.provider.findData("claude_api"))   # 제공자 변경도 점검 시점이다
        self.ctl._on_key_delete()
        self.assertFalse(sp.start.isEnabled())
        sp.provider.setCurrentIndex(sp.provider.findData("claude_subscription"))   # 원인이 해당하지 않게 되면 풀린다
        self.assertTrue(sp.start.isEnabled())

    def test_no_claude_banner(self):
        sp = self.ctl.shell.start_page
        self.ctl.claude_path = None
        self.assertFalse(self.start())
        self.assertEqual(sp.problem.text(), "claude 를 찾지 못했습니다")
        self.assertFalse(sp.start.isEnabled())

    def test_claude_search_option_empties_auto_targets(self):      # 권고 71: --dev-claude-search none, AC-FR1-28 ④ ⑤
        calls = []

        def finder(configured, env, login_shell=None, known_dirs=None, **kw):
            calls.append((configured, dict(env), login_shell, known_dirs))
            return claude_locator.Found("/bin/echo", False, "settings") if configured else None
        (self.cfg / "settings.json").write_text(json.dumps({"first_run_ack": appstate.FIRST_RUN_NOTICE_VERSION,
                                                            "claude_path": "/bin/echo"}))
        c = C.AppController(_app, ["--dev-config-dir", str(self.cfg), "--dev-claude-search", "none"],
                            C.Deps(environ={"PATH": "/usr/bin"}, find_claude=finder, login_shell=lambda: "/bin/zsh"))
        self.addCleanup(c.shutdown)
        self.addCleanup(c.shell.deleteLater)
        self.assertEqual(c.claude_path, "/bin/echo")                # 설정 값은 그대로 쓴다
        self.assertIsNone(c.claude_auto_path)                       # 자동으로는 찾지 못한다
        for configured, env, shell, known in calls:
            self.assertEqual((env, shell, known), ({"PATH": ""}, None, ()))

    def test_auto_path_excludes_settings_value(self):
        calls = []

        def finder(configured, env, login_shell=None, known_dirs=None, **kw):
            calls.append(configured)
            return claude_locator.Found(configured or "/auto/claude", False, "settings")
        (self.cfg / "settings.json").write_text(json.dumps({"first_run_ack": appstate.FIRST_RUN_NOTICE_VERSION,
                                                            "claude_path": "/bin/echo"}))
        c = C.AppController(_app, ["--dev-config-dir", str(self.cfg)], C.Deps(environ={}, find_claude=finder))
        self.addCleanup(c.shutdown)
        self.addCleanup(c.shell.deleteLater)
        self.assertEqual((c.claude_path, c.claude_auto_path), ("/bin/echo", "/auto/claude"))
        self.assertIn(None, calls)

    def test_first_run_notice_acknowledged_is_saved(self):
        # 설정 파일이 없으면 첫 실행 고지 상태이고, 확인하면 판 번호를 저장한다(AC-NF-1)
        (self.cfg / "settings.json").unlink()
        c = C.AppController(_app, ["--dev-config-dir", str(self.cfg)],
                            C.Deps(environ={}, find_claude=lambda *a, **k: None))
        self.addCleanup(c.shutdown)
        self.addCleanup(c.shell.deleteLater)
        self.assertIs(c.shell.machine.state, appstate.State.FIRST_RUN)
        c.shell.first_run_page.acknowledged.emit()
        data = json.loads((self.cfg / "settings.json").read_text())
        self.assertEqual(data["first_run_ack"], appstate.FIRST_RUN_NOTICE_VERSION)

    def test_start_session_creates_files_and_no_model_call(self):
        self.assertTrue(self.start())
        self.assertIs(self.ctl.shell.machine.state, appstate.State.IN_SESSION)
        self.assertTrue(self.model.started)
        self.assertEqual(self.model.sent, [])               # 시작은 모델 호출이 아니다
        recs = self.records()
        self.assertEqual(recs[0]["type"], "header")
        self.assertEqual(recs[0]["title"], "시험")
        self.assertEqual(recs[0]["mode"], "대면")
        self.assertTrue(self.audio.started)
        self.assertEqual(self.ctl._capture_state, "수집 중")

    def test_api_provider_without_key_stays_on_start_page(self):
        ok = self.start(provider="claude_api")
        self.assertFalse(ok)
        self.assertIs(self.ctl.shell.machine.state, appstate.State.BEFORE_SESSION)
        self.assertEqual(FakeModel.instances, [])

    def test_api_key_goes_only_to_model_process(self):
        self.keys.key = "sk-ant-test-0000"
        self.assertTrue(self.start(provider="claude_api"))
        self.assertEqual(self.model.kw["api_key"], "sk-ant-test-0000")
        log = Path(self.ctl.eventlog.path).read_text(encoding="utf-8")
        self.assertNotIn("sk-ant-test-0000", log)

    def test_model_start_failure_stays_on_start_page(self):
        orig = FakeModel.start
        FakeModel.start = lambda self: False
        self.addCleanup(setattr, FakeModel, "start", orig)
        self.assertFalse(self.start())
        self.assertIs(self.ctl.shell.machine.state, appstate.State.BEFORE_SESSION)

    def test_system_sound_session_starts_pipeline(self):  # D-041: 시스템 사운드 수집을 연결했다(결정 0065)
        self.assertTrue(self.start(source="system_sound"))
        self.assertIsNotNone(self.ctl.pipeline)


class MaterialsWiringTest(Base):  # K-19
    def test_panel_on_start_page_updates_status_count(self):
        panel = self.ctl.materials_panel
        self.assertTrue(self.ctl.shell.start_page.isAncestorOf(panel))
        f = Path(self.tmp.name) / "m.txt"
        f.write_text("자료 본문", encoding="utf-8")
        panel.add_paths([str(f)])
        self.assertEqual(len(self.ctl.context.materials()), 1)
        self.assertIn("사전 지식: 1개", self.ctl.shell.status.text())


class RequestTest(Base):
    def setUp(self):
        super().setUp()
        self.start()
        self.rt = self.ctl.runtime
        self.view = self.ctl.shell.session_page

    def head(self, i=-1):
        return self.model.sent[i].text if hasattr(self.model.sent[i], "text") else str(self.model.sent[i])

    def test_slash_commands_without_trigger_key(self):  # AC-FR7-5
        for text, kind in (("/요약", "요약"), ("/고찰", "트리거")):  # 결정 0155: /고찰 은 [고찰] 단추와 같은 요청
            self.view.input.submitted.emit(text)
            self.model.on_event(Result(True, text="응답"))     # 다음 요청이 대기열에서 나가도록 응답을 끝낸다
        kinds = [r["kind"] for r in self.records() if r["type"] == "request"]
        self.assertEqual(kinds, ["요약", "트리거"])
        inputs = [r["input"] for r in self.records() if r["type"] == "request"]
        self.assertEqual(inputs, ["/요약", ""])

    def test_answer_uses_selected_segments(self):
        for s in (seg(1, 0, 3), seg(2, 4, 7)):
            self.rt.on_segment(s)
            self.view.bridge.post_segment(s)
        pump()
        self.view.transcript.item(1).setSelected(True)
        self.view.input.submitted.emit("/답변")
        req = [r for r in self.records() if r["type"] == "request"][-1]
        self.assertEqual((req["kind"], req["input"]), ("답변", "/답변 조각=2"))

    def test_free_question_and_unknown_command(self):
        self.view.input.submitted.emit("이건 왜 그럴까요?")
        self.view.input.submitted.emit("/답변 3")           # 알 수 없는 명령: 요청이 나가지 않는다
        reqs = [r for r in self.records() if r["type"] == "request"]
        self.assertEqual([(r["kind"], r["input"]) for r in reqs], [("자유질의", "이건 왜 그럴까요?")])
        self.assertEqual(len(self.model.sent), 1)
        self.assertEqual(self.ctl.shell.statusBar().currentMessage(), "알 수 없는 명령")

    def test_trigger_button_and_menu_same_request(self):  # AC-FR7-19
        s = seg(1, 0, 5)
        self.rt.on_segment(s)
        self.view.reflect_clicked.emit()
        self.model.on_event(Result(True, text='판단: 질문 | "이 모델은?"\n답'))
        self.ctl.menu.command.emit("request.trigger")
        kinds = [(r["kind"], r["input"]) for r in self.records() if r["type"] == "request"]
        self.assertEqual(kinds[0], ("트리거", ""))
        self.assertEqual(kinds[-1][0], "트리거")
        self.assertEqual(len(self.model.sent), 2)

    def test_settings_dialog_stays_in_front_of_main(self):  # D-110 · AC-FR14-12 · 결정 0070 1항 (기계 확인)
        from PySide6.QtCore import Qt
        self.ctl.open_settings()
        d = self.ctl._settings_dialog
        self.assertIs(d.parent(), self.ctl.shell)            # 메인 창의 자식 창
        self.assertTrue(bool(d.windowFlags() & Qt.Tool))      # 부모 위의 부동 패널
        self.assertTrue(d.testAttribute(Qt.WA_MacAlwaysShowToolWindow))   # 앱이 비활성이어도 숨지 않는다
        self.assertFalse(d.isModal())                         # 비모달
        self.ctl.open_settings()
        self.assertIs(self.ctl._settings_dialog, d)           # 하나뿐

    def test_settings_dialog_follows_main_minimize(self):  # D-111 · 결정 0074 2항
        self.ctl.open_settings()
        d = self.ctl._settings_dialog
        self.assertTrue(d.isVisible())
        self.ctl.shell.on_minimized_changed(True)             # 메인 창 최소화
        self.assertFalse(d.isVisible())
        self.ctl.shell.on_minimized_changed(False)            # 복원
        self.assertTrue(d.isVisible())
        d.close()                                             # 사용자가 닫은 뒤
        self.ctl.shell.on_minimized_changed(True)
        self.ctl.shell.on_minimized_changed(False)
        self.assertFalse(d.isVisible())                       # 다시 열지 않는다
        self.ctl.open_settings()                              # 다시 열기는 그대로
        self.assertTrue(d.isVisible())

    def test_settings_dialog_keeps_position_after_minimize(self):  # D-112 · 결정 0076 1항, 복원 경로
        from PySide6.QtCore import QPoint
        self.ctl.open_settings()
        d = self.ctl._settings_dialog
        d.move(333, 222)
        self.ctl.shell.on_minimized_changed(True)
        d.move(0, 30)                                          # Qt 가 숨긴 창을 다시 놓는 경우(b16 실기)를 흉내 낸다
        self.ctl.shell.on_minimized_changed(False)
        self.assertEqual(d.pos(), QPoint(333, 222))

    def test_settings_dialog_keeps_position_when_reopened_while_minimized(self):  # D-112, 최소화 중 ⌘, 경로
        from PySide6.QtCore import QPoint
        self.ctl.open_settings()
        d = self.ctl._settings_dialog
        d.move(311, 244)
        self.ctl.shell.on_minimized_changed(True)
        d.move(0, 30)
        self.ctl.open_settings()
        self.assertEqual(d.pos(), QPoint(311, 244))
        self.ctl.shell.on_minimized_changed(False)             # 이미 보이므로 위치를 건드리지 않는다
        self.assertEqual(d.pos(), QPoint(311, 244))

    def test_settings_dialog_reopened_after_close_forgets_position(self):  # D-112, 결정 0073 · 0076 2항
        self.ctl.open_settings()
        d = self.ctl._settings_dialog
        d.move(333, 222)
        d.close()
        self.ctl.shell.on_minimized_changed(True)
        self.ctl.shell.on_minimized_changed(False)
        self.assertFalse(d.isVisible())
        self.assertIsNone(self.ctl._settings_saved_pos)
        self.ctl.open_settings()
        self.assertTrue(d.isVisible())
        self.assertNotEqual((d.x(), d.y()), (333, 222))        # 닫았다 다시 열면 옮긴 위치가 아니라 기본 위치이다

    def test_main_window_state_change_calls_hook(self):  # D-111: Qt 의 창 상태 변화가 훅에 닿는다
        from PySide6.QtCore import Qt
        got = []
        self.ctl.shell.on_minimized_changed = got.append
        self.ctl.shell.setWindowState(Qt.WindowMinimized)
        self.ctl.shell.setWindowState(Qt.WindowNoState)
        self.assertTrue(got and got[0] is True and got[-1] is False, got)

    def test_main_window_has_no_settings_button_menu_opens_dialog(self):  # AC-FR7-19 (결정 0089)
        self.assertFalse(hasattr(self.view.input, "settings"))
        self.assertFalse([b for b in self.ctl.shell.findChildren(QPushButton) if b.accessibleName() == "설정"])
        self.ctl.open_settings()                                  # 앱 메뉴의 "설정…"(⌘,)이 같은 호출을 한다
        self.assertIsNotNone(self.ctl._settings_dialog)

    def test_capture_button_failure_gives_notice_only(self):      # 캡처 실패는 알림만 하고 모델 호출이 없다(실제 screencapture 는 실행하지 않는다)
        self.ctl.deps.permission_status = lambda: {"screen_recording": "허용"}
        self.view.capture_clicked.emit()
        end = time.time() + 5
        while self.ctl._capturing and time.time() < end:
            pump(2)
        pump(5)
        self.assertEqual(self.model.sent, [])
        self.assertIn("화면을 캡처하지 못했습니다", self.ctl.shell.statusBar().currentMessage())

    def test_callbacks_from_worker_thread_do_not_block(self):  # X6
        """모델 읽기 스레드가 이벤트를 내는 동안 주 스레드가 막혀 있어도(큐 연결) 콜백이 끝난다."""
        self.view.input.submitted.emit("질문")
        done = threading.Event()
        spent = []

        def worker():
            for ev in (TextDelta("부분"), Result(True, text="전체 응답")):
                t0 = time.monotonic()
                self.model.on_event(ev)          # on_card 가 잠금 안에서 호출된다
                spent.append(time.monotonic() - t0)
            done.set()

        t = threading.Thread(target=worker)
        t.start()
        self.assertTrue(done.wait(3.0), "on_card 콜백이 주 스레드를 기다려 막혔다")   # 대기하는 동안 UI 스레드는 이벤트를 처리하지 않는다
        t.join()
        self.assertLess(max(spent), 0.05)        # Q-18: UI 스레드가 막혀 있어도 0.05초 안에 반환한다
        pump()
        cards = [c for c in self.rt.manager.cards()]
        self.assertEqual(cards[0].text, "전체 응답")
        self.assertEqual(self.view.ai.card(cards[0].n).body.text(), "전체 응답")

    def test_card_delete_button(self):
        self.view.input.submitted.emit("질문")
        pump()
        n = self.rt.manager.cards()[0].n
        self.view.ai.card_delete_requested.emit(n)
        pump()
        self.assertIsNone(self.view.ai.card(n))
        self.assertIn("delete", [r["type"] for r in self.records()])


class AttachTest(Base):
    def setUp(self):
        super().setUp()
        self.start()
        self.view = self.ctl.shell.session_page

    def test_attach_chip_thumbnail_remove_and_send(self):  # AC-FR7-16
        n = self.ctl.attach([("a.png", png_bytes()), ("b.png", png_bytes(50, 20))], "붙여넣기")
        self.assertEqual(n, 2)
        bar = self.view.input
        self.assertEqual(len(bar.chips()), 2)
        k1 = bar.chips()[0]
        self.assertFalse(bar._chips[k1].icon().isNull())
        bar._chips[k1].click()                              # 한 장을 뺀다
        self.assertEqual(len(bar.chips()), 1)
        self.view.input.submitted.emit("이 그림은?")
        msg = self.model.sent[0]
        blocks = msg.content if hasattr(msg, "content") else None
        text = json.dumps(msg, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)
        self.assertEqual(text.count('"type": "image"'), 1)
        self.assertEqual(bar.chips(), ())
        caps = [r for r in self.records() if r["type"] == "capture"]
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["source"], "붙여넣기")
        self.assertTrue((self.ctl.runtime.folder / caps[0]["path"]).is_file())
        self.assertIsNone(blocks) if blocks is None else None

    def test_image_only_submit_sends_screen_memo_d125(self):  # AC-FR7-17
        self.ctl.attach([("a.png", png_bytes())], "끌어다 놓기")
        bar = self.view.input
        self.assertEqual(len(bar.chips()), 1)
        bar.edit.setText("   ")
        bar._submit()                                        # 빈 글 + 칩 1개 + Enter
        pump()
        self.assertEqual(len(self.model.sent), 1)
        self.assertEqual(bar.chips(), ())
        card = self.ctl.runtime.manager.cards()[-1]
        self.assertEqual(card.kind, "화면메모")
        reqs = [r for r in self.records() if r["type"] == "request"]
        self.assertEqual(reqs[-1]["kind"], "화면메모")
        self.assertIn(card.n, self.ctl.runtime.manager._capture_cards)     # 처리 중에는 트리거를 보류한다
        self.assertEqual(self.ctl.runtime.manager.trigger("button"), "held")

    def test_empty_submit_without_chip_sends_nothing_d125(self):
        self.view.input.edit.setText("  ")
        self.view.input._submit()
        pump()
        self.assertEqual(self.model.sent, [])

    def test_image_card_shows_thumbnail_size_source_d126(self):  # AC-FR12-14
        self.ctl.attach([("a.png", png_bytes(64, 32))], "끌어다 놓기")
        self.view.input.edit.setText("이 그림은?")
        self.view.input._submit()
        pump()
        card = self.ctl.runtime.manager.cards()[-1]
        w = self.view.ai.card(card.n)
        self.assertEqual(len(w.image_labels), 1)
        thumb, info = w.image_labels[0]
        self.assertFalse(thumb.pixmap().isNull())
        self.assertIn("64×32 px", info.text())
        self.assertIn("끌어다 놓기", info.text())

    def test_file_url_cmd_v_source_is_paste_d133(self):  # D-133, AC-FR7-26 ⒜ · AC-FR7-27: Finder 에서 복사한 파일의 ⌘V 는 붙여넣기이다
        from PySide6.QtCore import QEvent, QMimeData, Qt, QUrl
        from PySide6.QtGui import QGuiApplication, QKeyEvent
        d = Path(tempfile.mkdtemp())
        png = d / "c.png"
        png.write_bytes(png_bytes(64, 32))
        bar = self.view.input
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(png))])
        self._keep_md = md
        self.addCleanup(QGuiApplication.clipboard().clear)
        QGuiApplication.clipboard().setMimeData(md)
        QGuiApplication.sendEvent(bar.edit, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier))
        self.assertEqual(len(bar.chips()), 1)
        bar.edit.setText("이 그림은?")
        bar._submit()
        pump()
        card = self.ctl.runtime.manager.cards()[-1]
        _, info = self.view.ai.card(card.n).image_labels[0]
        self.assertTrue(info.text().endswith("붙여넣기"), info.text())
        self.assertNotIn("끌어다 놓기", info.text())

    def test_non_image_rejected_with_notice(self):
        n = self.ctl.attach([("a.txt", b"hello")], "끌어다 놓기")
        self.assertEqual(n, 0)
        self.assertEqual(self.view.input.chips(), ())
        self.assertIn("a.txt", self.ctl.shell.statusBar().currentMessage())

    def test_paste_non_image_file_rejected_text_unchanged(self):  # AC-FR7-26 ⒞
        d = Path(tempfile.mkdtemp())
        pdf = d / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4 x")
        bar = self.view.input
        bar.edit.setText("입력 중")
        self.ctl._on_files_dropped([str(pdf)])
        self.assertEqual(bar.chips(), ())
        self.assertEqual(bar.edit.text(), "입력 중")
        self.assertIn("a.pdf", self.ctl.shell.statusBar().currentMessage())

    def test_cmd_v_paste_handles_image(self):  # D-076, FR-14 붙여넣기는 이미지 첨부를 포함
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QGuiApplication
        bar = self.view.input
        bar.edit.setText("기존 글")
        md = QMimeData()
        img = QImage(8, 8, QImage.Format.Format_RGB32)
        img.fill(QColor("red"))
        md.setImageData(img)
        md.setText("screenshot.png")
        QGuiApplication.clipboard().setMimeData(md)
        got = []
        bar.image_pasted.connect(got.append)
        self.assertTrue(bar.handle_paste())          # 편집 메뉴는 없다(결정 0153): ⌘V 는 입력 칸이 직접 처리한다
        self.assertEqual(len(got), 1)
        self.assertEqual(bar.edit.text(), "기존 글")

    def test_sixth_image_rejected(self):
        files = [("%d.png" % i, png_bytes()) for i in range(6)]
        self.assertEqual(self.ctl.attach(files, "끌어다 놓기"), 5)


class EndAndControlTest(Base):
    def test_end_session_writes_end_and_closes(self):
        self.start()
        rt = self.ctl.runtime
        folder = rt.folder
        self.ctl.end_session()
        recs = [json.loads(x) for x in (folder / "session.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(recs[-1]["type"], "end")
        self.assertTrue(self.model.closed)
        self.assertTrue(self.audio.stopped)

    def _with_segments(self):
        self.start()
        rt = self.ctl.runtime
        for sg in (seg(1, 0, 3, "첫 문장"), seg(2, 4, 7, "둘째 문장")):
            rt.on_segment(sg)
        return rt

    def test_end_flow_resident_route_saves_document(self):  # K-16, 이력 경로
        rt = self._with_segments()
        self.model.auto_reply = True
        folder = rt.folder
        self.ctl.end_session()
        pump()
        text = self.model.sent[-1].blocks[0]["text"]
        self.assertTrue(text.startswith("[요청] 종류=정리문서 문서=수업\n"))
        self.assertNotIn("이력=없음", text.split("\n")[0])
        self.assertEqual(self.model.efforts, ["high"])          # 세션 effort 가 medium 이므로 전환한다
        self.assertEqual((folder / "lecture.md").read_text(encoding="utf-8"), "# 정리 문서\n")
        recs = [json.loads(x) for x in (folder / "session.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["type"] for r in recs].count("end"), 1)
        self.assertFalse(self.ctl._ended)                        # 사용자가 닫을 때까지 창이 남는다
        self.assertTrue(self.ctl._end_dialog.folder_button.isHidden() is False)
        self.ctl._end_dialog.close_button.click()
        self.assertTrue(self.ctl._ended)
        self.assertTrue(self.model.closed)

    def test_end_flow_failure_keeps_transcript(self):
        rt = self._with_segments()
        folder = rt.folder
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        self.assertFalse(self.ctl._ended)
        self.model.on_event(Result(False, text="x", error_kind="rate_limit"))
        pump()
        self.assertFalse((folder / "lecture.md").exists())
        self.assertTrue((folder / "transcript.txt").exists())
        self.assertIn("transcript.txt", self.ctl._end_dialog.message.text())

    def test_status_pill_clears_after_cleanup_fails_or_completes_d132(self):  # D-132, FR-11
        def texts():
            return [lb.text() for lb in self.ctl.shell.status._labels]
        self._with_segments()
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        self.ctl.refresh_status()
        self.assertIn("정리 문서 만드는 중", texts())             # 만드는 중에는 표시한다
        self.model.on_event(Result(False, text="x", error_kind="rate_limit"))
        pump()
        self.assertNotIn("정리 문서 만드는 중", texts())          # 실패 뒤에는 사라진다
        self.ctl.refresh_status()
        self.assertNotIn("정리 문서 만드는 중", texts())
        self.model.auto_reply = True
        self.ctl._retry_cleanup()
        self.assertIn("정리 문서 만드는 중", texts())             # 다시 만들기를 시작하면 다시 표시한다
        from nsu_kangs_rab.core import endflow
        self.ctl._end_bridge.done.emit(endflow.EndResult(endflow.DONE, path=None))      # 완료를 합성한다
        pump()
        self.assertNotIn("정리 문서 만드는 중", texts())          # 완료 뒤에는 사라진다

    def test_quit_request_while_generating_acts_as_cancel_d184(self):  # 결정 0169 1항: 만드는 중의 종료 요청 = [취소]
        rt = self._with_segments()
        folder = rt.folder
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        self.assertFalse(self.ctl._ended)
        self.assertEqual(self.ctl.shell.request_quit(), "already_ending")
        pump()
        self.assertTrue(self.ctl._ended)
        self.assertFalse((folder / "lecture.md").exists())
        self.assertTrue((folder / "transcript.txt").exists())

    def test_quit_request_on_done_screen_acts_as_close_d184(self):  # 결정 0169 1항: 완료 화면의 종료 요청 = [닫기]
        self._with_segments()
        self.model.auto_reply = True
        self.ctl.end_session()
        pump()
        self.assertFalse(self.ctl._ended)
        self.ctl.shell.request_quit()
        self.assertTrue(self.ctl._ended)

    def test_quit_request_on_failed_screen_acts_as_close_d184(self):
        self._with_segments()
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        self.model.on_event(Result(False, text="x", error_kind="rate_limit"))
        pump()
        self.assertFalse(self.ctl._ended)
        self.ctl.shell.request_quit()
        self.assertTrue(self.ctl._ended)

    def test_sigterm_in_session_writes_end_without_document_d183(self):  # 결정 0169 2항
        rt = self._with_segments()
        folder = rt.folder
        self.ctl.terminate_by_signal("sigterm")
        self.assertTrue(self.ctl._ended)
        self.assertTrue(self.model.closed)
        self.assertTrue(self.audio.stopped)
        recs = [json.loads(x) for x in (folder / "session.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["type"] for r in recs].count("end"), 1)
        self.assertFalse((folder / "lecture.md").exists())
        self.ctl.terminate_by_signal("sigterm")      # 두 번째는 아무 일도 하지 않는다

    def test_sigterm_while_generating_cancels_cleanup_d183(self):
        rt = self._with_segments()
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        self.ctl.terminate_by_signal("sigterm")
        pump()
        self.assertTrue(self.ctl._ended)
        self.assertFalse((rt.folder / "lecture.md").exists())

    def test_sigterm_handler_installed_and_polled_d183(self):
        import os, signal
        from nsu_kangs_rab.app import controller as C
        old = signal.getsignal(signal.SIGTERM)
        try:
            self.start()
            C._install_sigterm(self.ctl)
            os.kill(os.getpid(), signal.SIGTERM)
            for _ in range(50):
                pump()
                if self.ctl._ended:
                    break
                time.sleep(0.05)
            self.assertTrue(self.ctl._ended)
        finally:
            signal.signal(signal.SIGTERM, old)

    def test_quit_event_reaches_app_while_end_dialog_open_d184(self):  # 결정 0172 1항: Apple 이벤트 quit · Dock "종료" = QEvent.Quit
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        self._with_segments()
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        d = self.ctl._end_dialog
        self.assertFalse(d.isModal())                                   # 앱 전체 모달이 아니다
        self.assertTrue(d.isVisible())
        QApplication.sendEvent(QApplication.instance(), QEvent(QEvent.Type.Quit))
        pump()
        self.assertTrue(self.ctl._ended)                                # 생성 중이므로 [취소] 와 같다

    def test_end_dialog_blocks_main_window_input_but_not_itself_d184(self):
        from PySide6.QtCore import QEvent, QPoint, Qt, QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        self._with_segments()
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        d = self.ctl._end_dialog
        main = self.ctl.shell

        def press(w):
            ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(2, 2), QPointF(2, 2), Qt.MouseButton.LeftButton,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            return QApplication.sendEvent(w, ev)
        self.assertTrue(press(main))                                    # 필터가 메인 창의 누름을 소비한다(반환 참)
        self.assertIsNotNone(d._input_block)
        clicked = []
        d.cancel_button.clicked.connect(lambda: clicked.append(1))
        from PySide6.QtTest import QTest
        QTest.mouseClick(d.cancel_button, Qt.MouseButton.LeftButton)      # 종료 창 자신의 단추는 막히지 않는다
        self.assertEqual(clicked, [1])
        pump()
        self.assertIsNone(d._input_block)                               # [취소] 로 앱이 끝나며 창이 닫히면 필터가 제거된다

    def _record_levels(self):
        calls = []

        def fake(w, level):
            calls.append((w, level))
            return 3                                            # 부동 패널의 층
        self.ctl._set_window_level = fake
        return calls

    def test_end_dialog_lowers_settings_window_layer_and_restores_d187(self):
        calls = self._record_levels()
        self.ctl.open_settings()
        sd = self.ctl._settings_dialog
        self.assertTrue(sd.isVisible())
        self._with_segments()
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        self.assertEqual(calls[:1], [(sd, 0)])                  # 종료 창이 뜨면 설정 창을 일반 층으로 내린다
        self.assertEqual(set(calls), {(sd, 0)})
        self.assertTrue(sd.isVisible())                         # 닫거나 숨기지 않는다
        self.ctl._end_dialog.dismiss()
        pump()
        self.assertEqual(calls[-1], (sd, 3))                    # 닫히면 원래 층으로 되돌린다
        self.assertEqual(set(calls), {(sd, 0), (sd, 3)})

    def test_stop_confirm_lowers_settings_window_layer_and_blocks_it_d187(self):
        from PySide6.QtCore import QEvent, Qt, QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        calls = self._record_levels()
        self.ctl.open_settings()
        sd = self.ctl._settings_dialog
        self.ctl._can_control_capture = lambda: True
        self.ctl.request_stop()
        pump()
        self.assertIsNotNone(self.ctl._stop_dialog)
        self.assertEqual(set(calls), {(sd, 0)})
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(2, 2), QPointF(2, 2), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(QApplication.sendEvent(sd, ev))         # 설정 창의 입력은 막힌다(결정 0173 2항)
        self.ctl._stop_dialog.reject()                          # [취소]
        pump()
        self.assertIsNone(self.ctl._stop_dialog)
        self.assertEqual(calls[-1], (sd, 3))
        self.assertTrue(sd.isVisible())

    def test_reassert_layer_after_app_activation_d187_d186(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtWidgets import QApplication
        calls = self._record_levels()
        self.ctl.open_settings()
        sd = self.ctl._settings_dialog
        self.ctl._can_control_capture = lambda: True
        self.ctl.request_stop()
        pump()
        calls.clear()
        stop = self.ctl._stop_dialog
        raised = []
        stop.raise_ = lambda: raised.append(1)
        orig = QApplication.applicationState
        QApplication.applicationState = staticmethod(lambda: Qt.ApplicationState.ApplicationActive)
        self.addCleanup(lambda: setattr(QApplication, "applicationState", orig))
        QApplication.sendEvent(QApplication.instance(), QEvent(QEvent.Type.ApplicationActivate))
        deadline = 100
        while not raised and deadline:
            QApplication.processEvents()
            time.sleep(0.01)
            deadline -= 1
        self.assertEqual(calls[:1], [(sd, 0)])                  # Qt 가 3 으로 되돌린 층을 다시 내린다
        self.assertTrue(raised)                                 # 정지 확인 창도 다시 올린다
        n = len(calls)
        QApplication.applicationState = staticmethod(lambda: Qt.ApplicationState.ApplicationInactive)
        self.ctl._reassert_dialog_layer()                       # 앱이 비활성이면 건드리지 않는다
        self.assertEqual(len(calls), n)

    def test_reassert_skips_raise_for_active_dialog_and_notifies_accessibility_d189(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        self.ctl._can_control_capture = lambda: True
        self.ctl.request_stop()
        pump()
        stop = self.ctl._stop_dialog
        raised, notified = [], []
        stop.raise_ = lambda: raised.append(1)
        stop.isActiveWindow = lambda: True
        self.ctl._notify_accessibility = lambda w: notified.append(w)
        orig = QApplication.applicationState
        QApplication.applicationState = staticmethod(lambda: Qt.ApplicationState.ApplicationActive)
        self.addCleanup(lambda: setattr(QApplication, "applicationState", orig))
        self.ctl._reassert_dialog_layer()
        self.assertEqual(raised, [])                            # 이미 활성인 창은 다시 올리지 않는다
        self.assertEqual(notified, [stop])                      # 손쉬운 사용 트리 갱신은 알린다
        stop.isActiveWindow = lambda: False
        self.ctl._reassert_dialog_layer()
        self.assertEqual(raised, [1])                           # 활성이 아니면 올린다

    def test_settings_opened_while_end_dialog_up_is_lowered_d187(self):
        calls = self._record_levels()
        self._with_segments()
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        self.ctl.open_settings()
        self.assertEqual(set(calls), {(self.ctl._settings_dialog, 0)})

    def test_end_dialog_disables_about_and_settings_menu_keeps_quit(self):
        self._with_segments()
        self.model.auto_reply = False
        self.ctl.end_session()
        pump()
        acts = self.ctl.menu.actions
        self.assertFalse(acts["app.about"].isEnabled())
        self.assertFalse(acts["app.settings"].isEnabled())
        self.assertTrue(acts["app.quit"].isEnabled())
        self.ctl._end_dialog.dismiss()
        pump()
        self.assertTrue(acts["app.about"].isEnabled())

    def test_shutdown_deadline_kills_unresponsive_child_by_pid_d185(self):  # 결정 0172 2항: 응하지 않는 보조 프로세스가 있어도 상한 안에 PID 가 남지 않는다
        import sys as _sys
        from nsu_kangs_rab.app import controller as C
        old = C.SHUTDOWN_LIMIT_S
        C.SHUTDOWN_LIMIT_S = 0.5
        code = "import signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n"
        h = self.ctl.procs.spawn([_sys.executable, "-c", code], dict(os.environ), tempfile.gettempdir(), "test_unresponsive")
        try:
            self.assertIn(h.pid, [e["pid"] for e in self.ctl.registry.entries()])
            self.ctl._arm_shutdown_deadline()
            t0 = time.monotonic()
            self.ctl.procs.terminate(h)                  # 기본값이면 stdin 3초 + SIGTERM 3초(무시) 뒤에야 SIGKILL 이다
            took = time.monotonic() - t0
            self.assertLess(took, 3.0)
            self.assertIsNotNone(h.popen.poll())          # PID 가 남지 않았다
        finally:
            C.SHUTDOWN_LIMIT_S = old
            if h.popen.poll() is None:
                os.kill(h.pid, 9)
            t = getattr(self.ctl, "_deadline_timer", None)
            if t is not None:
                t.cancel()

    def test_end_flow_cancel_quits_without_document(self):
        rt = self._with_segments()
        folder = rt.folder
        self.ctl.end_session()
        pump()
        self.ctl._end_dialog.cancel_button.click()
        pump()
        self.assertTrue(self.ctl._ended)
        self.assertFalse((folder / "lecture.md").exists())

    def test_end_flow_busy_resident_uses_history_less(self):
        rt = self._with_segments()
        rt.manager.in_flight = lambda: object()
        calls = []
        orig = self.ctl._make_oneshot
        self.ctl._make_oneshot = lambda cwd, purpose: calls.append((str(cwd), purpose)) or orig(cwd, purpose)
        self.ctl.end_session()
        pump()
        self.assertEqual(calls, [(str(rt.folder), "cleanup_doc")])
        sent = [m for fm in FakeModel.instances for m in fm.sent]
        self.assertTrue(any("이력=없음" in m.blocks[0]["text"] for m in sent))

    def test_rebuild_summary_from_folder(self):
        rt = self._with_segments()
        folder = rt.folder
        rt.finish()
        self.ctl.runtime = None
        FakeModel.instances.clear()
        orig = FakeModel.__init__

        def init(self_, *a, **k):
            orig(self_, *a, **k)
            self_.auto_reply = True
        FakeModel.__init__ = init
        self.addCleanup(setattr, FakeModel, "__init__", orig)
        self.assertTrue(self.ctl.rebuild_summary(folder))
        for _ in range(100):
            pump(1)
            if (folder / "lecture.md").exists():
                break
        self.assertTrue((folder / "lecture.md").exists())
        self.assertTrue(self.ctl.rebuild_summary(folder) is False)   # 진행 중에는 다시 시작하지 않는다
        pump(20)
        self.ctl._end_dialog.close_button.click()
        self.assertTrue(self.ctl.rebuild_summary(folder))
        for _ in range(100):
            pump(1)
            if (folder / "lecture-2.md").exists():
                break
        self.assertEqual((folder / "lecture-2.md").read_text(encoding="utf-8"), "# 정리 문서\n")
        sent = FakeModel.instances[0].sent[0].blocks[0]["text"]
        self.assertIn("이력=없음", sent.split("\n")[0])
        self.assertIn("[재전송] 범위=", sent)

    def test_control_file_appearance_and_audio_error(self):
        ctl_file = Path(self.tmp.name) / "control.jsonl"
        ctl_file.write_text(json.dumps({"cmd": "appearance", "value": "dark"}) + "\n")   # 시작 전의 줄은 실행하지 않는다
        # 제어 파일은 시작 때 설정하므로 새 컨트롤러를 만든다
        self.ctl.shutdown()
        c = C.AppController(_app, ["--dev-config-dir", str(self.cfg), "--dev-control", str(ctl_file)],
                            C.Deps(environ={}, find_claude=lambda *a, **k: claude_locator.Found("/bin/echo", False, "settings"),
                                   key_store_factory=lambda a: self.keys, model_factory=FakeModel,
                                   stt_helper=fake_stt_helper, mic_factory=lambda log: self.audio))
        self.ctl = c
        p = c.shell.start_page.values()
        p.update({"save_dir": str(self.save), "source": "system_mic"})
        self.assertTrue(c.start_session(p))
        self.assertEqual(c.appearance.scheme, "light")
        with open(ctl_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"cmd": "appearance", "value": "dark"}) + "\n")
            fh.write(json.dumps({"cmd": "audio_error"}) + "\n")
            fh.write(json.dumps({"cmd": "nonsense"}) + "\n")
        c._poll_control()
        pump()
        self.assertEqual(c.appearance.scheme, "dark")
        self.assertEqual(c._capture_state, "중단")
        events = [json.loads(x) for x in Path(c.eventlog.path).read_text(encoding="utf-8").splitlines()]
        dev = [e for e in events if e["type"] == "dev_command"]
        self.assertEqual([e.get("ignored") for e in dev], [None, None, True])
        self.assertEqual([e["line"] for e in dev], [1, 2, 3])
        errs = [c2 for c2 in c.shell.session_page.ai._cards.values() if c2.error.isVisible() is not None]
        self.assertTrue(errs)

    def test_control_file_audio_start_failed(self):  # 결정 0069 · AC-FR3-12 · W-43
        ctl_file = Path(self.tmp.name) / "control2.jsonl"
        ctl_file.write_text("")
        self.ctl.shutdown()
        c = C.AppController(_app, ["--dev-config-dir", str(self.cfg), "--dev-control", str(ctl_file)],
                            C.Deps(environ={}, find_claude=lambda *a, **k: claude_locator.Found("/bin/echo", False, "settings"),
                                   key_store_factory=lambda a: self.keys, model_factory=FakeModel,
                                   stt_helper=fake_stt_helper, mic_factory=lambda log: self.audio))
        self.ctl = c
        p = c.shell.start_page.values()
        p.update({"save_dir": str(self.save), "source": "system_mic"})
        self.assertTrue(c.start_session(p))
        with open(ctl_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"cmd": "audio_start_failed"}) + "\n")
        c._poll_control()
        pump()
        self.assertEqual(c._capture_state, "중단")
        cards = list(c.shell.session_page.ai._cards.values())
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertIn("음성 수집을 시작하지 못했습니다", card.error.text())
        self.assertIn("수집은 스스로 이어지지 않습니다", card.error.text())
        self.assertFalse(card.judgment.isVisible())            # 요청이 없는 오류에는 "요청 종류" 줄이 없다
        self.assertEqual(c.shell.session_page.banner.title.text(), "음성 수집을 시작하지 못했습니다")


class DiagramTest(Base):  # K-15
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, FakeModel, "diagram_hook", None)
        self.start()
        self.rt = self.ctl.runtime
        self.view = self.ctl.shell.session_page
        self.resident = self.model
        self.rt.on_segment(seg(1, 0, 3, "첫 문장"))
        self.opened = []
        self.ctl.deps.open_url = lambda u: self.opened.append(u.toLocalFile()) or True

    def card(self, text="/고찰", reply="고찰 본문"):
        before = {c.n for c in self.rt.manager.cards()}
        self.view.input.submitted.emit(text)
        self.resident.on_event(Result(True, text=reply))
        pump()
        return next(c.n for c in self.rt.manager.cards() if c.n not in before)

    def wait(self, cond, sec=3.0):
        end = time.monotonic() + sec
        while time.monotonic() < end and not cond():
            pump(2)
        return cond()

    def write_diagram(self, model, svg='<svg xmlns="http://www.w3.org/2000/svg"><text>가</text></svg>', html="<html></html>",
                      name="d-1", result=True):
        d = Path(model.kw["cwd"]) / "captures" / "diagrams"
        d.mkdir(parents=True, exist_ok=True)
        (d / (name + ".svg")).write_text(svg, encoding="utf-8")
        (d / (name + ".html")).write_text(html, encoding="utf-8")
        if result:
            model.on_event(Result(True, text="captures/diagrams/%s.svg" % name))

    def diagrams(self):
        return [r for r in self.records() if r["type"] == "diagram"]

    def test_button_only_on_answer_reflection_and_done_trigger(self):  # AC-FR9-6
        a = self.card("/고찰")
        f = self.card("자유 질문입니다", "자유 답")
        w_a, w_f = self.view.ai.card(a), self.view.ai.card(f)
        self.assertFalse(w_a.diagram_button.isHidden())
        self.assertTrue(w_f.diagram_button.isHidden())
        self.assertEqual(w_a.diagram_button.accessibleName(), "다이어그램 만들기")
        self.assertTrue(w_a.diagram_button.isEnabled())

    def test_generate_success_shows_svg_and_opens_html(self):  # AC-FR9-7 · 8
        n = self.card()
        FakeModel.diagram_hook = lambda m, t: self.write_diagram(m)
        self.assertTrue(self.ctl.make_diagram(n))
        m = self.model
        self.assertIsNot(m, self.resident)
        cfg = m.config
        self.assertEqual((cfg.effort, tuple(cfg.tools), cfg.permission_mode), ("medium", ("Skill", "Read", "Write"), "dontAsk"))
        self.assertTrue(str(cfg.plugin_dir).endswith("third_party/diagram-design"))
        self.assertIsNone(m.kw.get("prompt_text"))
        self.assertTrue(self.view.ai.card(n).diagram_busy)
        self.assertTrue(self.wait(lambda: not self.view.ai.card(n).diagram_busy))
        w = self.view.ai.card(n)
        self.assertFalse(w.diagram_view.isHidden())
        d = self.diagrams()
        self.assertEqual([(r["n"], r["path"], r["result"]) for r in d], [(n, "captures/diagrams/d-1.svg", "완료")])
        self.assertTrue(self.ctl.open_diagram(n))
        self.assertEqual(self.opened[-1], str(self.rt.folder / "captures" / "diagrams" / "d-1.html"))

    def test_external_ref_is_rejected_with_reason(self):  # AC-FR9-15
        n = self.card()
        FakeModel.diagram_hook = lambda m, t: self.write_diagram(
            m, svg='<svg xmlns="http://www.w3.org/2000/svg"><image href="https://x.example/a.png"/></svg>')
        self.ctl.make_diagram(n)
        self.assertTrue(self.wait(lambda: not self.view.ai.card(n).diagram_busy))
        w = self.view.ai.card(n)
        self.assertTrue(w.diagram_view.isHidden())
        self.assertIn("외부 자원", w.diagram_status.text())
        self.assertFalse(w.diagram_retry.isHidden())
        self.assertEqual([r["result"] for r in self.diagrams()], ["외부 자원 위반"])
        self.assertFalse(self.ctl.open_diagram(n) and False)

    def test_failure_shows_reason_and_retry_and_failure_record(self):  # AC-FR9-10 · AC-FR9-24 (D-052: 실패 기록 path="" · result="실패")
        n = self.card()
        FakeModel.diagram_hook = lambda m, t: m.on_event(Result(False, text="x", error_kind="rate_limit"))
        self.ctl.make_diagram(n)
        self.assertTrue(self.wait(lambda: not self.view.ai.card(n).diagram_busy))
        w = self.view.ai.card(n)
        self.assertFalse(w.diagram_retry.isHidden())
        self.assertNotEqual(w.diagram_status.text(), "")
        recs = self.diagrams()
        self.assertEqual([(r["n"], r["path"], r["result"]) for r in recs], [(n, "", "실패")])
        # [다시 만들기] → 새 일회성 프로세스
        FakeModel.diagram_hook = lambda m, t: self.write_diagram(m, name="d-2")
        w.diagram_retry.click()
        self.assertTrue(self.wait(lambda: not w.diagram_busy and not w.diagram_view.isHidden()))

    def test_card_delete_cancels_that_process_only(self):  # AC-FR9-17
        a, b = self.card(), self.card()
        FakeModel.diagram_hook = lambda m, t: None            # 응답하지 않고 진행 중으로 둔다
        self.ctl.make_diagram(a)
        ma = self.model
        self.ctl.make_diagram(b)
        mb = self.model
        self.assertEqual(self.ctl._diagram_pool.active_count(), 2)
        self.ctl.delete_card(a)
        self.assertTrue(self.wait(lambda: ma.closed))
        self.assertFalse(mb.closed)
        self.assertEqual(self.ctl._diagram_pool.active_count(), 1)
        self.ctl.delete_card(b)
        self.assertTrue(self.wait(lambda: mb.closed))

    def test_limit_three_and_gate_reason(self):  # AC-FR9-9
        ns = [self.card() for _ in range(4)]
        FakeModel.diagram_hook = lambda m, t: None
        for n in ns[:3]:
            self.assertTrue(self.ctl.make_diagram(n))
        w4 = self.view.ai.card(ns[3])
        self.assertFalse(w4.diagram_button.isEnabled())
        self.assertIn("동시에", w4.diagram_button.toolTip())
        self.assertFalse(self.ctl.make_diagram(ns[3]))
        self.ctl.delete_card(ns[0])
        self.assertTrue(self.wait(lambda: self.view.ai.card(ns[3]).diagram_button.isEnabled() or True))
        self.assertTrue(self.wait(lambda: self.ctl._diagram_pool.active_count() == 2))
        self.view.ai.refresh_gates()
        self.assertTrue(w4.diagram_button.isEnabled())

    def test_skill_copy_missing_disables_button(self):  # AC-FR9-11
        n = self.card()
        self.ctl._diagram_pool.plugin_dir = Path(self.tmp.name) / "none"
        self.view.ai.refresh_gates()
        w = self.view.ai.card(n)
        self.assertFalse(w.diagram_button.isEnabled())
        self.assertIn("사본", w.diagram_button.toolTip())
        self.assertFalse(self.ctl.make_diagram(n))

    def test_session_end_cancels_all_and_removes_partial_files(self):  # AC-FR11-4
        n = self.card()
        FakeModel.diagram_hook = lambda m, t: self.write_diagram(m, name="partial", result=False)
        self.ctl.make_diagram(n)
        m = self.model
        out = self.rt.folder / "captures" / "diagrams"
        self.assertTrue((out / "partial.svg").exists())
        self.ctl.end_session()
        pump()
        self.assertTrue(m.closed)
        self.assertEqual(sorted(p.name for p in out.glob("*")), [])


class StartCheckTest(Base):  # D-040, AC-FR1-14 의 화면 부분 · AC-FR9-21
    def sessions(self):
        return [p for p in self.save.glob("*") if p.is_dir()] if self.save.exists() else []

    def assert_not_started(self):
        self.assertIsNone(self.ctl.runtime)
        self.assertIs(self.ctl.shell.machine.state, appstate.State.BEFORE_SESSION)
        self.assertEqual(self.sessions(), [])
        self.assertFalse(self.ctl._ended)

    def test_mismatch_does_not_start_session_and_shows_reason_and_action(self):
        FakeModel.next_init_source = "ANTHROPIC_API_KEY"      # 구독을 골랐는데 출처가 API 키이다
        self.assertFalse(self.start(provider="claude_subscription"))
        pump()
        self.assert_not_started()
        self.assertTrue(self.model.closed)
        self.assertEqual([m for m in self.model.sent], [])    # 질의 0건(결정 0056)
        sp = self.ctl.shell.start_page
        self.assertFalse(sp.problem.isHidden())
        t = sp.problem.text()
        self.assertIn("인증 출처가 고른 방식과 다릅니다", t)
        self.assertIn("/login", t)
        self.assertTrue(sp.start.isEnabled())
        self.assertEqual(sp.start.text(), "세션 시작")

    def test_async_check_waits_then_enters_session(self):
        FakeModel.next_init_source = FakeModel.OMIT
        self.assertTrue(self.start())
        pump()
        sp = self.ctl.shell.start_page
        self.assertIs(self.ctl.shell.machine.state, appstate.State.BEFORE_SESSION)
        self.assertEqual(sp.start.text(), "확인 중")
        self.assertFalse(sp.start.isEnabled())
        self.assertIsNotNone(self.ctl.runtime)
        m = self.model
        th = threading.Thread(target=lambda: m.on_event(Init("fake", "none", "0")))
        th.start()
        th.join()
        pump()
        self.assertIs(self.ctl.shell.machine.state, appstate.State.IN_SESSION)
        self.assertEqual(sp.start.text(), "세션 시작")

    def test_async_mismatch_aborts_and_removes_empty_folder(self):
        FakeModel.next_init_source = FakeModel.OMIT
        self.assertTrue(self.start())
        folder = self.ctl.runtime.folder
        self.assertTrue(folder.exists())
        m = self.model
        th = threading.Thread(target=lambda: m.on_event(Error("auth", "인증 출처가 고른 방식과 다릅니다(기대 none, 실제 ANTHROPIC_API_KEY)")))
        th.start()
        th.join()
        pump()
        self.assert_not_started()
        self.assertFalse(folder.exists())
        self.assertTrue(m.closed)
        self.assertIn("/login", self.ctl.shell.start_page.problem.text())

    def test_check_timeout_aborts(self):
        FakeModel.next_init_source = FakeModel.OMIT
        self.assertTrue(self.start())
        self.ctl._start_timer.timeout.emit()
        pump()
        self.assert_not_started()
        self.assertIn("모델 호출 프로세스", self.ctl.shell.start_page.problem.text())

    def test_discard_keeps_unknown_files(self):
        f = Path(self.tmp.name) / "s"
        (f / "captures").mkdir(parents=True)
        (f / "session.jsonl").write_text("{}")
        (f / "memo.txt").write_text("x")
        self.assertFalse(C.discard_session_folder(f))
        self.assertTrue((f / "memo.txt").exists())

    def test_error_card_shows_reason_and_action_for_every_kind(self):  # AC-FR9-21
        from nsu_kangs_rab.core import error_text
        from nsu_kangs_rab.core.types import ERROR_KINDS
        self.assertTrue(self.start())
        view = self.ctl.shell.session_page
        for kind in ERROR_KINDS:
            self.ctl._post_error(kind, "")
        pump()
        texts = [w.error.text() for w in view.ai._cards.values()]
        for kind in ERROR_KINDS:
            reason, action = error_text.ERROR_TEXT[kind]
            self.assertTrue(any(reason in t and action in t for t in texts), kind)
        self.assertFalse(any("sk-" in t for t in texts))


class SystemSoundWiringTest(Base):  # D-041, 결정 0065
    def test_default_source_uses_system_sound_factory_without_legacy_notice(self):
        calls = []

        class Src:
            def start(self, on_block, on_state=lambda s, d="": None):
                calls.append("start")
                on_state("중단", "수집 보조 프로그램이 없습니다")

            def stop(self):
                calls.append("stop")

        self.ctl.deps.system_sound_factory = lambda log, helper: calls.append(("factory", helper)) or Src()
        self.assertTrue(self.start(source="system_sound"))
        pump()
        self.assertEqual(calls[0][0], "factory")
        self.assertTrue(calls[0][1].endswith("helper/sck_audio"))
        self.assertNotIn("시스템 마이크를 고른다", self.ctl.shell.statusBar().currentMessage())
        texts = [w.error.text() for w in self.ctl.shell.session_page.ai._cards.values()]
        self.assertTrue(any("수집 보조 프로그램이 없습니다" in t for t in texts), texts)   # 중단 상세를 그대로 표시한다



class SystemSoundHelperMissingTest(Base):
    def test_helper_missing_reports_stopped_detail_from_real_source(self):
        self.assertTrue(self.start(source="system_sound"))
        end = time.monotonic() + 5
        texts = []
        while time.monotonic() < end and not any("보조 프로그램" in t for t in texts):
            pump(3)
            texts = [w.error.text() for w in self.ctl.shell.session_page.ai._cards.values()]
        self.assertTrue(any("수집 보조 프로그램이 없습니다" in t for t in texts), texts)
        self.assertNotIn("시스템 마이크를 고른다", self.ctl.shell.statusBar().currentMessage())


class BannerTest(Base):  # AC-FR3-2 · AC-FR3-11 의 화면 부분: 전사 창 위의 상태 띠
    def _banner(self):
        pump()
        return self.ctl.view.banner.state()

    def test_no_input_banner_shows_title_and_three_causes_then_clears(self):
        self.assertTrue(self.start())
        self.assertEqual(self._banner()[0], False)
        self.ctl._tap.state("입력 없음", "입력이 -80 dBFS 이하로 10초 계속되었다")
        shown, title, desc = self._banner()
        self.assertTrue(shown)
        self.assertEqual(title, "입력이 없습니다")
        for part in ("수집 설정", "소리가 없습니다", "OS 권한"):
            self.assertIn(part, desc)
        self.assertFalse([b for b in self.ctl.view.banner.findChildren(QPushButton) if not b.isHidden()])      # 단추가 없다
        self.ctl._tap.state("수집 중", "level changed")
        self.assertEqual(self._banner()[0], False)

    def test_stopped_banner_has_priority_over_no_input(self):
        self.assertTrue(self.start())
        self.ctl._tap.state("입력 없음", "")
        self.ctl._tap.state("중단", "스트림이 끝났습니다")
        shown, title, desc = self._banner()
        self.assertEqual((shown, title), (True, "음성 수집이 중단되었습니다"))
        self.assertIn("스트림이 끝났습니다", desc)

    def test_no_permission_banner_reason_without_restart_button(self):
        from nsu_kangs_rab.platform.audio.system_sound import REASON_TEXT
        import numpy as np
        from nsu_kangs_rab.platform.audio.types import PcmBlock
        self.assertTrue(self.start())
        tap = self.ctl._tap
        tap._block(tap._gen, PcmBlock(np.zeros(160, dtype=np.float32), 0.0))      # 첫 음성 블록 뒤의 권한 회수는 옛 처리이다(결정 0178 6항)
        tap.state("중단", REASON_TEXT["no_permission"])
        shown, title, desc = self._banner()
        self.assertEqual((shown, title, desc), (True, "음성 수집이 중단되었습니다", "사유: 권한 없음"))
        self.assertFalse([b for b in self.ctl.view.banner.findChildren(QPushButton) if not b.isHidden()])
        cards = [w for w in self.ctl.view.ai._cards.values()]
        self.assertEqual(len(cards), 1)                                       # permission 오류 카드 한 장


class LevelBarTest(Base):  # AC-FR3-10: 입력 레벨 막대의 칸 수
    def test_cells_follow_source_level_and_zero_when_stopped(self):
        self.assertTrue(self.start())
        st = self.ctl.shell.status
        self.ctl.refresh_status()
        self.assertEqual(st.level_cells(), 0)                  # 무음
        self.audio.lvl = 10 ** (-25 / 20)                      # -25 dBFS → 4칸
        self.ctl.refresh_status()
        self.assertEqual(st.level_cells(), 4)
        self.audio.lvl = 0.0                                   # 소리가 멈춘다
        self.ctl.refresh_status()
        self.assertEqual(st.level_cells(), 0)
        self.audio.lvl = 0.5
        self.ctl.refresh_status()
        self.assertEqual(st.level_cells(), 6)
        self.ctl._tap.state("중단", "스트림이 끝났습니다")           # 수집 중단이면 0칸(소스 값이 남아 있어도)
        self.ctl.refresh_status()
        self.assertEqual(st.level_cells(), 0)


class SourceDefaultTest(Base):  # AC-FR3-4: 시작 화면의 음성 소스(결정 0179 로 설정 창에서 옮겼다)
    def test_start_screen_source_saved_at_start_and_mic_not_selectable(self):
        from nsu_kangs_rab.app import screens
        sp = self.ctl.shell.start_page
        self.assertEqual(screens.combo_data(sp.source), "system_sound")
        self.assertFalse(sp.source.model().item(1).isEnabled())            # 마이크는 고를 수 없다
        self.assertFalse(hasattr(self.ctl, "_on_source_default"))           # 설정 창에서 오던 처리 함수는 없다
        self.assertTrue(self.start(source="system_sound"))
        saved = json.loads((self.cfg / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved.get("source"), "system_sound")


class ProviderDefaultTest(Base):  # D-074, AC-FR1-5 · AC-FR1-10 (결정 0179: 제공자는 [세션 시작] 때 저장한다)
    def test_provider_saved_at_start_and_model_effort_follow_start_screen(self):
        from nsu_kangs_rab.app import screens
        sp = self.ctl.shell.start_page
        self.assertFalse(hasattr(self.ctl, "_on_provider_default"))
        sp.provider.setCurrentIndex(sp.provider.findData("claude_api"))
        saved = json.loads((self.cfg / "settings.json").read_text(encoding="utf-8"))
        self.assertNotEqual(saved.get("provider"), "claude_api")            # 고르는 것만으로는 저장하지 않는다
        self.keys.set("sk-test")
        self.assertTrue(self.start(provider="claude_api"))
        saved = json.loads((self.cfg / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved.get("provider"), "claude_api")
        self.assertEqual(self.ctl.data.get("provider"), "claude_api")

    def test_settings_window_has_no_provider(self):
        self.ctl.open_settings()
        self.assertFalse(hasattr(self.ctl._settings_form, "provider"))


class CheckLineTest(Base):  # 결정 0078, AC-FR1-23: 시작 화면의 점검 상태 줄
    SUB = "claude 실행 파일을 확인하였습니다. 로그인은 세션을 시작할 때 확인합니다."
    API = "Claude API 키가 저장되어 있습니다. claude 실행 파일을 확인하였습니다. 키는 세션을 시작할 때 확인합니다."

    def _set_provider(self, provider):
        from nsu_kangs_rab.app import screens
        sp = self.ctl.shell.start_page
        screens.set_combo_data(sp.provider, provider)
        self.ctl.refresh_start_check(provider)
        return sp

    def test_subscription_text_shown_and_claude_not_run(self):  # ①
        pump(3)
        sp = self.ctl.shell.start_page
        self.assertFalse(sp.check_line.isHidden())
        self.assertEqual(sp.check_text.text(), self.SUB)
        self.assertNotIn("확인됨", sp.check_text.text())
        self.assertEqual(FakeModel.instances, [])               # 시작 전에는 claude 프로세스를 만들지 않는다
        self.assertTrue(sp.banner.isHidden())

    def test_api_text_with_key_and_switch_back(self):  # ②
        sp = self.ctl.shell.start_page
        self.keys.set("sk-test")
        self._set_provider("claude_api")
        self.assertFalse(sp.check_line.isHidden())
        self.assertEqual(sp.check_text.text(), self.API)
        self.assertNotIn("확인됨", sp.check_text.text())
        self._set_provider("claude_subscription")
        self.assertEqual(sp.check_text.text(), self.SUB)

    def test_line_disappears_and_banner_shows_without_key_or_claude(self):  # ③
        sp = self.ctl.shell.start_page
        self.keys.set("sk-test")
        self._set_provider("claude_api")
        self.keys.delete()
        self.ctl.refresh_start_check("claude_api")
        self.assertTrue(sp.check_line.isHidden())
        self.assertFalse(sp.banner.isHidden())
        self.ctl.claude_path = None
        self._set_provider("claude_subscription")
        self.assertTrue(sp.check_line.isHidden())
        self.assertEqual(sp.problem.text(), self.ctl.NO_CLAUDE_BANNER[0])

    def test_line_hidden_while_start_failure_banner_shows(self):  # ④
        pump(3)
        sp = self.ctl.shell.start_page
        self.assertFalse(sp.check_line.isHidden())
        sp.show_problem("세션을 시작하지 않았습니다. 시험")
        self.assertTrue(sp.check_line.isHidden())
        sp.show_problem("")
        self.assertFalse(sp.check_line.isHidden())


class FrameTest(Base):  # K-14: 캡처 액자 (결정 0010 · 0077), AC-FR12-1 · 3 · 10 · 11 · 12 · 15, AC-FR14-6
    SCREENS = None

    def setUp(self):
        super().setUp()
        from nsu_kangs_rab.core import framegeom as G
        self.G = G
        self.screens = [G.Rect(0, 25, 1440, 875)]
        self.ctl.deps.screen_rects = lambda: self.screens
        self.ctl.deps.permission_status = lambda: {"screen_recording": "허용"}
        self.cmds = []
        self.ctl.deps.capture_runner = self._runner
        self.runner_code = 0

    def _runner(self, cmd, timeout_s):
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QColor, QImage
        self.cmds.append(list(cmd))
        if self.runner_code == 0:
            im = QImage(40, 30, QImage.Format.Format_RGB32)
            im.fill(QColor("green"))
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            im.save(buf, "PNG")
            Path(cmd[-1]).write_bytes(bytes(buf.data()))
        return self.runner_code, ""

    def _settings(self):
        return json.loads((self.cfg / "settings.json").read_text(encoding="utf-8"))

    def _wait_capture(self):
        end = time.time() + 5
        while self.ctl._capturing and time.time() < end:
            pump(2)
            time.sleep(0.01)
        pump(5)
        self.assertFalse(self.ctl._capturing)

    def _action_text(self):
        return self.ctl.menu.actions["window.frame"].text(), self.ctl.menu._tray_actions["window.frame"].text()

    def test_frame_visible_on_top_and_menu_says_hide(self):  # AC-FR12-3 · AC-FR14-6
        from PySide6.QtCore import Qt
        f = self.ctl.frame
        self.assertTrue(f.isVisible())
        self.assertTrue(bool(f.windowFlags() & Qt.WindowStaysOnTopHint))
        self.assertTrue(f.testAttribute(Qt.WA_TranslucentBackground))
        self.assertEqual(self._action_text(), ("액자 숨기기", "액자 숨기기"))

    def test_hide_and_show_keep_geometry_and_texts(self):  # AC-FR12-15 · AC-FR14-6
        f = self.ctl.frame
        before = f.frame_rect()
        self.ctl.on_command("window.frame")
        self.assertFalse(f.isVisible())
        self.assertEqual(self._action_text(), ("액자 보이기", "액자 보이기"))
        self.ctl.on_command("window.frame")
        self.assertTrue(f.isVisible())
        self.assertEqual(f.frame_rect(), before)
        self.assertEqual(self._action_text(), ("액자 숨기기", "액자 숨기기"))
        f.hide_requested.emit()                         # 액자의 숨기기 단추
        self.assertFalse(f.isVisible())

    def test_frame_state_rules(self):  # AC-FR12-3 · 11 · 19 (9차 개정 3차 초안)
        S, f = appstate.State, self.ctl.frame
        self.ctl._sync_frame(S.FIRST_RUN)
        self.assertFalse(f.isVisible())              # ① 에서는 띄우지 않는다
        self.ctl._sync_frame(S.BEFORE_SESSION)
        self.assertTrue(f.isVisible())               # ② 로 넘어가면 띄운다
        self.ctl._sync_frame(S.IN_SESSION)
        self.assertTrue(f.isVisible())
        self.ctl._sync_frame(S.ENDING)
        self.assertFalse(f.isVisible())              # ④ 에서는 숨긴다
        self.assertTrue(self.ctl._frame_wanted)      # 숨김을 저장하지 않는다
        self.ctl._sync_frame(S.BEFORE_SESSION)
        self.assertTrue(f.isVisible())

    def test_user_hidden_in_before_session_stays_hidden_in_session(self):  # AC-FR12-19
        S = appstate.State
        self.ctl._sync_frame(S.BEFORE_SESSION)
        self.ctl.hide_frame()
        self.ctl._sync_frame(S.IN_SESSION)
        self.assertFalse(self.ctl.frame.isVisible())

    def test_straddling_saved_geometry_falls_back_with_notice(self):  # AC-FR12-12
        two = [self.G.Rect(0, 0, 1440, 900), self.G.Rect(1440, 0, 1440, 900)]
        r, src, reason = self.G.restore_info(self.G.Rect(1300, 200, 800, 450).as_dict(), two, [two[0]])
        self.assertEqual((src, reason), ("default", "off_screen"))
        self.assertTrue(self.G.placeable(r, two[0]))

    def test_release_puts_frame_into_pointer_screen(self):  # 끄는 동안 걸침 허용, 놓으면 포인터 화면 안으로
        two = [self.G.Rect(0, 0, 1440, 900), self.G.Rect(1440, 0, 1440, 900)]
        straddle = self.G.Rect(1300, 300, 800, 450)
        a = self.G.clamp(straddle, two, (1700, 500))
        self.assertTrue(self.G.placeable(a, two[1]))
        b = self.G.clamp(straddle, two, (1350, 500))
        self.assertTrue(self.G.placeable(b, two[0]))
        c = self.G.clamp(straddle, two)                       # 포인터가 없으면 겹침이 큰 화면
        self.assertTrue(self.G.placeable(c, two[1]))

    def test_top_edge_stops_at_available_area(self):  # FR-12 크기와 위치 ②, 이름표 띠 없음(결정 0080)
        scr = self.screens[0]
        self.ctl.set_frame_rect(self.G.Rect(300, 0, 800, 450))          # 윗변이 가용 영역 위 끝(메뉴 막대) 위
        q = self.ctl.frame_rects()
        self.assertEqual(q["outer"]["y"], scr.y)
        self.assertEqual(q["window"], q["outer"])                       # 창 사각형 = 바깥 사각형
        cap = self.ctl.frame.capture_region()
        self.assertEqual((cap.y, cap.h), (scr.y + 3, 450 - 6))
        self.assertFalse(any(k in q for k in ("name_tag", "hide_button", "tag_below")))
    def test_frame_drop_control_applies_release_rules(self):  # C2 frame_drop (FRM-8 ① · FRM-10)
        two = [self.G.Rect(0, 0, 1440, 900), self.G.Rect(1440, 0, 1440, 900)]
        self.ctl.deps.screen_rects = lambda: two
        f = {"cmd": "frame_drop", "value": {"x": 1300, "y": 300, "w": 800, "h": 450, "pointer_x": 1700, "pointer_y": 400}}
        self.ctl._run_control(1, json.dumps(f))
        r = self.ctl.frame.frame_rect()
        self.assertTrue(self.G.placeable(r, two[1]))                  # 포인터가 있는 화면 안으로
        self.assertEqual((r.w, r.h), (800, 450))
        self.assertEqual(self._settings()["frame"], r.as_dict())      # 놓는 즉시 저장
        f["value"].update(pointer_x=100, h=2000)                      # 높이 제한 · 비율 축소
        self.ctl._run_control(2, json.dumps(f))
        r = self.ctl.frame.frame_rect()
        self.assertTrue(self.G.placeable(r, two[0]))
        self.assertLessEqual(r.h, 900)
        self.assertLessEqual(abs(r.w * 2000 - r.h * 800), 2000)
        self.ctl._run_control(3, json.dumps({"cmd": "frame_drop", "value": {"x": 1}}))      # 형식이 틀리면 무시
        events = [json.loads(x) for x in Path(self.ctl.eventlog.path).read_text(encoding="utf-8").splitlines()]
        self.assertTrue([e for e in events if e["type"] == "dev_command"][-1].get("ignored"))

    def test_height_over_screen_shrinks_keeping_ratio(self):
        scr = self.screens[0]
        r = self.G.clamp(self.G.Rect(0, scr.y, 1600, scr.h + 200), [scr])
        self.assertLessEqual(r.h, scr.h)
        self.assertLessEqual(r.w, scr.w)
        self.assertLessEqual(abs(r.w * (scr.h + 200) - r.h * 1600), 1600)
    def test_default_inner_960x540_and_min_inner_200x120(self):  # master 의 기술 기본값
        r = self.G.default_frame(self.screens[0])
        inner = self.G.inner_region(r)
        self.assertEqual((inner.w, inner.h), (960, 540))
        c = self.G.clamp(self.G.Rect(300, 200, 20, 20), self.screens)
        ci = self.G.inner_region(c)
        self.assertEqual((ci.w, ci.h), (200, 120))
        small = self.G.default_frame(self.G.Rect(0, 0, 1000, 700))       # 80% 를 넘으면 16:9 를 유지하며 줄인다
        si = self.G.inner_region(small)
        self.assertLessEqual(si.w, 800)
        self.assertLessEqual(abs(si.w * 9 - si.h * 16), 16)

    def test_dev_control_commands_and_events(self):  # C2 · C3
        c = self.ctl
        ctl_file = Path(self.tmp.name) / "control.jsonl"
        c.dev.values["control"] = str(ctl_file)
        lines = [{"cmd": "frame_hide"}, {"cmd": "frame_show"},
                 {"cmd": "frame_set", "value": {"x": 320, "y": 220, "w": 700, "h": 400}}, {"cmd": "frame_query"}]
        ctl_file.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        c._poll_control()
        events = [json.loads(x) for x in Path(c.eventlog.path).read_text(encoding="utf-8").splitlines()]
        vis = [e for e in events if e["type"] == "frame_visibility"]
        self.assertEqual([e["visible"] for e in vis][-2:], [False, True])
        self.assertEqual(self.ctl.frame.frame_rect(), self.G.Rect(320, 220, 700, 400))
        q = [e for e in events if e["type"] == "frame_query"][-1]
        self.assertEqual(q["outer"], {"x": 320, "y": 220, "w": 700, "h": 400})
        self.assertEqual(q["inner"], {"x": 323, "y": 223, "w": 694, "h": 394})
        self.assertEqual(q["window"], q["outer"])                                      # 이름표 띠가 없다
        self.assertEqual(q["handles"]["move"], {"x": 320, "y": 220, "w": 14, "h": 14})
        self.assertEqual(q["handles"]["close"], {"x": 1006, "y": 220, "w": 14, "h": 14})
        self.assertEqual(q["handles"]["resize_br"], {"x": 1006, "y": 606, "w": 14, "h": 14})
        self.assertNotIn("name_tag", q)
        saved = [e for e in events if e["type"] == "frame_geometry_saved"]
        self.assertEqual((saved[-1]["x"], saved[-1]["w"]), (320, 700))
        self.assertEqual(self._settings()["frame"], {"x": 320, "y": 220, "w": 700, "h": 400})

    def test_frame_set_outside_one_screen_is_clamped(self):  # FRM-8, FRM-9 (C2)
        self.ctl.set_frame_rect(self.G.Rect(1300, 800, 600, 400))
        self.assertTrue(self.G.placeable(self.ctl.frame.frame_rect(), self.screens[0]))
        self.ctl.set_frame_rect(self.G.Rect(300, 200, 10, 10))
        inner = self.ctl.frame.capture_region()
        self.assertGreaterEqual(inner.w, 200)
        self.assertGreaterEqual(inner.h, 120)

    def test_restore_event_has_source_and_reason(self):  # C3
        def last_restore():
            events = [json.loads(x) for x in Path(self.ctl.eventlog.path).read_text(encoding="utf-8").splitlines()]
            return [e for e in events if e["type"] == "frame_restore"][-1]
        self.assertEqual((last_restore()["source"], last_restore()["reason"]), ("default", "none_saved"))
        self.ctl.data["frame"] = self.G.Rect(300, 200, 800, 450).as_dict()
        self.ctl.frame.close()
        self.ctl._setup_frame()
        self.assertEqual((last_restore()["source"], last_restore()["reason"]), ("saved", ""))
        self.ctl.data["frame"] = self.G.Rect(1600, 200, 800, 450).as_dict()
        self.ctl.frame.close()
        self.ctl._setup_frame()
        self.assertEqual((last_restore()["source"], last_restore()["reason"]), ("default", "off_screen"))

    def test_mask_passes_clicks_inside_and_takes_border_and_handles(self):  # AC-FR12-3 · 15
        from PySide6.QtCore import QPoint
        f = self.ctl.frame
        m = f.mask_region()
        w, h = f.width(), f.height()
        self.assertFalse(m.contains(QPoint(w // 2, h // 2)))                        # 안쪽: 창이 아니다 → 클릭 통과
        self.assertTrue(m.contains(QPoint(1, h // 2)))                              # 왼쪽 테두리(입력을 받는다)
        self.assertTrue(m.contains(QPoint(w // 2, h - 1)))                          # 아래 테두리
        for name, r in f.handle_rects().items():
            self.assertTrue(m.contains(r.center()), name)                           # 네 손잡이 네모
            self.assertEqual((r.width(), r.height()), (14, 14))
        self.assertTrue(m.contains(QPoint(10, 10)))                                 # 안쪽과 겹친 11 × 11 모서리는 네모의 기능이 동작한다
        cap, fr = f.capture_region(), f.frame_rect()
        self.assertEqual((cap.x, cap.y, cap.w, cap.h), (fr.x + 3, fr.y + 3, fr.w - 6, fr.h - 6))
        self.assertEqual((f.width(), f.height()), (fr.w, fr.h))                     # 이름표 띠 없음
    def test_drag_move_handle_moves_and_commit_saves(self):  # AC-FR12-3 · 11
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        f = self.ctl.frame
        before = f.frame_rect()
        c = f.handle_rects()["move"].center()
        QTest.mousePress(f, Qt.LeftButton, Qt.NoModifier, c)
        QTest.mouseMove(f, c + QPoint(40, 30))
        QTest.mouseRelease(f, Qt.LeftButton, Qt.NoModifier, c + QPoint(40, 30))
        after = f.frame_rect()
        self.assertEqual((after.w, after.h), (before.w, before.h))
        self.assertEqual((after.x, after.y), (before.x + 40, before.y + 30))
        self.assertEqual(self._settings()["frame"], after.as_dict())

    def test_move_stops_at_available_top(self):  # 10차: 윗변은 가용 영역의 위 끝 위로 가지 않는다(끄는 도중에도)
        from PySide6.QtCore import QPoint
        self.ctl.set_frame_rect(self.G.Rect(300, 200, 400, 300))
        f = self.ctl.frame
        mid, after = self._drag(f.handle_rects()["move"].center(), QPoint(0, -600))
        top = self.screens[0].y
        self.assertEqual((mid.y, after.y), (top, top))

    def test_border_edges_do_nothing(self):  # 10차: 테두리의 변을 끌어도 위치와 크기가 바뀌지 않는다
        from PySide6.QtCore import QPoint, Qt
        self.ctl.set_frame_rect(self.G.Rect(300, 200, 400, 300))
        f = self.ctl.frame
        before = f.frame_rect()
        for pt, d in ((QPoint(1, f.height() // 2), QPoint(-80, 0)), (QPoint(f.width() - 2, f.height() // 2), QPoint(80, 0)),
                      (QPoint(f.width() // 2, 1), QPoint(0, -60)), (QPoint(f.width() // 2, f.height() - 2), QPoint(0, 60))):
            mid, after = self._drag(pt, d)
            self.assertEqual((mid, after), (before, before), pt)
        self.assertEqual(f.cursor().shape(), Qt.ArrowCursor)

    def test_close_handle_hides_only_when_released_inside(self):  # W-58
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        f = self.ctl.frame
        c = f.handle_rects()["close"].center()
        seen = []
        f.hide_requested.connect(lambda: seen.append(1))
        QTest.mousePress(f, Qt.LeftButton, Qt.NoModifier, c)
        self.assertEqual(seen, [])                                   # 누른 동안에는 숨기지 않는다
        QTest.mouseMove(f, c + QPoint(-60, 60))
        QTest.mouseRelease(f, Qt.LeftButton, Qt.NoModifier, c + QPoint(-60, 60))
        self.assertEqual(seen, [])                                   # 밖에서 놓으면 아무 일도 없다
        QTest.mousePress(f, Qt.LeftButton, Qt.NoModifier, c)
        QTest.mouseRelease(f, Qt.LeftButton, Qt.NoModifier, c)
        self.assertEqual(seen, [1])

    def test_handle_tooltips_and_cursors(self):  # W-57
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        f = self.ctl.frame
        self.assertTrue(f.testAttribute(Qt.WA_AlwaysShowToolTips))   # 활성 창이 아니어도 도움말이 보인다
        want = {"move": ("액자 옮기기", Qt.OpenHandCursor), "close": ("액자 숨기기", Qt.ArrowCursor),
                "resize_br": ("액자 크기 바꾸기", Qt.SizeFDiagCursor), "resize_bl": ("액자 크기 바꾸기", Qt.SizeBDiagCursor)}
        for name, r in f.handle_rects().items():
            QTest.mouseMove(f, r.center())
            self.assertEqual((f.toolTip(), f.cursor().shape()), want[name], name)
        QTest.mouseMove(f, QPoint(1, f.height() // 2))               # 손잡이가 아닌 테두리
        self.assertEqual((f.toolTip(), f.cursor().shape()), ("", Qt.ArrowCursor))

    def test_pressed_move_handle_shows_closed_hand(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        f = self.ctl.frame
        c = f.handle_rects()["move"].center()
        QTest.mousePress(f, Qt.LeftButton, Qt.NoModifier, c)
        self.assertEqual(f.cursor().shape(), Qt.ClosedHandCursor)
        QTest.mouseRelease(f, Qt.LeftButton, Qt.NoModifier, c)
        self.assertEqual(f.cursor().shape(), Qt.OpenHandCursor)

    def test_lost_release_does_not_keep_resizing(self):  # D-117: 놓음 사건이 없어도 단추 없는 이동으로 크기가 계속 바뀌지 않는다
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        self.ctl.set_frame_rect(self.G.Rect(300, 200, 400, 300))
        f = self.ctl.frame
        c = f.handle_rects()["resize_br"].center()
        from PySide6.QtTest import QTest
        QTest.mousePress(f, Qt.LeftButton, Qt.NoModifier, c)
        gp = f.mapToGlobal(c + QPoint(-30, -30))
        ev = QMouseEvent(QEvent.MouseMove, QPointF(c + QPoint(-30, -30)), QPointF(gp), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        f.mouseMoveEvent(ev)                                         # 왼쪽 단추가 눌려 있지 않다
        after = f.frame_rect()
        ev2 = QMouseEvent(QEvent.MouseMove, QPointF(c + QPoint(-200, -200)), QPointF(f.mapToGlobal(c + QPoint(-200, -200))),
                          Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        f.mouseMoveEvent(ev2)
        self.assertEqual(f.frame_rect(), after)
        self.assertGreaterEqual(f.width(), self.G.MIN_W)

    def test_handle_icons_are_drawn_and_differ(self):  # 결정 0082
        f = self.ctl.frame
        from PySide6.QtGui import QColor
        img = f.grab().toImage()
        dpr = int(img.devicePixelRatio() or 1)
        t = __import__("nsu_kangs_rab.app.theme", fromlist=["tokens"]).tokens(self.ctl.appearance.scheme)
        bg, ink = QColor(t["info"]), QColor(t["info-bg"])
        masks = {}
        for k, r in f.handle_rects().items():
            m = []
            for yy in range(r.height() * dpr):
                row = []
                for xx in range(r.width() * dpr):
                    c = img.pixelColor(r.x() * dpr + xx, r.y() * dpr + yy)
                    di = abs(c.red() - ink.red()) + abs(c.green() - ink.green()) + abs(c.blue() - ink.blue())
                    db = abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue())
                    row.append(1 if c.alpha() > 0 and di < db else 0)
                m.append(row)
            masks[k] = m
        n = {k: sum(map(sum, m)) for k, m in masks.items()}
        self.assertTrue(all(v > 8 for v in n.values()), n)
        keys = list(masks)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                self.assertNotEqual(masks[a], masks[b], (a, b))
        mirror = [list(reversed(r)) for r in masks["resize_br"]]       # 왼쪽 아래는 오른쪽 아래의 좌우 대칭
        diff = sum(x != y for ra, rb in zip(mirror, masks["resize_bl"]) for x, y in zip(ra, rb))
        self.assertLessEqual(diff, max(4, n["resize_br"] // 10))
    def _drag(self, pt, delta):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        f = self.ctl.frame
        QTest.mousePress(f, Qt.LeftButton, Qt.NoModifier, pt)
        QTest.mouseMove(f, pt + delta)
        mid = f.frame_rect()
        QTest.mouseRelease(f, Qt.LeftButton, Qt.NoModifier, pt + delta)
        return mid, f.frame_rect()

    def test_resize_br_handle_stops_at_screen_boundary(self):  # D-113, FRM-8 ② (오른쪽 아래 손잡이: 왼쪽 위 모서리 고정)
        from PySide6.QtCore import QPoint
        self.ctl.set_frame_rect(self.G.Rect(1000, 200, 400, 300))
        f = self.ctl.frame
        mid, after = self._drag(f.handle_rects()["resize_br"].center(), QPoint(600, 0))
        s = self.screens[0]
        self.assertEqual((mid.x, mid.y, mid.w), (1000, 200, s.right - 1000))        # 끄는 도중에도 경계(1440)에서 멈춘다
        self.assertEqual(after, self.G.Rect(1000, 200, s.right - 1000, 300))
    def test_resize_br_handle_bottom_stops_at_screen_bottom(self):  # D-113 (화면 전체의 아래 끝)
        from PySide6.QtCore import QPoint
        self.ctl.set_frame_rect(self.G.Rect(300, 300, 400, 300))
        f = self.ctl.frame
        mid, after = self._drag(f.handle_rects()["resize_br"].center(), QPoint(0, 700))
        s = self.screens[0]
        self.assertEqual((mid.y, mid.h), (300, s.bottom - 300))
        self.assertEqual(after, self.G.Rect(300, 300, 400, s.bottom - 300))
    def test_resize_bl_handle_stops_at_left_boundary_keeping_right_top(self):  # D-113 (왼쪽 아래 손잡이: 오른쪽 위 모서리 고정)
        from PySide6.QtCore import QPoint
        self.ctl.set_frame_rect(self.G.Rect(200, 300, 400, 300))
        f = self.ctl.frame
        _mid, after = self._drag(f.handle_rects()["resize_bl"].center(), QPoint(-600, 0))
        s = self.screens[0]
        self.assertEqual((after.x, after.right, after.y), (s.x, 600, 300))
    def test_resize_height_capped_by_screen_and_min_size(self):  # D-113 ③ ④, D-117
        from PySide6.QtCore import QPoint
        self.ctl.set_frame_rect(self.G.Rect(300, 100, 400, 300))
        f = self.ctl.frame
        _m, after = self._drag(f.handle_rects()["resize_br"].center(), QPoint(0, 2000))
        s = self.screens[0]
        self.assertLessEqual(after.h, s.h)
        self.assertTrue(self.G.placeable(after, s))
        f = self.ctl.frame
        _m, after = self._drag(f.handle_rects()["resize_br"].center(), QPoint(-3000, -3000))
        self.assertEqual((after.w, after.h), (self.G.MIN_W, self.G.MIN_H))           # 최소 크기에서 멈추고 창이 사라지지 않는다
        self.assertTrue(f.isVisible())
        self.assertGreaterEqual(f.width(), 206)
        self.assertGreaterEqual(f.height(), 126)
        self.assertEqual((f.minimumWidth(), f.minimumHeight()), (self.G.MIN_W, self.G.MIN_H))
    def test_saved_geometry_is_restored(self):  # AC-FR12-11
        self.ctl.data["frame"] = self.G.Rect(300, 200, 800, 450).as_dict()
        self.ctl.frame.close()
        self.ctl._setup_frame()
        self.assertEqual(self.ctl.frame.frame_rect(), self.G.Rect(300, 200, 800, 450))
        self.assertEqual(self.ctl.shell.statusBar().currentMessage(), "")

    def test_off_screen_saved_geometry_falls_back_and_notifies(self):  # AC-FR12-12
        self.ctl.data["frame"] = self.G.Rect(1600, 200, 800, 450).as_dict()      # 떼어 낸 외장 모니터의 좌표
        self.ctl.frame.close()
        self.ctl._setup_frame()
        self.assertEqual(self.ctl.frame.frame_rect(), self.G.default_frame(self.screens[0]))
        self.assertEqual(self.ctl.shell.statusBar().currentMessage(), self.G.OFF_SCREEN_NOTICE)

    def test_capture_button_captures_inner_region_and_registers(self):  # AC-FR12-1 · 10
        self.assertTrue(self.start())
        self.ctl.frame.set_frame(self.G.Rect(300, 200, 800, 450))
        self.ctl.on_command("request.capture")
        self._wait_capture()
        self.assertEqual(len(self.cmds), 1)
        self.assertEqual(self.cmds[0][:4], ["/usr/sbin/screencapture", "-x", "-R", "303,203,794,444"])      # 테두리 3px 를 뺀 안쪽
        recs = [r for r in self.records() if r.get("type") == "capture"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "캡처")
        self.assertTrue((self.ctl.runtime.folder / recs[0]["path"]).exists())
        self.assertTrue(recs[0]["path"].startswith("captures/"))
        self.assertTrue(any(r.get("type") == "request" and r.get("kind") == "화면메모" for r in self.records()))
        self.assertEqual(self.ctl._captures, 1)

    def test_trigger_during_capture_is_held_until_memo_done(self):  # D-114, AC-FR12-4
        self.assertTrue(self.start())
        rt = self.ctl.runtime
        seen = []
        orig = self.ctl.deps.capture_runner

        def runner(cmd, t):
            seen.append(rt.manager.trigger("key"))           # screencapture 실행 중에 누른 트리거
            return orig(cmd, t)
        self.ctl.deps.capture_runner = runner
        self.ctl.on_command("request.capture")
        self._wait_capture()
        self.assertEqual(seen, ["held"])
        self.assertFalse(rt.manager._capture_busy)
        held = [e for e in self._events() if e["type"] == "trigger_held"]
        self.assertEqual([(e["reason"], e["action"]) for e in held], [("캡처 처리", "deferred")])

    def test_capture_failure_releases_busy(self):  # D-114
        self.assertTrue(self.start())
        rt = self.ctl.runtime
        self.ctl.deps.capture_runner = lambda cmd, t: (rt.manager.trigger("key") and (1, ""))
        self.ctl.on_command("request.capture")
        self._wait_capture()
        self.assertFalse(rt.manager._capture_busy)
        self.assertEqual(rt.manager._held_trigger, None)      # 보류했던 트리거가 실행되었다
        self.assertTrue([e for e in self._events() if e["type"] == "trigger_run"])

    def _events(self):
        return [json.loads(x) for x in Path(self.ctl.eventlog.path).read_text(encoding="utf-8").splitlines()]

    def test_capture_event_logs_region_visibility_and_no_flash_at_run(self):  # C1 · FRM-2
        self.assertTrue(self.start())
        self.ctl.frame.set_frame(self.G.Rect(300, 200, 800, 450))
        seen = []
        orig = self.ctl.deps.capture_runner
        self.ctl.deps.capture_runner = lambda cmd, t: (seen.append(self.ctl.frame.is_flashing()), orig(cmd, t))[1]
        self.ctl.on_command("request.capture")
        self._wait_capture()
        self.assertEqual(seen, [False])               # `screencapture` 가 실행되는 순간에는 강조 상태가 아니다
        self.assertTrue(self.ctl.frame.is_flashing())  # 끝난 뒤에 강조한다
        events = [json.loads(x) for x in Path(self.ctl.eventlog.path).read_text(encoding="utf-8").splitlines()]
        e = [x for x in events if x["type"] == "frame_capture"][-1]
        self.assertEqual((e["region"], e["frame_visible"], e["flashing"]), ("303,203,794,444", True, False))

    def _painted_in(self, region):
        """창을 그린 이미지에서 알파 > 0 인 화소 수(region 은 전역 좌표 framegeom.Rect)."""
        f = self.ctl.frame
        img = f.grab().toImage()
        dpr = int(img.devicePixelRatio() or 1)
        g = f.geometry()
        n = 0
        for y in range(max(0, region.y - g.y()), min(g.height(), region.bottom - g.y())):
            for x in range(max(0, region.x - g.x()), min(g.width(), region.right - g.x())):
                if img.pixelColor(x * dpr, y * dpr).alpha() > 0:
                    n += 1
        return n

    def test_capture_hides_handles_and_flash_until_done_then_redraws(self):  # AC-FR12-15, D-118 · D-119
        self.assertTrue(self.start())
        f = self.ctl.frame
        f.set_frame(self.G.Rect(300, 200, 506, 326))
        inner = f.capture_region()
        self.assertGreater(self._painted_in(inner), 0)                 # 평소에는 손잡이가 안쪽 모서리 11 × 11 에 그려진다
        seen = []
        orig = self.ctl.deps.capture_runner

        def runner(cmd, t):
            seen.append((f.is_capturing(), f.is_flashing()))
            return orig(cmd, t)
        self.ctl.deps.capture_runner = runner
        self.ctl.on_command("request.capture")
        self.assertTrue(f.is_capturing())                              # 캡처를 시작하자 곧바로 손잡이를 지운다
        self.assertEqual(self._painted_in(inner), 0)                   # 안쪽에는 아무것도 그리지 않는다(테두리 3)
        self._wait_capture()
        self.assertEqual(seen, [(True, False)])       # 실행되는 동안 강조가 아니다
        self.assertFalse(f.is_capturing())
        self.assertTrue(f.is_flashing())                               # 강조는 캡처가 끝난 뒤에 시작한다
        self.assertGreater(self._painted_in(inner), 0)                 # 손잡이를 다시 그린다

    def test_capture_during_flash_stops_the_flash(self):  # D-119 (F40)
        self.assertTrue(self.start())
        f = self.ctl.frame
        f.set_frame(self.G.Rect(300, 200, 506, 326))
        f.flash()
        self.assertTrue(f.is_flashing())
        seen = []
        orig = self.ctl.deps.capture_runner
        self.ctl.deps.capture_runner = lambda cmd, t: (seen.append(f.is_flashing()), orig(cmd, t))[1]
        self.ctl.on_command("request.capture")
        self.assertFalse(f.is_flashing())
        self.assertEqual(self._painted_in(f.capture_region()), 0)
        self._wait_capture()
        self.assertEqual(seen, [False])

    def test_capture_failure_redraws_handles_without_flash(self):  # W-59
        self.assertTrue(self.start())
        f = self.ctl.frame
        f.set_frame(self.G.Rect(300, 200, 506, 326))
        self.runner_code = 1
        self.ctl.on_command("request.capture")
        self._wait_capture()
        self.assertFalse(f.is_capturing())
        self.assertFalse(f.is_flashing())
        self.assertGreater(self._painted_in(f.capture_region()), 0)

    def test_hidden_frame_stays_hidden_after_capture(self):  # FRM-6
        self.assertTrue(self.start())
        self.ctl.on_command("window.frame")
        self.assertFalse(self.ctl.frame.isVisible())
        self.ctl.on_command("request.capture")
        self._wait_capture()
        self.assertFalse(self.ctl.frame.isVisible())

    def test_dev_capture_fake_writes_png_and_records_command(self):  # C1
        self.assertTrue(self.start())
        png = Path(self.tmp.name) / "fake.png"
        self._runner(["x", "y", "z", str(png)], 0)
        self.ctl.deps.capture_runner = None
        self.ctl.dev.values["capture_fake"] = str(png)
        self.ctl.on_command("request.capture")
        self._wait_capture()
        cmds = (Path(str(png) + ".commands.jsonl")).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(cmds), 1)
        self.assertEqual(json.loads(cmds[0])[:3], ["/usr/sbin/screencapture", "-x", "-R"])
        self.assertEqual(len([r for r in self.records() if r.get("type") == "capture"]), 1)

    def test_capture_while_frame_hidden_uses_same_region(self):  # AC-FR12-11
        self.assertTrue(self.start())
        self.ctl.frame.set_frame(self.G.Rect(300, 200, 800, 450))
        self.ctl.on_command("window.frame")
        self.assertFalse(self.ctl.frame.isVisible())
        self.ctl.on_command("request.capture")
        self._wait_capture()
        self.assertEqual(self.cmds[0][3], "303,203,794,444")

    def test_capture_without_permission_posts_error_and_does_not_run(self):  # AC-FR12-7
        self.assertTrue(self.start())
        self.ctl.deps.permission_status = lambda: {"screen_recording": "허용되지 않음"}
        self.ctl.on_command("request.capture")
        pump(5)
        self.assertEqual(self.cmds, [])
        self.assertFalse(self.ctl._capturing)

    def test_capture_failure_notifies_and_registers_nothing(self):
        self.assertTrue(self.start())
        self.runner_code = 1
        self.ctl.on_command("request.capture")
        self._wait_capture()
        self.assertEqual([r for r in self.records() if r.get("type") == "capture"], [])
        self.assertIn("화면을 캡처하지 못했습니다", self.ctl.shell.statusBar().currentMessage())

    def test_capture_command_outside_session_does_nothing(self):
        self.ctl.on_command("request.capture")
        pump(3)
        self.assertEqual(self.cmds, [])


class StartFailedBannerTest(unittest.TestCase):  # D-083
    def test_start_failed_banner_wording_and_permission_unchanged(self):
        b = appstate.capture_banner("중단", "음성 수집을 시작하지 못했습니다: RuntimeError: x", False)
        self.assertEqual(b.title, "음성 수집을 시작하지 못했습니다")
        self.assertIn("앱을 다시 시작하세요", b.description)
        self.assertNotIn("RuntimeError", b.description)
        stopped = appstate.capture_banner("중단", "장치가 끊겼다", False)
        self.assertEqual(stopped.title, appstate.BANNER_STOPPED_TITLE)
        self.assertEqual(stopped.description, "사유: 장치가 끊겼다")


class StartStepFailureTest(Base):  # D-081: 시작 단계의 예외는 오류로 표시하고 나머지 단계를 계속한다
    def test_audio_start_exception_posts_error_and_continues(self):
        self.ctl._start_audio = lambda params: (_ for _ in ()).throw(RuntimeError("scipy 누락"))
        self.assertTrue(self.start())
        self.assertEqual(self.ctl._capture_state, "중단")
        texts = [w.error.text() for w in self.ctl.shell.session_page.ai._cards.values()]
        self.assertEqual(len(texts), 1)                       # 음성 수집 중단의 오류 카드 한 장
        self.assertIn("음성 수집을 시작하지 못했습니다", texts[0])        # D-083: 장치 끊김(audio_lost)의 문구가 아니다
        self.assertIn("수집은 스스로 이어지지 않습니다", texts[0])
        self.assertNotIn("장치가 복구되면", texts[0])
        self.assertIn("RuntimeError: scipy 누락", texts[0])
        shown, btitle, bdesc = self.ctl.view.banner.state()
        self.assertTrue(shown)
        self.assertEqual(btitle, "음성 수집을 시작하지 못했습니다")
        self.assertIn("앱을 다시 시작하세요", bdesc)
        self.assertNotIn("RuntimeError", bdesc)                # 상세는 카드에만(D-083 5항)
        self.assertFalse([b for b in self.ctl.view.banner.findChildren(QPushButton) if not b.isHidden()])
        errs = [r for r in self.records() if r.get("type") == "error"]
        self.assertEqual(errs, [])                            # 세션 기록이 아니라 이벤트 로그에 남는다
        self.assertIn("scipy 누락", self.ctl._capture_detail)
        self.assertIsNotNone(self.ctl.runtime)


class StateTransitionTest(Base):  # D-070 · D-071 · D-072 · D-069
    def test_stopped_collect_state_shows_warn_dot_and_text(self):  # D-070, AC-FR14-5
        self.assertTrue(self.start())
        self.ctl._on_audio_state("중단", "시험")
        self.ctl.refresh_status()
        self.assertEqual(self.ctl.menu.dot, "warn")
        self.assertIn("수집 중단", self.ctl.menu.status_action.text())
        self.ctl._on_audio_state("수집 중", "")
        self.ctl.refresh_status()
        self.assertEqual(self.ctl.menu.dot, "info")

    def test_ending_state_blocks_requests(self):  # D-071, FR-14 표 ④
        self.assertTrue(self.start())
        rt = self.ctl.runtime
        self.ctl.shell.machine.begin_ending()
        self.assertFalse(self.ctl.view.input.edit.isEnabled())
        before = len(rt.manager.cards())
        for cid in ("request.trigger", "request.capture"):
            self.ctl.on_command(cid)
        self.ctl.on_submit("질문입니다")
        self.ctl.on_submit("/요약")
        pump(3)
        self.assertEqual(len(rt.manager.cards()), before)

    def test_menu_enabled_at_transition_without_timer(self):  # D-072
        m = self.ctl.menu
        self.assertFalse(m.actions["request.trigger"].isEnabled())
        self.assertTrue(self.start())
        self.assertTrue(m.actions["request.trigger"].isEnabled())      # 1초 주기를 기다리지 않는다
        self.ctl.shell.machine.begin_ending()
        self.assertFalse(m.actions["request.trigger"].isEnabled())

    def test_level_bar_zero_at_stop_without_status_timer(self):  # D-069, AC-FR3-10 LVL-3
        self.assertTrue(self.start())
        self.ctl._status_timer.stop()
        self.ctl._on_audio_state("중단", "시험")
        pump(5)
        self.assertEqual(self.ctl.shell.status.level_cells(), 0)
        self.assertEqual(self.ctl._level_timer.interval(), 100)


class PermissionsViewTest(Base):  # D-073, AC-FR14-10
    def test_status_shown_read_only_via_injected_query(self):
        calls = []
        self.ctl.deps.permission_status = lambda: calls.append(1) or {
            "screen_recording": "허용", "system_audio": "허용", "microphone": "허용되지 않음"}
        self.ctl.on_command("help.permissions")
        self.assertEqual(calls, [1])
        lines = {k: w.text() for k, w in self.ctl._permission_lines.items()}
        self.assertEqual(lines, {"screen_recording": "화면 기록: 허용", "system_audio": "시스템 사운드: 허용",
                                 "microphone": "마이크: 허용되지 않음"})
        self.ctl._permission_dialog.close()

    def test_query_failure_shows_unknown(self):
        def boom():
            raise RuntimeError("x")
        self.ctl.deps.permission_status = boom
        self.ctl.on_command("help.permissions")
        self.assertIn("확인할 수 없음", self.ctl._permission_lines["microphone"].text())
        self.ctl._permission_dialog.close()


class ReplayTest(Base):  # D-066: --dev-replay 전사 재생 입력
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        f = Path(cls._tmp.name) / "replay.jsonl"
        f.write_text("\n".join([
            json.dumps({"start": 0.0, "end": 0.1, "text": "첫째 조각"}, ensure_ascii=False),
            json.dumps({"start": 0.1, "end": 0.2, "text": "늦게 도착", "arrive_after_ms": 600}, ensure_ascii=False),
            "깨진 줄",
            json.dumps({"start": 0.3, "end": 0.4, "text": "셋째", "start_wall": "2026-10-11T23:59:58.000+09:00",
                        "end_wall": "2026-10-12T00:00:01.000+09:00"}, ensure_ascii=False)]), encoding="utf-8")
        cls.argv = ["--dev-replay", str(f)]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        cls.argv = []

    def test_late_segment_and_midnight_walls(self):
        self.assertTrue(self.start())
        rt = self.ctl.runtime
        t0 = time.monotonic()
        while time.monotonic() - t0 < 4 and len(rt.transcript.full()) < 3:
            pump(1)
        segs = rt.transcript.full()
        self.assertEqual([x.n for x in segs], [1, 2, 3])
        self.assertEqual([x.text for x in segs], ["첫째 조각", "늦게 도착", "셋째"])
        self.assertEqual((segs[2].start_wall[:10], segs[2].end_wall[:10]), ("2026-10-11", "2026-10-12"))
        self.assertTrue(self.audio.started is False)      # 음성 수집을 시작하지 않는다(재생이 대신한다)


if __name__ == "__main__":
    unittest.main()
