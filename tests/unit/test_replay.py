"""D-066: 전사 재생 입력(core/replay.py)의 파일 읽기와 재생 순서."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import replay as RP  # noqa: E402


class LoadTest(unittest.TestCase):
    def test_load_skips_bad_lines_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "r.jsonl"
            f.write_text("\n".join([
                "# 주석", "", json.dumps({"start": 0, "end": 1, "text": "가"}),
                json.dumps({"start": 2, "end": 1, "text": "역전"}), "{깨짐",
                json.dumps({"start": 0, "end": 1}), json.dumps({"start": 1, "end": 2, "text": "나", "arrive_after_ms": 500})]),
                encoding="utf-8")
            items, errors = RP.load(str(f))
        self.assertEqual([i["text"] for i in items], ["가", "나"])
        self.assertEqual(items[1]["arrive_after_ms"], 500.0)
        self.assertEqual(len(errors), 3)


class FeederTest(unittest.TestCase):
    def test_late_final_does_not_hold_back_later_segment(self):
        items = [{"start": 0.0, "end": 0.05, "text": "a", "arrive_after_ms": 200, "start_wall": None, "end_wall": None},
                 {"start": 0.05, "end": 0.1, "text": "b", "arrive_after_ms": 0, "start_wall": None, "end_wall": None}]
        got, done = [], threading.Event()

        def seg(s):
            got.append(("seg", s.n))
            if len(got) == 2:
                done.set()
        f = RP.ReplayFeeder(items, 1.0)
        f.start(seg)
        self.assertTrue(done.wait(3))
        f.join(1)
        self.assertEqual(got, [("seg", 2), ("seg", 1)])   # b 는 a 의 전사가 늦게 도착하기 전에 온다

    def test_speed_divides_time(self):  # --dev-speed
        import time
        items = [{"start": 0.0, "end": 2.0, "text": "x", "arrive_after_ms": 1000, "start_wall": None, "end_wall": None}]
        got, done = [], threading.Event()
        f = RP.ReplayFeeder(items, 10.0)         # 2 초 + 1 초 지연 → 0.3 초
        t0 = time.monotonic()
        f.start(lambda s: (got.append(s.n), done.set()))
        self.assertTrue(done.wait(2))
        self.assertLess(time.monotonic() - t0, 1.5)
        f.join(1)

    def test_stop_ends_wait(self):
        items = [{"start": 0.0, "end": 30.0, "text": "x", "arrive_after_ms": 0, "start_wall": None, "end_wall": None}]
        got = []
        f = RP.ReplayFeeder(items, 1.0)
        f.start(got.append)
        f.stop()
        f.join(2)
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
