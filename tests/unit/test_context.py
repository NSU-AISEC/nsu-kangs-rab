"""K-05: 사전 지식(context) · 이미지 크기 · 시스템 프롬프트 조립 (FR-2, AC-FR2-1 ~ 11 의 판정 논리)."""
import hashlib
import importlib.util
import io
import os
import struct
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import context as C  # noqa: E402
from nsu_kangs_rab.core import devopts, imageinfo  # noqa: E402
from nsu_kangs_rab.core.procs import Procs  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pdf_fixtures as k05_pdf  # noqa: E402


def png(w, h):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00" + b"\0\0\0\0"


def gif(w, h):
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00;"


def webp(w, h):  # VP8X(확장) 머리
    return (b"RIFF" + struct.pack("<I", 22) + b"WEBPVP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00"
            + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little"))


def jpg(w, h):
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"\0\0" + sof + b"\xff\xd9"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.events = []
        self.scaled = []

        def scale(data, fmt, w, h):
            self.scaled.append((fmt, w, h))
            return b"SCALED:%d:%d" % (w, h)

        self.store = C.ContextStore(C.Limits(), imageinfo.ImageShrinker(scale),
                                    emit=lambda t, **f: self.events.append((t, f)))

    def mk(self, name, content):
        p = self.dir / name
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return p

    def mkchars(self, name, n):
        return self.mk(name, "가" * n)

    def names(self):
        return [t for t, _ in self.events]


class RegisterTest(Base):
    def test_four_kinds_and_image(self):  # AC-FR2-1
        md = self.mk("a.md", "# 제목\n본문 가나다\n")
        txt = self.mk("b.txt", "plain 텍스트")
        pdf = self.mk("c.pdf", k05_pdf.build_pdf(2, 3))
        r = [self.store.add_file(p) for p in (md, txt, pdf)]
        r.append(self.store.add_text("붙여넣음", "붙여 넣은 글"))
        self.assertTrue(all(isinstance(x, C.Accepted) for x in r), r)
        ms = self.store.materials()
        self.assertEqual(len(ms), 4)
        self.assertEqual(ms[0].chars, len(unicodedata.normalize("NFC", "# 제목\n본문 가나다\n")))
        self.assertEqual(ms[1].chars, len("plain 텍스트"))
        self.assertEqual(ms[3].chars, len("붙여 넣은 글"))
        self.assertGreater(ms[2].chars, 0)
        self.assertEqual(ms[2].text.count("quick brown fox"), 6)  # 2쪽 × 3줄
        img = self.store.add_file(self.mk("d.png", png(640, 480)))
        self.assertIsInstance(img, C.Accepted)
        m = img.material
        self.assertEqual((m.kind, m.width, m.height, m.chars), ("image", 640, 480, 0))
        self.assertEqual(self.store.count(), 5)
        self.assertEqual(self.store.total_chars(), sum(x.chars for x in ms))

    def test_char_count_unit(self):  # 결정 0047: NFC 코드 포인트, 공백 · 줄바꿈 포함
        r = self.store.add_text("t", "가 \n")
        self.assertEqual(r.material.chars, 3)
        decomposed = unicodedata.normalize("NFD", "한글 문서")
        self.assertNotEqual(len(decomposed), len("한글 문서"))
        r2 = self.store.add_text("d", decomposed)
        self.assertEqual(r2.material.chars, 5)
        self.assertEqual(r2.material.text, "한글 문서")

    def test_cap_boundary_same_for_nfd_and_nfc(self):
        nfc_ok = "가" * 50000
        nfd_ok = unicodedata.normalize("NFD", nfc_ok)
        self.assertIsInstance(self.store.add_text("a", nfc_ok), C.Accepted)
        s2 = C.ContextStore()
        self.assertIsInstance(s2.add_text("a", nfd_ok), C.Accepted)
        h = self.store.add_text("b", "가")
        self.assertIsInstance(h, C.Held)
        s3 = C.ContextStore()
        h2 = s3.add_text("x", unicodedata.normalize("NFD", "가" * 50001))
        self.assertIsInstance(h2, C.Held)
        self.assertEqual((h2.reason, h2.chars, h2.limit), ("chars", 50001, 50000))

    def test_single_item_over_cap_is_not_removable_and_cancel_empties(self):  # AC-FR2-2
        h = self.store.add_file(self.mkchars("big.txt", 50001))
        self.assertIsInstance(h, C.Held)
        self.assertFalse(h.removable)
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(len(self.store.held()), 1)
        self.assertEqual(self.store.cancel_held(), 1)
        self.assertEqual((self.store.count(), self.store.held()), (0, []))
        self.assertIn("material_hold_cancelled", self.names())

    def test_text_removal_resolves_hold_image_removal_keeps_it(self):  # AC-FR2-2
        a = self.store.add_text("A", "가" * 30000).material
        b = self.store.add_text("B", "나" * 20000).material
        img = self.store.add_file(self.mk("i.png", png(10, 10))).material
        h = self.store.add_text("C", "다" * 10000)
        self.assertIsInstance(h, C.Held)
        self.assertTrue(h.removable)
        r = self.store.remove(img.id)  # 이미지를 빼도 글자 수는 줄지 않는다
        self.assertTrue(r.removed)
        self.assertEqual(r.resolved, [])
        self.assertEqual([x.name for x in r.still_held], ["C"])
        self.assertIn("material_hold_kept", self.names())
        r = self.store.remove(b.id)
        self.assertEqual([m.name for m in r.resolved], ["C"])
        self.assertEqual(r.still_held, [])
        self.assertEqual(self.store.total_chars(), 40000)
        self.assertIn("material_hold_resolved", self.names())
        self.assertEqual([m.name for m in self.store.materials()], ["A", "C"])
        self.assertTrue(a.id)

    def test_batch_prefix_rule_and_ordered_release(self):  # ⑥ ⑦
        res = [self.store.add_text(n, "가" * k) for n, k in (("A", 30000), ("B", 30000), ("C", 10000), ("D", 10000))]
        self.assertEqual([type(r).__name__ for r in res], ["Accepted", "Held", "Held", "Held"])
        # C · D 는 상한 안에 들어가지만 앞의 B 가 보류이므로 순서대로 보류된다
        a_id = self.store.materials()[0].id
        r = self.store.remove(a_id)
        self.assertEqual([m.name for m in r.resolved], ["B", "C", "D"])
        self.assertEqual(self.store.total_chars(), 50000)
        self.assertEqual(r.still_held, [])

    def test_ordered_release_stops_at_cap(self):
        self.store.add_text("A", "가" * 40000)
        for n, k in (("B", 30000), ("C", 5000), ("D", 30000)):
            self.store.add_text(n, "나" * k)
        r = self.store.remove(self.store.materials()[0].id)
        # B(30000) 추가, C(5000) 추가, D(30000) 는 넘음 → 보류 유지
        self.assertEqual([m.name for m in r.resolved], ["B", "C"])
        self.assertEqual([h.name for h in r.still_held], ["D"])

    def test_image_cap_flow(self):  # AC-FR2-9
        paths = [self.mk("i%d.png" % i, png(100 + i, 50)) for i in range(8)]
        imgs = [self.store.add_file(p) for p in paths[:6]]
        self.assertTrue(all(isinstance(i, C.Accepted) for i in imgs))
        h = self.store.add_file(paths[6])
        self.assertIsInstance(h, C.Held)
        self.assertEqual((h.reason, h.kind, h.limit, h.removable), ("images", "image", 6, True))
        self.assertEqual(self.store.image_count(), 6)
        # (c) 텍스트를 빼도 보류 유지
        t = self.store.add_text("T", "텍스트").material
        r = self.store.remove(t.id)
        self.assertEqual(r.resolved, [])
        self.assertEqual(len(r.still_held), 1)
        # (b) 이미지 1장을 빼면 자동 추가
        first = self.store.first_request_images()[0]
        r = self.store.remove(first.id)
        self.assertEqual(len(r.resolved), 1)
        self.assertEqual(self.store.image_count(), 6)
        # (d) 취소하면 목록이 바뀌지 않는다
        self.store.add_file(paths[7])
        before = [m.id for m in self.store.materials()]
        self.store.cancel_held()
        self.assertEqual([m.id for m in self.store.materials()], before)

    def test_eight_images_at_once_then_remove_one(self):  # ⒡ ⒢
        paths = [self.mk("i%d.png" % i, png(200 + i, 50)) for i in range(8)]
        res = [self.store.add_file(p) for p in paths]
        self.assertEqual([type(r).__name__ for r in res], ["Accepted"] * 6 + ["Held"] * 2)
        r = self.store.remove(self.store.first_request_images()[0].id)
        self.assertEqual([m.name for m in r.resolved], ["i6.png"])
        self.assertEqual([h.name for h in r.still_held], ["i7.png"])

    def test_full_text_and_six_images_coexist(self):  # ⒠
        self.assertIsInstance(self.store.add_text("T", "가" * 50000), C.Accepted)
        for i in range(6):
            self.assertIsInstance(self.store.add_file(self.mk("i%d.jpg" % i, jpg(30, 30))), C.Accepted)

    def test_reduced_caps_via_devopts(self):  # AC-FR2-2 시험 연결점
        o = devopts.parse(["--dev-char-cap", "10", "--dev-image-cap", "1"])
        s = C.ContextStore(C.Limits.from_devopts(o))
        self.assertIsInstance(s.add_text("a", "가" * 10), C.Accepted)
        self.assertIsInstance(s.add_text("b", "나"), C.Held)
        self.assertIsInstance(s.add_file(self.mk("a.png", png(5, 5))), C.Accepted)
        self.assertIsInstance(s.add_file(self.mk("b.png", png(5, 5))), C.Held)


class FileSizeTest(Base):
    def test_over_size_not_extracted_not_listed_hash_unchanged(self):  # AC-FR2-10 · AC-FR2-6
        p = self.mkchars("big.txt", 100)
        before = hashlib.sha256(p.read_bytes()).hexdigest()
        mtime = p.stat().st_mtime_ns
        s = C.ContextStore(C.Limits(text_file_cap_bytes=50), emit=lambda t, **f: self.events.append((t, f)))
        orig = C._decode
        C._decode = lambda raw: self.fail("추출하면 안 된다")
        self.addCleanup(setattr, C, "_decode", orig)
        h = s.add_file(p)
        self.assertIsInstance(h, C.Held)
        self.assertEqual((h.reason, h.removable, h.size, h.limit, h.name), ("file_size", False, 300, 50, "big.txt"))
        self.assertEqual((s.count(), s.held()), (0, []))
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), before)
        self.assertEqual(p.stat().st_mtime_ns, mtime)
        ev = [(t, f) for t, f in self.events if t == "material_held"]
        self.assertEqual(ev[0][1]["reason"], "file_size")

    def test_batch_big_plus_small_ones(self):
        s = C.ContextStore(C.Limits(text_file_cap_bytes=40))
        big = self.mk("big.txt", "x" * 100)
        r = [s.add_file(big), s.add_file(self.mk("s1.txt", "abc")), s.add_file(self.mk("s2.md", "def"))]
        self.assertEqual([type(x).__name__ for x in r], ["Held", "Accepted", "Accepted"])
        self.assertEqual(s.count(), 2)

    def test_image_not_limited_by_file_cap(self):
        s = C.ContextStore(C.Limits(text_file_cap_bytes=10, pdf_file_cap_bytes=10))
        r = s.add_file(self.mk("a.png", png(5, 5) + b"0" * 1000))
        self.assertIsInstance(r, C.Accepted)

    def test_pdf_uses_pdf_cap(self):
        s = C.ContextStore(C.Limits(text_file_cap_bytes=10**9, pdf_file_cap_bytes=100))
        r = s.add_file(self.mk("a.pdf", k05_pdf.build_pdf(1, 2)))
        self.assertIsInstance(r, C.Held)
        self.assertEqual(r.reason, "file_size")

    def test_default_values(self):
        l = C.Limits()
        self.assertEqual((l.char_cap, l.image_cap, l.text_file_cap_bytes, l.pdf_file_cap_bytes),
                         (50000, 6, 2 * 1024 * 1024, 25 * 1024 * 1024))
        o = devopts.parse(["--dev-file-size-cap-bytes", "123"])
        l = C.Limits.from_devopts(o)
        self.assertEqual((l.text_file_cap_bytes, l.pdf_file_cap_bytes), (123, 123))


