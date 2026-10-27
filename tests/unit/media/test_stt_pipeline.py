"""`SttPipeline` 단위 시험 (기술 계획 2-8-3절, 단계 10 M-2). 가짜 `stt_speech` 프로세스를 쓰며 실제 macOS 엔진은 쓰지 않는다."""
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from nsu_kangs_rab.core.types import Error, PartialSegment, Segment  # noqa: E402
from nsu_kangs_rab.platform.audio.types import PcmBlock  # noqa: E402
from nsu_kangs_rab.platform.stt.pipeline import SttPipeline  # noqa: E402
from tests.unit.media.fakes import fake_stt_speech as fk  # noqa: E402

FAKE = os.path.join(os.path.dirname(fk.__file__), "fake_stt_speech.py")
WALL0 = dt.datetime(2026, 10, 24, 12, 0, 0, tzinfo=dt.timezone.utc)
READY = {"at_s": 0, "emit": {"type": "ready"}}


class Src:
    """수집 소스 대역: `start` 에서 콜백을 보관한다."""

    def __init__(self):
        self.calls = []
        self.on_block = self.on_state = None

    def start(self, on_block, on_state):
        self.calls.append("start")
        self.on_block, self.on_state = on_block, on_state

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")
        return True

    def stop(self):
        self.calls.append("stop")


class Log:
    def __init__(self):
        self.events = []

    def emit(self, type_, **f):
        self.events.append((type_, f))
        return True

    def of(self, t):
        return [f for (x, f) in self.events if x == t]


class Rec:
    def __init__(self):
        self.lock = threading.Lock()
        self.segs, self.parts, self.errs, self.assets, self.ready, self.exits = [], [], [], [], [], []
        self.pend, self.drop = [], []

    def add(self, lst):
        def f(*a):
            with self.lock:
                lst.append(a if len(a) != 1 else a[0])
        return f


def wait_for(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.01)
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.sc = os.path.join(self.dir, "sc.json")
        self.pipes = []

    def tearDown(self):
        for p in self.pipes:
            p.stop()
            p.join(10)

    def scenario(self, obj):
        with open(self.sc, "w") as f:
            json.dump(obj, f)
        fk.reset_files(self.sc)

    def make(self, begin=True, start_n=1, helper=None, mono=lambda: 105.0):
        log, rec, src = Log(), Rec(), Src()
        p = SttPipeline(helper or [sys.executable, FAKE], "ko_KR", start_n, eventlog=log, mono=mono,
                        wall_now=lambda: WALL0, extra_args=["--scenario", self.sc], drain_s=1.0)
        self.pipes.append(p)
        p.start(src, rec.add(rec.segs), rec.add(rec.pend), rec.add(rec.errs), rec.add(rec.drop),
                on_partial=rec.add(rec.parts), begin=begin, on_asset=rec.add(rec.assets), on_ready=lambda: rec.ready.append(1),
                on_exit=rec.add(rec.exits))
        return p, src, rec, log

    def feed(self, src, n=3, t0=100.0):
        for i in range(n):
            src.on_block(PcmBlock(np.zeros(1600, dtype=np.float32), t0 + i * 0.1))

    def rec_file(self, k=1):
        return fk.summarize_rec(self.sc + ".rec.jsonl").get(k, {})


