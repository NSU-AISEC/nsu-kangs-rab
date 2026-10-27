"""자체 점검의 메뉴 막대 그림 확인(결정 0085): 6장이 있어야 통과하고 빠지면 실패한다."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "mac"))

from nsu_kangs_rab.app import selfcheck
from nsu_kangs_rab.core import resources


def _check():
    return dict(selfcheck._construct())["resource:menubar_icons"]


class SelfCheckMenubarTest(unittest.TestCase):
    def test_passes_with_all_six(self):
        self.assertEqual(_check()(), 6)

    def test_fails_when_one_is_missing_or_unreadable(self):
        src = resources._DIR / "menubar"
        old = resources._DIR
        with tempfile.TemporaryDirectory() as t:
            dst = Path(t) / "menubar"
            shutil.copytree(src, dst)
            try:
                resources._DIR = Path(t)
                self.assertEqual(_check()(), 6)
                (dst / "face_warn_36.png").unlink()
                with self.assertRaises(FileNotFoundError):
                    _check()()
                (dst / "face_warn_36.png").write_bytes(b"not a png")
                with self.assertRaises(RuntimeError):
                    _check()()
            finally:
                resources._DIR = old


if __name__ == "__main__":
    unittest.main()
