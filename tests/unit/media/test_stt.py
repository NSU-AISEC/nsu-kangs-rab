"""K-09 단위 시험 중 파이프라인과 무관한 것: 음성 파일 입력(FileSource).
보관한 분할 측정 스크립트의 시험은 test_stt_experiment_scripts.py.
`SttPipeline` 은 test_stt_pipeline.py, 보조 프로세스는 test_stt_speech.py."""
import json
import os
import tempfile
import unittest
import wave

import numpy as np

from nsu_kangs_rab.platform.audio.file_source import FileSource
from nsu_kangs_rab.platform.audio.types import SAMPLE_RATE, PcmBlock


def tone(sec, amp=0.1, seed=0):
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal(int(sec * SAMPLE_RATE))).astype(np.float32)


def silence(sec):
    return np.zeros(int(sec * SAMPLE_RATE), dtype=np.float32)


def write_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


class FileSourceTest(unittest.TestCase):
    def test_bad_format_reports_state(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.wav")
            with wave.open(p, "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(48000)
                w.writeframes(b"\0" * 400)
            states = []
            s = FileSource(p, speed=None)
            s.start(lambda b: None, lambda st, d="": states.append(st))
            s.join(5)
            self.assertEqual(states, ["중단"])

    def test_realtime_pacing_uses_clock(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.wav")
            write_wav(p, silence(1.0))
            now = [0.0]
            slept = []

            def sleep(t):
                slept.append(t)
                now[0] += t
            got = []
            s = FileSource(p, speed=1.0, mono=lambda: now[0], sleep=sleep)
            s.start(got.append, lambda *a: None)
            s.join(5)
            self.assertEqual(len(got), 10)
            self.assertAlmostEqual(got[-1].t_mono, 0.9, places=6)
            self.assertAlmostEqual(sum(slept), 0.9, places=6)


if __name__ == "__main__":
    unittest.main()
