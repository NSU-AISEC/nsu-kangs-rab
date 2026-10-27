"""core/types.py 의 경계 자료형: 계획 2-3절의 필드와 같은지, core 가 platform 을 가져오지 않는지."""
import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import types as T  # noqa: E402


class BoundaryTypes(unittest.TestCase):
    def names(self, cls):
        return [f.name for f in dataclasses.fields(cls)]

    def test_fields_match_plan_2_3(self):
        self.assertEqual(self.names(T.Segment), ["n", "start_wall", "end_wall", "start_mono", "end_mono", "text"])
        self.assertFalse(hasattr(T, "PendingSegment"))   # M-3: 미완료 조각 형식은 지웠다
        self.assertEqual(self.names(T.CaptureItem),
                         ["path", "source", "width", "height", "sent_width", "sent_height", "sha256", "t_wall"])

    def test_frozen(self):
        s = T.Segment(1, "a", "b", 0.0, 1.0, "x")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.text = "y"

    def test_sources(self):
        self.assertEqual(T.CAPTURE_SOURCES, ("캡처", "붙여넣기", "끌어다 놓기"))

    def test_core_types_has_no_platform_import(self):
        t = (ROOT / "src/mac/nsu_kangs_rab/core/types.py").read_text(encoding="utf-8")
        self.assertNotIn("nsu_kangs_rab.platform", t)
        self.assertNotIn("PySide6", t)


if __name__ == "__main__":
    unittest.main()
