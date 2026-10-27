"""결정 0178 (AC-FR3-11 ① ~ ⑧ · AC-FR3-21 ④ · AC-FR3-22): 권한 없음으로 끝난 [재생] 은 수집 상태를 유지하고 권한 안내 띠를 표시한다.
가짜 수집 소스(`Src`)가 시도마다 정해 둔 동작(`script`)을 한다: deny = 권한 없음으로 중단, ok = 첫 음성 블록, hang = 아무 응답 없음."""
import json
import time
import unittest
from pathlib import Path

import numpy as np

import test_app_controller as T
from nsu_kangs_rab.platform.audio.system_sound import REASON_TEXT
from nsu_kangs_rab.platform.audio.types import PcmBlock


class Src:
    script: list = []
    instances: list = []

    def __init__(self, log):
        self.log, self.mode, self.starts, self.stopped = log, None, 0, False
        self.on_block = self.on_state = None
        Src.instances.append(self)

    def _go(self):
        self.mode = Src.script.pop(0) if Src.script else "ok"
        self.starts += 1
        if self.mode == "deny":
            self.on_state("중단", REASON_TEXT["no_permission"])
        elif self.mode == "ok":
            self.log.emit("capture_start", source="system_sound", device="fake", samplerate=16000, channels=1)
            self.on_block(PcmBlock(np.zeros(160, dtype=np.float32), 0.0))
            self.on_state("수집 중", "fake")

    def start(self, on_block, on_state=lambda s, d="": None):
        self.on_block, self.on_state = on_block, on_state
        self._go()

    def pause(self):
        pass

    def resume(self):
        self._go()
        return self.mode != "deny"

    def stop(self):
        self.stopped = True

    def level(self):
        return 0.0


class Base(T.Base):
    source = "system_sound"

    def setUp(self):
        T.AUTO_PLAY = False
        self.addCleanup(setattr, T, "AUTO_PLAY", True)
        Src.script, Src.instances = [], []
        super().setUp()
        self.ctl.deps.system_sound_factory = lambda log, helper: Src(log)
        self.ctl.deps.mic_factory = self.make_mic
        self.assertTrue(self.start(source=self.source))
        T.wait_stt_ready(self.ctl)
        T.pump()

    def make_mic(self, log):
        return Src(log)

    def events(self, kind):
        rows = [json.loads(x) for x in Path(self.ctl.eventlog.path).read_text(encoding="utf-8").splitlines()]
        return [e for e in rows if e["type"] == kind]

    def play(self):
        r = self.ctl.play_capture()
        T.pump(8)
        return r

    def banner(self):
        T.pump()
        return self.ctl.view.banner.state()


class FirstPlayDeniedTest(Base):
    def test_first_play_denied_keeps_before_and_shows_info_band(self):       # ①
        Src.script = ["deny"]
        self.assertFalse(self.play())
        self.assertEqual(self.ctl.capture_state(), "수집 전")
        self.assertTrue(self.ctl.view.transport.btn_play.isEnabled())
        shown, title, desc = self.banner()
        self.assertEqual((shown, title), (True, "화면 기록 권한이 필요합니다"))
        self.assertIn("화면 및 시스템 오디오 녹음", desc)
        self.assertEqual(self.ctl.view.banner.tone(), "info")
        self.assertFalse([b for b in self.ctl.view.banner.findChildren(T.QPushButton) if not b.isHidden()])   # 단추가 없다
        self.assertEqual(len(self.ctl.view.ai._cards), 0)                    # permission 오류 카드가 없다
        self.assertNotEqual(title, "음성 수집이 중단되었습니다")

    def test_events_numbering_and_no_capture_start(self):                    # ② · AC-FR3-21 ④
        Src.script = ["deny", "deny"]
        self.play()
        self.play()
        self.assertEqual([e["attempt"] for e in self.events("capture_attempt")], [1, 2])
        bands = self.events("permission_band")
        self.assertEqual([(b["permission"], b["from"], b["attempt"]) for b in bands], [("screen_recording", "idle", 1)] * 1 + [("screen_recording", "idle", 2)])
        self.assertEqual(self.events("capture_start"), [])

    def test_retry_success_clears_band_and_logs_start_once(self):             # ③ ④
        Src.script = ["deny", "ok"]
        self.play()
        self.assertTrue(self.play())
        self.assertEqual(self.ctl.capture_state(), "수집 중")
        self.assertEqual(self.banner()[0], False)
        self.assertEqual(len(self.events("capture_start")), 1)
        self.assertEqual(len(Src.instances), 2)                               # 시도마다 새 소스

    def test_play_while_pending_is_ignored(self):                            # ⑤
        Src.script = ["hang", "ok"]
        self.assertTrue(self.play())
        self.assertFalse(self.ctl.play_capture())
        self.assertEqual(len(self.events("capture_attempt")), 1)
        self.assertEqual(len(Src.instances), 1)

    def test_guide_line_hidden_and_frame_card_not_guided(self):               # ⑥ · AC-FR3-22
        Src.script = ["deny"]
        self.play()
        g = self.ctl.view.transcript_guide_permission
        self.assertTrue(g.isHidden())
        self.assertTrue(self.ctl._ever_played)

    def test_midcapture_revocation_keeps_old_handling(self):                  # ⑦
        Src.script = ["ok"]
        self.play()
        self.ctl._tap.state("중단", REASON_TEXT["no_permission"])
        T.pump()
        self.assertEqual(self.ctl.capture_state(), "중단")
        self.assertEqual(self.events("permission_band"), [])
        self.assertEqual(self.banner()[1], "음성 수집이 중단되었습니다")


