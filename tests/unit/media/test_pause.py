"""단계 9 음성 쪽 단위 시험(장치 없음): 일시 정지에서 닫고 [재생] 에서 다시 여는 수집(결정 0147 · 0150)과 음성 파일 입력의 시계."""
import os
import tempfile
import threading
import time
import unittest
import wave

import numpy as np

from nsu_kangs_rab.platform.audio.file_source import FileSource
from nsu_kangs_rab.platform.audio.mic_source import MicSource
from nsu_kangs_rab.platform.audio import system_sound
from nsu_kangs_rab.platform.audio.system_sound import SckBackend, SystemSoundSource

RATE = 16000


def write_wav(path, seconds):
    x = (0.1 * np.sin(np.arange(int(seconds * RATE)) * 0.05) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(x.tobytes())
    return len(x) * 2


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def drive(seconds, speed, script):
    """`FileSource._run` 을 같은 스레드에서 가짜 시계로 돌린다. `script(fs, clock)` 은 `sleep` 이 불릴 때마다 호출된다."""
    clock = Clock()
    holder = {}

    def sleep(s):
        clock.t += s
        script(holder["fs"], clock)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.wav")
        total = write_wav(p, seconds)
        fs = FileSource(p, speed=speed, mono=clock, sleep=sleep)
        holder["fs"] = fs
        fs._thread = threading.current_thread()          # `resume()` 가 시작한 소스로 보게 한다
        blocks, states = [], []
        fs._run(blocks.append, lambda s, d="": states.append((s, d)))
    return fs, blocks, states, total, clock


class FileSourceClockTest(unittest.TestCase):
    def test_nothing_opened_or_read_before_start(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.wav")
            write_wav(p, 1.0)
            fs = FileSource(p)
            self.assertEqual((fs.bytes_read, fs.opened), (0, False))

    def test_capture_start_logged_once_at_first_start(self):
        log = Log()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.wav")
            write_wav(p, 0.5)
            fs = FileSource(p, speed=None, eventlog=log)
            self.assertEqual(log.count("capture_start"), 0)
            done = threading.Event()
            fs.start(lambda b: None, lambda s, dt="": done.set() if s == "종료" else None)
            self.assertTrue(done.wait(5))
        self.assertEqual(log.ev[0], ("capture_start", dict(source="file", device="file", samplerate=RATE, channels=1)))
        self.assertEqual(log.count("capture_start"), 1)

    def test_pause_drops_interval_and_resume_skips_by_wall_clock(self):
        t0 = 100.0
        seen = {"paused": False, "resumed": False}

        def script(fs, clock):
            if not seen["paused"] and clock.t >= t0 + 1.0:
                fs.pause()
                seen["paused"], seen["pause_at"] = True, clock.t
            elif seen["paused"] and not seen["resumed"] and clock.t >= seen["pause_at"] + 2.0:
                fs.resume()
                seen["resumed"], seen["resume_at"] = True, clock.t
        fs, blocks, states, total, _ = drive(6.0, 1.0, script)
        pa, ra = seen["pause_at"], seen["resume_at"]
        # 일시 정지 구간(파일 시각 pa ~ ra)의 소리는 전달되지 않는다
        mid = [b for b in blocks if pa - t0 + 0.1 < b.t_mono - t0 < ra - t0 - 0.1]
        self.assertEqual(mid, [])
        before = [b for b in blocks if b.t_mono - t0 <= pa - t0 + 0.1]
        after = [b for b in blocks if b.t_mono - t0 >= ra - t0 - 0.1]
        self.assertTrue(before and after)
        # 다시 읽은 위치는 흐른 만큼 건너뛴 위치이다(블록 길이 이내)
        self.assertLess(abs((after[0].t_mono - t0) - (ra - t0)), 0.15)
        # 건너뛴 구간은 읽지 않았다
        self.assertLess(fs.bytes_read, total - 2 * RATE * 2 + 2 * RATE * 2 * 0.1)
        self.assertEqual(states[-1], ("종료", "eof"))

    def test_resume_beyond_end_finishes(self):
        seen = {}

        def script(fs, clock):
            if "p" not in seen and clock.t >= 100.5:
                fs.pause()
                seen["p"] = clock.t
            elif "p" in seen and "r" not in seen and clock.t >= seen["p"] + 10.0:
                fs.resume()
                seen["r"] = True
        fs, blocks, states, total, _ = drive(3.0, 1.0, script)
        self.assertEqual(states[-1], ("종료", "eof"))
        self.assertLess(fs.bytes_read, total)

    def test_unclocked_mode_does_not_skip(self):
        seen = {}

        def script(fs, clock):
            if "p" not in seen and not fs.paused and len(seen) == 0 and fs.bytes_read >= 16000:
                fs.pause()
                seen["p"] = 0
            elif "p" in seen and seen["p"] < 3:
                seen["p"] += 1
                if seen["p"] == 3:
                    fs.resume()
        # 기다리지 않는 모드는 `sleep` 이 일시 정지 중에만 불린다
        fs, blocks, states, total, _ = drive(3.0, None, script)
        self.assertEqual(fs.bytes_read, total)       # 건너뛰지 않았다: 모두 읽었다


class FakeStream:
    def __init__(self, b):
        self.b, self.closed = b, False

    def start(self):
        if self.b.fail_open:
            raise OSError("denied")

    def stop(self):
        pass

    def close(self):
        self.closed = True


class FakeBackend:
    def __init__(self):
        self.fail_open = False
        self.opens, self.cb, self.fin = [], None, None
        self.err, self.no_retry_flag = None, False

    def default_input(self):
        return ("Fake", 48000, 1)

    def open(self, callback, finished, device, samplerate, channels):
        self.cb, self.fin = callback, finished
        s = FakeStream(self)
        self.opens.append(s)
        return s


class Log:
    def __init__(self):
        self.ev = []

    def emit(self, t, **f):
        self.ev.append((t, f))

    def count(self, t):
        return sum(1 for e in self.ev if e[0] == t)


def wait_for(cond, sec=4.0):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class MicPauseResumeTest(unittest.TestCase):
    def setUp(self):
        self.b, self.log = FakeBackend(), Log()
        self.states, self.blocks = [], []
        self.m = MicSource(self.b, eventlog=self.log, tick_s=0.02, poll_s=10, stall_s=1000)
        self.addCleanup(self.m.stop)

    def start(self):
        self.m.start(self.blocks.append, lambda s, d="": self.states.append((s, d)))
        self.assertTrue(wait_for(lambda: self.b.opens))

    def send(self, n=4800, amp=0.1):
        self.b.cb(np.full((n, 1), amp, dtype=np.float32), None)

    def test_pause_closes_stream_without_state_and_resume_reopens_without_capture_start(self):
        self.start()
        self.send()
        self.assertTrue(wait_for(lambda: self.blocks))
        self.assertEqual(self.log.count("capture_start"), 1)
        n_states = len(self.states)
        self.m.pause()
        self.assertTrue(self.b.opens[0].closed)
        self.assertTrue(self.m.paused)
        self.assertEqual(len(self.states), n_states)            # 상태 알림 없음(호출한 쪽이 "일시 정지" 로 보인다)
        self.assertEqual(self.m.level(), 0.0)
        n_blocks = len(self.blocks)
        self.send()                                             # 닫힌 스트림의 뒤늦은 블록
        time.sleep(0.2)
        self.assertEqual(len(self.blocks), n_blocks)
        self.assertTrue(self.m.resume())
        self.assertEqual(len(self.b.opens), 2)
        self.assertEqual(self.log.count("capture_start"), 1)    # 다시 열어도 "수집 시작" 은 더하지 않는다
        self.send()
        self.assertTrue(wait_for(lambda: len(self.blocks) > n_blocks))
        self.assertEqual(self.states[-1][0], "수집 중")

    def test_stale_block_of_closed_stream_is_dropped_after_resume(self):
        self.start()
        old_cb = self.b.cb
        self.m.pause()
        self.assertTrue(self.m.resume())
        n = len(self.blocks)
        old_cb(np.full((4800, 1), 0.1, dtype=np.float32), None)     # 닫힌 스트림의 콜백
        self.b.fin and None
        time.sleep(0.2)
        self.assertEqual(len(self.blocks), n)

    def test_pause_before_first_open_is_noop_and_resume_false(self):
        self.assertFalse(self.m.resume())
        self.m.pause()
        self.assertFalse(self.m.paused)

    def test_resume_failure_reports_stopped_and_returns_false(self):
        self.start()
        self.m.pause()
        self.b.fail_open = True
        self.assertFalse(self.m.resume())
        self.assertEqual(self.states[-1][0], "중단")

    def test_silence_is_counted_again_after_resume(self):
        m = MicSource(self.b, eventlog=self.log, tick_s=0.02, poll_s=10, stall_s=1000, silence_s=0.6)
        self.addCleanup(m.stop)
        states = []
        m.start(lambda b: None, lambda s, d="": states.append(s))
        self.assertTrue(wait_for(lambda: self.b.opens))
        self.b.cb(np.zeros((4800, 1), dtype=np.float32), None)           # 0.1 초 무음
        time.sleep(0.2)
        m.pause()
        m.resume()
        self.b.cb(np.zeros((4800, 1), dtype=np.float32), None)           # 재생 뒤 0.1 초 무음: 합쳐서 세지 않는다
        time.sleep(0.3)
        self.assertNotIn("입력 없음", states)

    def test_stop_while_paused_ends(self):
        self.start()
        self.m.pause()
        self.m.stop()
        self.assertEqual(self.states[-1][0], "종료")


HELPER = """#!{py}
import sys, time
import numpy as np
x = (0.1 * np.sin(np.arange(4800) * 0.05)).astype('<f4')
st = np.stack([x, x], axis=1).astype('<f4').tobytes()
out = sys.stdout.buffer
for _ in range(400):
    out.write(st); out.flush(); time.sleep(0.05)
sys.stdin.buffer.read()
"""

PERMISSION = """#!{py}
import sys
sys.stderr.write('{{"error":"no_permission","detail":"denied"}}\\n')
sys.exit(3)
"""


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def write_helper(d, body):
    import stat
    import sys
    path = os.path.join(d, "helper.py")
    with open(path, "w") as f:
        f.write(body.format(py=sys.executable))
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class SystemSoundPauseTest(unittest.TestCase):
    def test_pause_ends_helper_pid_and_resume_starts_a_new_one(self):
        with tempfile.TemporaryDirectory() as d:
            src = SystemSoundSource(write_helper(d, HELPER), tick_s=0.02, poll_s=10)
            blocks, states = [], []
            self.addCleanup(src.stop)
            src.start(blocks.append, lambda s, dt="": states.append((s, dt)))
            self.assertTrue(wait_for(lambda: blocks))
            be = src._backend
            pid1 = be.streams[0].pid
            self.assertTrue(pid_alive(pid1))
            src.pause()
            self.assertTrue(wait_for(lambda: not pid_alive(pid1), 5))     # 기록한 PID 의 프로세스가 끝났다
            n = len(blocks)
            time.sleep(0.3)
            self.assertEqual(len(blocks), n)                               # 일시 정지 중에는 블록이 없다
            self.assertEqual(len(be.streams), 1)                           # 일시 정지 중에는 보조 프로세스가 없다
            self.assertNotIn("중단", [s[0] for s in states])
            self.assertTrue(src.resume())
            self.assertEqual(len(be.streams), 2)                           # 시작 횟수가 1 늘었다 (AC-FR3-13)
            pid2 = be.streams[1].pid
            self.assertNotEqual(pid1, pid2)
            self.assertTrue(wait_for(lambda: len(blocks) > n))
            src.stop()
            self.assertTrue(wait_for(lambda: not pid_alive(pid2), 5))

    def test_resume_no_permission_reports_permission_text_and_is_not_restarted(self):
        with tempfile.TemporaryDirectory() as d:
            counter = os.path.join(d, "count")
            good = write_helper(d, HELPER)
            src = SystemSoundSource(good, tick_s=0.02, retry_s=0.2, poll_s=10)
            blocks, states = [], []
            self.addCleanup(src.stop)
            src.start(blocks.append, lambda s, dt="": states.append((s, dt)))
            self.assertTrue(wait_for(lambda: blocks))
            src.pause()
            # 일시 정지 중에 권한이 철회된 상황: 같은 경로의 보조 프로그램이 종료 코드 3 으로 끝난다
            with open(good, "w") as f:
                import sys
                f.write(("#!%s\nopen(%r,'a').write('x')\n" % (sys.executable, counter)) +
                        PERMISSION.split("\n", 1)[1].replace("{{", "{").replace("}}", "}"))
            src.resume()
            self.assertTrue(wait_for(lambda: ("중단", system_sound.REASON_TEXT["no_permission"]) in states))
            time.sleep(0.8)
            with open(counter) as f:
                self.assertEqual(len(f.read()), 1)                          # 다시 시작하지 않는다
            self.assertTrue(src._backend.no_retry())


if __name__ == "__main__":
    unittest.main()
