"""단계 14 (결정 0189): 시작 화면의 6 · 7절 세로 배치와 절 사이 구분선. AC-FR1-33 ① ~ ④."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_app_controller as TC  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QFrame, QLabel, QWidget  # noqa: E402
from nsu_kangs_rab.app import screens, theme  # noqa: E402
from test_start_screen_stage6 import gap_sum  # noqa: E402

UR = screens.Qt.ItemDataRole.UserRole
_t = screens._t
BODY_MARGIN = 24


def geo(widget, form):
    """폼 좌표계에서의 (left, top, right, bottom) — right · bottom 은 마지막 화소."""
    p = widget.mapTo(form, QPoint(0, 0))
    return p.x(), p.y(), p.x() + widget.width() - 1, p.y() + widget.height() - 1


def seps(sp):
    return sp.findChildren(QFrame, "section_separator")


class VerticalTest(TC.Base):
    def _show(self, provider="claude_subscription", w=900, h=1600):
        sp = self.ctl.shell.start_page
        sp.provider.setCurrentIndex(sp.provider.findData(provider, UR))
        self.ctl.shell.show()
        sp.resize(w, h)
        sp.show()
        TC._app.processEvents()
        return sp

    def _title(self, sp, text):
        return next(lb for lb in sp.findChildren(QLabel) if lb.text() == text)

    def test_6_and_7_are_stacked_d1(self):                        # AC-FR1-33 ①
        sp = self._show()
        s6 = sp.findChild(QWidget, "stt_source_section")
        s7 = sp.findChild(QWidget, "stt_language_section")
        self.assertIsNotNone(s6)
        self.assertIsNotNone(s7)
        g6, g7 = geo(s6, sp), geo(s7, sp)
        self.assertGreater(g7[1], g6[3])                          # 세로 범위가 겹치지 않고 7 이 6 아래이다
        t6 = geo(self._title(sp, _t("start.init___049")), sp)
        t7 = geo(self._title(sp, _t("newlang.new80")), sp)
        self.assertEqual(t6[0], t7[0])                            # 제목의 왼쪽 가장자리가 같다
        self.assertEqual(sp.stt_language.width(), sp.provider.width())          # 결정 0190 1항: 2. 모델 제공자 드롭다운과 같은 본문 폭
        self.assertEqual(sp.app_language_section.app_language.width(), sp.provider.width())
        self.assertEqual(sp.provider.width(), sp.scroll.widget().width() - 2 * BODY_MARGIN)
        self.assertIs(s7.isAncestorOf(sp.stt_fallback_notice), True)   # NEW-59 줄은 7절 본문에 속한다

    def test_old_structure_removed(self):
        sp = self._show()
        for name in ("source_row", "source_block"):
            self.assertFalse(hasattr(sp, name), name)
        self.assertFalse(hasattr(screens, "LEFT_COLUMN_WIDTH"))
        self.assertFalse(hasattr(screens, "COLUMN_GAP"))

    def _check_separators(self, sp, expect):
        ss = seps(sp)
        visible = [s for s in ss if not s.isHidden()]
        self.assertEqual(len(visible), expect)
        edges = geo(sp.app_language_section, sp)
        for s in visible:
            g = geo(s, sp)
            self.assertEqual(s.height(), 1)
            self.assertEqual(g[0], edges[0])
            self.assertEqual(g[0], BODY_MARGIN + geo(sp.scroll.widget(), sp)[0])

    def test_separators_with_section5(self):                      # AC-FR1-33 ② (5절 표시: 9개)
        sp = self._show("claude_subscription")
        self.assertFalse(sp.claude_section.isHidden())
        self._check_separators(sp, 9)

    def test_separators_without_section5(self):                   # 5절 숨김: 8개, 5절 앞 구분선도 함께 숨는다
        sp = self._show("claude_subscription")
        sp.provider.addItem("fake", "fake_provider")
        sp.provider.setCurrentIndex(sp.provider.findData("fake_provider", UR))
        sp.effort_section.setVisible(True)                        # 가짜 제공자는 effort 표가 없어 4절도 숨으므로, 5절만 숨은 경우를 만든다
        sp._sync_separators()
        TC._app.processEvents()
        self.assertTrue(sp.claude_section.isHidden())
        self._check_separators(sp, 8)

    def test_separator_spacing_10(self):
        sp = self._show()
        ss = [s for s in seps(sp) if not s.isHidden()]
        body = sp.scroll.widget()
        items = []
        for i in range(sp._lay.count()):
            w = sp._lay.itemAt(i).widget()
            if w is not None and not w.isHidden():
                items.append(w)
        for s in ss:
            i = items.index(s)
            above, below = geo(items[i - 1], body), geo(items[i + 1], body)
            me = geo(s, body)
            self.assertEqual(me[1] - above[3] - 1, 10)
            self.assertEqual(below[1] - me[3] - 1, 10)

    def test_separator_color_equal_in_light_and_dark(self):       # AC-FR1-33 ②: 색 hairline, 밝은 · 어두운 테마
        for scheme in ("light", "dark"):
            css = theme.stylesheet(scheme)
            want = theme.tokens(scheme)["hairline"]
            self.assertIn("QFrame#section_separator { background: %s; border: none; }" % want, css, scheme)

    def test_settings_window_has_no_separator(self):              # AC-FR1-33 ③
        self.ctl.open_settings()
        form = self.ctl._settings_form
        self.assertEqual(form.findChildren(QFrame, "section_separator"), [])

    def test_content_height_counts_separators(self):              # AC-FR1-33 ④
        sp = self._show()
        els = sp.layout_elements()
        self.assertEqual(sum(1 for n, _h in els if n == "section_separator"), 9)
        for n, h in els:
            if n == "section_separator":
                self.assertEqual(h, 1)
        self.assertEqual(sp.content_height(), 20 + sum(h for _n, h in els) + gap_sum(els) + 20 + 64)


class Stage15Test(TC.Base):
    """단계 15 (결정 0190): 요소 간격 18 은 띠 · 점검 줄 아래만, 높이 상한 − 20 은 첫 실행 고지 · 세션 시작만."""
    def test_gap_below_check_line_is_18(self):                    # AC-FR1-33 ④ · AC-FR1-25
        sp = self.ctl.shell.start_page
        self.ctl.shell.show()
        sp.resize(900, 1600)
        sp.show()
        sp.show_check_line("확인 중")
        TC._app.processEvents()
        TC._app.processEvents()
        self.assertFalse(sp.check_line.isHidden())
        gap = geo(sp.app_language_section.head, sp)[1] - geo(sp.check_line, sp)[3] - 1
        self.assertEqual(gap, 18)

    def test_no_extra_top_margin_without_banner_and_check_line(self):
        sp = self.ctl.shell.start_page
        self.ctl.shell.show()
        sp.show()
        sp.show_check_line("확인 중")
        TC._app.processEvents()
        self.assertEqual(sp.app_language_section.contentsMargins().top(), 8)
        sp.check_line.setVisible(False)
        sp.banner.setVisible(False)
        TC._app.processEvents()
        self.assertEqual(sp.app_language_section.contentsMargins().top(), 0)

    def test_dialog_margin_20_only_for_start_and_first_run(self):
        from nsu_kangs_rab.app import shell
        self.assertEqual(shell.DIALOG_AVAIL_MARGIN, 20)
        self.assertEqual(shell.fit_to_screen((800, 100000), screen=self.ctl.shell.screen())[1],
                         self.ctl.shell.screen().availableGeometry().height() - 80)       # 설정 · 다시 보기 · 메인 창은 80 그대로


def tearDownModule():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
