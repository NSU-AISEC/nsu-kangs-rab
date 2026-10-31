"""K-14 단위 시험(장치 · 권한 없음): 폴더 감시 · 첨부 판정 · 축소 · 명령 구성."""
import hashlib
import os
import struct
import tempfile
import unittest
import zlib

from nsu_kangs_rab.core import imageinfo
from nsu_kangs_rab.platform.capture import attach, imagetypes, shrink
from nsu_kangs_rab.platform.capture.screenshotter import CaptureError, Screenshotter, build_command
from nsu_kangs_rab.platform.capture.store import write_bytes
from nsu_kangs_rab.platform.capture.types import FrameRegion


def png(w=10, h=10, salt=0):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([salt % 256]) * (w * 3) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpg(w=10, h=10):
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 4) + b"\x00\x00" + sof + b"\xff\xd9"


def gif(w=7, h=5):
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00;"


def webp_vp8x(w=30, h=20):
    return (b"RIFF" + struct.pack("<I", 22) + b"WEBPVP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00"
            + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little"))


def gif_animated(w=7, h=5):
    frame = b"\x2c" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00" + b"\x02" + b"\x00"
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00" + frame + frame + b";"


def webp_animated(w=30, h=20):
    d = bytearray(webp_vp8x(w, h))
    d[20] = 0x02
    return bytes(d)


class ImageTypesTest(unittest.TestCase):
    def test_formats_and_sizes(self):
        self.assertEqual(imagetypes.image_size(png(12, 8)), ("png", 12, 8))
        self.assertEqual(imagetypes.image_size(jpg(300, 200)), ("jpg", 300, 200))
        self.assertEqual(imagetypes.image_size(gif(7, 5)), ("gif", 7, 5))
        self.assertEqual(imagetypes.image_size(webp_vp8x(30, 20)), ("webp", 30, 20))
        self.assertIsNone(imagetypes.image_size(b"hello world, not an image"))
        self.assertIsNone(imagetypes.image_size(b"%PDF-1.4"))


class AttachTest(unittest.TestCase):
    def test_accepts_four_formats_rejects_others(self):
        ok, bad = attach.judge_attachments([("a.png", png()), ("b.jpg", jpg()), ("c.gif", gif()),
                                            ("d.webp", webp_vp8x()), ("e.pdf", b"%PDF-1.4 x"), ("f.png", b"not png")])
        self.assertEqual([a.name for a in ok], ["a.png", "b.jpg", "c.gif", "d.webp"])
        self.assertEqual([(r.name, r.reason) for r in bad], [("e.pdf", "format"), ("f.png", "format")])

    def test_format_by_content_not_name(self):
        ok, bad = attach.judge_attachments([("x.txt", png())])
        self.assertEqual(len(ok), 1)
        self.assertEqual(bad, [])

    def test_sixth_and_later_rejected(self):
        ok, bad = attach.judge_attachments([("%d.png" % i, png(salt=i)) for i in range(7)])
        self.assertEqual(len(ok), 5)
        self.assertEqual([r.reason for r in bad], ["count", "count"])
        self.assertEqual([r.name for r in bad], ["5.png", "6.png"])

    def test_already_attached_counts(self):
        ok, bad = attach.judge_attachments([("a.png", png()), ("b.png", png())], already=4)
        self.assertEqual((len(ok), len(bad)), (1, 1))


class ShrinkTest(unittest.TestCase):
    def test_small_image_unchanged_without_scaler(self):
        d = png(1000, 500)
        p = shrink.prepare(d)
        self.assertFalse(p.resized)
        self.assertIs(p.data, d)
        self.assertEqual((p.sent_width, p.sent_height), (1000, 500))

    def test_large_image_scaled_to_1568(self):
        calls = []

        def scale(data, fmt, w, h):
            calls.append((fmt, w, h))
            return b"scaled"
        p = shrink.prepare(png(3136, 1000), scale)
        self.assertTrue(p.resized)
        self.assertEqual(calls, [("png", 1568, 500)])
        self.assertEqual((p.width, p.height, p.sent_width, p.sent_height), (3136, 1000, 1568, 500))
        self.assertEqual(p.fmt, "png")

    def test_exactly_1568_not_scaled(self):
        self.assertFalse(shrink.prepare(png(1568, 900)).resized)

    def test_webp_gif_become_png(self):
        p = shrink.prepare(webp_vp8x(2000, 1000), lambda *a: b"x")
        self.assertEqual((p.fmt, p.sent_width, p.sent_height), ("png", 1568, 784))

    def test_not_image_raises(self):
        with self.assertRaises(shrink.ImageError):
            shrink.prepare(b"nope")

    def test_qt_scaler_with_fake_qt(self):
        seen = {}

        class Img:
            def loadFromData(self, d):
                seen["load"] = d
                return True

            def scaled(self, w, h, a, t):
                seen["scaled"] = (w, h, a, t)
                return self

            def save(self, buf, fmt, quality=-1):
                seen["fmt"] = fmt
                seen["quality"] = quality
                buf.payload = b"OUT"
                return True

        class Buf:
            def open(self, mode):
                pass

            def data(self):
                return self.payload

        class Q:
            QImage = Img
            QBuffer = Buf

            class Qt:
                IgnoreAspectRatio, SmoothTransformation = "ignore", "smooth"

            class QIODevice:
                WriteOnly = 2
        out = shrink.QtScaler(Q)(b"abc", "jpg", 100, 50)
        self.assertEqual(out, b"OUT")
        self.assertEqual(seen["scaled"], (100, 50, "ignore", "smooth"))
        self.assertEqual(seen["fmt"], "JPG")
        self.assertEqual(seen["quality"], 85)

    def test_qt_scaler_png_keeps_default_quality(self):
        seen = {}

        class Img:
            def loadFromData(self, d):
                return True

            def scaled(self, *a):
                return self

            def save(self, buf, fmt, quality=-1):
                seen["fmt"], seen["quality"] = fmt, quality
                buf.payload = b"P"
                return True

        class Buf:
            def open(self, mode):
                pass

            def data(self):
                return self.payload

        class Q:
            QImage = Img
            QBuffer = Buf

            class Qt:
                IgnoreAspectRatio, SmoothTransformation = 1, 2

            class QIODevice:
                WriteOnly = 2
        shrink.QtScaler(Q)(b"x", "png", 10, 10)
        self.assertEqual((seen["fmt"], seen["quality"]), ("PNG", -1))

    def test_animated_gif_webp_first_frame_png_even_if_small(self):
        for data in (gif_animated(7, 5), webp_animated(30, 20)):
            calls = []

            def scale(d, fmt, w, h):
                calls.append((fmt, w, h))
                return b"png-first"
            p = shrink.prepare(data, scale)
            self.assertTrue(p.resized)
            self.assertEqual(p.fmt, "png")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1:], (p.width, p.height))
            self.assertFalse(p.reencoded)

    def test_still_gif_webp_unchanged_when_small(self):
        d = gif(7, 5)
        p = shrink.prepare(d)
        self.assertFalse(p.resized)
        self.assertIs(p.data, d)

    def test_over_cap_reencoded_as_jpeg(self):
        big = png(1000, 500) + b"\x00" * 200
        calls = []

        def scale(d, fmt, w, h):
            calls.append((fmt, w, h))
            return b"j" * 50
        p = shrink.prepare(big, scale, max_bytes=len(big) - 1)
        self.assertEqual(calls, [("jpg", 1000, 500)])
        self.assertEqual((p.fmt, p.reencoded, len(p.data)), ("jpg", True, 50))
        self.assertFalse(p.resized)

    def test_resized_then_over_cap_reencoded(self):
        calls = []

        def scale(d, fmt, w, h):
            calls.append(fmt)
            return b"p" * 100 if fmt == "png" else b"j" * 10
        p = shrink.prepare(png(3136, 1000), scale, max_bytes=50)
        self.assertEqual(calls, ["png", "jpg"])
        self.assertEqual((p.fmt, p.reencoded, p.resized, p.sent_width), ("jpg", True, True, 1568))

    def test_still_over_cap_after_jpeg_raises(self):
        with self.assertRaises(imageinfo.ImageTooLarge):
            shrink.prepare(png(1000, 500) + b"\x00" * 200, lambda *a: b"j" * 300, max_bytes=100)

    def test_equal_to_cap_accepted(self):
        d = png(1000, 500)
        p = shrink.prepare(d, max_bytes=len(d))
        self.assertIs(p.data, d)
        self.assertFalse(p.reencoded)

    def test_scaled_equal_to_cap_after_jpeg_accepted(self):
        d = png(1000, 500) + b"\x00" * 50
        p = shrink.prepare(d, lambda *a: b"j" * 100, max_bytes=100)
        self.assertEqual((p.fmt, len(p.data), p.reencoded), ("jpg", 100, True))

    def test_default_cap_is_core_constant(self):
        import inspect
        self.assertEqual(inspect.signature(shrink.prepare).parameters["max_bytes"].default, imageinfo.IMAGE_BYTES_CAP)