class UnreadableTest(Base):
    def test_reasons(self):  # AC-FR2-7
        self.assertEqual(self.store.add_file(self.dir / "none.txt").reason, "not_found")
        self.assertEqual(self.store.add_file(self.mk("a.docx", b"x")).reason, "format")
        self.assertEqual(self.store.add_file(self.mk("bad.png", b"notpng")).reason, "format")
        self.assertEqual(self.store.add_file(self.mk("empty.txt", b"")).reason, "no_text")
        self.assertEqual(self.store.add_file(self.mk("bad.txt", b"\xff\xfe\x00\xd8abc\x81")).reason, "decode")
        self.assertEqual(self.store.add_file(self.mk("junk.pdf", b"not a pdf at all")).reason, "format")
        self.assertEqual(self.store.count(), 0)

    def test_permission(self):
        if os.geteuid() == 0:
            self.skipTest("root")
        p = self.mk("secret.txt", "x")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o600)
        self.assertEqual(self.store.add_file(p).reason, "permission")

    def test_encrypted_and_scan_pdf(self):
        from pypdf import PdfWriter
        w = PdfWriter()
        w.add_blank_page(100, 100)
        buf = io.BytesIO()
        w.write(buf)
        scan = self.store.add_file(self.mk("scan.pdf", buf.getvalue()))
        self.assertEqual((scan.reason, scan.detail), ("no_text", "텍스트를 추출하지 못했습니다"))
        w2 = PdfWriter()
        w2.add_blank_page(100, 100)
        w2.encrypt("pw")
        buf2 = io.BytesIO()
        w2.write(buf2)
        self.assertEqual(self.store.add_file(self.mk("enc.pdf", buf2.getvalue())).reason, "encrypted")

    def test_others_registered_when_one_fails(self):
        r = [self.store.add_file(self.dir / "none.txt"), self.store.add_text("ok", "내용")]
        self.assertIsInstance(r[0], C.Unreadable)
        self.assertIsInstance(r[1], C.Accepted)

    def test_cp949_text_is_read(self):
        r = self.store.add_file(self.mk("k.txt", "한글 완성형".encode("cp949")))
        self.assertIsInstance(r, C.Accepted)
        self.assertEqual(r.material.text, "한글 완성형")

    def test_pdf_timeout_kills_worker_by_pid(self):  # X3: 쪽 하나의 추출 중에도 끊고 자식이 남지 않는다
        procs = Procs()
        s = C.ContextStore(pdf_timeout_s=0.5, procs=procs,
                           pdf_worker_cmd=[sys.executable, "-c", "import time; time.sleep(60)"])
        t0 = time.monotonic()
        r = s.add_file(self.mk("slow.pdf", k05_pdf.build_pdf(1, 2)))
        self.assertLess(time.monotonic() - t0, 5.0)
        self.assertIsInstance(r, C.Unreadable)
        self.assertEqual(r.reason, "timeout")
        self.assertEqual(procs.live(), [])

    def test_heavy_single_page_pdf_times_out_with_real_worker(self):
        procs = Procs()
        s = C.ContextStore(pdf_timeout_s=0.5, procs=procs)
        t0 = time.monotonic()
        r = s.add_file(self.mk("heavy.pdf", k05_pdf.build_heavy_pdf()))
        self.assertLess(time.monotonic() - t0, 4.0)
        self.assertEqual((type(r).__name__, getattr(r, "reason", None)), ("Unreadable", "timeout"))
        self.assertEqual(procs.live(), [])

    def test_pdf_text_via_worker_and_owner_only_password(self):  # AC-FR2-7
        plain = k05_pdf.build_pdf(2, 3)
        a = C.ContextStore(procs=Procs()).add_file(self.mk("p.pdf", plain))
        self.assertIsInstance(a, C.Accepted)
        owner = k05_pdf.build_owner_only_pdf(plain)
        b = C.ContextStore(procs=Procs()).add_file(self.mk("o.pdf", owner))
        self.assertIsInstance(b, C.Accepted)
        self.assertEqual(b.material.chars, a.material.chars)   # 글자 수가 추출한 텍스트와 같다
        self.assertEqual(b.material.text, a.material.text)

    def test_aes_owner_only_password_is_registered(self):  # D-033, AC-FR2-7 (`pypdf[crypto]`)
        plain = k05_pdf.build_pdf(2, 3)
        base = C.ContextStore(procs=Procs()).add_file(self.mk("p.pdf", plain))
        for alg in ("AES-128", "AES-256"):
            with self.subTest(alg=alg):
                data = k05_pdf.build_owner_only_pdf(plain, algorithm=alg)
                r = C.ContextStore(procs=Procs()).add_file(self.mk("a-%s.pdf" % alg, data))
                self.assertIsInstance(r, C.Accepted, r)
                self.assertEqual(r.material.text, base.material.text)

    def test_relative_path_pdf_is_registered(self):  # D-034
        plain = k05_pdf.build_pdf(1, 2)
        p = self.mk("rel.pdf", plain)
        rel = Path(os.path.relpath(str(p), os.getcwd()))
        r = C.ContextStore(procs=Procs()).add_file(rel)
        self.assertIsInstance(r, C.Accepted, r)

    def test_aes_open_password_is_encrypted(self):
        data = k05_pdf.build_owner_only_pdf(k05_pdf.build_pdf(1, 2), algorithm="AES-128", user="open-me")
        r = C.ContextStore(procs=Procs()).add_file(self.mk("au.pdf", data))
        self.assertEqual((type(r).__name__, r.reason), ("Unreadable", "encrypted"))

    def test_pdf_with_open_password_is_encrypted(self):
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(k05_pdf.build_pdf(1, 2))))
        w.encrypt(user_password="open-me", owner_password="o", algorithm="RC4-128")
        buf = io.BytesIO()
        w.write(buf)
        r = C.ContextStore(procs=Procs()).add_file(self.mk("e.pdf", buf.getvalue()))
        self.assertEqual((type(r).__name__, r.reason), ("Unreadable", "encrypted"))

    def test_broken_pdf_is_format_and_empty_is_no_text(self):
        r = C.ContextStore(procs=Procs()).add_file(self.mk("bad.pdf", b"not a pdf"))
        self.assertEqual((type(r).__name__, r.reason), ("Unreadable", "format"))


