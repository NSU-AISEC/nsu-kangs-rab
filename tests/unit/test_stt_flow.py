# -*- coding: utf-8 -*-
"""음성 인식 보조 프로세스(`stt_speech`) 연동의 앱 쪽 흐름 (결정 0162 · 0166 · 0167, 기술 계획 2-8-4절).

가짜 보조 프로세스(`media/fakes/fake_stt_speech.py`)의 시나리오로 준비 칩, 종료 처리표, [다시 시도], 로캘 회색 처리를 확인한다.
실제 macOS 엔진 · 마이크 · `claude` 는 쓰지 않는다."""
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QCoreApplication  # noqa: E402

import test_app_controller as T  # noqa: E402
from nsu_kangs_rab.app import controller as C  # noqa: E402
from nsu_kangs_rab.core import languages  # noqa: E402

READY = [{"at_s": 0, "emit": {"type": "locales", "list": ["ko_KR", "en_US"]}},
         {"at_s": 0, "emit": {"type": "asset", "state": "installed", "installed": True}},
         {"at_s": 0, "emit": {"type": "ready"}}]


def asset(at, state, fraction=None):
    d = {"type": "asset", "state": state}
    if fraction is not None:
        d["fraction"] = fraction
    return {"at_s": at, "emit": d}


def wait_for(cond, timeout_s=8.0):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


class SttFlowBase(T.Base):
    def setUp(self):
        super().setUp()
        self.sc = str(Path(self.tmp.name) / "scenario.json")
        self.ctl._auto_play_ok = False                    # 준비가 끝나기 전에 [재생] 을 누르지 않는다(시험이 직접 정한다)

    def scenario(self, data):
        with io.open(self.sc, "w", encoding="utf-8") as f:
            json.dump(data, f)
        for suf in (".rec.jsonl", ".count", ".list_count"):
            try:
                os.remove(self.sc + suf)
            except OSError:
                pass
        self.ctl.deps.stt_helper = lambda: ([sys.executable, T.FAKE_STT], ["--scenario", self.sc])

    def starts_args(self):
        out = []
        try:
            f = io.open(self.sc + ".rec.jsonl", encoding="utf-8")
        except OSError:
            return out
        with f:
            for line in f:
                d = json.loads(line)
                if "args" in d:
                    out.append(d["args"])
        return out


class PrepChipTest(SttFlowBase):
    def test_percent_truncated_capped_and_never_shrinks_and_play_blocked(self):
        self.scenario({"starts": [[asset(0, "checking"), asset(0.1, "downloading", 0.5),
                                   asset(0.2, "downloading", 0.999), asset(0.3, "downloading", 0.2)]]})
        self.assertTrue(self.start())
        self.assertTrue(wait_for(lambda: self.ctl._stt_prep_pct == 99))
        time.sleep(0.5)
        T.pump()
        self.assertEqual(self.ctl._stt_prep_pct, 99)                 # 0.999 → 99, 0.2 로 줄지 않는다
        self.assertIn("99", self.ctl._stt_prep)
        self.assertTrue(self.ctl.view.transport.play_blocked())
        self.assertFalse(self.ctl._stt_ready)

    def test_downloading_without_fraction_shows_plain_chip_and_installed_shows_none(self):
        self.scenario({"starts": [[asset(0, "downloading"), asset(0.3, "installed")]]})
        self.assertTrue(self.start())
        self.assertTrue(wait_for(lambda: self.ctl._stt_prep is not None))
        first = self.ctl._stt_prep
        self.assertNotIn("%", first)
        self.assertTrue(wait_for(lambda: self.ctl._stt_prep is None))        # installed: 칩이 없다
        self.assertTrue(self.ctl.view.transport.play_blocked())              # ready 전까지 [재생] 은 꺼져 있다

    def test_ready_clears_chip_and_unblocks_play(self):
        self.scenario({"starts": [[asset(0, "downloading", 0.4)] + [dict(s, at_s=0.3) for s in READY]]})
        self.assertTrue(self.start())
        self.assertTrue(T.wait_stt_ready(self.ctl))
        self.assertIsNone(self.ctl._stt_prep)
        self.assertEqual(self.ctl._stt_prep_pct, -1)
        self.assertFalse(self.ctl.view.transport.play_blocked())