class StoreTest(unittest.TestCase):
    def test_write_bytes_stays_in_captures_dir(self):
        with tempfile.TemporaryDirectory() as d:
            cap = os.path.join(d, "session", "captures")
            data = png(salt=11)
            dest = write_bytes(data, "png", cap, "attach-1")
            self.assertEqual(os.path.dirname(dest), cap)
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), data)
            dest2 = write_bytes(data, "png", cap, "attach-1")      # 같은 이름은 덮어쓰지 않는다
            self.assertNotEqual(dest, dest2)


class ScreenshotterTest(unittest.TestCase):
    def test_command(self):
        self.assertEqual(build_command(FrameRegion(100, 200, 1440, 900), "/x/y.png"),
                         ["/usr/sbin/screencapture", "-x", "-t", "png", "-R", "100,200,1440,900", "/x/y.png"])
        self.assertEqual(build_command(FrameRegion(-1920, 0, 800.4, 600.6), "o.png")[5], "-1920,0,800,601")
        with self.assertRaises(CaptureError):
            build_command(FrameRegion(0, 0, 0, 10), "o.png")

    def _leftovers(self, d):
        return sorted(os.listdir(d))

    def test_capture_with_fake_runner(self):
        """AC-FR12-23: 임시 PNG 로 받아 JPEG 80 을 쓰고 임시 PNG 를 지운다. 긴 변이 1568 을 넘으면 줄여 한 번만 부호화한다."""
        with tempfile.TemporaryDirectory() as d:
            seen = []

            def runner(cmd, timeout):
                seen.append(cmd)
                self.assertFalse(os.path.basename(cmd[-1]).startswith("."))                    # 실제 screencapture 처럼 거부
                with open(cmd[-1], "wb") as f:
                    f.write(png(3000, 1500, salt=1))
                return 0, ""
            item = Screenshotter(runner, d).capture(FrameRegion(0, 0, 3000, 1500))
            self.assertEqual(item.source, "캡처")
            self.assertEqual((item.width, item.height, item.sent_width, item.sent_height), (3000, 1500, 1568, 784))
            self.assertTrue(item.path.startswith(d) and item.path.endswith(".jpg"))
            with open(item.path, "rb") as f:
                data = f.read()
            self.assertEqual(item.sha256, hashlib.sha256(data).hexdigest())
            self.assertEqual(imagetypes.image_size(data), ("jpg", 1568, 784))
            self.assertEqual(seen[0][:5], ["/usr/sbin/screencapture", "-x", "-t", "png", "-R"])
            tmp = seen[0][-1]
            self.assertEqual(os.path.dirname(tmp), os.path.join(d, ".tmp"))                    # D-232: 숨김 폴더 안
            self.assertFalse(os.path.basename(tmp).startswith("."))                            # 점으로 시작하지 않는 이름
            self.assertEqual(self._leftovers(d), [os.path.basename(item.path)])               # 임시 PNG 없음
            self.assertEqual(shrink.prepare(data).resized, False)                              # _register_capture 의 prepare 는 바이트를 그대로 둔다

    def test_not_resized_at_or_below_limit(self):
        with tempfile.TemporaryDirectory() as d:
            def runner(cmd, timeout):
                with open(cmd[-1], "wb") as f:
                    f.write(png(1568, 900, salt=2))
                return 0, ""
            item = Screenshotter(runner, d).capture(FrameRegion(0, 0, 1568, 900))
            self.assertEqual((item.width, item.height, item.sent_width, item.sent_height), (1568, 900, 1568, 900))

    def test_failures(self):
        """AC-FR12-23: 실패 · 시간 초과 · 빈 파일 · not_image 뒤에도 임시 PNG 가 남지 않고 `.jpg` 도 없다."""
        with tempfile.TemporaryDirectory() as d:
            def part(cmd, t):                                   # 시간 초과: 일부만 쓴 임시 파일이 남을 수 있다
                with open(cmd[-1], "wb") as f:
                    f.write(b"partial")
                return None, "timeout"

            def exit_after_write(cmd, t):
                with open(cmd[-1], "wb") as f:
                    f.write(png(5, 5))
                return 1, "err"
            for runner, kind in ((exit_after_write, "exit"), (part, "timeout"), (lambda c, t: (0, ""), "no_file")):
                with self.assertRaises(CaptureError) as cm:
                    Screenshotter(runner, d).capture(FrameRegion(0, 0, 10, 10))
                self.assertEqual(cm.exception.kind, kind)
                self.assertEqual(self._leftovers(d), [])

            def empty(cmd, t):
                open(cmd[-1], "wb").close()
                return 0, ""

            def junk(cmd, t):
                with open(cmd[-1], "wb") as f:
                    f.write(b"junk")
                return 0, ""
            with self.assertRaises(CaptureError) as cm:
                Screenshotter(empty, d).capture(FrameRegion(0, 0, 10, 10))
            self.assertEqual(cm.exception.kind, "no_file")
            self.assertEqual(self._leftovers(d), [])
            with self.assertRaises(CaptureError) as cm:
                Screenshotter(junk, d).capture(FrameRegion(0, 0, 10, 10))
            self.assertEqual(cm.exception.kind, "not_image")
            self.assertEqual(self._leftovers(d), [])

    def test_no_file_keeps_stderr(self):
        with tempfile.TemporaryDirectory() as d:
            sh = Screenshotter(lambda c, t: (0, "cannot write file to intended destination"), d)
            with self.assertRaises(CaptureError):
                sh.capture(FrameRegion(0, 0, 10, 10))
            self.assertIn("cannot write", sh.last_stderr)
            self.assertEqual(self._leftovers(d), [])

    def test_save_failure_leaves_nothing(self):
        from nsu_kangs_rab.platform.capture.jpeg import JpegError
        with tempfile.TemporaryDirectory() as d:
            def runner(cmd, timeout):
                with open(cmd[-1], "wb") as f:
                    f.write(png(8, 8))
                return 0, ""

            def bad_save(src, dest):
                open(dest, "wb").write(b"half")
                raise JpegError("save_failed", "x")
            with self.assertRaises(CaptureError):
                Screenshotter(runner, d, save=bad_save).capture(FrameRegion(0, 0, 8, 8))
            self.assertFalse([n for n in self._leftovers(d) if n.startswith(".")])               # 임시 PNG 와 .tmp 폴더를 지웠다


