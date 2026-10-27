"""K-19: 사전 지식 화면의 모델 · 위젯 (FR-2, AC-FR2-1 · 2 · 7 · 9 · 10 · 13). QT_QPA_PLATFORM=offscreen, 창을 띄우지 않는다."""
import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel  # noqa: E402

from nsu_kangs_rab.app import materials as W  # noqa: E402
from nsu_kangs_rab.core import context as C  # noqa: E402
from nsu_kangs_rab.core import imageinfo  # noqa: E402
from nsu_kangs_rab.core import materials_view as V  # noqa: E402

_app = QApplication.instance() or QApplication([])


def tearDownModule():
    import gc
    for _ in range(3):
        _app.processEvents()
        QCoreApplication.sendPostedEvents(None, 0)
        gc.collect()


def png(w, h):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00" + b"\0\0\0\0"


class Base(unittest.TestCase):
    LIMITS = dict(char_cap=30, image_cap=1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.events = []
        self.store = C.ContextStore(C.Limits(**self.LIMITS), imageinfo.ImageShrinker(lambda d, f, w, h: d),
                                    emit=lambda t, **f: self.events.append((t, f)))
        self.model = V.MaterialsModel(self.store)

    def mk(self, name, content):
        p = self.dir / name
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return str(p)

    def chars(self, name, n):
        return self.mk(name, "가" * n)


class ModelTest(Base):
    def test_rows_text_and_image(self):  # AC-FR2-1
        self.model.add_paths([self.chars("a.txt", 12), self.mk("b.png", png(640, 480))])
        a, b = self.model.rows()
        self.assertEqual((a.name, a.kind, a.chars, a.dimensions), ("a.txt", "text", 12, None))
        self.assertIn("12자", a.label)
        self.assertIn("a.txt", a.label)
        self.assertEqual((b.kind, b.chars, b.dimensions), ("image", None, "640 × 480"))
        self.assertIn("640 × 480", b.label)
        self.assertNotIn("자", b.label.replace("640", ""))

    def test_order_preserved_and_over_cap_held(self):  # AC-FR2-7 · FR-2 ⑥
        rep = self.model.add_paths([self.chars("a.txt", 20), self.chars("b.txt", 20), self.chars("c.txt", 5)])
        self.assertEqual([r.name for r in self.model.rows()], ["a.txt"])
        self.assertTrue(rep.show_selection)
        self.assertEqual([h.name for h in rep.pending], ["b.txt", "c.txt"])   # 보류 뒤의 자료는 순서를 지켜 함께 보류된다
        sel = self.model.selection()
        self.assertFalse(sel.cancel_only)
        self.assertIn("b.txt", sel.message + " ".join(h.text for h in sel.held))

    def test_sole_over_cap_is_cancel_only_and_cancel_keeps_list(self):  # AC-FR2-13 ③ ④
        self.model.add_paths([self.chars("a.txt", 10)])
        rep = self.model.add_paths([self.chars("big.txt", 50)])
        self.assertTrue(rep.show_selection)
        sel = self.model.selection()
        self.assertTrue(sel.cancel_only)
        self.assertIn("big.txt", sel.message)
        before = [r.label for r in self.model.rows()]
        self.assertEqual(self.model.cancel(), 1)
        self.assertEqual([r.label for r in self.model.rows()], before)
        self.assertIsNone(self.model.selection())

    def test_mixed_hold_one_selection_distinguishes_and_drops_sole(self):  # AC-FR2-15
        self.model.add_paths([self.chars("a.txt", 20)])
        self.model.add_paths([self.chars("b.txt", 20)])                    # 20 + 20 > 30: 빼면 풀리는 보류
        self.model.add_paths([self.chars("big.txt", 31)])                  # 단독으로 상한 초과
        sel = self.model.selection()
        self.assertFalse(sel.cancel_only)
        by = {h.name: h for h in sel.held}
        self.assertEqual(set(by), {"b.txt", "big.txt"})
        self.assertEqual(sel.sole_ids, (by["big.txt"].id,))
        self.assertIn("단독으로 상한을 넘어 추가되지 않습니다", by["big.txt"].text)
        self.assertNotIn("단독으로 상한을 넘어 추가되지 않습니다", by["b.txt"].text)
        rep = self.model.remove(self.model.rows()[0].id)
        self.assertEqual([m.name for m in rep.resolved], ["b.txt"])
        self.assertEqual(rep.dropped, ["big.txt"])
        self.assertFalse(rep.show_selection)                               # 선택 창이 다시 표시되지 않는다
        self.assertEqual([r.name for r in self.model.rows()], ["b.txt"])
        self.assertIsNone(self.model.selection())
        names = [t for t, _f in self.events]
        self.assertIn("material_hold_dropped", names)
        self.assertNotIn("material_hold_cancelled", names)

    def test_mixed_hold_cancel_keeps_list_and_cancels_all(self):  # AC-FR2-15
        self.model.add_paths([self.chars("a.txt", 20)])
        self.model.add_paths([self.chars("b.txt", 20), self.chars("big.txt", 31)])
        before = [r.label for r in self.model.rows()]
        self.assertEqual(self.model.cancel(), 2)
        self.assertEqual([r.label for r in self.model.rows()], before)
        names = [t for t, _f in self.events]
        self.assertEqual(names.count("material_hold_cancelled"), 2)
        self.assertNotIn("material_hold_dropped", names)

    def test_remove_registered_auto_registers_held(self):  # ⑦
        self.model.add_paths([self.chars("a.txt", 20)])
        self.model.add_paths([self.chars("b.txt", 20)])
        a = self.model.rows()[0]
        rep = self.model.remove(a.id)
        self.assertTrue(rep.removed)
        self.assertEqual([m.name for m in rep.resolved], ["b.txt"])
        self.assertFalse(rep.show_selection)
        self.assertEqual([r.name for r in self.model.rows()], ["b.txt"])
        self.assertIsNone(self.model.selection())

    def test_image_held_then_resolved_and_still_held(self):  # ⑦ ⑧ (이미지 장 수)
        self.model.add_paths([self.mk("1.png", png(10, 10))])
        rep = self.model.add_paths([self.mk("2.png", png(20, 20))])
        self.assertEqual([h.reason for h in rep.pending], ["images"])
        rep2 = self.model.remove(self.model.rows()[0].id)
        self.assertEqual([m.name for m in rep2.resolved], ["2.png"])

    def test_file_size_is_fact_only(self):  # AC-FR2-10
        store = C.ContextStore(C.Limits(text_file_cap_bytes=5), imageinfo.ImageShrinker(lambda d, f, w, h: d))
        model = V.MaterialsModel(store)
        rep = model.add_paths([self.mk("x.txt", "0123456789")])
        self.assertEqual(len(rep.facts), 1)
        self.assertIn("x.txt", rep.facts[0].text)
        self.assertFalse(rep.show_selection)
        self.assertEqual(rep.pending, [])
        self.assertEqual(model.rows(), [])
        self.assertIsNone(model.selection())

    def test_unreadable_reasons(self):  # AC-FR2-9
        rep = self.model.add_paths([str(self.dir / "없음.txt"), self.mk("z.xyz", "x")])
        self.assertEqual(len(rep.unreadable), 2)
        self.assertIn("없음.txt", rep.unreadable[0])
        self.assertIn("z.xyz", rep.unreadable[1])
        self.assertEqual(self.model.rows(), [])

    def test_add_text_default_name(self):
        rep = self.model.add_text("", "붙여 넣은 글")
        self.assertEqual(rep.accepted[0].name, "붙여넣은 글")
        self.assertEqual(self.model.rows()[0].chars, len("붙여 넣은 글"))


class WidgetTest(Base):
    def setUp(self):
        super().setUp()
        self.panel = W.MaterialsPanel(self.model)
        self.addCleanup(self.panel.deleteLater)
        self.changes = 0
        self.panel.changed.connect(self._changed)

    def _changed(self):
        self.changes += 1

    def test_column_widths_and_alignment_d216(self):
        """문자 수 칸은 160 이고 영어 "999,999 characters" 가 잘리지 않는다. 형식 왼쪽, 크기 · 문자 수는 머리 행 포함 오른쪽(D-216)."""
        from PySide6.QtWidgets import QLabel
        self.assertEqual(W.COL_W, (64, 84, 160, 60))
        self.panel.show()
        self.panel.add_paths([self.chars("A.TXT", 5)])
        row = self.panel.table.findChildren(QFrame, "materials_row")[0]
        cells = row.findChildren(QLabel)                                   # 이름 · 형식 · 크기 · 문자 수
        chars = cells[3]
        self.assertEqual(chars.width(), 160)
        need = chars.fontMetrics().horizontalAdvance("999,999 characters")
        self.assertLessEqual(need, chars.width())
        head = [lb for lb in self.panel.head.findChildren(QLabel)]          # 이름 · 형식 · 크기 · 문자 수 · (빈 칸)
        L, R = Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignRight
        self.assertTrue(cells[1].alignment() & L)
        self.assertTrue(cells[2].alignment() & R and cells[3].alignment() & R)
        self.assertTrue(head[1].alignment() & L)
        self.assertTrue(head[2].alignment() & R and head[3].alignment() & R)
        btn = self.panel.remove_buttons[0]
        self.assertEqual(btn.width(), 60)
        self.assertEqual(row.width() - 14, btn.geometry().right() + 1)    # [제거] 칸은 오른쪽 끝

    def test_table_header_rows_remove_and_zero_rows_d149(self):  # AC-FR2-16
        from PySide6.QtWidgets import QLabel, QPushButton
        self.panel.show()
        self.assertTrue(self.panel.table.isHidden())                       # 0행: 머리 행을 포함한 표 전체를 숨긴다
        self.assertFalse(self.panel.empty_label.isHidden())
        self.assertEqual(self.panel.empty_label.text(), "사전 지식 없음")
        self.assertFalse(self.panel.footer.isVisible())                     # 바닥 줄도 상자와 함께 숨는다
        self.assertFalse(any(lb.text() == "이름" and lb.isVisible() for lb in self.panel.findChildren(QLabel)))
        self.panel.add_paths([self.chars("A.TXT", 5), self.mk("i.png", png(30, 20))])
        self.assertFalse(self.panel.table.isHidden())
        heads = [lb.text() for lb in self.panel.head.findChildren(QLabel) if lb.text()]
        self.assertEqual(heads, ["이름", "형식", "크기", "문자 수"])
        btns = [b.text() for b in self.panel.findChildren(QPushButton)]
        self.assertEqual(sorted(btns), sorted(["파일 추가…", "글 붙여넣기…", "제거", "제거"]))   # 제목 줄에 [빼기] 가 없다
        self.assertTrue(all(b.accessibleName() == "자료 제거" for b in self.panel.remove_buttons))
        cells = [[lb.text() for lb in row.findChildren(QLabel)] for row in self.panel.table.findChildren(QFrame, "materials_row")]
        self.assertEqual(cells[0][1], "txt")                                # 형식은 소문자 확장자
        self.assertEqual(cells[1][1], "png")
        self.assertIn("30 × 20", cells[1][3])                                # 이미지의 문자 수 칸은 가로 × 세로
        self.assertTrue(all(c for row in cells for c in row))
        self.assertEqual(self.panel.rows_area.height(), 2 * 44)
        self.assertEqual(self.panel.head.height(), 28)                      # 머리 행 28
        self.assertEqual(self.panel.footer.height(), 33)                    # 바닥 줄 33, 상자 안 맨 아래
        self.assertIs(self.panel.footer.parent(), self.panel.table)
        self.assertEqual(self.panel.table.height(), 2 + 28 + 2 * 44 + 33)   # 상자 높이 = 테두리 2 + 머리 28 + 본문 + 바닥 33
        self.assertGreaterEqual(self.panel.footer.geometry().bottom(), self.panel.rows_area.geometry().bottom())
        self.panel.remove_buttons[0].click()
        self.assertEqual([r.name for r in self.model.rows()], ["i.png"])
        self.assertIn("1개", self.panel.footer.text())
        self.panel.remove_buttons[0].click()
        self.assertTrue(self.panel.table.isHidden())
        self.assertFalse(self.panel.empty_label.isHidden())
        self.panel.hide()
    def test_d152_columns_align_with_and_without_scrollbar(self):
        from PySide6.QtWidgets import QLabel, QFrame
        for n in (4, 9):                                              # 4행: 막대 없음, 9행: 표 안 스크롤 막대
            store = C.ContextStore(C.Limits(char_cap=10_000, image_cap=3), imageinfo.ImageShrinker(lambda d, f, w, h: d))
            panel = W.MaterialsPanel(V.MaterialsModel(store))
            self.addCleanup(panel.deleteLater)
            panel.resize(700, 600)
            panel.show()
            panel.add_paths([self.chars("g%d_%d.txt" % (n, i), 5) for i in range(n)])
            QCoreApplication.processEvents()
            self.assertEqual(len(panel.model.rows()), n)
            heads = [lb.mapTo(panel, lb.rect().topLeft()).x() for lb in panel.head.findChildren(QLabel) if lb.text()]
            row = panel.table.findChildren(QFrame, "materials_row")[0]
            cells = [lb.mapTo(panel, lb.rect().topLeft()).x() for lb in row.findChildren(QLabel)]
            self.assertEqual(heads, cells, n)                          # 막대 유무와 관계없이 머리 행과 본문 행의 열 x 가 같다
            self.assertEqual(panel.rows_area.verticalScrollBar().maximum() > 0, n > 6)
            panel.hide()

    def test_table_height_caps_at_six_rows(self):
        self.panel.add_paths([self.chars("f%d.txt" % i, 5) for i in range(8)])
        self.assertEqual(self.panel.rows_area.height(), 264)
        self.assertEqual(self.panel.table.height(), 2 + 28 + 264 + 33)


    def test_d153_footer_does_not_cover_last_row_and_d154_pad_style(self):
        for n in (3, 6, 8):
            self.panel.add_paths([self.chars("g%d_%d.txt" % (n, i), 5) for i in range(n - len(self.model.rows()))])
            self.panel.show()
            self.panel.table.layout().activate()
            self.assertEqual(self.panel.table.layout().contentsMargins().top(), 0)
            area = self.panel.rows_area.geometry()
            foot = self.panel.footer.geometry()
            self.assertGreaterEqual(foot.top(), area.bottom() + 1)          # 바닥 줄 위 끝 ≥ 본문 영역 아래 끝
            self.assertEqual(self.panel.head.geometry().bottom() + 1, area.top())
            self.assertEqual(area.height(), 44 * min(n, 6))
            self.assertEqual(foot.height(), 33)
            self.panel.hide()
        cells = [w for w in self.panel.head.findChildren(QLabel) if w.objectName() == "materials_head_cell"]
        self.assertEqual(len(cells), 5)                                     # 이름 · 형식 · 크기 · 문자 수 · [제거] 칸

    def test_ac_fr2_17_top_lines_only_and_remove_text_centered(self):  # 결정 0124 · AC-FR2-17
        import numpy as np
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QColor, QImage
        from nsu_kangs_rab.app import theme
        old = _app.styleSheet()
        self.addCleanup(_app.setStyleSheet, old)
        _app.setStyleSheet(theme.stylesheet("light"))
        hair = QColor(theme.tokens("light")["hairline"])
        want = (hair.red(), hair.green(), hair.blue())
        self.panel.add_paths([self.chars("한글자료%d.txt" % i, 5) for i in range(3)])
        self.panel.show()
        self.panel.table.layout().activate()
        img = self.panel.table.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
        w, h = img.width(), img.height()
        a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3).astype(int)
        lines = [y for y in range(1, h - 1) if (np.abs(a[y, 100:300] - np.array(want)).sum(axis=1) == 0).all()]
        top = self.panel.rows_area.geometry().top()
        self.assertEqual(lines, [top + 44 * i for i in range(3)] + [self.panel.footer.geometry().top()])   # 행의 위 선과 바닥 줄 위 선뿐
        self.assertNotIn(self.panel.head.geometry().bottom(), lines)         # 머리 행에는 아래 선이 없다

        def ink(wid):
            p = wid.mapTo(self.panel.table, QPoint(0, 0))
            reg = a[p.y():p.y() + wid.height(), p.x():p.x() + wid.width()]
            ys = np.where((np.abs(reg - reg[1, 1]).sum(axis=2) > 60).any(axis=1))[0]
            self.assertTrue(len(ys))
            return p.y() + (ys.min() + ys.max()) / 2.0
        for r in range(3):
            row = self.panel._rows_host.layout().itemAt(r).widget()
            chars = [c for c in row.findChildren(QLabel) if c.text().endswith("자")][0]
            self.assertEqual(self.panel.remove_buttons[r].height(), 28)       # 전역 단추의 안쪽 여백 · 최소 높이를 받지 않는다
            self.assertLessEqual(abs(ink(chars) - ink(self.panel.remove_buttons[r])), 1.0)   # 잉크 중심 차이 1pt 이하
        self.panel.hide()

    def test_pasted_text_format_is_txt(self):
        self.panel.add_text("글", "붙여넣은 글")
        self.assertEqual(self.panel.format_of(self.model.rows()[0]), "txt")

    def test_d150_empty_notice_takes_no_space(self):
        self.panel.show()
        self.assertTrue(self.panel.notice.isHidden())          # 문구가 없으면 공간을 차지하지 않는다
        self.panel._set_notice("보류한 자료 1건을 추가하지 않았다")
        self.assertFalse(self.panel.notice.isHidden())
        self.panel._set_notice("")
        self.assertTrue(self.panel.notice.isHidden())
        self.panel.hide()

    def test_list_shows_rows_and_changed_signal(self):
        self.panel.add_paths([self.chars("a.txt", 5), self.mk("i.png", png(30, 20))])
        labels = self.panel.row_labels()
        self.assertEqual(len(labels), 2)
        self.assertIn("5자", labels[0])
        self.assertIn("30 × 20", labels[1])
        self.assertEqual(self.changes, 1)

    def test_row_remove_button_removes_that_row(self):
        self.panel.add_paths([self.chars("a.txt", 5), self.chars("b.txt", 5)])
        self.panel.remove_buttons[0].click()                  # 행마다 [제거] (AC-FR2-16)
        self.assertEqual([r.name for r in self.model.rows()], ["b.txt"])
        self.assertEqual(len(self.panel.row_labels()), 1)

    def test_paste_flow(self):
        self.panel.paste_button.click()                       # 입력란을 연다
        self.assertFalse(self.panel.paste_edit.isHidden())
        self.panel.paste_edit.setPlainText("붙여 넣은 글")
        self.panel.paste_button.click()                       # 추가한다
        self.assertEqual([r.name for r in self.model.rows()], ["붙여넣은 글"])
        self.assertTrue(self.panel.paste_edit.isHidden())

    def test_notice_has_file_size_fact_before_selection(self):  # AC-FR2-10
        store = C.ContextStore(C.Limits(text_file_cap_bytes=5), imageinfo.ImageShrinker(lambda d, f, w, h: d))
        self.model = V.MaterialsModel(store)
        self.panel.model = self.model
        rep = self.panel.add_paths([self.mk("x.txt", "0123456789")])
        self.assertIn("x.txt", self.panel.notice.text())
        self.assertIsNone(self.panel.selection_dialog)
        self.assertEqual(self.model.rows(), [])
        self.assertTrue(rep.facts)

    def test_selection_dialog_remove_resolves_and_closes(self):  # AC-FR2-13
        self.panel.add_paths([self.chars("a.txt", 20), self.chars("b.txt", 20)])
        dlg = self.panel.selection_dialog
        self.assertIsNotNone(dlg)
        self.assertEqual(dlg.held_list.count(), 1)
        self.assertEqual(dlg.registered_list.count(), 1)
        self.assertFalse(dlg.remove_button.isEnabled())       # 고르기 전에는 누를 수 없다
        dlg.registered_list.setCurrentRow(0)
        self.assertTrue(dlg.remove_button.isEnabled())
        dlg.remove_button.click()
        self.assertEqual([r.name for r in self.model.rows()], ["b.txt"])
        self.assertEqual(dlg.result(), int(W.QDialog.DialogCode.Accepted.value))
        self.assertEqual(self.panel.row_labels()[0].split(" · ")[0], "b.txt")

    def test_selection_dialog_cancel_only_for_sole_over(self):  # ③ ④
        self.panel.add_paths([self.chars("a.txt", 10)])
        self.panel.add_paths([self.chars("big.txt", 50)])
        dlg = self.panel.selection_dialog
        self.assertTrue(dlg.remove_button.isHidden())
        self.assertIn("big.txt", dlg.message.text())
        before = self.panel.row_labels()
        dlg.cancel_button.click()
        self.assertEqual(self.panel.row_labels(), before)
        self.assertEqual(self.model.held_rows(), [])
        self.assertIn("1건", self.panel.notice.text())

    def test_selection_dialog_mixed_sole_not_selectable(self):  # AC-FR2-15
        self.panel.add_paths([self.chars("a.txt", 20)])
        self.panel.add_paths([self.chars("b.txt", 20), self.chars("big.txt", 31)])
        dlg = self.panel.selection_dialog
        self.assertFalse(dlg.remove_button.isHidden())                       # 빼기 대상이 있으므로 선택 창이 하나이다
        texts = {dlg.held_list.item(i).text().split(":")[0]: dlg.held_list.item(i) for i in range(dlg.held_list.count())}
        self.assertEqual(set(texts), {"b.txt", "big.txt"})
        self.assertFalse(bool(texts["big.txt"].flags() & Qt.ItemIsSelectable))
        self.assertTrue(bool(texts["b.txt"].flags() & Qt.ItemIsSelectable))
        dlg.registered_list.setCurrentRow(0)
        dlg.remove_button.click()
        self.assertEqual([r.name for r in self.model.rows()], ["b.txt"])
        self.assertEqual(self.model.held_rows(), [])
        self.assertEqual(dlg.result(), int(W.QDialog.DialogCode.Accepted.value))   # 다시 표시되지 않는다
        self.assertIn("big.txt", self.panel.notice.text())

    def test_selection_dialog_stays_when_still_held(self):  # ③ ⑦: 빼도 남으면 다시 표시한다
        self.panel.add_paths([self.chars("a.txt", 12), self.chars("b.txt", 12)])        # 24 ≤ 30
        self.panel.add_paths([self.chars("c.txt", 28)])                                 # 보류 (자료 하나는 상한 이하)
        dlg = self.panel.selection_dialog
        self.assertIsNotNone(dlg)
        dlg.registered_list.setCurrentRow(0)                                            # a 를 빼면 12 + 28 = 40 > 30
        dlg.remove_button.click()
        self.assertEqual(dlg.held_list.count(), 1)                                      # 남은 보류를 다시 표시
        self.assertEqual([r.name for r in self.model.rows()], ["b.txt"])

    def test_drop_files(self):
        from PySide6.QtCore import QMimeData, QUrl, QPoint
        from PySide6.QtGui import QDropEvent
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(self.chars("d.txt", 3))])
        ev = QDropEvent(QPoint(1, 1), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
        self.panel.dropEvent(ev)
        self.assertEqual([r.name for r in self.model.rows()], ["d.txt"])


if __name__ == "__main__":
    unittest.main()