class PausedPlayDeniedTest(Base):
    def test_paused_denied_stays_paused_without_pause_end_line(self):         # ⑧
        Src.script = ["ok", "deny", "ok"]
        self.play()
        self.assertTrue(self.ctl.pause_capture())
        T.pump()
        self.assertFalse(self.play())
        self.assertEqual(self.ctl.capture_state(), "일시 정지")
        ends = [r for r in self.records() if r.get("type") == "pause" and r.get("state") == "끝"]
        self.assertEqual(ends, [])
        bands = self.events("permission_band")
        self.assertEqual(bands[-1]["from"], "paused")
        self.assertTrue(self.play())
        ends = [r for r in self.records() if r.get("type") == "pause" and r.get("state") == "끝"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(len(self.events("capture_start")), 1)                # 재개는 capture_start 를 더하지 않는다


class AttemptScreenTest(Base):
    """b56 M1 (D-191 · D-192): 시도 중(첫 음성 블록 · 종료 전)에는 화면이 누르기 전과 같다."""

    def _screen(self):
        T.pump(3)
        v = self.ctl.view
        t = v.transport
        return (self.ctl.capture_state(), v.chip_before.isHidden(), v.chip_paused.isHidden(), v.transcript_guide.isHidden(),
                t.btn_play.isEnabled(), t.btn_pause.isEnabled(), t.btn_stop.isEnabled(),
                self.ctl.menu.actions["session.play"].isEnabled(), self.ctl.menu.actions["session.pause"].isEnabled(), self.banner())

    def test_first_attempt_keeps_before_screen(self):
        before = self._screen()
        Src.script = ["hang"]
        self.assertTrue(self.play())
        self.assertEqual(self._screen(), before)
        self.assertEqual(self.ctl.capture_state(), "수집 전")
        self.assertFalse(self.ctl.view.transport.btn_pause.isEnabled())
        self.assertTrue(self.ctl.view.transport.btn_stop.isEnabled())
        self.assertFalse(self.ctl.pause_capture())                       # [일시 정지] · 메뉴 · 전역 키는 무시한다
        self.assertFalse(self.ctl.play_capture())                        # 시도 중 [재생] 도 무시한다
        T.pump(40)                                                       # 시간이 흘러도 수집 중단 카드 · 띠가 없다
        self.assertEqual(self._screen(), before)
        self.assertEqual(len(self.ctl.view.ai._cards), 0)
        self.assertEqual(len(Src.instances), 1)                          # 보조 프로그램을 스스로 다시 시작하지 않는다

    def test_attempt_with_band_keeps_band(self):
        Src.script = ["deny", "hang"]
        self.play()
        denied = self._screen()
        self.assertTrue(self.play())
        self.assertEqual(self._screen(), denied)                         # 띠 · 칩 · 안내 상자 · 단추가 그대로이다
        self.assertEqual(self.ctl.view.banner.tone(), "info")

    def test_attempt_after_pause_keeps_paused_screen(self):
        Src.script = ["ok", "hang"]
        self.play()
        self.assertTrue(self.ctl.pause_capture())
        T.pump(3)
        paused = self._screen()
        self.assertEqual(paused[0], "일시 정지")
        self.assertTrue(self.play())
        self.assertEqual(self._screen(), paused)
        ends = [r for r in self.records() if r.get("type") == "pause" and r.get("state") == "끝"]
        self.assertEqual(ends, [])

    def test_state_becomes_running_at_first_block(self):
        Src.script = ["hang", "ok"]
        self.play()
        self.assertEqual(self.ctl.capture_state(), "수집 전")
        src = Src.instances[0]
        src.log.emit("capture_start", source="system_sound", device="fake", samplerate=16000, channels=1)
        src.on_block(PcmBlock(np.zeros(160, dtype=np.float32), 0.0))
        T.pump(5)
        self.assertEqual(self.ctl.capture_state(), "수집 중")
        self.assertTrue(self.ctl.view.chip_before.isHidden())
        self.assertTrue(self.ctl.view.transport.btn_pause.isEnabled())
        self.assertEqual(len(self.events("capture_start")), 1)

    def test_attempt_ended_by_exit_returns_error_card(self):
        Src.script = ["hang"]
        self.play()
        Src.instances[0].on_state("중단", "수집을 시작하지 못했습니다: 시험")
        T.pump(5)
        self.assertEqual(self.ctl.capture_state(), "중단")

    def test_pause_then_start_failure_goes_to_stopped_with_one_end_line(self):      # S10-31 (AC-FR3-16)
        Src.script = ["ok"]
        self.play()
        self.assertTrue(self.ctl.pause_capture())
        T.pump(3)
        self.ctl._start_fail_armed = True
        self.assertFalse(self.play())
        T.pump(5)
        self.assertEqual(self.ctl.capture_state(), "중단")
        ends = [r for r in self.records() if r.get("type") == "pause" and r.get("state") == "끝"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(len(self.ctl.view.ai._cards), 1)
        self.assertFalse(self.ctl.view.transport.btn_play.isEnabled())

    def test_stop_during_attempt_is_active(self):                                    # 권고 83
        Src.script = ["hang"]
        self.play()
        self.assertTrue(self.ctl.view.transport.btn_stop.isEnabled())
        self.ctl.request_stop()
        T.pump(3)
        self.assertIsNotNone(self.ctl._stop_dialog)


class FakeStream:
    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class FinishBackend:
    """실제 MicSource 의 백엔드: 열기는 성공하고, `finish()` 로 첫 블록 없이 스트림이 끝났음을 알린다(종료 코드 4 · 0 에 해당)."""

    def __init__(self, why):
        self.opens, self.fin, self.cb, self.why, self.fail_opens = 0, None, None, why, 0

    def default_input(self):
        return ("Fake Mic", 48000, 1)

    def open(self, callback, finished, device, samplerate, channels):
        self.opens += 1
        if self.fail_opens > 0:
            self.fail_opens -= 1
            raise OSError("장치 열기 시험")
        self.cb, self.fin = callback, finished
        return FakeStream()

    def last_error(self):
        return self.why

    def finish(self):
        self.fin()


class RealMicFailureTest(Base):
    """D-194 ③: 상태를 직접 넣지 않고 실제 `MicSource` 가 첫 블록 전 종료를 알리게 한다."""
    source = "system_mic"
    why = "수집 중 오류가 발생했습니다"

    def make_mic(self, log):
        from nsu_kangs_rab.platform.audio.mic_source import MicSource
        self.backend = FinishBackend(self.why)
        return MicSource(self.backend, eventlog=log, poll_s=600.0, tick_s=0.02, retry_s=0.2, stall_s=0.5)

    def wait(self, cond, sec=5.0):
        end = time.monotonic() + sec
        while time.monotonic() < end and not cond():
            T.pump(2)
            time.sleep(0.02)
        return cond()

    def _fail_once(self):
        self.ctl.play_capture()
        self.assertTrue(self.wait(lambda: self.backend.fin is not None))
        self.backend.finish()
        self.assertTrue(self.wait(lambda: self.ctl.capture_state() == "중단"))
        T.pump(5)

    def test_after_pause_exit_before_first_block_writes_one_end_line(self):     # S10-31 (AC-FR3-16)
        import numpy as np
        self.ctl.play_capture()
        self.assertTrue(self.wait(lambda: self.backend.cb is not None))
        self.backend.cb(np.zeros((4800, 1), dtype=np.float32), None)
        self.assertTrue(self.wait(lambda: self.ctl.capture_state() == "수집 중"))
        self.assertTrue(self.ctl.pause_capture())
        T.pump(3)
        self.backend.fin = None
        self.ctl.play_capture()
        self.assertTrue(self.wait(lambda: self.backend.fin is not None))
        self.backend.finish()
        self.assertTrue(self.wait(lambda: self.ctl.capture_state() == "중단"))
        T.pump(5)
        ends = [r for r in self.records() if r.get("type") == "pause" and r.get("state") == "끝"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(len(self.ctl.view.ai._cards), 1)
        self.assertFalse(self.ctl.view.transport.btn_play.isEnabled())
        self.assertEqual(self.backend.opens, 2)

    def test_open_exception_during_attempt_is_audio_lost_and_recovers(self):     # D-195: 접두어 없는 "중단" 은 수집 중단, 재시도 성공 시 수집 중
        import numpy as np
        self.backend.fail_opens = 1
        self.ctl.play_capture()
        self.assertTrue(self.wait(lambda: self.ctl.capture_state() == "중단"))
        T.pump(5)
        self.assertEqual(len(self.ctl.view.ai._cards), 1)
        self.assertNotEqual(self.banner()[1], "음성 수집을 시작하지 못했습니다")        # UI-288 이 아니다
        self.assertTrue(self.wait(lambda: self.backend.cb is not None))            # 소스가 스스로 다시 열었다
        self.backend.cb(np.zeros((4800, 1), dtype=np.float32), None)
        self.assertTrue(self.wait(lambda: self.ctl.capture_state() == "수집 중"))
        self.assertEqual(self.backend.opens, 2)

    def test_exit_before_first_block_is_start_failure_without_restart(self):     # S10-31 · D-194
        self._fail_once()
        self.assertEqual(self.ctl.capture_state(), "중단")
        self.assertEqual(self.events("permission_band"), [])
        self.assertEqual(len(self.ctl.view.ai._cards), 1)
        self.assertNotEqual(self.banner()[1], "음성 수집이 중단되었습니다")        # UI-253(audio_lost) 이 아니다
        self.assertEqual(self.banner()[1], "음성 수집을 시작하지 못했습니다")             # UI-288
        self.assertFalse(self.ctl.view.transport.btn_play.isEnabled())
        self.assertFalse(self.ctl.view.transport.btn_pause.isEnabled())
        time.sleep(0.8)
        T.pump(5)
        self.assertEqual(self.backend.opens, 1)                                  # 다시 시작하지 않았다


class RealMicFailureNoReasonTest(RealMicFailureTest):
    """사유 문구가 없는 종료(종료 코드 0): 같은 처리이다."""
    why = None


class MicDeniedTest(Base):
    source = "system_mic"

    def test_microphone_band_text(self):
        Src.script = ["deny"]
        self.play()
        shown, title, desc = self.banner()
        self.assertEqual(title, "마이크 권한이 필요합니다")
        self.assertEqual(self.events("permission_band")[0]["permission"], "microphone")

    def test_band_cleared_when_recovered_after_audio_lost(self):                 # D-196: 시도가 아닌 경로로 "수집 중" 이 되어도 띠를 지운다
        Src.script = ["deny"]
        self.play()
        self.assertTrue(self.banner()[0])
        Src.script = ["hang"]
        self.play()
        src = Src.instances[-1]
        src.on_state("중단", "사유: 열기 실패: OSError")                         # 접두어 없는 "중단" → 시도 표지 해제, audio_lost
        T.pump(5)
        self.assertEqual(self.ctl.capture_state(), "중단")
        src.on_state("수집 중", "fake")                                          # 소스가 스스로 복구
        T.pump(5)
        self.assertEqual(self.ctl.capture_state(), "수집 중")
        self.assertTrue(self.ctl.pause_capture())
        T.pump(5)
        self.assertEqual(self.banner(), (False, "", ""))


if __name__ == "__main__":
    unittest.main()
