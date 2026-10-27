"""사전 지식 화면의 문구(AC-FR2-14, 기능 정의 FR-2 "사전 지식 화면의 문구" 표)의 사유 → 문구 대응."""
import unittest

from nsu_kangs_rab.core import materials_view as mv
from nsu_kangs_rab.core.context import Held, Unreadable

REASONS = ("not_found", "permission", "format", "encrypted", "no_text", "decode", "timeout", "io", "dependency",
           "image_bytes", "registered_bytes")


class TextsTest(unittest.TestCase):
    def test_every_unreadable_reason_has_reason_and_action(self):
        self.assertEqual(set(mv.UNREADABLE_TEXT), set(REASONS))
        for r in REASONS:
            t = mv.unreadable_text(Unreadable("a.txt", r, limit=3_750_000))
            self.assertTrue(t.startswith("a.txt: "), t)
            reason, action = mv.UNREADABLE_TEXT[r]
            self.assertIn(action, t)
            self.assertNotIn("{limit}", t)

    def test_applied_limits_are_shown(self):
        self.assertIn("상한(3.75 MB)", mv.unreadable_text(Unreadable("i.png", "image_bytes", limit=3_750_000)))
        self.assertIn("상한(15 MB)", mv.unreadable_text(Unreadable("i.png", "registered_bytes", limit=15_000_000)))
        self.assertIn("상한(2.5 MB)", mv.unreadable_text(Unreadable("i.png", "registered_bytes", limit=2_500_000)))
        self.assertIn("상한(5만 자)", mv.held_text(Held("a", "text", "chars", True, chars=50001, limit=50000)))
        self.assertIn("상한(20자)", mv.held_text(Held("a", "text", "chars", True, chars=30, limit=20)))
        self.assertIn("상한(6장)", mv.held_text(Held("a", "image", "images", True, limit=6)))
        t = mv.held_text(Held("a", "text", "file_size", False, size=2048, limit=1024))
        self.assertIn("파일 크기가 제한을 넘습니다", t)
        self.assertIn("2.0 KB", t)
        self.assertIn("1.0 KB", t)
        self.assertIn("취소만 제공합니다", t)


if __name__ == "__main__":
    unittest.main()


class PasteNameTest(unittest.TestCase):
    """D-043: 같은 이름이 있으면 '붙여넣은 글 2' 처럼 번호를 붙인다(AC-FR2-14)."""

    def test_second_and_third_paste_are_numbered(self):
        from nsu_kangs_rab.core.context import ContextStore
        m = mv.MaterialsModel(ContextStore())
        for t in ("가", "나", "다"):
            m.add_text("", t)
        self.assertEqual([r.name for r in m.rows()], ["붙여넣은 글", "붙여넣은 글 2", "붙여넣은 글 3"])