class ExitTableTest(SttFlowBase):
    def _exit_reason(self, code):
        self.scenario({"starts": [[{"at_s": 0.1, "exit_code": code}]]})
        self.assertTrue(self.start())
        self.assertTrue(wait_for(lambda: self.ctl._stt_exit is not None))
        return self.ctl.view.stt_guide_state()

    def test_unsupported_locale_has_no_retry(self):
        mode, _t, _b, shown, _on = self._exit_reason(1)
        self.assertEqual((mode, self.ctl._stt_exit, shown), ("error", "unsupported_locale", False))

    def test_os_too_old_has_no_retry(self):
        mode, _t, _b, shown, _on = self._exit_reason(4)
        self.assertEqual((mode, self.ctl._stt_exit, shown), ("error", "os_too_old", False))

    def test_asset_failed_has_retry(self):
        mode, _t, _b, shown, on = self._exit_reason(2)
        self.assertEqual((mode, self.ctl._stt_exit, shown, on), ("error", "asset_failed", True, True))

    def test_analyzer_error_has_retry(self):
        mode, _t, _b, shown, on = self._exit_reason(3)
        self.assertEqual((mode, self.ctl._stt_exit, shown, on), ("error", "analyzer_error", True, True))


class RetryTest(SttFlowBase):
    def test_exit_after_ready_in_collection_shows_band_with_retry_then_retry_resumes(self):
        first = READY + [{"at_s": 0.6, "exit_code": 2}]          # ready 뒤의 어떤 사유도 analyzer_error 로 본다
        second = [dict(s, at_s=0.1) for s in READY]
        self.scenario({"starts": [first, second]})
        self.assertTrue(self.start())
        self.assertTrue(T.wait_stt_ready(self.ctl))
        self.ctl.play_capture()
        T.pump()
        self.assertTrue(wait_for(lambda: self.ctl._stt_exit is not None))
        self.assertEqual(self.ctl._stt_exit, "analyzer_error")
        shown, title, desc = self.ctl.view.banner.state()
        self.assertTrue(shown)
        self.assertTrue([b for b in self.ctl.view.banner.findChildren(T.QPushButton) if not b.isHidden()])      # [다시 시도]
        self.ctl.retry_stt()
        self.assertTrue(self.ctl._stt_retrying)
        self.assertTrue(wait_for(lambda: self.ctl._stt_ready and self.ctl._stt_exit is None))
        self.assertFalse(self.ctl._stt_retrying)
        args = self.starts_args()
        self.assertEqual(len(args), 2)
        self.assertIn("--start-n", args[1])
        self.assertEqual(args[1][args[1].index("--start-n") + 1], "1")             # 도착한 조각이 없으므로 1 에서 이어 간다

    def test_retry_timeout_reenables_button(self):
        first = [{"at_s": 0.1, "exit_code": 3}]
        second = []                                                # ready 도 종료도 없다
        self.scenario({"starts": [first, second]})
        self.assertTrue(self.start())
        self.assertTrue(wait_for(lambda: self.ctl._stt_exit is not None))
        self.ctl.retry_stt()
        self.assertTrue(self.ctl._stt_retrying)
        self.assertFalse(self.ctl.view.stt_guide_state()[4])        # 기다리는 동안 단추는 꺼진다
        self.ctl._on_retry_timeout()                               # 30초 시간 제한(타이머는 직접 호출한다)
        self.assertFalse(self.ctl._stt_retrying)
        self.assertTrue(self.ctl.view.stt_guide_state()[4])

    def test_retry_ignored_for_non_retryable_reason(self):
        self.scenario({"starts": [[{"at_s": 0.1, "exit_code": 1}]]})
        self.assertTrue(self.start())
        self.assertTrue(wait_for(lambda: self.ctl._stt_exit is not None))
        self.ctl.retry_stt()
        self.assertFalse(self.ctl._stt_retrying)


class EmptyFinalTest(SttFlowBase):
    def test_blank_final_closes_open_section_and_clears_partial_row(self):
        # 잠정은 첫 끊기(C)에, 빈 확정은 두 번째 끊기에 낸다: [재생] 시각이나 실행 부하와 관계없이 순서가 같다(D-180)
        part = {"type": "partial", "text": "안녕", "start_mono": 0.0, "end_mono": 0.5}
        self.scenario({"starts": [READY + [{"after_cut": {"n": 1, "s": 0.0}, "emit": part},
                                           {"after_cut": {"n": 2, "s": 0.0},
                                            "emit": {"type": "final", "text": "   ", "start_mono": 0.0, "end_mono": 0.5}}]]})
        self.assertTrue(self.start())
        self.assertTrue(T.wait_stt_ready(self.ctl))
        self.ctl.play_capture()
        tr = self.ctl.view.transcript
        self.ctl.runtime.stt_cut()                                 # 첫 C: 가짜가 잠정을 낸다
        self.assertTrue(wait_for(lambda: tr.partial_text() == "안녕"))
        self.assertIsNotNone(self.ctl.runtime.transcript._open)
        self.ctl.runtime.stt_cut()                                 # 두 번째 C: 빈 final
        self.assertTrue(wait_for(lambda: tr.partial_text() is None))
        self.assertIsNone(self.ctl.runtime.transcript._open)


