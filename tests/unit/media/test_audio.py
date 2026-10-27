"""K-10 단위 시험(장치 없음): 재표본화 · 무음 감시 · 중단 감시 · 기본 장치 변경 · 한 스트림."""
import threading
import time
import unittest

import numpy as np
from scipy.signal import resample_poly

from nsu_kangs_rab.platform.audio.mic_source import MicSource
from nsu_kangs_rab.platform.audio.resampler import Resampler


class ResamplerTest(unittest.TestCase):
    def test_streaming_equals_one_shot(self):
        rng = np.random.default_rng(1)
        for sr in (48000, 44100, 8000, 24000, 32000):
            x = rng.standard_normal(sr * 2).astype(np.float32)
            g = np.gcd(16000, sr)
            ref = resample_poly(x.astype(np.float64), 16000 // g, sr // g)
            r = Resampler(sr)
            out, i = [], 0
            while i < x.size:
                sz = int(rng.integers(1, 4000))
                out.append(r.process(x[i:i + sz]))
                i += sz
            out.append(r.flush())
            y = np.concatenate(out)
            self.assertEqual(len(y), len(ref), sr)
            self.assertLess(float(np.max(np.abs(y - ref))), 1e-5, sr)

    def test_downmix_and_passthrough(self):
        r = Resampler(16000)
        st = np.stack([np.ones(100), np.zeros(100)], axis=1).astype(np.float32)
        y = r.process(st)
        self.assertEqual(y.shape, (100,))
        self.assertTrue(np.allclose(y, 0.5))

    def test_output_rate(self):
        r = Resampler(48000)
        n = sum(r.process(np.zeros(4800, dtype=np.float32)).size for _ in range(10)) + r.flush().size
        self.assertEqual(n, 16000)


def _write_wav(path, seconds, rate=16000):
    import wave
    x = (0.1 * np.sin(np.arange(int(seconds * rate)) * 0.05) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.tobytes())


class FileSourceSpeedTest(unittest.TestCase):
    def _run(self, speed):
        import os
        import tempfile
        from nsu_kangs_rab.platform.audio.file_source import FileSource
        clock = Clock()
        sleeps = []
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.wav")
            _write_wav(p, 3.0)

            def sleep(s):
                sleeps.append(s)
                clock.t += s
            fs = FileSource(p, speed=speed, mono=clock, sleep=sleep)
            blocks = []
            fs._run(blocks.append, lambda s, d="": None)
        return blocks, sleeps, clock

    def test_t_mono_is_file_position_at_any_speed(self):
        for speed in (1.0, 8.0, 0.5, 0, None):
            blocks, _, _ = self._run(speed)
            t0 = blocks[0].t_mono
            pos = 0
            for b in blocks:
                self.assertAlmostEqual(b.t_mono - t0, pos / 16000, places=6, msg=speed)
                pos += b.samples.size

    def test_speed_changes_only_arrival_pacing(self):
        _, _, c1 = self._run(1.0)
        _, _, c8 = self._run(8.0)
        self.assertAlmostEqual(c1.t - 100.0, 3.0 - 0.1, delta=0.15)
        self.assertAlmostEqual(c8.t - 100.0, (3.0 - 0.1) / 8, delta=0.05)

    def test_block_timestamps_same_at_any_speed(self):
        blocks1, _, _ = self._run(1.0)
        blocks8, _, _ = self._run(8.0)
        self.assertEqual([round(b.t_mono, 6) for b in blocks1], [round(b.t_mono, 6) for b in blocks8])
        self.assertEqual(sum(b.samples.size for b in blocks1), sum(b.samples.size for b in blocks8))
        self.assertGreaterEqual(len(blocks1), 30)


class FakeStream:
    def __init__(self, backend):
        self.b = backend
        self.started = self.closed = False

    def start(self):
        if self.b.fail_open:
            raise OSError("denied")
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


class FakeBackend:
    def __init__(self, dev=("Built-in Mic", 48000, 1)):
        self.dev = dev
        self.fail_open = False
        self.opens = []
        self.cb = None
        self.fin = None

    def default_input(self):
        return self.dev

    def open(self, callback, finished, device, samplerate, channels):
        self.cb, self.fin = callback, finished
        s = FakeStream(self)
        self.opens.append((device, samplerate, channels, s))
        return s


class Log:
    def __init__(self):
        self.ev = []

    def emit(self, t, **f):
        self.ev.append((t, f))


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def mk(backend=None, **kw):
    b = backend or FakeBackend()
    log, clock, states, blocks = Log(), Clock(), [], []
    m = MicSource(b, eventlog=log, mono=clock, **kw)
    m._on_block, m._on_state = blocks.append, lambda s, d="": states.append((s, d))
    return m, b, log, clock, states, blocks


def feed(m, clock, rate, sec, amp=0.1, step=0.1, seed=0):
    rng = np.random.default_rng(seed)
    for _ in range(int(round(sec / step))):
        clock.t += step
        n = int(rate * step)
        x = (amp * rng.standard_normal((n, 1))).astype(np.float32) if amp else np.zeros((n, 1), dtype=np.float32)
        m._handle_block(x, clock.t)
        m._check(clock.t)


class MicLogicTest(unittest.TestCase):
    def test_start_converts_to_16k_and_logs(self):
        m, b, log, clock, states, blocks = mk()
        m._open(clock.t)
        feed(m, clock, 48000, 2.0)
        self.assertEqual(log.ev[0][0], "capture_start")
        self.assertEqual(log.ev[0][1]["samplerate"], 48000)
        self.assertEqual(states[0][0], "수집 중")
        total = sum(b_.samples.size for b_ in blocks)
        self.assertAlmostEqual(total / 16000, 2.0, delta=0.05)
        self.assertTrue(all(b_.samples.dtype == np.float32 for b_ in blocks))
        ts = [b_.t_mono for b_ in blocks]
        self.assertEqual(ts, sorted(ts))
        self.assertGreater(m.level(), 0.0)

    def test_silence_10s_notice_and_recovery(self):
        m, b, log, clock, states, blocks = mk(silence_s=10.0)
        m._open(clock.t)
        feed(m, clock, 48000, 9.0, amp=0.0)
        self.assertNotIn("입력 없음", [s for s, _ in states])
        feed(m, clock, 48000, 2.0, amp=0.0)
        self.assertEqual([s for s, _ in states].count("입력 없음"), 1)
        feed(m, clock, 48000, 1.0, amp=0.1)
        self.assertEqual(states[-1][0], "수집 중")

    def test_changing_level_never_reports_silence(self):
        m, b, log, clock, states, blocks = mk(silence_s=3.0)
        m._open(clock.t)
        feed(m, clock, 48000, 8.0, amp=0.05)
        self.assertNotIn("입력 없음", [s for s, _ in states])

    def test_stall_detected_and_reopened(self):
        m, b, log, clock, states, blocks = mk(stall_s=3.0, retry_s=1.0)
        m._open(clock.t)
        feed(m, clock, 48000, 1.0)
        for _ in range(60):  # 입력 없이 시간만 흐른다 (중단 3 s + 재시도 1 s)
            clock.t += 0.1
            m._check(clock.t)
        self.assertIn("중단", [s for s, _ in states])
        self.assertEqual(len(b.opens), 2)  # 다시 열었다
        feed(m, clock, 48000, 1.0)
        self.assertEqual(states[-1][0], "수집 중")
        self.assertEqual([e[0] for e in log.ev].count("capture_start"), 2)

    def test_no_stall_watch_before_first_block(self):
        """결정 0091 M2 (D-193): 첫 블록 전에는 stall_s 를 넘겨도 중단 · 다시 열기가 없다. 첫 블록 뒤에는 지금처럼 중단한다."""
        m, b, log, clock, states, blocks = mk(stall_s=3.0, retry_s=1.0)
        m._open(clock.t)
        for _ in range(200):                  # 20초 동안 블록 없음 (stall_s 의 6배 이상)
            clock.t += 0.1
            m._check(clock.t)
        self.assertEqual(len(b.opens), 1)
        self.assertNotIn("중단", [s for s, _ in states])
        self.assertNotIn("capture_stalled", [e[0] for e in log.ev])
        feed(m, clock, 48000, 1.0)            # 첫 블록이 온다
        for _ in range(60):
            clock.t += 0.1
            m._check(clock.t)
        self.assertIn("중단", [s for s, _ in states])
        self.assertEqual([e[1].get("reason") for e in log.ev if e[0] == "capture_stalled"], ["no_blocks"])
        self.assertEqual(len(b.opens), 2)

    def test_stream_finished_before_first_block_is_still_reported(self):
        m, b, log, clock, states, blocks = mk(stall_s=3.0, retry_s=1.0)
        m._open(clock.t)
        m._handle_finished(clock.t)
        self.assertIn("중단", [s for s, _ in states])
        self.assertEqual([e[1].get("reason") for e in log.ev if e[0] == "capture_stalled"], ["stream_finished"])

    def test_finished_before_first_block_is_start_failure_without_restart(self):
        """D-194: 첫 블록 전에 끝난 스트림(종료 코드 4 · 0 등)은 시작 실패이다: 중단 상세에 접두어, 다시 열지 않는다."""
        from nsu_kangs_rab.core.appstate import START_FAILED_PREFIX
        for why in (None, "화면 기록 스트림 오류"):
            with self.subTest(why=why):
                b = FakeBackend()
                b.last_error = lambda why=why: why
                m, b, log, clock, states, blocks = mk(b, stall_s=3.0, retry_s=1.0)
                m._open(clock.t)
                m._handle_finished(clock.t)
                self.assertEqual(states[-1][0], "중단")
                self.assertTrue(states[-1][1].startswith(START_FAILED_PREFIX + ": "), states[-1])
                for _ in range(100):
                    clock.t += 0.1
                    m._check(clock.t)
                self.assertEqual(len(b.opens), 1)                 # 다시 열지 않았다

    def test_finished_after_first_block_restarts(self):
        from nsu_kangs_rab.core.appstate import START_FAILED_PREFIX
        m, b, log, clock, states, blocks = mk(stall_s=3.0, retry_s=1.0)
        m._open(clock.t)
        feed(m, clock, 48000, 1.0)
        m._handle_finished(clock.t)
        self.assertFalse(states[-1][1].startswith(START_FAILED_PREFIX))
        for _ in range(30):
            clock.t += 0.1
            m._check(clock.t)
        self.assertEqual(len(b.opens), 2)

    def _advance(self, m, clock, sec):
        for _ in range(int(round(sec / 0.1))):
            clock.t += 0.1
            m._check(clock.t)

    def test_auto_retry_finished_before_first_block_is_retried_again(self):
        """D-195 L1: 수집 중 끝남 → 자동 재시도 스트림이 블록 없이 바로 끝남 → 접두어 없이 중단하고 다시 열어 수집이 돌아온다."""
        from nsu_kangs_rab.core.appstate import START_FAILED_PREFIX
        m, b, log, clock, states, blocks = mk(stall_s=3.0, retry_s=1.0)
        m._open(clock.t)
        feed(m, clock, 48000, 1.0)
        m._handle_finished(clock.t)                       # 첫 블록 뒤의 종료
        self._advance(m, clock, 1.2)
        self.assertEqual(len(b.opens), 2)                 # 자동 재시도
        m._handle_finished(clock.t)                       # 블록 없이 바로 끝남 (종료 코드 4 에 해당)
        self.assertEqual(states[-1][0], "중단")
        self.assertFalse(states[-1][1].startswith(START_FAILED_PREFIX), states[-1])
        self._advance(m, clock, 1.2)
        self.assertEqual(len(b.opens), 3)
        feed(m, clock, 48000, 1.0)
        self.assertEqual(states[-1][0], "수집 중")

    def test_auto_retry_after_stall_then_finished_before_block_is_retried_again(self):
        """D-195 L2: 블록 멈춤(정지 감시) → 자동 재시도 → 블록 없이 바로 끝남 → 다시 열어 수집이 돌아온다."""
        m, b, log, clock, states, blocks = mk(stall_s=3.0, retry_s=1.0)
        m._open(clock.t)
        feed(m, clock, 48000, 1.0)
        self._advance(m, clock, 4.3)                      # 정지 감시 작동 + 재시도
        self.assertEqual(len(b.opens), 2)
        m._handle_finished(clock.t)
        self._advance(m, clock, 1.2)
        self.assertEqual(len(b.opens), 3)
        feed(m, clock, 48000, 1.0)
        self.assertEqual(states[-1][0], "수집 중")

    def test_auto_retry_stream_without_blocks_is_stall_watched(self):
        """D-195: 자동 재시도로 연 스트림은 블록을 하나도 내지 않아도 정지 감시가 작동해 다시 연다 (열린 직후의 유예 뒤)."""
        m, b, log, clock, states, blocks = mk(stall_s=3.0, retry_s=1.0)
        m._open(clock.t)
        feed(m, clock, 48000, 1.0)
        m._handle_finished(clock.t)
        self._advance(m, clock, 1.2)
        self.assertEqual(len(b.opens), 2)
        self._advance(m, clock, 3.5)                      # 유예 3초 뒤 no_blocks → 중단 → 재시도
        self.assertIn("no_blocks", [e[1].get("reason") for e in log.ev if e[0] == "capture_stalled"])
        self._advance(m, clock, 1.2)
        self.assertEqual(len(b.opens), 3)

    def test_default_device_change_follows_new_device(self):
        m, b, log, clock, states, blocks = mk(poll_s=0.5)
        m._open(clock.t)
        feed(m, clock, 48000, 1.0)
        b.dev = ("AirPods", 16000, 1)
        feed(m, clock, 16000, 1.0)
        self.assertEqual(len(b.opens), 2)
        self.assertEqual(b.opens[1][:3], ("AirPods", 16000, 1))
        names = [e[0] for e in log.ev]
        self.assertIn("device_change", names)
        self.assertEqual(names.count("capture_start"), 2)
        self.assertIn("장치 변경", [s for s, _ in states])
        self.assertEqual(states[-1][0], "수집 중")

    def test_no_default_device_then_recovers(self):
        m, b, log, clock, states, blocks = mk(poll_s=0.5, retry_s=1.0)
        m._open(clock.t)
        feed(m, clock, 48000, 1.0)
        b.dev = None
        for _ in range(20):
            clock.t += 0.1
            m._check(clock.t)
        self.assertEqual(states[-1], ("중단", "기본 입력 장치 없음"))
        b.dev = ("Built-in Mic", 48000, 1)
        for _ in range(30):
            clock.t += 0.1
            m._check(clock.t)
        self.assertEqual(len(b.opens), 2)
        feed(m, clock, 48000, 1.0)
        self.assertEqual(states[-1][0], "수집 중")

    def test_open_failure_reports_and_retries(self):
        m, b, log, clock, states, blocks = mk(retry_s=1.0)
        b.fail_open = True
        self.assertFalse(m._open(clock.t))
        self.assertEqual(states[-1][0], "중단")
        self.assertIn("capture_open_failed", [e[0] for e in log.ev])
        b.fail_open = False
        clock.t += 1.5
        m._check(clock.t)
        self.assertEqual(len(b.opens), 2)
        self.assertTrue(b.opens[1][3].started)

    def test_stream_finished_triggers_reopen(self):
        m, b, log, clock, states, blocks = mk(retry_s=0.5)
        m._open(clock.t)
        feed(m, clock, 48000, 0.5)            # D-194: 첫 블록 뒤에 끝난 스트림만 다시 연다
        m._handle_finished(clock.t)
        self.assertEqual(states[-1][0], "중단")
        clock.t += 0.6
        m._check(clock.t)
        self.assertEqual(len(b.opens), 2)

    def test_event_log_has_no_audio(self):
        m, b, log, clock, states, blocks = mk()
        m._open(clock.t)
        feed(m, clock, 48000, 1.0)
        for _, f in log.ev:
            self.assertFalse(any(isinstance(v, np.ndarray) for v in f.values()))


def db_amp(db):
    return 10 ** (db / 20.0)


class SilenceDefinitionTest(unittest.TestCase):
    """A-10: RMS -80 dBFS 이하가 10 초 연속이면 `입력 없음`. 지속음 -20 · 잡음 -60 · -70 은 무음이 아니다."""

    def _states(self, amp, sec=12.0, tone=False, rate=48000):
        m, b, log, clock, states, blocks = mk(FakeBackend(("Mic", rate, 1)), silence_s=10.0)
        m._open(clock.t)
        step = 0.1
        rng = np.random.default_rng(3)
        for i in range(int(sec / step)):
            clock.t += step
            n = int(rate * step)
            if tone:
                x = (np.sqrt(2) * amp * np.sin(2 * np.pi * 440 * (np.arange(n) + i * n) / rate)).astype(np.float32)
            else:
                x = (amp * rng.standard_normal(n)).astype(np.float32)
            m._handle_block(x[:, None], clock.t)
            m._check(clock.t)
        return [s for s, _ in states]

    def test_below_threshold_is_silence(self):
        for db in (-85, -95):
            self.assertEqual(self._states(db_amp(db)).count("입력 없음"), 1, db)

    def test_above_threshold_is_not_silence(self):
        for db, tone in ((-20, True), (-60, False), (-70, False)):
            self.assertNotIn("입력 없음", self._states(db_amp(db), tone=tone), db)

    def test_boundary_at_16khz_without_resampling(self):
        """16 kHz 입력은 변환이 없어 RMS 가 그대로다: -79 는 무음이 아니고 -81 은 무음이다(백색 잡음의 RMS 변동 ±0.5 dB 안)."""
        self.assertNotIn("입력 없음", self._states(db_amp(-78), rate=16000))
        self.assertEqual(self._states(db_amp(-82), rate=16000).count("입력 없음"), 1)

    def test_not_before_ten_seconds(self):
        self.assertNotIn("입력 없음", self._states(db_amp(-90), sec=9.5))

    def test_returns_to_collecting_within_one_block_when_sound_exceeds(self):
        m, b, log, clock, states, blocks = mk(silence_s=10.0)
        m._open(clock.t)
        feed(m, clock, 48000, 11.0, amp=0.0)
        self.assertEqual(states[-1][0], "입력 없음")
        t = clock.t
        feed(m, clock, 48000, 0.2, amp=0.05)
        self.assertEqual(states[-1][0], "수집 중")
        self.assertLessEqual(clock.t - t, 2.0)

    def test_loud_blip_resets_the_ten_seconds(self):
        m, b, log, clock, states, blocks = mk(silence_s=10.0)
        m._open(clock.t)
        feed(m, clock, 48000, 6.0, amp=0.0)
        feed(m, clock, 48000, 0.1, amp=0.05)
        feed(m, clock, 48000, 8.0, amp=0.0)
        self.assertNotIn("입력 없음", [s for s, _ in states])
        feed(m, clock, 48000, 3.0, amp=0.0)
        self.assertEqual([s for s, _ in states].count("입력 없음"), 1)

    def test_level_dbfs(self):
        m, b, log, clock, states, blocks = mk(FakeBackend(("Mic", 16000, 1)))
        m._open(clock.t)
        self.assertEqual(m.level_dbfs(), -120.0)
        feed(m, clock, 16000, 0.5, amp=0.0)
        self.assertEqual(m.level_dbfs(), -120.0)
        feed(m, clock, 16000, 0.5, amp=0.1)
        self.assertAlmostEqual(m.level_dbfs(), -20.0, delta=1.0)


class MicThreadTest(unittest.TestCase):
    def test_single_stream_and_stop(self):
        b = FakeBackend()
        states, blocks = [], []
        m = MicSource(b, tick_s=0.02, poll_s=10)
        m.start(blocks.append, lambda s, d="": states.append(s))
        m.start(blocks.append, lambda s, d="": states.append(s))  # 무시된다
        deadline = time.time() + 3
        while not b.opens and time.time() < deadline:
            time.sleep(0.01)
        b.cb(np.full((4800, 1), 0.1, dtype=np.float32), None)
        while not blocks and time.time() < deadline:
            time.sleep(0.01)
        m.stop()
        self.assertEqual(len(b.opens), 1)
        self.assertTrue(blocks)
        self.assertTrue(b.opens[0][3].closed)
        self.assertEqual(states[-1], "종료")


if __name__ == "__main__":
    unittest.main()
