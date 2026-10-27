"""`platform/stt/stt_speech.py` 와 가짜 `fakes/fake_stt_speech.py` 의 단위 시험 (기술 계획 2-8절, 단계 10 M-1).

실제 macOS 엔진은 쓰지 않는다(가짜 프로세스). 실제 보조 프로세스와의 형식 대조는 빌드된 실행 파일이 있을 때만 한다
(환경 변수 `STT_SPEECH_HELPER`)."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src", "mac"))
from nsu_kangs_rab.platform.stt import stt_speech as ss  # noqa: E402
from tests.unit.media.fakes import fake_stt_speech as fk  # noqa: E402

FAKE = os.path.join(os.path.dirname(fk.__file__), "fake_stt_speech.py")
CMD = [sys.executable, FAKE]

# 줄 종류별 필드 집합 (기술 계획 2-8-2절). 선택 필드는 OPTIONAL.
REQUIRED = {"locales": {"type", "list"}, "ready": {"type"}, "partial": {"type", "text", "start_mono", "end_mono"},
            "final": {"type", "n", "text", "start_mono", "end_mono"}, "asset": {"type", "state"}, "error": {"type", "kind", "detail"}}
OPTIONAL = {"asset": {"fraction", "installed"}, "error": {"full"}}


def shape_ok(d: dict) -> bool:
    t = d["type"]
    keys = set(d)
    return REQUIRED[t] <= keys <= REQUIRED[t] | OPTIONAL.get(t, set())


class Collector:
    def __init__(self):
        self.lines, self.bad, self.exit = [], [], None
        self.cv = threading.Condition()

    def on_line(self, d):
        with self.cv:
            self.lines.append(d)
            self.cv.notify_all()

    def on_bad(self, raw):
        with self.cv:
            self.bad.append(raw)

    def on_exit(self, reason, code, detail):
        with self.cv:
            self.exit = (reason, code, detail)
            self.cv.notify_all()

    def wait(self, pred, timeout=8.0):
        end = time.monotonic() + timeout
        with self.cv:
            while not pred(self):
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self.cv.wait(left)
        return True

    def of(self, t):
        return [x for x in self.lines if x["type"] == t]


def read_text(path):
    with open(path) as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.sc = os.path.join(self.dir, "sc.json")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.close()

    def scenario(self, obj):
        with open(self.sc, "w") as f:
            json.dump(obj, f)
        fk.reset_files(self.sc)

    def start(self, extra=None, start_n=1, scenario=True):
        c = Collector()
        cmd = CMD + ss.helper_command("X", "ko_KR", start_n)[1:] + (["--scenario", self.sc] if scenario else [])
        p = ss.SttSpeechProcess(cmd, c.on_line, c.on_exit, on_bad_line=c.on_bad)
        self.procs.append(p)
        p.start()
        return p, c


class FramesAndParsing(unittest.TestCase):
    def test_audio_frame_layout(self):
        f = ss.audio_frame(12.5, np.array([0.5, -0.25], dtype=np.float32))
        self.assertEqual(f[0], 0x41)
        self.assertEqual(int.from_bytes(f[1:5], "little"), 8 + 8)
        self.assertEqual(np.frombuffer(f[5:13], dtype="<f8")[0], 12.5)
        self.assertEqual(list(np.frombuffer(f[13:], dtype="<f4")), [0.5, -0.25])

    def test_control_frames(self):
        self.assertEqual(ss.CUT_FRAME, b"C\x00\x00\x00\x00")
        self.assertEqual(ss.QUIT_FRAME, b"Q\x00\x00\x00\x00")

    def test_parse_line(self):
        self.assertEqual(ss.parse_line(b'{"type":"ready"}'), {"type": "ready"})
        for bad in (b"not json", b"[1]", b'{"type":"nope"}', b'{"x":1}', b"\xff\xfe"):
            self.assertIsNone(ss.parse_line(bad), bad)

    def test_classify_exit(self):
        c = ss.classify_exit
        self.assertEqual(c(2, "asset_failed", False), "asset_failed")
        self.assertEqual(c(3, None, False), "analyzer_error")
        self.assertEqual(c(1, None, False), "unsupported_locale")
        self.assertEqual(c(4, None, False), "os_too_old")
        self.assertEqual(c(0, None, True), "ended")
        self.assertEqual(c(0, None, False), "analyzer_error")      # Q 를 보내지 않았는데 정상 종료
        self.assertEqual(c(-9, None, False), "analyzer_error")     # 신호로 끝남
        self.assertEqual(c(None, None, False), "analyzer_error")
        self.assertEqual(c(7, None, False), "analyzer_error")      # 알 수 없는 코드
        self.assertEqual(c(3, "os_too_old", False), "os_too_old")  # error 줄의 kind 가 사유이다
        self.assertEqual(c(0, "segment_failed", False), "analyzer_error")  # 치명 종류가 아니다

    def test_helper_command(self):
        self.assertEqual(ss.helper_command("/h", "ja_JP", 5), ["/h", "--locale", "ja_JP", "--start-n", "5"])

    def test_build_helper_command(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "h", "out")
            ss.build_helper(dest, swift_source="/s.swift", run=lambda c, check: calls.append(c))
        self.assertEqual(calls[0][:3], ["swiftc", "-O", "-parse-as-library"])
        self.assertEqual(calls[0][-3:], ["/s.swift", "-o", dest])


class FakeProcess(Base):
    def test_default_ready_and_shapes(self):
        p, c = self.start(scenario=False)
        self.assertTrue(c.wait(lambda c: c.of("ready")))
        self.assertTrue(all(shape_ok(d) for d in c.lines), c.lines)
        p.send_quit()
        self.assertTrue(c.wait(lambda c: c.exit))
        self.assertEqual(c.exit[0], "ended")
        self.assertEqual(c.exit[1], 0)

    def test_start_count_choice_and_args(self):
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "ready"}}],
                                  [{"at_s": 0, "emit": {"type": "error", "kind": "asset_failed", "detail": "x"}},
                                   {"at_s": 0.05, "exit_code": 2}]]})
        p1, c1 = self.start()
        self.assertTrue(c1.wait(lambda c: c.of("ready")))
        p1.send_quit()
        self.assertTrue(c1.wait(lambda c: c.exit))
        p2, c2 = self.start(start_n=7)
        self.assertTrue(c2.wait(lambda c: c.exit))
        self.assertEqual(c2.exit[0], "asset_failed")
        self.assertEqual(c2.exit[1], 2)
        p3, c3 = self.start()                       # 시작 횟수가 배열 길이를 넘으면 마지막 것을 되풀이한다
        self.assertTrue(c3.wait(lambda c: c.exit))
        self.assertEqual(c3.exit[0], "asset_failed")
        self.assertEqual(read_text(self.sc + ".count"), "3")
        rec = fk.summarize_rec(self.sc + ".rec.jsonl")
        self.assertEqual(rec[2]["args"][:4], ["--locale", "ko_KR", "--start-n", "7"])
        self.assertEqual(sorted(rec), [1, 2, 3])

    def test_list_locales_not_counted_as_start(self):                   # Q-49 ①
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "ready"}}]],
                       "list_locales": {"list": ["ko_KR", "en_US"]}})
        self.assertEqual(ss.list_locales(CMD + ["--scenario", self.sc]), ["ko_KR", "en_US"])
        self.assertFalse(os.path.exists(self.sc + ".count"))
        self.assertEqual(read_text(self.sc + ".list_count"), "1")
        p, c = self.start()                                              # 이 시작이 k=1 이다
        self.assertTrue(c.wait(lambda c: c.of("ready")))
        p.send_quit()
        self.assertEqual(read_text(self.sc + ".count"), "1")

    def test_list_locales_timeout_and_failure(self):                    # Q-49 ②
        self.scenario({"list_locales": {"list": ["ko_KR"], "line_after_s": 3.0}})
        t0 = time.monotonic()
        self.assertIsNone(ss.list_locales(CMD + ["--scenario", self.sc], timeout_s=0.5))
        self.assertLess(time.monotonic() - t0, 2.5)
        self.scenario({"list_locales": {"list": [], "exit_code": 3}})
        self.assertIsNone(ss.list_locales(CMD + ["--scenario", self.sc], timeout_s=3.0))
        self.scenario({"list_locales": {"list": ["ko_KR"], "line_after_s": 0.0, "delay_s": 0.2}})
        self.assertEqual(ss.list_locales(CMD + ["--scenario", self.sc], timeout_s=3.0), ["ko_KR"])
        self.assertIsNone(ss.list_locales(["/nonexistent/helper"]))

    def test_cut_final_and_rel_times(self):
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "ready"}},
                                   {"after_first_a_s": 0, "emit": {"type": "partial", "text": "안녕", "start_mono": {"rel": "first_a", "s": 0.0},
                                                                    "end_mono": {"rel": "last_a", "s": 0.5}}}]],
                       "on_cut": [{"final_after_s": 0.05, "text": "안녕하세요", "start_mono": {"rel": "first_a", "s": 0},
                                   "end_mono": {"rel": "last_a", "s": 0.1}}, None]})
        p, c = self.start(start_n=4)
        self.assertTrue(c.wait(lambda c: c.of("ready")))
        p.send_audio(100.0, np.zeros(160, dtype=np.float32))
        p.send_audio(101.0, np.zeros(160, dtype=np.float32))
        self.assertTrue(c.wait(lambda c: c.of("partial")))
        pt = c.of("partial")[0]
        self.assertEqual(pt["start_mono"], 100.0)
        p.send_cut()
        self.assertTrue(c.wait(lambda c: c.of("final")))
        f = c.of("final")[0]
        self.assertEqual((f["n"], f["text"], f["start_mono"], f["end_mono"]), (4, "안녕하세요", 100.0, 101.1))
        p.send_cut()                                                      # 두 번째 C: 확정 없음
        time.sleep(0.3)
        self.assertEqual(len(c.of("final")), 1)
        p.send_quit()
        self.assertTrue(c.wait(lambda c: c.exit))
        r = fk.summarize_rec(self.sc + ".rec.jsonl")[1]
        self.assertEqual(len(r["C"]), 2)
        self.assertEqual(len(r["Q"]), 1)
        self.assertEqual(r["a"], {"count": 2, "first": 100.0, "last": 101.0})
        self.assertEqual(r["exit"], 0)
        for d in c.lines:
            self.assertTrue(shape_ok(d), d)

    def test_final_n_is_one_counter_for_emit_and_on_cut(self):           # 권고 57
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "ready"}},
                                   {"after_first_a_s": 0, "emit": {"type": "final", "n": 99, "text": "a", "start_mono": 1, "end_mono": 2}}]],
                       "on_cut": [{"final_after_s": 0, "text": "b", "start_mono": 3, "end_mono": 4}]})
        p, c = self.start(start_n=5)
        self.assertTrue(c.wait(lambda c: c.of("ready")))
        p.send_audio(1.0, np.zeros(160, dtype=np.float32))
        self.assertTrue(c.wait(lambda c: c.of("final")))
        p.send_cut()
        self.assertTrue(c.wait(lambda c: len(c.of("final")) == 2))
        self.assertEqual([f["n"] for f in c.of("final")], [5, 6])

    def test_after_cut_step_and_exit_on_cut(self):
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "ready"}},
                                   {"after_cut": {"n": 1, "s": 0.0}, "emit": {"type": "error", "kind": "segment_failed", "detail": "d"}}]],
                       "on_cut": [None, {"exit_after_s": 0.05, "exit_code": 3}]})
        p, c = self.start()
        self.assertTrue(c.wait(lambda c: c.of("ready")))
        p.send_cut()
        self.assertTrue(c.wait(lambda c: c.of("error")))
        self.assertIsNone(c.exit)
        p.send_cut()
        self.assertTrue(c.wait(lambda c: c.exit))
        self.assertEqual(c.exit[:2], ("analyzer_error", 3))               # error 줄 없이 코드 3

    def test_fatal_error_line_decides_reason(self):
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "error", "kind": "unsupported_locale", "detail": "ko_KR"}},
                                   {"at_s": 0.05, "exit_code": 3}]]})
        p, c = self.start()
        self.assertTrue(c.wait(lambda c: c.exit))
        self.assertEqual(c.exit[0], "unsupported_locale")                 # 종료 코드 3 이어도 error 줄의 kind
        self.assertEqual(c.exit[2], "ko_KR")

    def test_exit0_without_quit_and_bad_lines(self):
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "ready"}}, {"at_s": 0.1, "exit_code": 0}]]})
        p, c = self.start()
        self.assertTrue(c.wait(lambda c: c.exit))
        self.assertEqual(c.exit[0], "analyzer_error")
        # 해석할 수 없는 줄은 무시하고 알린다
        out = []
        c2 = Collector()
        sh = [sys.executable, "-c", "print('not json'); print('{\"type\":\"ready\"}')"]
        p2 = ss.SttSpeechProcess(sh, c2.on_line, c2.on_exit, on_bad_line=c2.on_bad)
        self.procs.append(p2)
        p2.start()
        self.assertTrue(c2.wait(lambda c: c.exit))
        self.assertEqual(c2.bad, [b"not json"])
        self.assertEqual(c2.lines, [{"type": "ready"}])

    def test_rec_survives_sigkill(self):                                  # 권고 55
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "ready"}}]]})
        p, c = self.start()
        self.assertTrue(c.wait(lambda c: c.of("ready")))
        p.send_audio(5.0, np.zeros(16, dtype=np.float32))
        p.send_cut()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not fk.summarize_rec(self.sc + ".rec.jsonl").get(1, {}).get("C"):
            time.sleep(0.05)
        os.kill(p.pid, signal.SIGKILL)
        self.assertTrue(c.wait(lambda c: c.exit))
        self.assertEqual(c.exit[:2], ("analyzer_error", -9))
        r = fk.summarize_rec(self.sc + ".rec.jsonl")[1]
        self.assertEqual(len(r["C"]), 1)
        self.assertEqual(r["a"]["count"], 1)
        self.assertIsNone(r["exit"])                                      # 종료 기록은 없다(죽었다)

    def test_close_kills_only_recorded_pid(self):
        self.scenario({"starts": [[{"at_s": 0, "emit": {"type": "ready"}}]]})
        p, c = self.start()
        pid = p.pid
        self.assertTrue(c.wait(lambda c: c.of("ready")))
        p.close()
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertIsNone(c.exit)                                         # close 로 끝낸 경우 on_exit 를 부르지 않는다

    def test_close_waits_for_slow_graceful_exit(self):                   # 권고 58
        marker = os.path.join(self.dir, "released")
        code = ("import sys,time\nsys.stdin.buffer.read()\ntime.sleep(1.5)\nopen(%r,'w').write('x')\n" % marker)
        c = Collector()
        p = ss.SttSpeechProcess([sys.executable, "-c", code], c.on_line, c.on_exit)
        self.procs.append(p)
        p.start()
        t = time.time()
        p.close()
        self.assertTrue(os.path.exists(marker))                           # SIGTERM 전에 정상 종료까지 기다렸다
        self.assertGreaterEqual(time.time() - t, 1.4)
        self.assertLess(time.time() - t, 2.9)

    def test_write_after_exit_is_harmless(self):
        self.scenario({"starts": [[{"at_s": 0, "exit_code": 4}]]})
        p, c = self.start()
        self.assertTrue(c.wait(lambda c: c.exit))
        self.assertEqual(c.exit[:2], ("os_too_old", 4))
        self.assertFalse(p.send_audio(1.0, np.zeros(16, dtype=np.float32)) and p.send_cut() and p.send_quit() and False)


@unittest.skipUnless(os.environ.get("STT_SPEECH_HELPER") and sys.platform == "darwin", "빌드한 stt_speech 가 없다")
class RealHelperShape(unittest.TestCase):
    def test_list_locales_matches_fake_shape(self):
        h = os.environ["STT_SPEECH_HELPER"]
        out = subprocess.run([h, "--list-locales"], capture_output=True, timeout=10).stdout.splitlines()
        d = json.loads(out[0])
        self.assertTrue(shape_ok(d))
        self.assertIn("ko_KR", d["list"])
        fake = subprocess.run(CMD + ["--list-locales"], capture_output=True, timeout=10).stdout.splitlines()
        self.assertEqual(set(json.loads(fake[0])), set(d))

    def test_unsupported_locale_exit(self):
        h = os.environ["STT_SPEECH_HELPER"]
        r = subprocess.run([h, "--locale", "xx_XX"], capture_output=True, timeout=10, input=b"")
        self.assertEqual(r.returncode, 1)
        last = json.loads(r.stdout.splitlines()[-1])
        self.assertEqual((last["type"], last["kind"]), ("error", "unsupported_locale"))
        self.assertTrue(shape_ok(last))

    def test_exits_when_stdin_closes_without_audio(self):
        """D-183: 음성을 먹이지 않고 stdin 이 닫혀도 보조 프로세스가 스스로 끝난다(준비 전 · 준비 후 모두)."""
        h = os.environ["STT_SPEECH_HELPER"]
        for wait_ready in (False, True):
            p = subprocess.Popen([h, "--locale", "ko_KR"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                if wait_ready:
                    for line in p.stdout:
                        if b'"ready"' in line:
                            break
                p.stdin.close()
                self.assertEqual(p.wait(timeout=10), 0)
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait()


if __name__ == "__main__":
    unittest.main()