class PauseCutPartialTest(SttFlowBase):                            # D-177, AC-FR7-14 ⓖ
    argv = ["--dev-final-wait-cap-s", "0.6"]

    def _partial(self):
        now = time.monotonic()
        w = "2026-10-24T04:00:00.000+09:00"
        from nsu_kangs_rab.core.types import PartialSegment
        self.ctl.runtime.on_partial(PartialSegment("끊긴잠정고유어", now - 2.0, now - 1.0), w, w)

    def _start_playing(self):
        self.scenario({"starts": [READY]})
        self.assertTrue(self.start())
        self.assertTrue(T.wait_stt_ready(self.ctl))
        self.ctl.play_capture()

    def _sent_texts(self):
        return [m.blocks[0].get("text", "") for m in self.model.sent if getattr(m, "blocks", None)]

    def test_pause_during_wait_does_not_send_cut_partial(self):
        self._start_playing()
        self._partial()
        self.ctl.menu.command.emit("request.trigger")
        T.pump()
        self.assertEqual(len(self.model.sent), 0)                  # 확정을 기다리는 중이다
        self.assertTrue(self.ctl.pause_capture())
        self.assertTrue(wait_for(lambda: len(self.model.sent) == 1, 5.0))
        self.assertNotIn("[잠정]", self._sent_texts()[0])
        self.assertNotIn("끊긴잠정고유어", self._sent_texts()[0])

    def test_request_during_pause_does_not_send_cut_partial(self):
        self._start_playing()
        self._partial()
        self.assertTrue(self.ctl.pause_capture())
        self.ctl.menu.command.emit("request.trigger")
        self.assertTrue(wait_for(lambda: len(self.model.sent) == 1, 5.0))
        self.assertNotIn("끊긴잠정고유어", self._sent_texts()[0])

    def test_without_pause_partial_is_sent_after_cap(self):       # 대조: 일시 정지가 없으면 상한 뒤 `[잠정]` 이 나간다
        self._start_playing()
        self._partial()
        self.ctl.menu.command.emit("request.trigger")
        self.assertTrue(wait_for(lambda: len(self.model.sent) == 1, 5.0))
        self.assertIn("[잠정]", self._sent_texts()[0])

    def test_transcript_abandon_keeps_waiting_for_final_and_drops_partial_at_cap(self):
        from nsu_kangs_rab.core.transcript import Transcript
        t = Transcript()
        w = "2026-10-24T04:00:00.000+09:00"
        t.set_open("x", w, w, 0.0, 1.0)
        t.abandon_open()
        self.assertIsNone(t.partial_for(5.0))
        self.assertIsNotNone(t.open_for(5.0))                      # 확정은 계속 기다린다
        self.assertIsNone(t.wait_final(5.0, 0.1))                  # 상한 뒤에도 잠정을 돌려주지 않는다
        t.set_open("y", w, w, 0.0, 1.0)                            # 새 잠정은 끊긴 표시를 지운다
        self.assertIsNotNone(t.partial_for(5.0))


class ResumeStaleTest(PauseCutPartialTest):                        # 권고 62
    argv = ["--dev-final-wait-cap-s", "3.0"]

    def test_request_after_resume_sends_at_once_without_cut_partial(self):
        self._start_playing()
        self._partial()
        self.assertTrue(self.ctl.pause_capture())
        T.pump()
        self.ctl.play_capture()
        T.pump()
        t0 = time.monotonic()
        self.ctl.menu.command.emit("request.trigger")
        self.assertTrue(wait_for(lambda: len(self.model.sent) == 1, 2.0))
        self.assertLess(time.monotonic() - t0, 1.5)                # 대기 상한(3.0초)을 기다리지 않는다
        self.assertNotIn("끊긴잠정고유어", self._sent_texts()[0])
        self.assertNotIn("[잠정]", self._sent_texts()[0])

    def test_transcript_resume_open_marks_stale_and_late_final_still_accepted(self):
        from nsu_kangs_rab.core.transcript import Transcript
        t = Transcript()
        w = "2026-10-24T04:00:00.000+09:00"
        t.set_open("x", w, w, 0.0, 1.0)
        t.resume_open()                                            # 끊기지 않은 구간은 영향이 없다
        self.assertIsNotNone(t.open_for(5.0))
        t.abandon_open()
        t.resume_open()
        self.assertIsNone(t.open_for(5.0))
        t0 = time.monotonic()
        self.assertIsNone(t.wait_final(5.0, 3.0, cut=lambda: self.fail("끊기 신호를 보내지 않는다")))
        self.assertLess(time.monotonic() - t0, 0.5)
        self.assertTrue(t.add(T.seg(1, 0, 1)))                     # 늦은 확정은 조각으로 받는다
        t.set_open("y", w, w, 0.0, 1.0)                            # 새 잠정은 진행 중 구간이다
        self.assertIsNotNone(t.open_for(5.0))


