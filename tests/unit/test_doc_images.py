"""단계 18 (결정 0194): 정리 문서의 이미지 링크를 JPEG 사본으로 바꾼다 (기술 계획 2-13절 S18-2 · S18-3)."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import cleanup_doc, doc_images, endflow  # noqa: E402


class Fix(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="docimg-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "captures").mkdir()
        self.calls = []
        self.events = []

    def put(self, rel, data=b"x"):
        p = self.d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def conv(self, src, dest):
        self.calls.append((Path(src).name, Path(dest).relative_to(self.d).as_posix()))
        Path(dest).write_bytes(b"jpegdata")

    def emit(self, name, **f):
        self.events.append((name, f))

    def run_(self, text, **kw):
        return doc_images.convert_links(text, self.d, self.conv, self.emit, **kw)


class ConvertTest(Fix):
    def test_png_link_replaced_with_copy_and_original_kept(self):
        self.put("captures/a.png")
        out = self.run_("앞\n![슬라이드](captures/a.png)\n뒤")
        self.assertEqual(out, "앞\n![슬라이드](captures/jpeg/a.png.jpg)\n뒤")
        self.assertTrue((self.d / "captures/a.png").exists())
        self.assertTrue((self.d / "captures/jpeg/a.png.jpg").exists())

    def test_title_alt_and_several_links(self):
        self.put("captures/a.png"); self.put("captures/b.webp"); self.put("captures/c.gif")
        out = self.run_('![x](captures/a.png "제목") ![](captures/b.webp) ![y]( captures/c.gif )')
        self.assertEqual(out, '![x](captures/jpeg/a.png.jpg "제목") ![](captures/jpeg/b.webp.jpg) ![y](captures/jpeg/c.gif.jpg)')

    def test_uppercase_extension_and_dot_slash(self):
        self.put("captures/A.PNG")
        self.assertEqual(self.run_("![](./captures/A.PNG)"), "![](captures/jpeg/A.PNG.jpg)")

    def test_jpeg_untouched(self):
        self.put("captures/a.jpg"); self.put("captures/b.JPEG")
        t = "![](captures/a.jpg) ![](captures/b.JPEG)"
        self.assertEqual(self.run_(t), t)
        self.assertEqual(self.calls, [])

    def test_outside_url_absolute_hidden_svg_untouched(self):
        self.put("captures/a.png"); self.put("captures/.capture-1.tmp.png"); self.put("captures/diagrams/d.svg")
        t = ("![](../x.png) ![](https://e.com/a.png) ![](/etc/a.png) ![](captures/.capture-1.tmp.png) "
             "![](captures/diagrams/d.svg) ![](captures/../../x.png)")
        self.assertEqual(self.run_(t), t)
        self.assertEqual(self.calls, [])

    def test_missing_file_keeps_link_and_emits_event(self):
        t = "![](captures/none.png)"
        self.assertEqual(self.run_(t), t)
        self.assertEqual(self.events, [("doc_image", dict(kind="missing", path="captures/none.png", detail=""))])

    def test_conversion_failure_keeps_link_and_removes_partial(self):
        self.put("captures/a.png")

        def bad(src, dest):
            Path(dest).write_bytes(b"part")
            raise ValueError("깨진 파일")
        t = "![](captures/a.png)"
        self.assertEqual(doc_images.convert_links(t, self.d, bad, self.emit), t)
        self.assertFalse((self.d / "captures/jpeg/a.png.jpg").exists())
        self.assertEqual(self.events[0][0], "doc_image")
        self.assertEqual(self.events[0][1]["kind"], "convert_failed")
        self.assertEqual(self.events[0][1]["path"], "captures/a.png")
        self.assertNotIn(str(self.d), repr(self.events))                # 절대 경로를 남기지 않는다

    def test_copy_reused_only_when_newer_than_original(self):
        src = self.put("captures/a.png")
        self.run_("![](captures/a.png)")
        self.assertEqual(len(self.calls), 1)
        self.run_("![](captures/a.png)")
        self.assertEqual(len(self.calls), 1)                            # 사본이 더 새로우면 다시 만들지 않는다
        later = time.time() + 5
        os.utime(src, (later, later))
        self.run_("![](captures/a.png)")
        self.assertEqual(len(self.calls), 2)

    def test_same_file_linked_twice_converted_once(self):
        self.put("captures/a.png")
        out = self.run_("![](captures/a.png) ![](captures/a.png)")
        self.assertEqual(out.count("captures/jpeg/a.png.jpg"), 2)
        self.assertEqual(len(self.calls), 1)

    def test_skip_deleted_card_files(self):
        self.put("captures/a.png")
        t = "![](captures/a.png)"
        self.assertEqual(self.run_(t, skip={"captures/a.png"}), t)
        self.assertEqual(self.calls, [])

    def test_name_with_space_uses_angle_brackets(self):
        self.put("captures/내 그림.png")
        self.assertEqual(self.run_("![](<captures/내 그림.png>)"), "![](<captures/jpeg/내 그림.png.jpg>)")

    def test_unwrapped_path_with_spaces(self):                   # D-231 (결정 0194 범위): 감싸지 않은 공백 경로
        self.put("captures/스크린샷 2026-10-31 오후 12.00.00.png")
        out = self.run_("![12:19:54 화면](captures/스크린샷 2026-10-31 오후 12.00.00.png)")
        self.assertEqual(out, "![12:19:54 화면](<captures/jpeg/스크린샷 2026-10-31 오후 12.00.00.png.jpg>)")
        self.assertTrue((self.d / "captures/jpeg/스크린샷 2026-10-31 오후 12.00.00.png.jpg").exists())

    def test_unwrapped_spaced_path_with_title_and_uppercase_ext(self):
        self.put("captures/a b.PNG")
        out = self.run_('![](captures/a b.PNG "제목")')
        self.assertEqual(out, '![](<captures/jpeg/a b.PNG.jpg> "제목")')

    def test_several_links_on_one_line_with_spaces(self):
        self.put("captures/a b.png"); self.put("captures/c d.webp")
        out = self.run_("![x](captures/a b.png) 글 ![y](captures/c d.webp)")
        self.assertEqual(out, "![x](<captures/jpeg/a b.png.jpg>) 글 ![y](<captures/jpeg/c d.webp.jpg>)")
        self.assertEqual(len(self.calls), 2)

    def test_spaced_path_without_image_extension_untouched(self):
        self.put("captures/a b.txt")
        t = "![x](captures/a b.txt) 와 ![y](captures/a b)"
        self.assertEqual(self.run_(t), t)
        self.assertEqual(self.calls, [])

    def test_spaced_missing_file_emits_event(self):
        t = "![x](captures/없는 파일.png)"
        self.assertEqual(self.run_(t), t)
        self.assertEqual(self.events[0][1]["kind"], "missing")
        self.assertEqual(self.events[0][1]["path"], "captures/없는 파일.png")

    def test_spaced_jpeg_kept(self):
        self.put("captures/a b.jpg")
        t = "![x](captures/a b.jpg)"
        self.assertEqual(self.run_(t), t)
        self.assertEqual(self.calls, [])

    def test_text_without_images_unchanged(self):
        t = "# 제목\n본문 [링크](captures/a.png)"
        self.assertEqual(self.run_(t), t)

    def test_deleted_paths(self):
        v = cleanup_doc.View(None)
        v.captures = [{"n": 1, "path": "captures/a.png"}, {"n": 2, "path": "captures/b.png"}]
        v.deletes = [{"n": 2}]
        self.assertEqual(doc_images.deleted_paths(v), {"captures/b.png"})


class EndFlowTest(Fix):
    def _flow(self, to_jpeg):
        return endflow.EndFlow(folder=self.d, doc_kind="수업", template="## 1\n", to_jpeg=to_jpeg)

    def test_saved_document_links_the_copy(self):
        self.put("captures/a.png")
        f = self._flow(self.conv)
        got = []
        f._on_done = got.append
        f._route = "history_less"
        f._finish_text("# 문서\n![](captures/a.png)\n")
        r = got[0]
        self.assertEqual(r.status, endflow.DONE)
        self.assertIn("captures/jpeg/a.png.jpg", r.path.read_text(encoding="utf-8"))
        self.assertTrue((self.d / "captures/a.png").exists())

    def test_without_converter_text_unchanged(self):
        self.put("captures/a.png")
        f = self._flow(None)
        got = []
        f._on_done = got.append
        f._finish_text("![](captures/a.png)\n")
        self.assertIn("(captures/a.png)", got[0].path.read_text(encoding="utf-8"))

    def test_converter_exception_does_not_block_save(self):
        def boom(*a):
            raise RuntimeError("x")
        self.put("captures/a.png")
        f = self._flow(boom)
        got = []
        f._on_done = got.append
        f._finish_text("![](captures/a.png)\n")
        self.assertEqual(got[0].status, endflow.DONE)
        self.assertIn("(captures/a.png)", got[0].path.read_text(encoding="utf-8"))


class RealConvertTest(Fix):
    """실제 `save_jpeg` 로 변환한다(화소 수를 줄이지 않는다)."""
    def test_real_conversion_keeps_pixels(self):
        from PySide6.QtGui import QGuiApplication, QImage
        _a = QGuiApplication.instance() or QGuiApplication([])
        img = QImage(2000, 900, QImage.Format.Format_ARGB32)
        img.fill(0x80FF0000)
        self.assertTrue(img.save(str(self.d / "captures/big.png"), "PNG"))
        from nsu_kangs_rab.platform.capture import jpeg
        out = doc_images.convert_links(
            "![](captures/big.png)", self.d,
            lambda s, d: jpeg.save_jpeg(s, d, jpeg.CAPTURE_JPEG_QUALITY, limit=1 << 30), self.emit)
        self.assertEqual(out, "![](captures/jpeg/big.png.jpg)")
        got = QImage(str(self.d / "captures/jpeg/big.png.jpg"))
        self.assertEqual((got.width(), got.height()), (2000, 900))
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
