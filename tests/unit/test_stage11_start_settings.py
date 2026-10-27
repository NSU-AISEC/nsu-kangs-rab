"""단계 11 (결정 0179) · 단계 12 (결정 0181): 시작 화면으로 옮긴 설정 7종 · 설정 창의 축소 · 세션 시작 때 고정하는 값.
AC-FR1-16 · AC-FR1-26 ⑤⑥ · AC-FR1-28 ~ 31 · AC-FR2-5 · AC-FR16-1 · AC-FR16-8."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_app_controller as TC  # noqa: E402
from nsu_kangs_rab.app import screens  # noqa: E402
from nsu_kangs_rab.core import resources  # noqa: E402

UR = screens.Qt.ItemDataRole.UserRole


def saved(case):
    return json.loads((case.cfg / "settings.json").read_text(encoding="utf-8"))


class SectionsTest(TC.Base):
    """앱 환경 카드는 없고(결정 0181) 앱 언어 · claude 실행 파일 · API 키는 번호 있는 절이다(AC-FR1-29 ②, AC-FR1-31)."""
    def test_card_is_gone(self):
        sp = self.ctl.shell.start_page
        self.assertFalse(hasattr(sp, "app_env"))
        self.assertFalse(hasattr(sp, "expand_app_env"))
        self.assertFalse(hasattr(screens, "AppEnvCard"))
        names = {w.objectName() for w in sp.findChildren(screens.QWidget)}
        self.assertFalse({n for n in names if n.startswith("app_env")})

    def test_key_entry_clears_banner(self):                         # AC-FR1-31
        sp = self.ctl.shell.start_page
        sp.provider.setCurrentIndex(sp.provider.findData("claude_api", UR))
        self.ctl.refresh_start_check()
        self.assertFalse(sp.banner.isHidden())
        sp.claude_section.api_key_submitted.emit("sk-test-1234")
        self.assertEqual(self.keys.get(), "sk-test-1234")
        self.assertTrue(sp.banner.isHidden())


class ImmediateSaveTest(TC.Base):
    """카드의 항목은 즉시 저장하고 [취소] 로 되돌리지 않는다(AC-FR1-28)."""
    def test_app_language_saved_on_select(self):
        sec = self.ctl.shell.start_page.app_language_section
        sec.app_language.setCurrentIndex(sec.app_language.findData("en", UR))
        self.assertEqual(saved(self).get("app_language"), "en")
        self.assertFalse(sec.lang_notice.isHidden())                # 다시 시작 안내(NEW-6)

    def test_claude_path_flushed_before_start(self):                # S11-10
        sp = self.ctl.shell.start_page
        sp.claude_section.claude_edit.setText("/bin/ls")
        got = []
        sp.start_requested.connect(got.append)
        sp.start.click()
        self.assertEqual(saved(self).get("claude_path"), "/bin/ls")
        self.assertTrue(got)

    def test_claude_path_flushed_before_cancel(self):
        sp = self.ctl.shell.start_page
        sp.claude_section.claude_edit.setText("/bin/ls")
        got = []
        sp.cancel_requested.connect(lambda: got.append(1))
        sp.claude_section.flush_claude_path()
        sp._on_cancel_clicked()
        self.assertEqual(saved(self).get("claude_path"), "/bin/ls")
        self.assertTrue(got)


class SessionStartSaveTest(TC.Base):
    def test_stt_language_saved_at_start(self):
        self.assertTrue(self.start(stt_language="en"))
        self.assertEqual(saved(self).get("stt_language"), "en")

    def test_stt_language_not_saved_by_selection_alone(self):
        sp = self.ctl.shell.start_page
        sp.stt_language.setCurrentIndex(sp.stt_language.findData("en", UR))
        self.assertNotEqual(saved(self).get("stt_language"), "en")


class SessionFixedValuesTest(TC.Base):
    """AC-FR1-26 ⑤⑥: 세션이 쓰는 키와 프롬프트는 시작 때 고정한다."""
    def test_session_key_and_prompt_fixed_at_start(self):
        self.keys.set("sk-first")
        self.assertTrue(self.start(provider="claude_api", session_prompt="처음 프롬프트"))
        self.keys.set("sk-second")                                  # 시작 뒤에 키체인이 바뀌어도
        self.ctl.data["default_session_prompt"] = "바뀐 기본 문구"
        self.assertEqual(self.ctl._session_key, "sk-first")
        self.assertEqual(self.ctl._session_prompt, "처음 프롬프트")
        one = self.ctl._make_oneshot(self.ctl.runtime.folder, "test")
        self.assertEqual(one._api_key, "sk-first")
        self.assertIn("처음 프롬프트", one._prompt)


class SettingsWindowTest(TC.Base):
    """AC-FR1-30: 설정 창에는 테마 · 단축키 · 정리 문서 템플릿만 남는다."""
    def test_widgets_removed(self):
        self.ctl.open_settings()
        f = self.ctl._settings_form
        for name in ("provider", "source", "api_key", "claude_edit", "app_language", "stt_language", "default_prompt"):
            self.assertFalse(hasattr(f, name), name)

    def test_removed_events_have_no_handlers(self):
        for name in ("_on_stt_language", "_on_provider_default", "_on_source_default"):
            self.assertFalse(hasattr(self.ctl, name), name)


class PromptButtonsTest(TC.Base):
    """AC-FR2-5: [처음 문구] · [기본값] · [기본값으로 저장]."""
    def test_buttons_enabled_by_text(self):
        sp = self.ctl.shell.start_page
        original = resources.default_session_prompt()
        sp.reset_prompt_to_original()
        self.assertEqual(sp.session_prompt.toPlainText(), original)
        self.assertFalse(sp.original_prompt_btn.isEnabled())
        sp.session_prompt.setPlainText("고친 문구")
        self.assertTrue(sp.original_prompt_btn.isEnabled())
        self.assertTrue(sp.save_default_btn.isEnabled())
        sp.session_prompt.setPlainText("   ")
        self.assertFalse(sp.save_default_btn.isEnabled())

    def test_save_default_emits_and_persists(self):
        sp = self.ctl.shell.start_page
        sp.session_prompt.setPlainText("저장할 문구")
        sp.save_default_btn.click()
        self.assertEqual(saved(self).get("default_session_prompt"), "저장할 문구")


class DefectsB60Test(TC.Base):
    """b60 판정의 결함: D-204(자동 경로가 칸에 보인다) · D-207(음성 인식 언어 열의 간격)."""
    def test_auto_claude_path_shown_in_field_d204(self):
        card = self.ctl.shell.start_page.claude_section
        self.assertEqual(card.claude_edit.text(), "/bin/echo")                 # Base 의 자동으로 찾은 경로
        self.assertFalse(card.claude_restore.isHidden())
        self.assertFalse(card.claude_note.isHidden())
        self.assertIn("자동으로 찾은", card.claude_found.text())

    def test_set_claude_auto_keeps_user_text_d204(self):
        card = screens.ClaudeSection({"claude_path": None}, None, "claude_subscription")
        self.addCleanup(card.deleteLater)
        card.set_claude_auto("/a/claude")
        self.assertEqual(card.claude_edit.text(), "/a/claude")
        card.claude_edit.setText("/mine/claude")
        card.set_claude_auto("/b/claude")                                     # 사용자가 고친 글은 그대로 둔다
        self.assertEqual(card.claude_edit.text(), "/mine/claude")

    def test_stt_column_spacing_d207(self):
        sp = self.ctl.shell.start_page
        self.ctl.shell.show()                       # 창이 숨은 채로는 배치를 읽을 수 없다(다른 모듈 뒤에 실행될 때의 순서 의존, D-220)
        sp.resize(900, 1100)
        sp.show()
        TC._app.processEvents()
        head, combo, note = sp.stt_head, sp.stt_language, sp.stt_note
        self.assertEqual(head.height(), 18)
        self.assertEqual(combo.geometry().top() - head.geometry().bottom() - 1, 8)
        self.assertEqual(note.geometry().top() - combo.geometry().bottom() - 1, 6)


def tearDownModule():          # 부모 없는 위젯(카드 · 폼)을 인터프리터 종료 전에 지운다(종료 때의 비정상 종료 방지)
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
