"""단계 6 세션 시작 화면 개정(결정 0117 ~ 0121)의 시험: AC-FR1-24 · AC-FR1-25 · AC-FR2-3 · AC-FR2-5 · AC-FR13-3.
설정 파일은 쓰지 않는다(사용자의 실제 설정을 읽거나 쓰지 않는다, 결정 0121 3항). 화면은 offscreen 이다."""
from __future__ import annotations

import unittest

from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QRadioButton

from nsu_kangs_rab.app import screens, shell
from nsu_kangs_rab.core import resources, settings

_app = QApplication.instance() or QApplication([])


def defaults():
    return settings.load_defaults()


def _form(**over):
    d = defaults()
    d.update(over)
    return screens.SessionStartForm(d, "/tmp/RAB")


class _Screen:
    def __init__(self, h):
        self._h = h

    def availableGeometry(self):
        return QRect(0, 0, 1600, self._h)


class ModelDropdownAndPlainRadiosTest(unittest.TestCase):  # AC-FR1-24
    def test_model_is_radio_line_with_three_families(self):
        f = _form()
        self.assertIsInstance(f.family, QComboBox)
        self.assertIs(f.family_cards._combo, f.family)
        self.assertEqual([f.family.itemText(i) for i in range(f.family.count())], ["Sonnet", "Opus", "Haiku"])
        f.family.setCurrentIndex(1)
        self.assertEqual(f.values()["model"], f.family.currentData())

    def test_radio_geometry_and_no_card(self):
        f = _form()
        f.show()
        _app.processEvents()
        for cards in (f.family_cards, f.effort_cards, f.source_cards, f.kind_cards):
            bs = cards.findChildren(QRadioButton)
            self.assertGreaterEqual(len(bs), 2)
            for b in bs:
                self.assertEqual(b.height(), 28)
                self.assertLessEqual(b.width(), b.sizeHint().width())          # 줄 폭에 맞추어 늘어나지 않는다
            for a, b in zip(bs, bs[1:]):
                self.assertEqual(b.x() - (a.x() + a.width()), 24)             # 이웃한 라디오 사이의 가로 간격
        f.close()

    def test_radio_row_pixels_outside_controls_match_background(self):
        f = _form()
        f.show()
        _app.processEvents()
        for cards in (f.family_cards, f.effort_cards, f.source_cards):
            img = cards.grab().toImage()
            bs = cards.findChildren(QRadioButton)
            bg = img.pixelColor(img.width() - 1, img.height() // 2)
            boxes = [b.geometry() for b in bs]
            for x in range(img.width()):
                if any(r.left() <= x <= r.right() for r in boxes):
                    continue
                for y in range(img.height()):
                    self.assertEqual(img.pixelColor(x, y), bg, (x, y))        # 라디오 밖은 바탕색(테두리 · 카드 없음)
            for b in bs:                                                       # 라디오 안의 가장자리 한 줄도 바탕색이다
                r = b.geometry()
                for x in (r.left(), r.right()):
                    self.assertEqual(img.pixelColor(x, r.top()), bg)
        f.close()


class WindowHeightTest(unittest.TestCase):  # AC-FR1-25
    def _shell(self, avail):
        s = shell.MainShell(defaults(), "/tmp", None, first_run=False)
        s.screen = lambda: _Screen(avail)
        return s

    @staticmethod
    def _outer(s):
        """내용 높이의 바깥 높이(안쪽 내용 높이 + 창틀 높이). offscreen 의 창틀 높이는 실측 4 이다."""
        return s.start_page.content_height() + (s.frameGeometry().height() - s.geometry().height())

    def _with_panel(self, s):
        """컨트롤러가 놓는 사전 지식 구역을 시험 창에도 놓는다(D-151: 이 구역의 힌트 폭이 본문 sizeHint 의 폭을 좁혔다)."""
        from nsu_kangs_rab.app import materials as W
        from nsu_kangs_rab.core import context as C, materials_view as MV
        panel = W.MaterialsPanel(MV.MaterialsModel(C.ContextStore()))
        s.start_page.add_section(panel)
        s._test_panel = panel
        return s

    def _settle(self, s):
        s.show()
        for _ in range(3):
            QTest.qWait(30)
            _app.processEvents()

    def test_height_equals_content_when_room(self):
        s = self._shell(5000)
        self._settle(s)
        page = s.start_page
        c = page.content_height()
        self.assertEqual(s.frameGeometry().height(), max(shell.DIALOG_MIN_HEIGHT, self._outer(s)))
        self.assertEqual(page.scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(page.scroll.widget().sizeHint().height() + 64, c)
        s.close()

    def test_content_height_formula(self):
        f = _form()
        f.show()
        _app.processEvents()
        els = f.layout_elements()
        self.assertEqual(f.content_height(), 20 + sum(h for _n, h in els) + 18 * (len(els) - 1) + 20 + 64)
        f.close()

    def test_height_limited_by_available_and_scrolls(self):
        s = self._shell(700)            # 가용 − 80 = 620 < 내용
        self._settle(s)
        page = s.start_page
        self.assertGreater(page.content_height(), 620)
        self.assertEqual(s.frameGeometry().height(), 620)
        self.assertGreater(page.scroll.verticalScrollBar().maximum(), 0)
        bottom_y = page.start.mapTo(s, page.start.rect().topLeft()).y()
        page.scroll.verticalScrollBar().setValue(page.scroll.verticalScrollBar().maximum())
        self.assertEqual(page.start.mapTo(s, page.start.rect().topLeft()).y(), bottom_y)   # 하단 행의 위치가 변하지 않는다
        s.close()

    def test_min_height_420(self):
        s = self._shell(450)            # 가용 − 80 = 370 < 420
        self._settle(s)
        self.assertEqual(s.frameGeometry().height(), shell.DIALOG_MIN_HEIGHT)
        s.close()

    def test_equal_boundary_equals_content(self):
        s = self._shell(5000)
        self._settle(s)
        c = self._outer(s)
        s.close()
        s = self._shell(c + 80)
        self._settle(s)
        self.assertEqual(s.frameGeometry().height(), c)
        self.assertEqual(s.start_page.scroll.verticalScrollBar().maximum(), 0)
        s.close()

    def test_d151_content_height_uses_height_for_width_and_no_leftover(self):
        """창 높이 = 창틀 + 내용 높이이고, 남는 높이가 어느 요소에도 배분되지 않으며(요소 높이 = 실제 폭의 선호 높이), 경계에서 스크롤이 없다."""
        s = self._with_panel(self._shell(5000))
        page = s.start_page
        LONG = "구독 로그인을 확인했다 · 음성 인식 모델이 준비되어 있다 · " + "가나다라마바사 " * 13      # 힌트 폭에서는 두 줄, 실제 폭에서는 한 줄인 글(결정 0179 로 본문 최소 폭이 두 열(300 + 24 + 300) 때문에 넓어져 글을 늘렸다)
        page.show_check_line(LONG)
        self._settle(s)
        body = page.scroll.widget()
        lay = body.layout()
        want = lay.heightForWidth(body.width()) if lay.hasHeightForWidth() else body.sizeHint().height()
        self.assertEqual(body.height(), want)
        self.assertLess(want, body.sizeHint().height())                      # sizeHint(좁은 힌트 폭)의 높이보다 작다: 옛 계산이면 이 차이만큼 창이 높게 열린다
        els = page.layout_elements()
        self.assertEqual(page.content_height(), 20 + sum(h for _n, h in els) + 18 * (len(els) - 1) + 20 + 64)
        c = self._outer(s)
        s.close()
        for avail, scroll in ((c + 80, False), (c + 79, True)):
            s = self._with_panel(self._shell(avail))
            s.start_page.show_check_line(LONG)
            self._settle(s)
            sb = s.start_page.scroll.verticalScrollBar().maximum()
            self.assertEqual(sb > 0, scroll, avail)
            self.assertEqual(s.frameGeometry().height(), c if not scroll else c - 1)
            s.close()

    def test_refit_when_content_changes_and_top_stays(self):
        s = self._shell(5000)
        self._settle(s)
        page = s.start_page
        before = s.frameGeometry().height()
        top = s.frameGeometry().top()
        page.show_problem("시작할 수 없다", "설정에서 고친다")
        for _ in range(3):
            QTest.qWait(30)
            _app.processEvents()
        self.assertGreater(s.frameGeometry().height(), before)
        self.assertEqual(s.frameGeometry().height(), self._outer(s))
        self.assertEqual(s.frameGeometry().top(), top)
        page.show_problem("")
        for _ in range(3):
            QTest.qWait(30)
            _app.processEvents()
        self.assertEqual(s.frameGeometry().height(), before)
        s.close()


class SessionPromptFieldTest(unittest.TestCase):  # AC-FR2-3 · AC-FR2-5
    def test_prefilled_with_default_no_placeholder(self):
        f = _form()
        self.assertEqual(f.session_prompt.toPlainText().strip(), resources.default_session_prompt().strip())
        self.assertEqual(f.session_prompt.placeholderText(), "")

    def test_default_button_resets_and_is_enabled_when_equal(self):
        f = _form()
        self.assertTrue(f.default_prompt_btn.isEnabled())
        f.session_prompt.setPlainText("고쳤다")
        f.default_prompt_btn.click()
        self.assertEqual(f.session_prompt.toPlainText(), f.effective_default_prompt())
        self.assertTrue(f.default_prompt_btn.isEnabled())

    def test_settings_default_flows_into_field(self):
        f = _form(default_session_prompt="설정의 문구")
        self.assertEqual(f.session_prompt.toPlainText(), "설정의 문구")
        f.reload_default_prompt({"default_session_prompt": "바뀐 문구"})
        self.assertEqual(f.session_prompt.toPlainText(), "바뀐 문구")
        f.session_prompt.setPlainText("내가 고침")
        f.reload_default_prompt({"default_session_prompt": "또 바뀐 문구"})
        self.assertEqual(f.session_prompt.toPlainText(), "내가 고침")       # 고친 칸은 덮어쓰지 않는다

    def test_resolve_source_by_equality(self):
        app = "앱 기본"
        S = settings
        self.assertEqual(S.resolve_session_prompt({}, None, app), (S.SOURCE_APP_DEFAULT, app))
        for blank in ("", "   ", "\n \r\n"):
            self.assertEqual(S.resolve_session_prompt({}, blank, app), (S.SOURCE_APP_DEFAULT, app))
        self.assertEqual(S.resolve_session_prompt({}, "앱 기본", app), (S.SOURCE_APP_DEFAULT, app))
        self.assertEqual(S.resolve_session_prompt({}, "a\r\nb", "a\nb"), (S.SOURCE_APP_DEFAULT, "a\nb"))
        self.assertEqual(S.resolve_session_prompt({}, "다름", app), (S.SOURCE_SESSION_INPUT, "다름"))
        d = {"default_session_prompt": "설정 문구"}
        self.assertEqual(S.resolve_session_prompt(d, "설정 문구", app), (S.SOURCE_SETTINGS_DEFAULT, "설정 문구"))
        self.assertEqual(S.resolve_session_prompt(d, " ", app), (S.SOURCE_SETTINGS_DEFAULT, "설정 문구"))
        self.assertEqual(S.resolve_session_prompt(d, app, app), (S.SOURCE_SESSION_INPUT, app))
        self.assertEqual(S.resolve_session_prompt({"default_session_prompt": "  "}, None, app), (S.SOURCE_APP_DEFAULT, app))


class SaveDirTest(unittest.TestCase):  # AC-FR13-3
    def test_placeholder_only_when_empty(self):
        f = _form()
        self.assertEqual(f.save_dir.text(), "")
        self.assertEqual(f.save_dir.placeholderText(), "이 폴더 아래 날짜 폴더에 세션마다 전사 · 정리 문서 · 캡처를 저장합니다")
        self.assertEqual(f.values()["save_dir"], "")
        f.save_dir.setText("/tmp/x")
        self.assertEqual(f.values()["save_dir"], "/tmp/x")


class RegressionD148D150Test(unittest.TestCase):
    def test_d148_rebuild_keeps_single_trailing_stretch(self):  # 다시 만들어도 줄이 왼쪽에 붙는다
        f = _form()
        for cards in (f.family_cards, f.effort_cards, f.source_cards, f.kind_cards):
            for _ in range(3):
                cards.rebuild()
            lay = cards.layout()
            kinds = ["S" if lay.itemAt(i).widget() is None else "W" for i in range(lay.count())]
            n = len(cards.buttons())
            self.assertEqual(kinds, ["W"] * n + ["S"])
        f.show()
        _app.processEvents()
        bs = f.effort_cards.findChildren(QRadioButton)
        self.assertEqual(bs[0].x(), 0)                                      # 첫 라디오가 왼쪽 끝에 있다
        f.close()


if __name__ == "__main__":
    unittest.main()