class ImageTest(Base):
    def test_resize_ratio_within_1px(self):  # AC-FR2-8
        for w, h in ((3000, 1000), (1000, 3000), (2001, 1999), (1569, 1000), (4000, 4000), (1568, 1568), (800, 600)):
            tw, th = imageinfo.target_size(w, h)
            self.assertLessEqual(max(tw, th), 1568)
            if max(w, h) <= 1568:
                self.assertEqual((tw, th), (w, h))
            else:
                self.assertAlmostEqual(tw / th, w / h, delta=1.0 / min(tw, th) + 1e-9)
                self.assertLessEqual(abs(tw * h - th * w), max(w, h))  # 1px 안

    def test_shrink_called_only_above_limit(self):
        big = self.store.add_file(self.mk("big.png", png(3000, 1000))).material
        self.assertEqual((big.sent_width, big.sent_height), (1568, 523))
        self.assertEqual(big.bytes, b"SCALED:1568:523")
        self.assertEqual((big.width, big.height, big.media_type), (3000, 1000, "image/png"))
        raw = png(1568, 900)
        small = self.store.add_file(self.mk("small.jpg", jpg(1200, 800))).material
        self.assertEqual((small.sent_width, small.sent_height), (1200, 800))
        self.assertEqual(small.media_type, "image/jpeg")
        self.assertEqual(self.scaled, [("png", 1568, 523)])
        edge = self.store.add_file(self.mk("edge.png", raw)).material
        self.assertEqual(edge.bytes, raw)
        self.assertEqual(len(self.scaled), 1)

    def test_gif_webp_registered_like_attachments(self):  # 결정 0057
        self.assertEqual(imageinfo.read_size(gif(7, 9)), ("gif", 7, 9))
        self.assertEqual(imageinfo.read_size(webp(7, 9)), ("webp", 7, 9))
        raw_g, raw_w = gif(800, 600), webp(1568, 100)
        g = self.store.add_file(self.mk("a.gif", raw_g)).material
        w = self.store.add_file(self.mk("b.webp", raw_w)).material
        self.assertEqual((g.bytes, g.media_type, g.sent_width), (raw_g, "image/gif", 800))   # 이하이면 바이트 · 형식 그대로
        self.assertEqual((w.bytes, w.media_type), (raw_w, "image/webp"))
        self.assertEqual(self.scaled, [])
        big = self.store.add_file(self.mk("c.gif", gif(3000, 1000))).material           # 넘으면 첫 프레임을 png 로
        self.assertEqual((big.media_type, big.bytes, self.scaled[-1][0]), ("image/png", b"SCALED:1568:523", "gif"))
        bigw = self.store.add_file(self.mk("d.webp", webp(1000, 4000))).material
        self.assertEqual(bigw.media_type, "image/png")
        self.assertEqual((bigw.sent_width, bigw.sent_height), (392, 1568))

    def test_shrink_failure_is_unreadable_and_not_duplicated(self):  # D-032
        bad = {3000}

        def scale(data, fmt, w, h):
            if w == 1568 and h in (523, 1045):    # 3000x1000 · 3000x2000 이 실패한다
                raise ValueError("decode")
            return b"S"

        st = C.ContextStore(C.Limits(image_cap=2), imageinfo.ImageShrinker(scale),
                            emit=lambda t, **f: self.events.append((t, f)))
        a = st.add_file(self.mk("a.png", png(100, 100)))
        b = st.add_file(self.mk("b.png", png(100, 100)))
        h_bad0 = st.add_file(self.mk("bad0.png", png(3000, 1000)))      # 보류
        h_ok = st.add_file(self.mk("ok.png", png(100, 100)))            # 보류
        h_bad1 = st.add_file(self.mk("bad1.png", png(3000, 2000)))      # 보류
        for h in (h_bad0, h_ok, h_bad1):
            self.assertIsInstance(h, C.Held)
        r = st.remove(a.material.id)   # 자리 1 → bad0 추가 시도(축소 실패) → ok 추가, bad1 은 상한으로 보류
        self.assertEqual([m.name for m in r.resolved], ["ok.png"])
        self.assertEqual([u.name for u in r.unreadable], ["bad0.png"])
        self.assertEqual(r.unreadable[0].reason, "format")
        self.assertEqual([h.name for h in st.held()], ["bad1.png"])
        names = [m.name for m in st._items]
        self.assertEqual(sorted(names), ["b.png", "ok.png"])
        r2 = st.retry_held()           # 다시 시도해도 같은 자료가 두 번 추가되지 않는다
        self.assertEqual(r2.resolved, [])
        self.assertEqual(sorted(m.name for m in st._items), ["b.png", "ok.png"])
        self.assertTrue(any(t == "material_unreadable" for t, _ in self.events))
        # 처음 등록(add_file)에서 실패해도 예외가 나가지 않는다
        st2 = C.ContextStore(C.Limits(), imageinfo.ImageShrinker(scale))
        u = st2.add_file(self.mk("bad2.png", png(3000, 1000)))
        self.assertIsInstance(u, C.Unreadable)
        self.assertEqual(st2._items, [])

    def test_file_size_held_event_has_removable(self):  # B-23
        big = self.mk("big.txt", b"x" * (C.TEXT_FILE_CAP_BYTES + 1))
        self.assertIsInstance(self.store.add_file(big), C.Held)
        ev = [f for t, f in self.events if t == "material_held"][-1]
        self.assertIn("removable", ev)
        self.assertFalse(ev["removable"])

    def test_original_hash_recorded(self):
        raw = png(3000, 1000)
        m = self.store.add_file(self.mk("a.png", raw)).material
        self.assertEqual(m.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(m.size, len(raw))

    def test_header_parsers(self):
        self.assertEqual(imageinfo.read_size(png(7, 9)), ("png", 7, 9))
        self.assertEqual(imageinfo.read_size(jpg(7, 9)), ("jpg", 7, 9))
        for bad in (b"", b"GIF89a", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff\xd9"):
            with self.assertRaises(imageinfo.ImageFormatError):
                imageinfo.read_size(bad)

    def test_held_image_is_shrunk_only_when_registered(self):
        s = C.ContextStore(C.Limits(image_cap=1), imageinfo.ImageShrinker(lambda d, f, w, h: self.scaled.append(1) or b"x"))
        s.add_file(self.mk("a.png", png(100, 100)))
        h = s.add_file(self.mk("b.png", png(4000, 2000)))
        self.assertIsInstance(h, C.Held)
        self.assertEqual(self.scaled, [])
        s.remove(s.materials()[0].id)
        self.assertEqual(len(self.scaled), 1)


class PromptTest(Base):
    RULES = "앱 규칙 블록\n[입력의 성격]\n- 규칙"

    def test_long_session_prompt_is_whole(self):  # AC-FR2-11
        sp = "수업 안내 가나다라 " * 2500  # 약 2.5만 자
        out = self.store.system_prompt(self.RULES, sp)
        self.assertIn(sp, out)
        self.assertTrue(out.startswith(self.RULES))

    def test_order_and_material_format(self):
        self.store.add_text("데이터,관리;개요.md", "첫 줄\n[표지 같은 줄]\n끝")
        self.store.add_text("b.md", "본문")
        self.store.add_file(self.mk("i.png", png(10, 10)))
        out = self.store.system_prompt(self.RULES, "세션 문구")
        i_rules, i_user, i_mat = out.index(self.RULES), out.index("[사용자 문구]\n세션 문구"), out.index("[사전 지식] 개수=2")
        self.assertLess(i_rules, i_user)
        self.assertLess(i_user, i_mat)
        self.assertIn("[자료] 이름=데이터_관리_개요.md 문자=%d\n첫 줄\n\\[표지 같은 줄]\n끝" % len("첫 줄\n[표지 같은 줄]\n끝"), out)
        self.assertIn("[자료] 이름=b.md 문자=2\n본문", out)
        self.assertNotIn("i.png", out)  # 이미지는 시스템 프롬프트에 넣지 않는다

    def test_no_texts_no_material_block(self):
        out = self.store.system_prompt(self.RULES, "x")
        self.assertNotIn("[사전 지식]", out)
        self.assertEqual(out, self.RULES + "\n\n[사용자 문구]\nx")

    def test_rules_block_independent_of_session_prompt(self):  # PS-1
        a = self.store.system_prompt(self.RULES, "")
        b = self.store.system_prompt(self.RULES, "아무 문구")
        cut = a.index("[사용자 문구]")
        self.assertEqual(a[:cut], b[:b.index("[사용자 문구]")])

    def test_held_and_unreadable_not_in_prompt(self):
        self.store.add_text("ok", "내용")
        self.store.add_text("big", "가" * 50000)  # 보류
        out = self.store.system_prompt(self.RULES, "s")
        self.assertIn("개수=1", out)
        self.assertNotIn("이름=big", out)

    def test_first_request_images_in_order(self):
        for i, (w, h) in enumerate(((10, 10), (4000, 1000), (20, 20))):
            self.store.add_file(self.mk("n%d.png" % i, png(w, h)))
        names = [m.name for m in self.store.first_request_images()]
        self.assertEqual(names, ["n0.png", "n1.png", "n2.png"])
        self.assertEqual(self.store.first_request_images()[1].sent_width, 1568)


class IsolationTest(unittest.TestCase):
    def test_no_qt_or_platform_import(self):
        d = ROOT / "src" / "mac" / "nsu_kangs_rab" / "core"
        for name in ("context.py", "imageinfo.py"):
            text = (d / name).read_text(encoding="utf-8")
            for bad in ("PySide6", "from ..platform", "import platform", "QImage"):
                self.assertNotIn(bad, text.replace("`QImage.scaled`", "").replace("Qt 의 `QImage.scaled`", ""))


if __name__ == "__main__":
    unittest.main()


class PdfWorkerCommandTest(unittest.TestCase):
    """K-17: 묶은 앱(frozen)에서는 sys.executable 이 앱 자신이므로 `--pdf-worker` 로 다시 시작한다."""

    def test_dev_command_is_isolated_script(self):
        import sys
        cmd = C.default_pdf_worker_cmd()
        self.assertEqual(cmd[:2], [sys.executable, "-I"])
        self.assertTrue(cmd[2].endswith("pdfworker.py"))

    def test_frozen_command_uses_flag(self):
        import sys
        from unittest import mock
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(C.default_pdf_worker_cmd(), [sys.executable, "--pdf-worker"])

    def test_main_dispatches_worker_without_qt(self):
        import subprocess, sys, tempfile, json, os
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "src" / "mac"
        code = ("import sys; sys.argv=['x','--pdf-worker','/nonexistent.pdf']; import nsu_kangs_rab; nsu_kangs_rab.main()")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(root)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["status"], "format")


class BundledHelperPathTest(unittest.TestCase):
    def test_none_when_not_frozen(self):
        from nsu_kangs_rab.core import resources
        self.assertIsNone(resources.bundled_helper_path())

    def test_frozen_path_under_meipass(self):
        from unittest import mock
        from nsu_kangs_rab.core import resources
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "_MEIPASS", "/x/App/Frameworks", create=True):
            self.assertEqual(str(resources.bundled_helper_path()), "/x/App/Frameworks/helper/sck_audio")