class FlowTest(Base):
    def test_partial_final_ready_asset_and_events(self):
        self.scenario({"starts": [[
            READY,
            {"at_s": 0, "emit": {"type": "asset", "state": "downloading", "fraction": 0.5}},
            {"after_first_a_s": 0, "emit": {"type": "partial", "text": "안녕", "start_mono": {"rel": "first_a", "s": 0.0},
                                             "end_mono": {"rel": "first_a", "s": 0.1}}},
            {"after_first_a_s": 0.05, "emit": {"type": "final", "n": 7, "text": " 안녕하세요 ", "start_mono": {"rel": "first_a", "s": 0.0},
                                                "end_mono": {"rel": "first_a", "s": 2.0}}}]]})
        p, src, rec, log = self.make(start_n=7)
        self.assertTrue(wait_for(lambda: rec.ready))
        self.assertEqual(src.calls, ["start"])
        self.feed(src)
        self.assertTrue(wait_for(lambda: rec.segs and rec.parts))
        self.assertEqual(rec.parts[0], PartialSegment("안녕", 100.0, 100.1))
        s = rec.segs[0]
        self.assertIsInstance(s, Segment)
        self.assertEqual((s.n, s.text, s.start_mono, s.end_mono), (7, "안녕하세요", 100.0, 102.0))
        self.assertEqual(s.start_wall, "2026-10-24T11:59:55.000+00:00")
        self.assertEqual(s.end_wall, "2026-10-24T11:59:57.000+00:00")        # mono0 = 105.0 이므로 100.0 은 5 초 전
        self.assertEqual(rec.assets[0]["state"], "downloading")
        self.assertEqual(p.next_n, 8)
        self.assertEqual(rec.pend, [])                 # 호환 인자는 호출하지 않는다
        self.assertEqual(rec.drop, [])
        self.assertEqual(log.of("stt_partial_first"), [{"latency_s": 5.0}])
        self.assertEqual(log.of("segment_arrived"), [{"n": 7, "start_mono": 100.0, "end_mono": 102.0, "chars": 5, "latency_s": 3.0}])
        phases = [f["phase"] for f in log.of("stt_asset")]
        self.assertEqual(sorted(phases), ["ready", "state"])
        for _, f in log.events:
            self.assertNotIn("text", f)
        a = fk.summarize_rec(self.sc + ".rec.jsonl")[1]
        self.assertIn("7", " ".join(a["args"]))                                # --start-n 7

    def test_asset_start_line_logs_installed(self):
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "asset", "state": "checking", "installed": True}}, READY]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        ph = log.of("stt_asset")
        self.assertEqual(ph[0], {"phase": "start", "locale": "ko_KR", "installed": True})
        self.assertEqual(ph[1], {"phase": "state", "locale": "ko_KR", "state": "checking"})
        self.assertEqual(ph[-1]["phase"], "ready")
        self.assertEqual(rec.assets[0]["installed"], True)

    def test_empty_final_makes_no_segment_but_counts_n(self):
        self.scenario({"starts": [[READY, {"after_first_a_s": 0, "emit": {"type": "final", "n": 3, "text": "  ", "start_mono": 1.0, "end_mono": 2.0}}]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 1)
        self.assertTrue(wait_for(lambda: p.next_n == 2))
        self.assertTrue(wait_for(lambda: rec.drop == [1]))             # 구간이 조각 없이 끝났다: on_dropped(n)
        self.assertEqual(rec.segs, [])
        self.assertEqual(rec.errs, [])
        self.assertEqual(log.of("segment_arrived"), [])

    def _final_scenario(self, text):
        self.scenario({"starts": [[READY, {"after_first_a_s": 0, "emit": {"type": "final", "n": 1, "text": text, "start_mono": 1.0, "end_mono": 2.0}}]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 1)
        self.assertTrue(wait_for(lambda: rec.segs or rec.drop))
        return rec, log

    def test_final_without_letter_or_digit_is_dropped(self):
        """결정 0171 1항 (D-185): L · N 범주 문자가 없는 확정은 조각이 아니다. 본문은 사건에 남지 않는다."""
        for text in [".", "。", "?!", " … ", "  ", "- ,"]:
            with self.subTest(text=text):
                rec, log = self._final_scenario(text)
                self.assertEqual(rec.segs, [])
                self.assertEqual(rec.drop, [1])
                self.assertEqual(log.of("segment_arrived"), [])
                ev = log.of("stt_dropped")
                self.assertEqual(len(ev), 1)
                self.assertEqual(ev[0]["n"], 1)
                self.assertEqual(ev[0]["reason"], "empty" if not text.strip() else "no_letter_digit")
                self.assertNotIn("text", ev[0])
                self.tearDown(); self.setUp()

    def test_final_with_letter_or_digit_is_kept(self):
        for text in ["a", "1", "네.", "you", "Ⅷ"]:
            with self.subTest(text=text):
                rec, log = self._final_scenario(text)
                self.assertEqual([x.text for x in rec.segs], [text])
                self.assertEqual(rec.drop, [])
                self.assertEqual(log.of("stt_dropped"), [])
                self.tearDown(); self.setUp()

    def test_asset_diagnostic_fields_are_logged(self):
        """Q-52: downloading 줄의 completed · total · indeterminate 가 stt_asset(state) 사건에 실린다."""
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "asset", "state": "downloading", "completed": 0, "total": 1, "indeterminate": False}}, READY]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        ev = [f for f in log.of("stt_asset") if f.get("state") == "downloading"]
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["completed"], ev[0]["total"], ev[0]["indeterminate"]), (0, 1, False))
        self.assertNotIn("fraction", ev[0])

    def test_audio_blocks_are_all_sent_in_order(self):
        self.scenario({"starts": [[READY]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 20)
        p.stop()
        self.assertTrue(p.join(10))
        a = self.rec_file()["a"]
        self.assertEqual(a["count"], 20)
        self.assertAlmostEqual(a["first"], 100.0)
        self.assertAlmostEqual(a["last"], 101.9)


class LocaleTest(Base):
    def test_locale_argument_reaches_helper_for_all_nine(self):     # AC-FR16-3 ②: 언어 하나에 로캘 하나(결정 0167 5항)
        for loc in ("ko_KR", "en_US", "ja_JP", "zh_CN", "de_DE", "fr_FR", "es_ES", "it_IT", "pt_BR"):
            self.scenario({"starts": [[READY]]})
            p = SttPipeline([sys.executable, FAKE], loc, 3, extra_args=["--scenario", self.sc])
            self.pipes.append(p)
            got = []
            p.start(Src(), lambda s: None, on_ready=lambda: got.append(1))
            self.assertTrue(wait_for(lambda: got), loc)
            args = self.rec_file()["args"]
            self.assertEqual(args[args.index("--locale") + 1], loc)
            self.assertEqual(args[args.index("--start-n") + 1], "3")
            p.stop()
            self.assertTrue(p.join(10))

    def test_default_locale_is_korean(self):
        self.scenario({"starts": [[READY]]})
        p = SttPipeline([sys.executable, FAKE], extra_args=["--scenario", self.sc])
        self.pipes.append(p)
        got = []
        p.start(Src(), lambda s: None, on_ready=lambda: got.append(1))
        self.assertTrue(wait_for(lambda: got))
        args = self.rec_file()["args"]
        self.assertEqual(args[args.index("--locale") + 1], "ko_KR")


class CutTest(Base):
    def test_cut_sends_c_after_queued_audio_and_final_arrives(self):
        self.scenario({"starts": [[READY, {"after_first_a_s": 0, "emit": {"type": "partial", "text": "가나", "start_mono": {"rel": "first_a", "s": 0},
                                                                          "end_mono": {"rel": "last_a", "s": 0}}}]],
                       "on_cut": [{"final_after_s": 0.05, "text": "가나다", "start_mono": {"rel": "first_a", "s": 0}, "end_mono": {"rel": "last_a", "s": 0.1}}]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 5)
        self.assertTrue(wait_for(lambda: rec.parts))
        p.cut()
        self.assertTrue(wait_for(lambda: rec.segs))
        self.assertEqual(rec.segs[0].text, "가나다")
        r = self.rec_file()
        self.assertEqual(len(r["C"]), 1)
        self.assertEqual(r["a"]["count"], 5)

    def test_pause_pauses_source_and_sends_c(self):
        self.scenario({"starts": [[READY]], "on_cut": [None]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        p.pause()
        self.assertIn("pause", src.calls)
        self.assertTrue(wait_for(lambda: len(self.rec_file().get("C", [])) == 1))
        self.assertTrue(p.resume())
        self.assertEqual(src.calls[-1], "resume")

    def test_pause_before_begin_is_noop_and_begin_false_defers_source(self):
        self.scenario({"starts": [[READY]]})
        p, src, rec, log = self.make(begin=False)
        self.assertEqual(src.calls, [])
        p.pause()
        self.assertEqual(src.calls, [])
        self.assertTrue(wait_for(lambda: rec.ready))
        self.assertTrue(p.resume())                       # 처음 [재생]
        self.assertEqual(src.calls, ["start"])
        self.assertEqual(self.rec_file().get("C", []), [])

    def test_final_after_pause_is_still_delivered(self):          # AC-FR4-17: 늦은 확정도 조각이다
        self.scenario({"starts": [[READY, {"after_first_a_s": 0, "emit": {"type": "partial", "text": "x", "start_mono": 1.0, "end_mono": 2.0}}]],
                       "on_cut": [{"final_after_s": 0.4, "text": "늦은 확정", "start_mono": 1.0, "end_mono": 2.0}]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 2)
        self.assertTrue(wait_for(lambda: rec.parts))
        p.pause()
        self.assertEqual(rec.segs, [])
        self.assertTrue(wait_for(lambda: rec.segs))
        self.assertEqual(rec.segs[0].text, "늦은 확정")


class ErrorTest(Base):
    def test_segment_failed_calls_on_error_and_continues(self):
        self.scenario({"starts": [[READY, {"after_first_a_s": 0, "emit": {"type": "error", "kind": "segment_failed", "detail": "Err"}},
                                   {"after_first_a_s": 0.1, "emit": {"type": "final", "n": 1, "text": "다음", "start_mono": 1.0, "end_mono": 2.0}}]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 1)
        self.assertTrue(wait_for(lambda: rec.segs))
        self.assertEqual(len(rec.errs), 1)
        self.assertEqual(rec.drop, [])                              # segment_failed 는 on_dropped 가 아니다
        self.assertIsInstance(rec.errs[0], Error)
        self.assertEqual(rec.errs[0].kind, "stt_fail")
        self.assertEqual(rec.exits, [])
        self.assertEqual([f["reason"] for f in log.of("stt_error")], ["segment_failed"])

    def test_fatal_before_ready_reports_exit_without_error_count(self):
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "error", "kind": "asset_failed", "detail": "AssetErr", "full": "/Users/x/y failed"}},
                                   {"at_s": 0.05, "exit_code": 2}]]})
        p, src, rec, log = self.make(begin=False)
        self.assertTrue(wait_for(lambda: rec.exits))
        self.assertEqual(rec.exits[0], ("asset_failed", "AssetErr"))
        self.assertEqual(rec.errs, [])                             # 오류 횟수에 더하지 않는다
        failed = [f for f in log.of("stt_asset") if f["phase"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual((failed[0]["kind"], failed[0]["error"]), ("asset_failed", "/Users/x/y failed"))
        self.assertEqual(log.of("stt_error")[0]["reason"], "asset_failed")
        self.assertTrue(p.join(10))                                 # 전송 스레드가 끝난다

    def test_unexpected_exit_after_ready_is_analyzer_error_without_asset_failed(self):
        self.scenario({"starts": [[READY, {"at_s": 0.1, "exit_code": 0}]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.exits))
        self.assertEqual(rec.exits[0][0], "analyzer_error")
        self.assertEqual([f for f in log.of("stt_asset") if f["phase"] == "failed"], [])
        self.feed(src, 3)                                           # 끝난 프로세스에 보내도 안전하다
        self.assertEqual(rec.errs, [])

    def test_missing_helper_reports_analyzer_error(self):
        p, src, rec, log = self.make(helper=["/nonexistent/stt_speech"])
        self.assertTrue(wait_for(lambda: rec.exits))
        self.assertEqual(rec.exits[0][0], "analyzer_error")
        self.assertTrue(p.join(10))

    def test_callback_exception_does_not_stop_reader(self):
        self.scenario({"starts": [[READY, {"after_first_a_s": 0, "emit": {"type": "final", "n": 1, "text": "a", "start_mono": 1, "end_mono": 2}},
                                   {"after_first_a_s": 0.1, "emit": {"type": "final", "n": 2, "text": "b", "start_mono": 3, "end_mono": 4}}]]})
        got = []
        log, src = Log(), Src()
        p = SttPipeline([sys.executable, FAKE], eventlog=log, extra_args=["--scenario", self.sc])
        self.pipes.append(p)

        def boom(s):
            got.append(s.n)
            raise RuntimeError("x")
        p.start(src, boom)
        time.sleep(0.5)
        self.feed(src, 1)
        self.assertTrue(wait_for(lambda: len(got) == 2))


class StopTest(Base):
    def test_stop_sends_q_not_c_and_does_not_report_exit(self):
        self.scenario({"starts": [[READY, {"after_first_a_s": 0, "emit": {"type": "partial", "text": "x", "start_mono": 1.0, "end_mono": 2.0}}]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 2)
        self.assertTrue(wait_for(lambda: rec.parts))
        pid = p.pid
        p.stop()
        self.assertTrue(p.join(10))
        self.assertIn("stop", src.calls)
        r = self.rec_file()
        self.assertEqual(r.get("C", []), [])
        self.assertEqual(len(r.get("Q", [])), 1)
        self.assertEqual(rec.exits, [])
        self.assertEqual(rec.segs, [])
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)                                          # 기록한 PID 의 프로세스가 끝났다
        p.stop()                                                     # 두 번째 호출은 아무 일도 하지 않는다

    def test_blocks_after_stop_are_dropped(self):
        self.scenario({"starts": [[READY]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        p.stop()
        self.assertTrue(p.join(10))
        self.feed(src, 3)
        self.assertEqual(self.rec_file()["a"], None)
        self.assertFalse(p.resume())


class EofDrainTest(Base):
    def test_eof_with_open_segment_cuts_and_waits_for_final(self):
        self.scenario({"starts": [[READY, {"after_first_a_s": 0, "emit": {"type": "partial", "text": "꼬리", "start_mono": 1.0, "end_mono": 2.0}}]],
                       "on_cut": [{"final_after_s": 0.2, "text": "꼬리 구간", "start_mono": 1.0, "end_mono": 2.0}]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 2)
        self.assertTrue(wait_for(lambda: rec.parts))
        src.on_state("종료", "eof")
        self.assertTrue(p.join(10))
        self.assertEqual([s.text for s in rec.segs], ["꼬리 구간"])
        self.assertEqual(len(self.rec_file()["C"]), 1)

    def test_eof_without_open_segment_sends_no_c(self):
        self.scenario({"starts": [[READY]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        self.feed(src, 2)
        t = time.time()
        src.on_state("종료", "eof")
        self.assertTrue(p.join(10))
        self.assertLess(time.time() - t, 0.9)                        # drain_s(1.0) 를 기다리지 않는다
        self.assertEqual(self.rec_file().get("C", []), [])

    def test_source_stop_state_ends_without_c(self):
        self.scenario({"starts": [[READY]]})
        p, src, rec, log = self.make()
        self.assertTrue(wait_for(lambda: rec.ready))
        src.on_state("종료", "stop")
        self.assertTrue(p.join(10))
        self.assertEqual(self.rec_file().get("C", []), [])


if __name__ == "__main__":
    unittest.main()