def _dqt(data: bytes) -> bytes:
    """JPEG 의 양자화 표(DQT) 마커 본문을 모은다."""
    out, i = b"", 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            break
        m, ln = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if m == 0xDB:
            out += data[i + 4:i + 2 + ln]
        if m == 0xDA:
            break
        i += 2 + ln
    return out


class JpegSaveTest(unittest.TestCase):
    def _gradient_png(self, path, w, h, alpha=False):
        from PySide6.QtGui import QImage, QColor
        img = QImage(w, h, QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32)
        for y in range(h):
            for x in range(w):
                img.setPixelColor(x, y, QColor((x * 7) % 256, (y * 5) % 256, (x + y) % 256, 128 if alpha else 255))
        self.assertTrue(img.save(path, "PNG"))
        return img

    def test_dqt_matches_qimage_q80_and_size_kept(self):
        from PySide6.QtGui import QImage
        from nsu_kangs_rab.platform.capture.jpeg import save_jpeg
        with tempfile.TemporaryDirectory() as d:
            src, dst, ref = (os.path.join(d, n) for n in ("a.png", "b.jpg", "ref.jpg"))
            img = self._gradient_png(src, 400, 300)
            self.assertEqual(save_jpeg(src, dst), (400, 300, 400, 300))
            img.convertToFormat(QImage.Format.Format_RGB32).save(ref, "JPEG", 80)
            a, b = open(dst, "rb").read(), open(ref, "rb").read()
            self.assertEqual(_dqt(a), _dqt(b))                      # 품질 80 (QImage 와 같은 양자화 표)
            q90 = os.path.join(d, "q90.jpg")
            save_jpeg(src, q90, quality=90)
            self.assertNotEqual(_dqt(open(q90, "rb").read()), _dqt(a))
            self.assertEqual(imagetypes.image_size(a), ("jpg", 400, 300))

    def test_long_side_over_limit_is_scaled_once(self):
        from nsu_kangs_rab.platform.capture.jpeg import save_jpeg
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "a.png"), os.path.join(d, "b.jpg")
            self._gradient_png(src, 1600, 1200)
            self.assertEqual(save_jpeg(src, dst), (1600, 1200, 1568, 1176))
            self.assertEqual(imagetypes.image_size(open(dst, "rb").read()), ("jpg", 1568, 1176))
            self._gradient_png(src, 1200, 3000)
            self.assertEqual(save_jpeg(src, dst), (1200, 3000, 627, 1568))

    def test_transparent_pixels_are_flattened_on_white(self):
        from PySide6.QtGui import QImage, QColor
        from nsu_kangs_rab.platform.capture.jpeg import save_jpeg
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "a.png"), os.path.join(d, "b.jpg")
            img = QImage(64, 64, QImage.Format.Format_ARGB32)
            img.fill(QColor(0, 0, 0, 0))
            img.save(src, "PNG")
            save_jpeg(src, dst)
            px = QImage(dst).pixelColor(32, 32)
            self.assertTrue(px.red() > 240 and px.green() > 240 and px.blue() > 240, px.getRgb())

    def test_bytes_input_and_errors(self):
        from nsu_kangs_rab.platform.capture.jpeg import JpegError, convert_file, save_jpeg
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "b.jpg")
            self.assertEqual(save_jpeg(png(20, 10, salt=3), dst), (20, 10, 20, 10))
            with self.assertRaises(JpegError) as cm:
                save_jpeg(b"junk", dst)
            self.assertEqual(cm.exception.kind, "not_image")
            with self.assertRaises(JpegError):
                convert_file(os.path.join(d, "missing.png"), dst)
            with self.assertRaises(JpegError) as cm:
                save_jpeg(png(8, 8), os.path.join(d, "no_such_dir", "x.jpg"))
            self.assertEqual(cm.exception.kind, "save_failed")


if __name__ == "__main__":
    unittest.main()
