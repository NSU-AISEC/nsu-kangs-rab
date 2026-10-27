"""결정 0058 ~ 0061 의 단위 시험: 이미지 한 장 · 사전 지식 합계 · 요청 합계 상한 (AC-FR2-12 · AC-FR2-13 · AC-FR7-22 · AC-FR7-23)."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import context as C  # noqa: E402
from nsu_kangs_rab.core import devopts, imageinfo  # noqa: E402
from nsu_kangs_rab.core import requests as R  # noqa: E402
from nsu_kangs_rab.core.transcript import Transcript  # noqa: E402
from nsu_kangs_rab.core.types import Result  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_requests_manager import FakeSession, Log  # noqa: E402


def png_n(n, w=100, h=100):
    """머리는 PNG 이고 전체 바이트 수가 정확히 n 이다(판독은 머리만 본다)."""
    head = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00\0\0\0\0"
    return head + b"\0" * (n - len(head))


def gif_frames(frames, w=10, h=10):
    out = b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00"
    for _ in range(frames):
        out += b"\x21\xf9\x04\x00\x0a\x00\x00\x00" + b"\x2c" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00" + b"\x02\x01\x44\x00"
    return out + b"\x3b"


def webp_vp8x(flag, w=10, h=10):
    return (b"RIFF" + struct.pack("<I", 22) + b"WEBPVP8X" + struct.pack("<I", 10) + bytes([flag]) + b"\0\0\0"
            + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little"))


class AnimatedTest(unittest.TestCase):
    def test_gif(self):
        self.assertFalse(imageinfo.is_animated(gif_frames(1), "gif"))
        self.assertTrue(imageinfo.is_animated(gif_frames(2), "gif"))
        self.assertFalse(imageinfo.is_animated(b"GIF89a", "gif"))     # 깨진 머리는 정적으로 본다

    def test_webp(self):
        self.assertFalse(imageinfo.is_animated(webp_vp8x(0x00), "webp"))
        self.assertTrue(imageinfo.is_animated(webp_vp8x(0x02), "webp"))
        self.assertFalse(imageinfo.is_animated(png_n(40), "png"))


class ShrinkerTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def scale(data, fmt, w, h):
            self.calls.append((fmt, w, h))
            return b"J" * 100 if fmt == "jpg" else b"P" * 5000

        self.sh = imageinfo.ImageShrinker(scale)

    def test_animated_gif_first_frame_png_even_when_small(self):   # 결정 0058 1항
        s = self.sh(gif_frames(3), "gif", 10, 10, max_bytes=None)
        self.assertEqual((s.fmt, s.width, s.height, s.resized), ("png", 10, 10, True))
        self.assertEqual(self.calls, [("gif", 10, 10)])

    def test_static_gif_kept_as_is(self):
        raw = gif_frames(1)
        s = self.sh(raw, "gif", 10, 10, max_bytes=None)
        self.assertEqual((s.data, s.fmt, s.resized), (raw, "gif", False))
        self.assertEqual(self.calls, [])

    def test_over_cap_reencoded_jpeg(self):   # 결정 0058 2항
        s = self.sh(png_n(4000), "png", 100, 100, max_bytes=3000)
        self.assertEqual((s.fmt, s.reencoded, len(s.data)), ("jpg", True, 100))
        self.assertEqual(self.calls, [("jpg", 100, 100)])

    def test_equal_to_cap_is_accepted(self):   # 결정 0061 4항
        raw = png_n(3000)
        s = self.sh(raw, "png", 100, 100, max_bytes=3000)
        self.assertEqual((s.data, s.reencoded), (raw, False))
        self.assertEqual(self.calls, [])

    def test_still_over_after_jpeg_rejected(self):
        with self.assertRaises(imageinfo.ImageTooLarge):
            self.sh(png_n(4000), "png", 100, 100, max_bytes=50)

    def test_resized_then_over_cap_reencodes_from_resized(self):
        big = png_n(10_000, 3000, 2000)
        s = self.sh(big, "png", 3000, 2000, max_bytes=4000)   # 축소 결과 5000 바이트 > 4000 → JPEG
        self.assertEqual([c[0] for c in self.calls], ["png", "jpg"])
        self.assertEqual((s.fmt, s.reencoded, s.width, s.height), ("jpg", True, 1568, 1045))


class RegisteredCapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.events = []

    def store(self, **lim):
        return C.ContextStore(C.Limits(**lim), imageinfo.ImageShrinker(lambda d, f, w, h: b"X" * 10),
                              emit=lambda t, **f: self.events.append((t, f)))

    def add(self, st, name, n):
        p = self.dir / name
        p.write_bytes(png_n(n))
        return st.add_image(p)

    def test_ac_fr2_12_boundary(self):
        st = self.store(registered_image_bytes_cap=3_000_000)
        r = [self.add(st, "a%d.png" % i, 1_000_000) for i in range(4)]
        self.assertEqual([type(x).__name__ for x in r], ["Accepted", "Accepted", "Accepted", "Unreadable"])
        self.assertEqual(r[3].reason, "registered_bytes")
        self.assertEqual(len(st.materials()), 3)
        self.assertEqual(st.held(), [])

    def test_ac_fr2_12_skips_only_the_overflowing_one(self):
        st = self.store(registered_image_bytes_cap=3_000_000)
        r = [self.add(st, "b%d.png" % i, n) for i, n in enumerate((1_000_000, 2_500_000, 500_000))]
        self.assertEqual([type(x).__name__ for x in r], ["Accepted", "Unreadable", "Accepted"])

    def test_ac_fr2_12_lower_cap(self):
        st = self.store(registered_image_bytes_cap=2_500_000)
        r = [self.add(st, "c%d.png" % i, 1_000_000) for i in range(4)]
        self.assertEqual([type(x).__name__ for x in r], ["Accepted", "Accepted", "Unreadable", "Unreadable"])

    def test_ac_fr2_13_count_first_then_sum_on_resolve(self):
        st = self.store(image_cap=2, registered_image_bytes_cap=3_000_000)
        a = self.add(st, "a.png", 1_000_000)
        self.add(st, "b.png", 1_000_000)
        c = self.add(st, "c.png", 2_500_000)
        self.assertIsInstance(c, C.Held)
        self.assertEqual(c.reason, "images")
        res = st.remove(a.material.id)
        self.assertTrue(res.removed)
        self.assertEqual(res.resolved, [])
        self.assertEqual(res.still_held, [])            # 선택 창은 다시 표시되지 않는다
        self.assertEqual([u.reason for u in res.unreadable], ["registered_bytes"])
        self.assertEqual(len(st.materials()), 1)

    def test_ac_fr2_13_count_judged_before_sum(self):
        st = self.store(image_cap=2, registered_image_bytes_cap=3_000_000)
        r = [self.add(st, "d%d.png" % i, n) for i, n in enumerate((1_000_000, 1_000_000, 2_500_000))]
        self.assertEqual([type(x).__name__ for x in r], ["Accepted", "Accepted", "Held"])

    def test_single_image_over_image_cap_rejected_with_reason(self):   # AC-FR7-22 의 사전 지식 부분
        st = C.ContextStore(C.Limits(image_bytes_cap=1000), imageinfo.ImageShrinker(lambda d, f, w, h: b"Y" * 2000))
        p = self.dir / "big.png"
        p.write_bytes(png_n(5000))
        r = st.add_image(p)
        self.assertIsInstance(r, C.Unreadable)
        self.assertEqual(r.reason, "image_bytes")
        ok = self.dir / "ok.png"
        ok.write_bytes(png_n(500))
        self.assertIsInstance(st.add_image(ok), C.Accepted)    # 나머지는 추가된다

    def test_devopts_to_limits(self):
        o = devopts.parse(["--dev-image-bytes-cap", "1234", "--dev-registered-image-bytes-cap", "5678",
                           "--dev-request-image-bytes-cap", "9"])
        lim = C.Limits.from_devopts(o)
        self.assertEqual((lim.image_bytes_cap, lim.registered_image_bytes_cap), (1234, 5678))
        self.assertEqual(o.get("request_image_bytes_cap"), 9)
        self.assertEqual(C.Limits().image_bytes_cap, 3_750_000)
        self.assertEqual(C.Limits().registered_image_bytes_cap, 15_000_000)
        self.assertEqual(imageinfo.REQUEST_IMAGE_BYTES_CAP, 20_000_000)


class FakeCtx:
    def __init__(self, sizes):
        self.items = [C.Material("m%d" % i, "r%d.png" % i, "image", bytes=b"R" * n, media_type="image/png")
                      for i, n in enumerate(sizes)]

    def first_request_images(self):
        return list(self.items)


def att(name, n):
    return R.AttachedImage("첨부", "2026-10-11T14:00:00.000+09:00", "image/png", b"A" * n, name)


class RequestCapTest(unittest.TestCase):
    def comp(self, cap, ctx_sizes, att_sizes, due=True):
        c = R.Composer(Transcript(), FakeCtx(ctx_sizes) if ctx_sizes is not None else None, request_image_bytes_cap=cap)
        if not due:
            c._registered_due = False
        return c.compose("자유질의", 1, "2026-10-11T14:00:00.000+09:00", 0.0,
                         user_text="q", images=tuple(att("a%d.png" % i, n) for i, n in enumerate(att_sizes)))

    def n_images(self, comp):
        return sum(1 for b in comp.message.blocks if b.get("type") == "image")

    def test_first_two_of_four_at_2_5m(self):
        r = self.comp(2_500_000, None, [1_000_000] * 4)
        self.assertEqual(self.n_images(r), 2)
        self.assertEqual(r.dropped, ("a2.png", "a3.png"))

    def test_equal_to_cap_accepted(self):
        r = self.comp(3_000_000, None, [1_000_000] * 4)
        self.assertEqual((self.n_images(r), r.dropped), (3, ("a3.png",)))

    def test_stops_at_first_overflow_even_if_later_fits(self):
        r = self.comp(3_000_000, None, [1_000_000, 2_500_000, 500_000])
        self.assertEqual((self.n_images(r), r.dropped), (1, ("a1.png", "a2.png")))

    def test_registered_counted_first(self):
        r = self.comp(3_000_000, [1_000_000, 1_000_000], [1_000_000, 1_000_000])
        self.assertEqual(self.n_images(r), 3)       # 추가 2 + 첨부 1
        self.assertEqual(r.dropped, ("a1.png",))

    def test_no_resend_means_all_attachments(self):
        r = self.comp(3_000_000, [1_000_000, 1_000_000], [1_000_000, 1_000_000], due=False)
        self.assertEqual((self.n_images(r), r.dropped), (2, ()))

    def test_below_cap_no_drop(self):
        r = self.comp(20_000_000, None, [3_000_000] * 5)
        self.assertEqual((self.n_images(r), r.dropped), (5, ()))
        self.assertEqual(r.log["images_dropped"], 0)

    def test_card_shows_dropped_and_event_has_count_only(self):   # 결정 0061 3항
        s, log, cards = FakeSession(), Log(), []
        m = R.RequestManager(s, R.Composer(Transcript(), None, request_image_bytes_cap=2_500_000), eventlog=log,
                             on_card=lambda c, ch: cards.append(c))
        self.addCleanup(m.close)
        m.submit(R.Request("자유질의", input="q", images=tuple(att("p%d.png" % i, 1_000_000) for i in range(4))))
        self.assertEqual(len(s.sent), 1)                       # 요청은 그대로 보낸다
        last = cards[-1]
        self.assertEqual((last.dropped, R.DROPPED_REASON), (("p2.png", "p3.png"), "요청 크기"))
        sent = log.of("request_sent")[0]
        self.assertEqual(sent["images_dropped"], 2)
        self.assertNotIn("p2.png", repr(sent))
        m.on_model_event(Result(True, text="답"))


if __name__ == "__main__":
    unittest.main()


class PdfDependencyTest(unittest.TestCase):
    def test_missing_pypdf_is_dependency_not_format(self):
        from nsu_kangs_rab.core import pdfworker
        saved = sys.modules.get("pypdf")
        sys.modules["pypdf"] = None      # import 시 ImportError
        try:
            r = pdfworker.extract("/nonexistent.pdf")
        finally:
            if saved is None:
                sys.modules.pop("pypdf", None)
            else:
                sys.modules["pypdf"] = saved
        self.assertEqual(r, {"status": "dependency", "detail": "pypdf"})
