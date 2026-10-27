"""캡처 액자의 좌표 계산(`core/framegeom.py`): 안쪽 영역 · 창 사각형 · 저장 복원 · 화면 밖 보정 (AC-FR12-10 · 11 · 12 · 15)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))

from nsu_kangs_rab.core import framegeom as G  # noqa: E402

PRIMARY = G.Rect(0, 25, 1440, 875)          # 메뉴 막대를 뺀 가용 영역
EXTRA = G.Rect(1440, 0, 1920, 1080)
FULL = G.Rect(0, 0, 1440, 900)             # 화면 전체
AV = G.Rect(0, 25, 1440, 875)              # 가용 영역(메뉴 막대 아래)


class GeomTest(unittest.TestCase):
    def test_inner_region_excludes_border(self):          # AC-FR12-10
        f = G.Rect(100, 200, 640, 360)
        self.assertEqual(G.inner_region(f), G.Rect(103, 203, 634, 354))

    def test_no_strip_and_handles_inside_outer_rect(self):     # 결정 0080: 이름표 띠가 없다. 손잡이는 바깥 사각형 안쪽이다
        self.assertFalse(hasattr(G, "STRIP") or hasattr(G, "window_of") or hasattr(G, "tag_below"))
        f = G.Rect(100, 200, 640, 360)
        self.assertEqual(G.HANDLE, 14)
        self.assertGreater(G.inner_region(f).x, f.x)              # 테두리는 안쪽 영역 바깥이다

    def test_from_setting_validates(self):
        self.assertEqual(G.from_setting({"x": 1, "y": 2, "w": 400, "h": 300}), G.Rect(1, 2, 400, 300))
        for bad in (None, {}, {"x": 1}, {"x": "1", "y": 2, "w": 400, "h": 300}, {"x": 1, "y": 2, "w": 10, "h": 300},
                    {"x": True, "y": 2, "w": 400, "h": 300}, [1, 2, 3, 4]):
            self.assertIsNone(G.from_setting(bad), bad)

    def test_restore_saved_inside_screen(self):            # AC-FR12-11
        saved = G.Rect(300, 200, 800, 450).as_dict()
        r, notice = G.restore(saved, [PRIMARY])
        self.assertEqual((r, notice), (G.Rect(300, 200, 800, 450), False))

    def test_restore_on_second_screen_when_present(self):
        saved = G.Rect(1600, 200, 800, 450).as_dict()
        self.assertEqual(G.restore(saved, [PRIMARY, EXTRA]), (G.Rect(1600, 200, 800, 450), False))

    def test_restore_off_screen_uses_primary_default_and_notifies(self):      # AC-FR12-12
        saved = G.Rect(1600, 200, 800, 450).as_dict()            # 외장 모니터를 뗀 뒤
        r, notice = G.restore(saved, [PRIMARY])
        self.assertTrue(notice)
        self.assertEqual(r, G.default_frame(PRIMARY))
        self.assertTrue(G.placeable(r, PRIMARY))

    def test_restore_spanning_two_screens_is_default(self):  # 두 화면에 걸친 저장값은 허용하지 않는다
        saved = G.Rect(1200, 200, 800, 450).as_dict()
        self.assertEqual(G.restore(saved, [PRIMARY, EXTRA]), (G.default_frame(PRIMARY), True))

    def test_restore_without_saved_has_no_notice(self):
        self.assertEqual(G.restore(None, [PRIMARY]), (G.default_frame(PRIMARY), False))

    def test_default_frame_inner_960x540_centered_on_primary(self):
        r = G.default_frame(PRIMARY)
        i = G.inner_region(r)
        self.assertEqual((i.w, i.h), (960, 540))
        self.assertTrue(G.placeable(r, PRIMARY))
        self.assertLessEqual(abs((r.x + r.w // 2) - (PRIMARY.x + PRIMARY.w // 2)), 1)

    def test_default_frame_shrinks_keeping_16_9_within_80_percent(self):
        small = G.Rect(0, 0, 800, 600)
        r = G.default_frame(small)
        i = G.inner_region(r)
        self.assertLessEqual(i.w, 640)
        self.assertLessEqual(abs(i.w * 9 - i.h * 16), 16)
        self.assertTrue(G.placeable(r, small))

    def test_min_inner_is_200x120(self):
        c = G.clamp(G.Rect(300, 200, 20, 20), [PRIMARY])
        i = G.inner_region(c)
        self.assertEqual((i.w, i.h), (200, 120))

    def test_default_inner_follows_ac_fr12_19_examples(self):
        for w, h in ((1280, 800), (1280, 700), (1200, 675)):
            i = G.inner_region(G.default_frame(G.Rect(0, 0, w, h)))
            self.assertEqual((i.w, i.h), (960, 540), (w, h))
        i = G.inner_region(G.default_frame(G.Rect(0, 0, 1024, 640)))
        self.assertEqual((i.w, i.h), (819, 460))            # 80% 안으로 줄이며 소수 포인트는 내린다

    def test_resize_stops_at_screen_boundary_and_keeps_other_edges(self):  # D-113
        s = PRIMARY
        r = G.resize(G.Rect(1000, 200, 400, 300), {"r"}, 600, 0, s)
        self.assertEqual((r.x, r.right), (1000, s.right))
        r = G.resize(G.Rect(300, 300, 400, 300), {"b"}, 0, 2000, s)
        self.assertEqual((r.y, r.bottom), (300, s.bottom))
        r = G.resize(G.Rect(300, 300, 400, 300), {"l"}, -2000, 0, s)
        self.assertEqual((r.x, r.right), (s.x, 700))
        r = G.resize(G.Rect(300, 300, 400, 300), {"t"}, 0, -2000, s)
        self.assertEqual((r.y, r.bottom), (s.y, 600))

    def test_resize_height_cap_min_size_and_corner(self):  # D-113 ③ ④
        s = PRIMARY
        r = G.resize(G.Rect(300, 100, 400, 300), {"b"}, 0, 5000, s)
        self.assertLessEqual(r.h, s.h)                     # 높이 상한은 화면(가용 영역 아래) 높이이다
        self.assertEqual(r.bottom, s.bottom)
        self.assertTrue(G.placeable(r, s))
        r = G.resize(G.Rect(300, 300, 400, 300), {"r", "b"}, -5000, -5000, s)
        self.assertEqual((r.w, r.h), (G.MIN_W, G.MIN_H))
        r = G.resize(G.Rect(300, 300, 400, 300), {"l", "t"}, 5000, 5000, s)
        self.assertEqual((r.w, r.h, r.right, r.bottom), (G.MIN_W, G.MIN_H, 700, 600))

    def test_restore_info_reasons(self):
        self.assertEqual(G.restore_info(None, [PRIMARY])[1:], ("default", "none_saved"))
        self.assertEqual(G.restore_info({"x": 1}, [PRIMARY])[1:], ("default", "invalid"))
        self.assertEqual(G.restore_info(G.Rect(1600, 200, 800, 450).as_dict(), [PRIMARY])[1:], ("default", "off_screen"))
        self.assertEqual(G.restore_info(G.Rect(300, 200, 800, 450).as_dict(), [PRIMARY])[1:], ("saved", ""))

    def test_clamp_moves_into_one_screen(self):
        r = G.clamp(G.Rect(1300, 800, 400, 300), [PRIMARY, EXTRA])      # 두 화면에 걸쳐 있다
        for s in (PRIMARY, EXTRA):
            if G.placeable(r, s):
                break
        else:
            self.fail(r)
        self.assertEqual((r.w, r.h), (400, 300))

    def test_clamp_shrinks_to_screen_and_keeps_min(self):
        r = G.clamp(G.Rect(-50, -50, 5000, 4000), [PRIMARY])
        self.assertTrue(G.placeable(r, PRIMARY))

    def test_clamp_top_edge_stops_at_available_area(self):      # D-113 · 10차: 윗변은 가용 영역의 위 끝보다 위로 가지 않는다
        r = G.clamp(G.Rect(100, 0, 400, 300), [FULL], None, [AV])
        self.assertEqual(r.y, AV.y)
        r = G.clamp(G.Rect(100, 700, 400, 300), [FULL], None, [AV])         # 아래 변은 화면 전체(Dock 아래 포함)까지
        self.assertEqual(r.bottom, FULL.bottom)

    def test_clamp_height_limited_below_available_top(self):
        r = G.clamp(G.Rect(0, 0, 400, 5000), [FULL], None, [AV])
        self.assertTrue(G.placeable(r, FULL, AV.y))
        self.assertLessEqual(r.h, AV.bottom - AV.y)

    def test_resize_top_stops_at_available_area(self):
        r = G.resize(G.Rect(300, 300, 400, 300), {"t"}, 0, -2000, FULL, AV.y)
        self.assertEqual((r.y, r.bottom), (AV.y, 600))
        r = G.resize(G.Rect(300, 300, 400, 300), {"b"}, 0, 5000, FULL, AV.y)
        self.assertEqual(r.bottom, FULL.bottom)                    # 아래 변은 화면 전체

    def test_restore_top_above_available_is_default(self):      # 저장된 윗변이 가용 영역 위이면 쓸 수 없는 좌표이다
        saved = G.Rect(300, 5, 800, 450).as_dict()
        self.assertEqual(G.restore_info(saved, [FULL], [AV])[1:], ("default", "off_screen"))
        self.assertEqual(G.restore_info(G.Rect(300, 25, 800, 450).as_dict(), [FULL], [AV])[1:], ("saved", ""))

    def test_default_frame_is_centered_in_available_area(self):
        r = G.default_frame(AV)
        self.assertEqual(r.y, AV.y + (AV.h - r.h) // 2)


if __name__ == "__main__":
    unittest.main()


class Rev15BorderTest(unittest.TestCase):  # 결정 0089 4항 · 0093
    def test_border_values_and_overlap(self):
        self.assertEqual((G.BORDER, G.FLASH_BORDER, G.HANDLE, G.OVERLAP), (2.5, 4, 14, 11.5))

    def test_capture_region_unchanged_integer_rect(self):
        r = G.inner_region(G.Rect(100, 200, 1006, 566))
        self.assertEqual((r.x, r.y, r.w, r.h), (103, 203, 1000, 560))      # 테두리가 늘 영역 밖이다
        self.assertEqual((G.MIN_W, G.MIN_H), (206, 126))                    # 안쪽 200 × 120 이 유지된다
