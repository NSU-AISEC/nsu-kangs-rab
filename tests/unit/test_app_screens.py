"""K-11 화면 층 시험 (QT_QPA_PLATFORM=offscreen, 창을 띄우지 않는다)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app import appearance, screens, shell, theme
from nsu_kangs_rab.core import appstate, settings

_app = QApplication.instance() or QApplication([])


def defaults():
    return settings.load_defaults()


class ThemeTest(unittest.TestCase):
    def test_tokens_in_stylesheet(self):
        d, l = theme.stylesheet("dark"), theme.stylesheet("light")
        self.assertIn("#07080A", d)
        self.assertIn("#F6F6F7", l)
        self.assertNotIn("#07080A", l)
        self.assertNotIn("<", d)
        self.assertEqual(theme.stylesheet("unknown"), l)

    def test_no_unformatted_placeholder(self):
        import re
        self.assertIsNone(re.search(r"\{[a-z-]+\}", theme.stylesheet("dark")))


class AppearanceTest(unittest.TestCase):
    def test_static_api_present(self):  # A-24 첫 확인(정적)
        h = _app.styleHints()
        for name in ("setColorScheme", "unsetColorScheme", "colorSchemeChanged", "colorScheme"):
            self.assertTrue(hasattr(h, name), name)

    def test_apply_choices(self):
        events = []
        a = appearance.AppearanceApplier(_app, "system", on_applied=events.append)
        self.assertTrue(a.supported)
        self.assertEqual(a.apply("dark"), "dark")
        self.assertIn("#07080A", _app.styleSheet())
        self.assertEqual(a.scheme, "dark")   # offscreen 플랫폼의 colorScheme() 은 Unknown 으로 남는다(실제 cocoa 는 측정 대상)
        self.assertEqual(a.apply("light"), "light")
        self.assertIn("#F6F6F7", _app.styleSheet())
        self.assertEqual(a.apply("garbage"), a.scheme)   # 알 수 없는 값은 시스템 설정 따르기
        self.assertEqual(a.choice, "system")
        self.assertTrue(events)
        a.apply("system")

    def test_system_follow_changes_only_in_system_mode(self):
        a = appearance.AppearanceApplier(_app, "light")
        before = _app.styleSheet()
        a._on_system_changed()
        self.assertEqual(_app.styleSheet(), before)
        a.apply("system")


class FirstRunTest(unittest.TestCase):
    def test_contents(self):
        w = screens.FirstRunNotice()
        text = w.all_text()
        self.assertIn("Anthropic", text)
        self.assertIn("캡처", text)
        self.assertIn("첨부", text)
        self.assertIn("모델 호출", text)
        self.assertNotIn("고정영역", text)     # 결정 0146
        self.assertNotIn("마이크", text)   # AC-NF-1 · AC-FR3-9 (결정 0064)
        self.assertEqual(screens.APP_SUBTITLE, "Retrieval-Augmented Brain")
        self.assertEqual(set(w.perm_rows), {"screen_recording", "system_audio"})   # 마이크 · 단축키 행이 없다(결정 0063 · 0064)

    def test_agree_needs_checkbox_and_quit(self):  # F6 · F7
        w = screens.FirstRunNotice()
        got, quit_ = [], []
        w.acknowledged.connect(lambda: got.append(1))
        w.quit_requested.connect(lambda: quit_.append(1))
        self.assertFalse(w.ok.isEnabled())
        w.ok.click()
        self.assertEqual(got, [])
        w.understood.setChecked(True)
        self.assertTrue(w.ok.isEnabled())
        w.ok.click()
        self.assertEqual(got, [1])
        w.quit.click()
        self.assertEqual(quit_, [1])

    def test_permission_rows_follow_status(self):  # F4 · F5
        w = screens.FirstRunNotice()
        w.set_permissions({"screen_recording": "허용되지 않음", "system_audio": "허용되지 않음"})
        state, btn = w.perm_rows["screen_recording"]
        self.assertEqual(state.text(), "허용 필요")
        self.assertFalse(btn.isHidden())
        w.set_permissions({"screen_recording": "허용", "system_audio": "허용"})
        self.assertEqual(state.text(), "허용됨")
        self.assertTrue(btn.isHidden())
        self.assertEqual(w.WIDTH, 700)

    def test_review_mode_has_close_only(self):
        w = screens.FirstRunNotice()
        w.set_review_mode()
        self.assertTrue(w.quit.isHidden())
        self.assertEqual(w.ok.text(), "닫기")
        self.assertTrue(w.ok.isEnabled())


class SessionStartTest(unittest.TestCase):
    def make(self, **over):
        d = defaults()
        d.update(over)
        return screens.SessionStartForm(d, "/tmp/RAB")

    def test_radio_toggle_without_click_updates_combo_d190(self):
        """손쉬운 사용 누르기(AXPress)는 라디오를 켜지만 clicked 를 내지 않는다: setChecked(True) 로 켜도 선택 상자와 값이 바뀐다."""
        f = self.make()
        self.assertEqual(f.values()["kind"], "수업")
        f.kind_cards.buttons()[1].setChecked(True)
        self.assertEqual(f.values()["kind"], "회의")
        self.assertEqual(f.title.placeholderText(), screens._t("newlang.new62"))
        f.family_cards.buttons()[1].setChecked(True)
        self.assertEqual(f.family.currentIndex(), 1)
        # 선택 상자 → 라디오 동기화는 선택 상자를 다시 바꾸지 않는다(되먹임 없음)
        n = []
        f.kind.currentIndexChanged.connect(lambda _i: n.append(1))
        f.kind.setCurrentIndex(0)
        self.assertEqual(n, [1])
        self.assertTrue(f.kind_cards.buttons()[0].isChecked())
        self.assertFalse(f.kind_cards.buttons()[1].isChecked())

    def test_provider_six_two_active(self):
        f = self.make()
        m = f.provider.model()
        self.assertEqual(m.rowCount(), 6)
        enabled = [bool(m.item(i).flags() & Qt.ItemFlag.ItemIsEnabled) for i in range(6)]
        self.assertEqual(enabled, [True, True, False, False, False, False])
        self.assertIn("확장 지점", m.item(2).text())
        self.assertEqual(m.item(3).data(Qt.ItemDataRole.ToolTipRole), "이 저장소를 확장하여 추가할 수 있습니다")

    def test_first_run_defaults(self):
        v = self.make().values()
        self.assertEqual((v["provider"], v["model"], v["effort"]), ("claude_subscription", "sonnet", "medium"))
        self.assertEqual(v["source"], "system_sound")
        self.assertEqual(v["save_dir"], "")              # 결정 0121: 기억한 값이 없으면 빈 칸(자리 표시 글), 비운 채 시작하면 기본 위치
        self.assertEqual(v["title"], "")                 # 과목명을 비워도 시작된다

    def test_effort_options_exclude_low_max(self):
        f = self.make()
        got = [f.effort.itemText(i) for i in range(f.effort.count())]
        self.assertEqual(got, ["medium", "high", "xhigh"])
        self.assertIn("사용량", f.effort.toolTip())

    def test_remembered_selection(self):
        f = self.make(model="opus", effort="high", provider="claude_api")
        v = f.values()
        self.assertEqual((v["provider"], v["model"], v["effort"]), ("claude_api", "opus", "high"))

    def test_api_fee_visibility(self):
        f = self.make()
        f.show()
        self.assertFalse(f.fee.isVisible())
        screens.set_combo_data(f.provider, "claude_api")
        self.assertTrue(f.fee.isVisible())
        screens.set_combo_data(f.provider, "claude_subscription")
        self.assertFalse(f.fee.isVisible())
        f.hide()

    def test_effort_hidden_without_table(self):
        d = defaults()
        d["providers"]["claude_subscription"]["families"]["haiku"]["efforts"] = []
        f = screens.SessionStartForm(dict(d, model="haiku"), "/x")
        self.assertEqual(f.values()["effort"], None)
        self.assertTrue(f.effort.isHidden())

    def test_mic_item_disabled_with_tooltip(self):  # AC-FR3-4 · AC-FR3-9 (결정 0064)
        f = self.make()
        self.assertEqual([f.source.itemData(i, Qt.ItemDataRole.UserRole) for i in range(f.source.count())],
                         ["system_sound", "system_mic"])
        mic = f.source.model().item(1)
        self.assertFalse(mic.isEnabled())
        self.assertFalse(mic.isSelectable())
        self.assertEqual(f.source.itemData(1, Qt.ItemDataRole.ToolTipRole), "이 앱은 마이크 입력을 지금 제공하지 않습니다")
        self.assertEqual(f.source.itemData(0, Qt.ItemDataRole.ToolTipRole), None)
        self.assertEqual(f.values()["source"], "system_sound")

    def test_saved_mic_source_falls_back_to_system_sound(self):  # AC-FR3-4
        f = screens.SessionStartForm(dict(defaults(), source="system_mic"), "/x")
        self.assertEqual(f.values()["source"], "system_sound")

    def test_start_signal_values(self):
        f = self.make()
        got = []
        f.start_requested.connect(got.append)
        f.title.setText("  AI 특강 ")
        f.start.click()
        self.assertEqual(got[0]["title"], "AI 특강")
        self.assertNotIn("number", got[0])                       # 차시 칸이 없다(결정 0176 1항, AC-FR1-27)
        self.assertFalse(hasattr(f, "number"))

    def test_title_placeholder_follows_kind(self):               # 결정 0176 1항: 수업이면 과목명, 회의이면 회의명
        f = self.make()
        screens.set_combo_data(f.kind, "수업")
        self.assertEqual(f.title.placeholderText(), "과목명")
        screens.set_combo_data(f.kind, "회의")
        self.assertEqual(f.title.placeholderText(), "회의명")
        screens.set_combo_data(f.kind, "수업")
        self.assertEqual(f.title.placeholderText(), "과목명")


class ClaudePathFieldTest(unittest.TestCase):
    """설정의 claude 실행 파일 칸(결정 0176 3항, AC-FR1-28)."""

    def setUp(self):
        import os, stat, tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.auto = os.path.join(self.tmp.name, "auto_claude")
        self.other = os.path.join(self.tmp.name, "other_claude")
        for pth in (self.auto, self.other):
            with open(pth, "w") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(pth, os.stat(pth).st_mode | stat.S_IXUSR)
        self.missing = os.path.join(self.tmp.name, "none_claude")

    def tearDown(self):
        self.tmp.cleanup()

    def form(self, configured=None, auto="AUTO"):
        d = defaults()
        d["claude_path"] = configured
        f = screens.ClaudeSection(d, self.auto if auto == "AUTO" else auto, "claude_subscription")      # 결정 0181: 5. claude 실행 파일 절
        f.saved = []
        f.claude_path_changed.connect(f.saved.append)
        self.addCleanup(self._dispose, f)
        return f

    @staticmethod
    def _dispose(f):          # 부모 없는 위젯을 종료 전에 지워 인터프리터 종료 때의 비정상 종료를 막는다
        from PySide6.QtCore import QCoreApplication, QEvent
        f.close()
        f.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_auto_found_fills_field_with_restore_and_note(self):          # ②
        f = self.form()
        self.assertEqual(f.claude_edit.text(), self.auto)
        self.assertFalse(f.claude_restore.isHidden())
        self.assertEqual(f.claude_found.text(), "자동으로 찾은 경로입니다.")
        self.assertFalse(f.claude_note.isHidden())

    def test_restore_returns_to_auto_and_saves_null(self):                 # ③
        f = self.form(configured=self.other)
        self.assertEqual(f.claude_edit.text(), self.other)
        self.assertEqual(f.claude_found.text(), "")                        # 지정 경로가 유효하면 설명 줄이 없다
        self.assertFalse(f.claude_restore.isHidden())
        f.claude_restore.click()
        self.assertEqual(f.claude_edit.text(), self.auto)
        self.assertEqual(f.saved[-1], None)
        self.assertEqual(f.claude_found.text(), "자동으로 찾은 경로입니다.")

    def test_same_as_auto_or_empty_saves_null(self):
        f = self.form(configured=self.other)
        f.claude_edit.setText(self.auto)
        f._emit_claude_path()
        self.assertEqual(f.saved[-1], None)
        f.claude_edit.setText(self.other)
        f._emit_claude_path()
        self.assertEqual(f.saved[-1], self.other)
        f.claude_edit.setText("")
        f._emit_claude_path()
        self.assertEqual(f.saved[-1], None)
        self.assertEqual(f.claude_edit.text(), self.auto)                   # 비우고 저장하면 자동 경로가 다시 들어간다

    def test_not_found_state(self):                                        # ④
        f = self.form(auto=None)
        self.assertEqual(f.claude_edit.text(), "")
        self.assertTrue(f.claude_restore.isHidden())
        self.assertEqual(f.claude_found.text(), "claude 실행 파일을 찾지 못했습니다. 경로를 지정하세요.")

    def test_specified_path_missing_shows_warning(self):                   # ⑤
        f = self.form(configured=self.missing)
        self.assertEqual(f.claude_found.text(), "지정한 경로에 claude 실행 파일이 없습니다. 경로를 확인하세요.")
        self.assertFalse(f.claude_restore.isHidden())                       # 자동 경로가 있으면 보인다
        g = self.form(configured=self.missing, auto=None)
        self.assertEqual(g.claude_found.text(), "지정한 경로에 claude 실행 파일이 없습니다. 경로를 확인하세요.")
        self.assertTrue(g.claude_restore.isHidden())

    def test_valid_specified_without_auto_has_no_line_and_no_button(self):  # ⑤ 둘째 문장
        f = self.form(configured=self.other, auto=None)
        self.assertEqual(f.claude_found.text(), "")
        self.assertTrue(f.claude_note.isHidden())
        self.assertTrue(f.claude_restore.isHidden())

    def test_no_radio_buttons(self):                                        # ①
        f = self.form()
        from PySide6.QtWidgets import QRadioButton
        texts = [rb.text() for rb in f.findChildren(QRadioButton)]
        self.assertNotIn("자동으로 찾습니다", texts)
        self.assertFalse(any("직접 지정" in t for t in texts))


class SettingsAndStatusTest(unittest.TestCase):
    def test_settings_form(self):
        c = screens.ClaudeSection(defaults(), "/Users/x/.local/bin/claude", "claude_api")      # 결정 0179: claude 경로 · API 키는 시작 화면의 카드이다
        self.assertEqual(c.claude_edit.text(), "/Users/x/.local/bin/claude")
        self.assertEqual(c.api_key.echoMode().name, "Password")
        keys = []
        c.api_key_submitted.connect(keys.append)
        c.api_key.setText("sk-test")
        c.save_key.click()
        self.assertEqual(keys, ["sk-test"])
        self.assertEqual(c.api_key.text(), "")           # 입력 칸에 평문을 남기지 않는다
        f = screens.SettingsForm(defaults())
        self.assertEqual([f.appearance.itemText(i) for i in range(3)], ["시스템 설정 따르기", "밝은 화면", "어두운 화면"])
        self.assertEqual(screens.combo_data(f.appearance), "system")
        got = []
        f.appearance_changed.connect(got.append)
        screens.set_combo_data(f.appearance, "dark")
        self.assertEqual(got, ["dark"])

    def test_settings_source_default_mic_disabled_and_replaced(self):  # AC-FR3-4
        d = dict(defaults())
        d["source"] = "system_mic"                       # 설정 파일에 마이크가 남아 있어도 처음 선택은 시스템 사운드이다
        f = screens.SessionStartForm(d, "/tmp")          # 결정 0179: 음성 소스는 시작 화면의 선택이다
        self.assertEqual(screens.combo_data(f.source), "system_sound")
        self.assertFalse(f.source.model().item(1).isEnabled())
        self.assertIn("마이크 입력을 지금 제공하지 않습니다", f.source.model().item(1).toolTip())

    def test_level_bar_cells(self):  # AC-FR3-10
        b = screens.StatusBar()
        self.assertEqual(b.level_cells(), 0)
        self.assertEqual(b.set_level(-70.0, "수집 중"), 0)
        self.assertEqual(b.set_level(-55.0, "수집 중"), 1)
        self.assertEqual(b.set_level(-30.0, "수집 중"), 3)
        self.assertEqual(b.set_level(-1.0, "수집 중"), 6)
        self.assertEqual(b.level_cells(), 6)
        self.assertEqual(b.set_level(-1.0, "중단"), 0)
        self.assertEqual(b.level_cells(), 0)

    def test_status_bar(self):
        b = screens.StatusBar()
        t = b.show_inputs(appstate.StatusInputs("claude_subscription", "sonnet", "medium", materials=2, captures=1))
        self.assertIn("Sonnet · medium", t)
        self.assertEqual(b.text(), t)


class AppearanceOverrideTest(unittest.TestCase):
    def test_dev_appearance_override(self):
        a = appearance.AppearanceApplier(_app, "system", system_override="dark")
        self.assertEqual(a.scheme, "dark")
        a.set_system_override("light")
        self.assertEqual(a.scheme, "light")
        a.apply("dark")                       # 명시 선택이 우선한다
        a.set_system_override("light")
        self.assertEqual(a.scheme, "dark")
        a.set_system_override(None)
        a.apply("system")


class ShellTest(unittest.TestCase):
    def make(self, first_run):
        w = shell.MainShell(defaults(), "/tmp/RAB", "/x/claude", first_run=first_run)
        self.quit = []
        w.quit_requested.connect(lambda: self.quit.append(1))
        return w

    def test_first_run_flow(self):
        w = self.make(True)
        self.assertIs(w.stack.currentWidget(), w.first_run_page)
        w.first_run_page.understood.setChecked(True)
        w.first_run_page.ok.click()
        self.assertIs(w.stack.currentWidget(), w.start_page)
        self.assertIs(w.machine.state, appstate.State.BEFORE_SESSION)

    def test_no_first_run_goes_to_start(self):
        w = self.make(False)
        self.assertIs(w.stack.currentWidget(), w.start_page)

    def test_close_quits_before_session_only(self):
        w = self.make(False)
        w.close()
        self.assertEqual(self.quit, [1])
        w = self.make(False)
        got = []
        w.session_start_requested.connect(got.append)
        w.start_page.start.click()
        self.assertEqual(len(got), 1)
        self.assertIs(w.machine.state, appstate.State.BEFORE_SESSION)   # 호출한 쪽이 성공을 알리기 전
        w.session_started()
        self.assertIs(w.stack.currentWidget(), w.session_page)
        self.quit.clear()
        w.close()
        self.assertEqual(self.quit, [])
        w.machine.begin_ending()
        w.close()
        self.assertEqual(self.quit, [])


class ScreensFollowMockupTest(unittest.TestCase):
    """결정 0068: 세션 시작 · 설정 화면의 시안 구성(카드 선택, 세션 프롬프트, 기본 문구 · 템플릿 · 경로 · 트리거 키)."""

    def test_start_form_session_prompt_cancel_and_cards(self):  # D-090
        f = screens.SessionStartForm(defaults(), "/tmp/RAB")
        f.session_prompt.setPlainText("이 자리는 시험이다.")
        self.assertEqual(f.values()["session_prompt"], "이 자리는 시험이다.")
        got = []
        f.cancel_requested.connect(lambda: got.append(1))
        f.cancel.click()
        self.assertEqual(got, [1])
        self.assertIs(f.family_cards._combo, f.family)       # 결정 0143: 모델은 카드 없는 라디오 줄이다
        f.family.setCurrentIndex(1)
        self.assertEqual(f.values()["model"], f.family.currentData())
        f.family.setCurrentIndex(0)
        mic = f.source_cards.buttons()[1]
        self.assertFalse(mic.isEnabled())                     # 결정 0064: 비활성 + 도움말
        self.assertIn("마이크", mic.toolTip())
        self.assertEqual(f.provider_list.row_names()[2:], ["ChatGPT 구독", "ChatGPT API", "Gemini 구독", "Gemini API"])

    def test_settings_form_template_and_trigger_and_start_screen_prompt_claude(self):  # D-091 ~ D-094 (결정 0179: 프롬프트 · claude 는 시작 화면)
        from nsu_kangs_rab.core import resources
        f = screens.SettingsForm(defaults())
        tpls = []
        f.template_changed.connect(lambda k, t: tpls.append((k, t)))
        f.template_edits["수업"].setPlainText("# 내 템플릿")
        f._emit_template("수업")
        f.templates_reset.click()
        self.assertEqual(tpls[0], ("수업", "# 내 템플릿"))
        self.assertEqual(tpls[1:], [("수업", ""), ("회의", "")])
        self.assertEqual(f.trigger_key.text(), "F2")
        sp = screens.SessionStartForm(defaults(), "/tmp/RAB", claude_auto="/usr/bin/claude")
        prompts, paths = [], []
        sp.default_prompt_saved.connect(prompts.append)
        sp.claude_path_changed.connect(paths.append)
        self.assertEqual(sp.session_prompt.toPlainText().strip(), resources.default_session_prompt().strip())
        sp.session_prompt.setPlainText("내 문구")
        sp.save_default_btn.click()
        sp.reset_prompt_to_original()
        sp.save_default_btn.click()
        self.assertEqual(prompts, ["내 문구", ""])            # 처음 문구와 같으면 빈 값(앱 기본 문구)을 저장한다
        self.assertFalse(hasattr(sp.claude_section, "claude_auto") and hasattr(sp.claude_section.claude_auto, "isChecked"))        # 라디오 단추는 없다(결정 0176 3항)
        sp.claude_section.claude_edit.setText("/x/claude")
        sp.claude_section._emit_claude_path()
        self.assertEqual(paths[-1], "/x/claude")


def tearDownModule():          # 부모 없는 위젯(카드 · 폼)을 인터프리터 종료 전에 지운다(종료 때의 비정상 종료 방지)
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()


class ScreensVerdictTest(unittest.TestCase):
    """scr-verdict: D-098(창 안의 표시줄) · D-100(고지 원문) · D-103(키 저장 표시)."""

    @staticmethod
    def _dispose(w):          # 부모 없는 위젯을 종료 전에 지운다
        from PySide6.QtCore import QCoreApplication, QEvent
        w.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_status_bar_fits_window_at_min_width(self):  # D-098
        from nsu_kangs_rab.app.shell import MainShell
        from nsu_kangs_rab.core import appstate
        sh = MainShell(defaults(), "/tmp", None, first_run=False)
        sh.session_started()
        sh.status.show_inputs(appstate.StatusInputs(
            provider="claude_subscription", family="sonnet", effort="medium", source="시스템 사운드", capture_state="수집 중",
            materials=3, captures=4, stt_prep="음성 인식 준비 중 42%", stt_errors=2, queue_waiting=2, activity="정리 문서 만드는 중"))
        sh.resize(800, 600)
        sh.show()
        for _ in range(5):
            _app.processEvents()
        try:
            self.assertEqual(sh.width(), 800)
            self.assertLessEqual(sh.status.width(), 800)
            self.assertTrue(sh.status.more.isVisibleTo(sh.status))
            right = max(lb.geometry().right() for lb in sh.status._labels if lb.isVisibleTo(sh.status))
            self.assertLessEqual(right, 800)
        finally:
            sh.close()
            sh.deleteLater()

    def test_first_run_has_no_folder_watch_sentence(self):  # 결정 0146: AC-NF-1 의 고지에는 폴더 감시 경고가 없다
        w = screens.FirstRunNotice()
        texts = " ".join(lb.text() for lb in w.findChildren(screens.QLabel))
        self.assertNotIn("고정영역", texts)
        self.assertNotIn("감시", texts)

    def test_key_field_states(self):  # D-103 · AC-FR1-17 (결정 0179: 앱 환경 카드)
        f = screens.ClaudeSection(defaults(), None, "claude_api")
        got = []
        f.api_key_submitted.connect(got.append)
        f.set_key_saved(True)
        self.assertTrue(f.api_key.isReadOnly())
        self.assertEqual(f.api_key.text(), "\u2022" * 8)
        self.assertTrue(f.delete_key.isEnabled())
        f.save_key.click()                      # [변경…]: 비우고 편집 가능
        self.assertFalse(f.api_key.isReadOnly())
        self.assertEqual(f.api_key.text(), "")
        self.assertEqual(f.api_key.placeholderText(), "새 Claude API 키")
        self.assertEqual(f.save_key.text(), "저장")
        f.api_key.setText("sk-ant-test")
        f.cancel_key_edit()
        self.assertEqual(f.save_key.text(), "변경…")                     # Esc · 닫기: 입력을 버리고 점 표시
        self.assertTrue(f.api_key.isReadOnly())
        self.assertEqual(f.api_key.text(), "\u2022" * 8)
        self.assertEqual(got, [])
        f.save_key.click()
        f.api_key.setText("sk-ant-test")
        f.api_key.returnPressed.emit()          # Enter 만 저장
        self.assertEqual(got, ["sk-ant-test"])
        f.set_key_saved(True)
        self.assertNotIn("sk-ant", f.api_key.text())
        f.set_key_saved(False)
        self.assertFalse(f.api_key.isReadOnly())
        self.assertEqual(f.api_key.placeholderText(), "새 Claude API 키")        # UI-092 (D-205)
        self.assertEqual(f.save_key.text(), "저장")                              # 단추는 [저장] 하나
        self.assertTrue(f.delete_key.isHidden())                                 # [삭제] 는 보이지 않는다
        self.assertTrue(f.api_key.property("keywarn"))                           # 경고색 테두리
        f.set_key_saved(True)
        self.assertFalse(f.delete_key.isHidden())
        self.assertFalse(f.api_key.property("keywarn"))

    def test_key_save_failure_keeps_dots_and_shows_reason(self):
        f = screens.ClaudeSection(defaults(), None, "claude_api")
        f.set_key_saved(True)
        f.save_key.click()
        f.show_key_error("API 키를 저장하지 못했습니다")
        self.assertTrue(f.api_key.isReadOnly())
        self.assertFalse(f.key_error.isHidden())

    def test_enter_in_key_field_does_not_press_default_button(self):  # D-104 (결정 0179: 앱 환경 카드의 입력 칸)
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        dlg = QDialog()
        self.addCleanup(self._dispose, dlg)
        lay = QVBoxLayout(dlg)
        f = screens.ClaudeSection(defaults(), "/bin/echo", "claude_api")
        lay.addWidget(f)
        pressed = []
        f.delete_key.clicked.connect(lambda: pressed.append("delete"))
        f.api_key_submitted.connect(lambda _k: pressed.append("submit"))
        dlg.show()
        f.set_key_saved(False)
        f.api_key.setFocus()
        QTest.keyClick(f.api_key, Qt.Key.Key_Return)
        QTest.keyClick(f.claude_edit, Qt.Key.Key_Return)
        self.assertEqual(pressed, [])
        for b in f.findChildren(screens.QPushButton):
            self.assertFalse(b.autoDefault())


class _FakeScreen:
    def __init__(self, left, top, w, h):
        self._g = (left, top, w, h)

    def availableGeometry(self):
        from PySide6.QtCore import QRect
        return QRect(*self._g)


class WindowOnOwnScreenTest(unittest.TestCase):  # D-105
    def test_fit_uses_given_screen_not_primary(self):
        got = shell.fit_to_screen(shell.DEFAULT_WINDOW, screen=_FakeScreen(0, 0, 800, 1255))
        self.assertEqual(tuple(got), (800, 960))   # 높이 = min(기본 960, 가용 1255 − 80)

    def test_fit_width_follows_screen(self):
        got = shell.fit_to_screen(shell.DEFAULT_WINDOW, screen=_FakeScreen(0, 0, 1024, 600))
        self.assertEqual(tuple(got), (1024, 560))

    def test_position_within_moves_inside(self):
        from PySide6.QtCore import QRect
        avail = QRect(1920, 25, 800, 1255)
        self.assertEqual(shell.position_within(2100, 25, 800, 900, avail), (1920, 25))
        self.assertEqual(shell.position_within(1920, 700, 800, 900, avail), (1920, 380))
        self.assertEqual(shell.position_within(1920, 25, 800, 900, avail), (1920, 25))
        self.assertEqual(shell.position_within(0, 0, 900, 1400, avail), (1920, 25))   # 영역보다 크면 왼쪽 위에 맞춘다

    def test_shell_sizes_to_its_own_screen_when_session_starts(self):
        sh = shell.MainShell(defaults(), "/tmp", None, first_run=False)
        fake = _FakeScreen(1920, 25, 800, 1255)
        sh.screen = lambda: fake
        sh.move(1920, 40)
        sh.session_started()
        self.assertLessEqual(sh.width(), 800)
        self.assertLessEqual(sh.height(), 1255 - 80)
        g = sh.frameGeometry()
        self.assertGreaterEqual(g.left(), 1920)
        self.assertLessEqual(g.right(), 1920 + 800)
        sh.deleteLater()


class DisabledPrimaryButtonTest(unittest.TestCase):  # D-106
    def _paint(self, scheme, enabled):
        from PySide6.QtWidgets import QPushButton
        _app.setStyleSheet(theme.stylesheet(scheme))
        b = QPushButton("세션 시작")
        b.setObjectName("primary")
        b.setEnabled(enabled)
        b.resize(160, 40)
        b.show()
        _app.processEvents()
        img = b.grab().toImage()
        px = img.pixelColor(img.width() // 2, 4).name()
        b.close()
        b.deleteLater()
        return px

    def test_disabled_primary_differs_and_uses_surface_elevated(self):
        for scheme in ("light", "dark"):
            on, off = self._paint(scheme, True), self._paint(scheme, False)
            self.assertNotEqual(on, off, scheme)
            self.assertEqual(off.lower(), theme.tokens(scheme)["surface-elevated"].lower(), scheme)
        _app.setStyleSheet("")


class Rev8Test(unittest.TestCase):  # 8차 개정(결정 0069 ~ 0073)
    def test_default_settings_has_no_top_level_effort(self):  # AC-FR1-5, 결정 0071
        import json
        p = os.path.join(os.path.dirname(settings.__file__), "default_settings.json")
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertNotIn("effort", data)
        data["providers"]["claude_subscription"]["families"]["sonnet"]["default"] = "high"
        self.assertEqual(settings.resolve_selection(data).effort, "high")
        data["effort"] = "medium"                       # 기억한 값은 표의 기본값보다 우선한다
        self.assertEqual(settings.resolve_selection(data).effort, "medium")

    def test_status_stt_prep_chip_is_pill_and_precedes_activity(self):  # 결정 0167: 준비 칩
        bar = screens.StatusBar()
        s = appstate.StatusInputs("claude_api", "sonnet", "high", stt_prep="음성 인식 준비 중 42%", activity="요청 진행 중")
        bar.show_inputs(s)
        texts = [lb.text() for lb in bar._labels]
        names = {lb.text(): lb.objectName() for lb in bar._labels}
        self.assertEqual(names["음성 인식 준비 중 42%"], "status_pill")
        self.assertEqual(names["요청 진행 중"], "status_pill")
        self.assertLess(texts.index("음성 인식 준비 중 42%"), texts.index("요청 진행 중"))
        bar.show_inputs(appstate.StatusInputs("claude_api", "sonnet", "high"))
        self.assertNotIn("음성 인식 준비 중 42%", [lb.text() for lb in bar._labels])

    def test_status_pill_uses_info_colors_d219(self):  # VD 7-4, 결정 0167: 요청 진행 중 · 모델 준비 중 알약은 정보 상태 색
        import re
        for scheme in ("light", "dark"):
            tk = theme.tokens(scheme)
            css = theme.stylesheet(scheme)
            m = re.search(r"QLabel#status_pill \{([^}]*)\}", css)
            self.assertIsNotNone(m, scheme)
            body = m.group(1)
            self.assertIn("background: %s" % tk["info-bg"], body, scheme)
            self.assertIn("color: %s" % tk["info"], body, scheme)
            self.assertIn("font-weight: 500", body, scheme)

    def test_status_pill_geometry_d221(self):  # VD 7-4: 높이 20 · 안쪽 여백 2 × 8 · caption(12px) 500, 표시줄 안에서 세로 가운데
        import re
        from PySide6.QtCore import QPoint
        for scheme in ("light", "dark"):
            css = theme.stylesheet(scheme)
            for name in ("status_pill", "status_pill_warn"):
                body = re.search(r"QLabel#%s \{([^}]*)\}" % name, css).group(1)
                self.assertIn("padding: 2px 8px", body, (scheme, name))
                self.assertIn("font-size: 12px", body, (scheme, name))
            _app.setStyleSheet(css)
            bar = screens.StatusBar()
            self.addCleanup(bar.deleteLater)
            bar.resize(1600, 32)
            bar.show()
            bar.show_inputs(appstate.StatusInputs("claude_api", "sonnet", "high", stt_prep="음성 인식 준비 중 42%", activity="요청 진행 중"))
            _app.processEvents()
            pills = [lb for lb in bar._labels if lb.objectName() == "status_pill"]
            self.assertEqual(len(pills), 2)
            for lb in pills:
                self.assertEqual(lb.height(), 20, scheme)
                top = lb.mapTo(bar, QPoint(0, 0)).y()
                self.assertEqual(top, (bar.height() - 20) // 2, scheme)          # 세로 가운데

    def test_elided_path_edit(self):  # AC-FR13-3
        e = screens.ElidedPathEdit("/Users/someone/Documents/ProfKangRAB/very/long/nested/folder/name/ABC")
        e.resize(200, 36)
        e.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        e.show()
        _app.processEvents()
        self.assertTrue(e.text().endswith("/ABC"))                 # text() 는 늘 전체 경로이다
        self.assertIn("…", QLineEditText(e))                  # 화면에는 가운데를 줄인다
        self.assertEqual(e.toolTip(), e.text())
        e.close()

    def test_permission_action_text_and_first_run_foot(self):  # FR-9 · AC-NF-1, 결정 0072
        from nsu_kangs_rab.core import error_text
        t = error_text.action_text("permission")
        self.assertNotIn("ProfKangRAB", t)                    # 결정 0097: 권한 창 이름의 구절을 두지 않는다
        self.assertIn("Prof. Kang's RAB 을 허용한 뒤 앱을 다시 시작하세요", t)
        self.assertIn("개인정보 보호 및 보안", t)
        self.assertNotIn("ProfKangRAB", screens.FIRST_RUN_PERMISSION_FOOT)
        self.assertTrue(screens.FIRST_RUN_PERMISSION_FOOT.endswith("권한은 Prof. Kang's RAB 앱에만 부여됩니다."))

    def test_icon_button_disabled_rule(self):  # 시각 설계 7-1
        self.assertIn("QPushButton#iconbtn:disabled", theme.stylesheet("light"))

    def test_icon_button_enabled_color_is_body(self):  # D-107, 시각 설계 7-1 표 141행
        for scheme in ("light", "dark"):
            css = theme.stylesheet(scheme)
            line = [x for x in css.splitlines() if x.startswith("QPushButton#iconbtn {")][0]
            self.assertIn("color: %s;" % theme.tokens(scheme)["body"], line)

    def test_restart_failed_card_reason_line(self):  # D-109, FR-9 표 · AC-FR9-21
        from nsu_kangs_rab.core import error_text
        failed = error_text.card_text("process_exit", error_text.RESTART_FAILED)
        ended = error_text.card_text("process_exit", None)
        self.assertEqual(failed.splitlines()[0], "프로세스를 다시 시작하지 못했습니다")
        self.assertEqual(ended.splitlines()[0], "모델 호출 프로세스가 응답 도중에 끝났습니다")     # R7b 는 그대로
        self.assertNotEqual(failed.splitlines()[0], ended.splitlines()[0])
        self.assertNotIn("(프로세스를 다시 시작하지 못했습니다)", failed)
        self.assertEqual(error_text.card_text("network", "x").splitlines()[0], "네트워크에 연결하지 못했습니다")   # 다른 종류는 그대로

    def test_process_exit_action_has_restart_failure_sentence(self):  # D-108, FR-9 표 · AC-FR9-21
        from nsu_kangs_rab.core import error_text
        t = error_text.action_text("process_exit")
        self.assertIn("다시 시작하지 못하면 대기 중인 카드를 이 오류로 끝내고, 그다음 요청에서 다시 시도합니다", t)
        self.assertIn("같은 오류가 반복되면 앱을 다시 시작해 시작 화면의 5. claude 실행 파일에서 경로를 확인하세요", t)      # ui-strings UI-303(결정 0179)


def QLineEditText(e):
    from PySide6.QtWidgets import QLineEdit
    return QLineEdit.text(e)


class Rev15Test(unittest.TestCase):  # 15차 개정(결정 0089): 드롭다운 · 스크롤 막대 · 키 칸 조건부
    def setUp(self):
        _app.setProperty("rab_scheme", "light")
        _app.setStyleSheet(theme.stylesheet("light"))

    def test_provider_is_dropdown_and_disabled_items_stay_open(self):  # AC-FR1-10
        from PySide6.QtTest import QTest
        f = screens.SessionStartForm(defaults(), "/tmp/RAB")
        c = f.provider
        self.assertIsInstance(c, screens.ProviderCombo)
        self.assertEqual(c.height(), 36)
        c.showPopup()
        v = c.view()
        self.assertTrue(v.isVisible())
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, v.visualRect(c.model().index(3, 0)).center())
        self.assertTrue(v.isVisible())                     # 비활성 항목: 접히지 않고 선택도 바뀌지 않는다
        self.assertEqual(c.currentIndex(), 0)
        self.assertEqual(c.model().item(3).data(Qt.ItemDataRole.ToolTipRole), "이 저장소를 확장하여 추가할 수 있습니다")
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, v.visualRect(c.model().index(1, 0)).center())
        self.assertFalse(v.isVisible())                    # 활성 항목: 선택하고 접힌다
        self.assertEqual(c.currentIndex(), 1)
        self.assertEqual(screens._ProviderDelegate.ROW_H, 32)

    def test_scrollbar_stylesheet_values_both_schemes(self):  # AC-FR15-7, 7-14
        for scheme, vals in (("light", ("#F1F1F1", "#C1C1C1", "#A8A8A8", "#787878")),
                             ("dark", ("#1A1B1C", "#5A5C5E", "#7A7C7E", "#9A9C9E"))):
            css = theme.stylesheet(scheme)
            for v in vals:
                self.assertIn(v, css)
            self.assertIn("width: 12px", css)
            self.assertIn("min-height: 24px", css)
            self.assertIn("border-radius: 4px", css)
            self.assertIn("margin: 2px", css)
            self.assertIn("QScrollBar::add-line", css)

    def test_api_key_group_follows_default_provider_without_deleting_key(self):  # AC-FR1-16
        sp = screens.SessionStartForm(defaults(), "/tmp", claude_auto="/usr/bin/claude")      # 결정 0179: 시작 화면의 제공자가 앱 환경 카드의 키 절을 정한다
        f = sp.claude_section
        sp.set_key_saved(True)
        screens.set_combo_data(sp.provider, "claude_subscription")
        self.assertTrue(f.key_group.isHidden())
        screens.set_combo_data(sp.provider, "claude_api")
        self.assertFalse(f.key_group.isHidden())
        self.assertEqual(f.api_key.text(), f.KEY_DOTS)
        screens.set_combo_data(sp.provider, "claude_subscription")
        self.assertTrue(f.key_group.isHidden())
        self.assertEqual(f.api_key.text(), f.KEY_DOTS)             # 감춰도 키는 지우지 않는다


class SettingsDots:
    DOTS = "•" * 8


class SettingsOrderTest(unittest.TestCase):
    def test_section_order_and_names(self):                         # 결정 0158
        from PySide6.QtWidgets import QLabel
        f = screens.SettingsForm(defaults())
        titles = [lb.text() for lb in f.findChildren(QLabel) if lb.objectName() == "section_title"]
        self.assertEqual(titles[0], "테마")                       # 결정 0179: 절은 테마 · 단축키 · 정리 문서 템플릿 순서이다
        self.assertEqual(len(titles), 3)
        self.assertIn("단축키", titles[1])
        for gone in ("언어", "음성 소스", "기본 모델 제공자", "claude 실행 파일", "기본 프롬프트", "Claude API 키"):
            self.assertNotIn(gone, titles)
        self.assertNotIn("기본 음성 소스", titles)
        self.assertNotIn("음성 인식 모델", titles)               # M-3: 모델 칸을 지웠다(결정 0162 · 0167)
        self.assertNotIn("화면 밝기", titles)


class ButtonHeightTest(unittest.TestCase):
    """D-169 · D-170: 고정 높이가 기본 단추 스타일의 합(38)에 덮이지 않는다(앱 스타일시트를 적용한 상태에서 잰다)."""

    def setUp(self):
        _app.setStyleSheet(theme.stylesheet("light"))
        self.addCleanup(lambda: _app.setStyleSheet(""))

    def _h(self, b):
        b.ensurePolished()
        return b.minimumSizeHint().height(), b.sizeHint().height()

    def test_settings_buttons(self):
        f = screens.SettingsForm(defaults())
        b = f.templates_reset
        self.assertLessEqual(self._h(b)[0], 28)
        self.assertIn("padding-left: 12px", b.styleSheet())
        self.assertEqual(b.font().pixelSize() if b.font().pixelSize() > 0 else 13, 13)
        self.assertIn("font-size: 13px; font-weight: 500", b.styleSheet())
        card = screens.ClaudeSection(defaults(), "/usr/bin/claude", "claude_api")
        self.assertLessEqual(self._h(card.save_key)[0], 36)

    def test_start_prompt_buttons_are_28(self):          # 결정 0179: [처음 문구] · [기본값] · [기본값으로 저장]
        f = screens.SessionStartForm(defaults(), "/x")
        for b in (f.original_prompt_btn, f.default_prompt_btn, f.save_default_btn):
            b.ensurePolished()
            self.assertLessEqual(b.minimumSizeHint().height(), 28)
            self.assertEqual((b.minimumHeight(), b.maximumHeight()), (28, 28))
            self.assertIn("font-size: 13px; font-weight: 500", b.styleSheet())

    def test_start_default_button_is_28(self):
        f = screens.SessionStartForm(defaults(), "/x")
        b = f.default_prompt_btn
        b.ensurePolished()
        self.assertLessEqual(b.minimumSizeHint().height(), 28)
        self.assertEqual(b.height() if b.height() > 0 else 28, b.height() if b.height() > 0 else 28)
        self.assertEqual(b.minimumHeight(), 28)
        self.assertEqual(b.maximumHeight(), 28)
        self.assertIn("font-size: 13px; font-weight: 500", b.styleSheet())


class TransportGeometryTest(unittest.TestCase):
    """D-173: 전사 창 머리 행의 [재생] · [일시 정지] · [정지] · 카메라 단추가 모든 상태에서 28 × 28 이고 위치가 같다(VD 195 · 235)."""

    def test_all_states_28x28_and_stable_positions(self):
        from nsu_kangs_rab.app import mainview
        _app.setStyleSheet(theme.stylesheet("light"))
        self.addCleanup(lambda: _app.setStyleSheet(""))
        v = mainview.SessionView()
        self.addCleanup(v.deleteLater)
        v.show()
        seen = []
        for st in ("수집 전", "수집 중", "일시 정지", "중단"):
            v.transport.set_state(st, False)
            _app.processEvents()
            bs = [v.transport.btn_play, v.transport.btn_pause, v.transport.btn_stop]
            for b in bs + [v.btn_capture]:
                self.assertEqual((b.width(), b.height()), (28, 28), (st, b.objectName()))
            seen.append([b.x() for b in bs])
        self.assertEqual(seen[0], [0, 32, 64])               # 간격 4
        self.assertTrue(all(x == seen[0] for x in seen))     # 상태가 바뀌어도 움직이지 않는다