class RetryFailTest(SttFlowBase):                                  # D-179
    def test_second_start_exit_before_ready_reenables_band_retry(self):
        first = READY + [{"at_s": 0.6, "exit_code": 3}]
        second = [{"at_s": 0.1, "exit_code": 3}]                    # ready 전에 끝난다
        third = [dict(s, at_s=0.1) for s in READY]
        self.scenario({"starts": [first, second, third]})
        self.assertTrue(self.start())
        self.assertTrue(T.wait_stt_ready(self.ctl))
        self.ctl.play_capture()
        self.assertTrue(wait_for(lambda: self.ctl._stt_exit is not None))
        self.ctl.retry_stt()
        self.assertTrue(wait_for(lambda: len(self.starts_args()) == 2 and not self.ctl._stt_retrying and self.ctl._stt_exit is not None))
        vis, on = self.ctl.view.banner.retry_state()
        self.assertEqual((vis, on), (True, True))
        self.assertIsNotNone(self.ctl._stt_band)
        self.ctl.retry_stt()                                       # 세 번째 시작
        self.assertTrue(wait_for(lambda: self.ctl._stt_ready and self.ctl._stt_exit is None))
        self.assertEqual(len(self.starts_args()), 3)


class PrepHundredTest(SttFlowBase):                                # D-178
    def test_fraction_one_shows_100_percent(self):
        self.scenario({"starts": [[asset(0, "downloading", 0.999), asset(0.2, "downloading", 1.0)]]})
        self.assertTrue(self.start())
        self.assertTrue(wait_for(lambda: self.ctl._stt_prep_pct == 100))
        self.assertIn("100", self.ctl._stt_prep)


class LocaleGreyTest(SttFlowBase):
    def test_unsupported_locales_grey_and_failure_greys_nothing(self):
        self.ctl.deps.list_locales = lambda cmd, timeout: ["ko_KR", "en_US"]
        self.ctl._sync_language_settings()                         # 시작 화면을 열 때(결정 0179)
        self.assertTrue(wait_for(lambda: self.ctl._stt_locales is not None))
        form = self.ctl.shell.start_page
        T.pump()
        grey = form.unsupported_locale_codes()
        self.assertNotIn("ko", grey)
        self.assertNotIn("en", grey)
        self.assertEqual(grey, {c for c in languages.CODES if c not in ("ko", "en")})

    def test_lookup_failure_greys_nothing(self):
        self.ctl.deps.list_locales = lambda cmd, timeout: None
        self.ctl._sync_language_settings()
        self.assertTrue(wait_for(lambda: not self.ctl._stt_locales_loading))
        T.pump()
        self.assertEqual(self.ctl.shell.start_page.unsupported_locale_codes(), set())


class BundledHelperPathTest(unittest.TestCase):
    def test_bundled_path_none_outside_bundle_and_under_meipass_inside(self):
        from nsu_kangs_rab.core import resources
        self.assertIsNone(resources.bundled_stt_helper_path())
        sys._MEIPASS, sys.frozen = "/tmp/meipass_x", True
        try:
            self.assertEqual(str(resources.bundled_stt_helper_path()), "/tmp/meipass_x/helper/stt_speech")
        finally:
            del sys._MEIPASS, sys.frozen


class ClockLabelTest(unittest.TestCase):
    def test_width_cache_reset_on_font_change(self):
        from PySide6.QtGui import QFont
        from nsu_kangs_rab.app import mainview
        lab = mainview._ClockLabel()
        w1 = lab.sizeHint().width()
        self.assertGreater(lab._w, 0)
        f = QFont(lab.font())
        f.setPointSize(f.pointSize() + 12)
        lab.setFont(f)
        QCoreApplication.processEvents()
        self.assertGreater(lab.sizeHint().width(), w1)


if __name__ == "__main__":
    unittest.main()
