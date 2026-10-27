"""단계 8 (FR-16 언어 선택): 문구 표 · 언어 목록 · 설정의 언어 절 · 음성 인식 언어의 전달 · 영문 별칭.
영어 화면은 문구를 모듈을 가져올 때 정하므로 별도 프로세스에서 확인한다(`test_stage8_english.py`)."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_app_controller as TC  # noqa: E402
from nsu_kangs_rab.app import screens  # noqa: E402
from nsu_kangs_rab.core import inputparse, languages, resources  # noqa: E402
from nsu_kangs_rab.core.strings import en, ko  # noqa: E402

_PLACE = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[sdfgx%]|\{[^{}]*\}")
_HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")


class StringTableTest(unittest.TestCase):
    def test_key_sets_equal(self):
        self.assertEqual(set(ko.STRINGS), set(en.STRINGS))

    def test_placeholders_equal(self):
        bad = [k for k in ko.STRINGS if sorted(_PLACE.findall(ko.STRINGS[k])) != sorted(_PLACE.findall(en.STRINGS[k]))]
        self.assertEqual(bad, [])

    def test_english_has_no_hangul_except_korean_self_name(self):
        bad = [k for k, v in en.STRINGS.items() if _HANGUL.search(v.replace("한국어", ""))]
        self.assertEqual(bad, [])

    def test_singular_keys_have_base_key(self):
        for table in (ko.STRINGS, en.STRINGS):
            for k in table:
                if k.endswith(".one"):
                    self.assertIn(k[:-4], table)

    def test_core_has_no_qt_import(self):
        bad = []
        for p in (ROOT / "src" / "mac" / "nsu_kangs_rab" / "core").rglob("*.py"):
            if re.search(r"^\s*(?:from|import)\s+PySide6", p.read_text(encoding="utf-8"), re.M):
                bad.append(p.name)
        self.assertEqual(bad, [])


class LanguagesTest(unittest.TestCase):
    def test_nine_codes_and_locales(self):          # FR-16 · 결정 0167 6항: 아홉 언어, 언어마다 로캘 하나
        self.assertEqual(
            {c: languages.locale(c) for c in languages.CODES},
            {"ko": "ko_KR", "en": "en_US", "ja": "ja_JP", "zh": "zh_CN", "de": "de_DE", "fr": "fr_FR",
             "es": "es_ES", "it": "it_IT", "pt": "pt_BR"})
        self.assertEqual(len(languages.CODES), 9)

    def test_retired_codes_read_as_ko_with_names(self):          # NEW-59 · 59L
        for code in ("ca", "sk", "vi"):
            self.assertEqual(languages.normalize_stt(code), "ko")
            self.assertFalse(languages.is_saved_value_valid(code))
        self.assertEqual(languages.retired_name("sk", "ko"), "슬로바키아어")
        self.assertEqual(languages.retired_name("sk", "en"), "Slovak")
        self.assertIsNone(languages.retired_name("xx", "ko"))
        self.assertIsNone(languages.retired_name(5, "ko"))

    def test_missing_or_unknown_reads_as_ko(self):
        for v in (None, "", "xx", 5, "EN"):
            self.assertEqual(languages.normalize_stt(v), "ko")
            self.assertEqual(languages.normalize_app(v), "ko")
        self.assertEqual(languages.normalize_stt("pt"), "pt")
        self.assertEqual(languages.normalize_app("en"), "en")

    def test_sorted_by_app_language_name(self):
        ko_names = [languages.app_name(c, "ko") for c in languages.sorted_codes("ko")]
        self.assertEqual(ko_names, sorted(ko_names))
        en_names = [languages.app_name(c, "en").casefold() for c in languages.sorted_codes("en")]
        self.assertEqual(en_names, sorted(en_names))

    def test_display_text_self_name_and_app_name(self):
        self.assertEqual(languages.display_text("es", "ko"), "Español · 스페인어")
        self.assertEqual(languages.display_text("ko", "en"), "한국어 · Korean")
        self.assertEqual(languages.display_text("ko", "ko"), "한국어")          # 두 이름이 같으면 한 번만
        self.assertEqual(languages.display_text("en", "en"), "English")

    def test_english_names_for_model_block(self):
        self.assertEqual(languages.english_name("zh"), "Chinese (Mandarin)")


class LabelsTest(unittest.TestCase):
    def test_title_label_maps_only_stored_placeholder(self):
        from nsu_kangs_rab.core import labels
        self.assertEqual(labels.title_label("(이름 없음)"), "(이름 없음)")      # ko 프로세스
        self.assertEqual(labels.title_label("AI 개론"), "AI 개론")
        self.assertEqual(labels.UNTITLED, "(이름 없음)")                          # 저장 값은 바뀌지 않는다
        self.assertEqual(en.STRINGS["newlang.new8"], "(Untitled)")
        self.assertEqual(labels.kind_label("정리문서"), "정리 문서")
        self.assertEqual(labels.kind_label("다이어그램"), "다이어그램")
        self.assertEqual(en.STRINGS["newlang.new9"], "Summary document")
        self.assertEqual(en.STRINGS["newlang.new10"], "Diagram")


class AliasTest(unittest.TestCase):
    def test_english_aliases_are_same_requests(self):
        for alias, kor, kind in (("/answer", "/답변", "답변"), ("/reflect", "/고찰", "트리거"), ("/summary", "/요약", "요약")):
            self.assertEqual(inputparse.parse(alias).kind, kind)
            self.assertEqual(inputparse.parse(kor).kind, kind)
        self.assertTrue(inputparse.parse("/answer 더").unknown)           # 뒤에 글이 있으면 알 수 없는 명령이다
        self.assertTrue(inputparse.parse("/other").unknown)


class ResourcesTest(unittest.TestCase):
    def test_language_block_ko_and_others(self):
        ko_rules = resources.app_rules("ko")
        self.assertIn("한국어 문어체 평서문", ko_rules)
        self.assertNotIn(resources.LANGUAGE_PLACEHOLDER, ko_rules)
        head = resources.app_rules().split("[언어]")[0]
        for code in languages.CODES:
            text = resources.app_rules(code)
            self.assertTrue(text.startswith(head))                       # 2절 블록은 모든 언어에서 같다
            if code != "ko":
                self.assertIn("응답은 %s 로 쓴다" % languages.english_name(code), text)
                self.assertNotIn("문어체 평서문(", text.split("[언어]")[1])

    def test_default_prompt_by_app_language(self):
        self.assertTrue(resources.default_session_prompt("ko").startswith("이 세션은"))
        self.assertTrue(resources.default_session_prompt("en").startswith("This session is"))


    def test_templates_by_app_language(self):
        for fn in (resources.lecture_template, resources.meeting_template):
            en_text, ko_text = fn("en"), fn("ko")
            self.assertIsNone(_HANGUL.search(en_text))
            self.assertIsNotNone(_HANGUL.search(ko_text))
            self.assertNotEqual(en_text, ko_text)
            self.assertEqual(fn(), ko_text)                              # 이 프로세스의 앱 언어는 ko


class SessionLanguageTest(TC.Base):
    def _builder(self):
        """`SttPipeline` 생성에 쓰인 로캘을 모은다. 반환: [(None, 언어 코드)] — 로캘에서 언어 코드를 되돌린다."""
        from nsu_kangs_rab.platform.stt import pipeline as P
        calls = []
        orig = P.SttPipeline
        by_locale = {languages.locale(c): c for c in languages.CODES}

        class Rec(orig):
            def __init__(self, helper, locale="ko_KR", *a, **k):
                calls.append((None, by_locale[locale]))
                super().__init__(helper, locale, *a, **k)
        P.SttPipeline = Rec
        self.addCleanup(setattr, P, "SttPipeline", orig)
        return calls

    def _events(self):
        return [json.loads(x) for x in Path(self.ctl.eventlog.path).read_text(encoding="utf-8").splitlines()]

    def test_default_session_is_ko(self):
        calls = self._builder()
        self.assertTrue(self.start())
        self.assertEqual([c[1] for c in calls], ["ko"])
        ev = [e for e in self._events() if e["type"] == "session_start"][0]
        self.assertEqual((ev["stt_language"], ev["app_language"]), ("ko", "ko"))
        self.assertIn("한국어 문어체 평서문", self.model.kw["prompt_text"])

    def test_language_chosen_on_start_screen_is_saved_at_start_and_external_edit_ignored(self):
        """AC-FR1-29 ③ · AC-FR16-4: 시작 화면에서 고른 값은 [세션 시작] 때 저장하고, 세션 중 설정 파일을 외부에서 바꾸어도 진행 중인 세션의 값은 그대로이다."""
        self._builder()
        self.assertTrue(self.start(stt_language="en"))
        self.assertEqual(self.ctl.data.get("stt_language"), "en")
        saved = json.loads((self.cfg / "settings.json").read_text())
        self.assertEqual(saved.get("stt_language"), "en")
        self.ctl.data["stt_language"] = "de"                             # 외부 편집을 흉내 낸다
        self.assertEqual(self.ctl._session_stt_language(), "en")

    def test_invalid_saved_value_reads_as_ko_and_file_untouched(self):
        (self.cfg / "settings.json").write_text(json.dumps({"first_run_ack": TC.appstate.FIRST_RUN_NOTICE_VERSION, "stt_language": "xx"}))
        self.ctl.data = dict(json.loads((self.cfg / "settings.json").read_text()))
        self.assertEqual(self.ctl._session_stt_language(), "ko")
        saved = json.loads((self.cfg / "settings.json").read_text())
        self.assertEqual(saved["stt_language"], "xx")


def _make_code_test(code):
    def test(self):
        calls = self._builder()
        self.assertTrue(self.start(stt_language=code))
        self.assertEqual([c[1] for c in calls], [code])
        ev = [e for e in self._events() if e["type"] == "session_start"][-1]
        self.assertEqual(ev["stt_language"], code)
        prompt = self.model.kw["prompt_text"]
        if code != "ko":
            self.assertIn("응답은 %s 로 쓴다" % languages.english_name(code), prompt)
    return test


for _code in languages.CODES:
    setattr(SessionLanguageTest, "test_code_" + _code, _make_code_test(_code))


class StartScreenLanguageSectionTest(TC.Base):
    """결정 0179 · 0181: 앱 언어(1) · 음성 인식 언어(7)는 시작 화면에 있고 설정 창에는 없다(AC-FR16-1 · AC-FR16-8)."""
    def _card(self):
        sp = self.ctl.shell.start_page
        return sp, sp.app_language_section

    def test_dropdowns_and_notice(self):
        sp, card = self._card()
        self.assertEqual(card.app_language.count(), 2)
        self.assertEqual(sp.stt_language.count(), 9)
        self.assertEqual({screens.combo_data_at(sp.stt_language, i) for i in range(9)}, set(languages.CODES))
        self.assertEqual(screens.combo_data(card.app_language), "ko")
        self.assertTrue(card.lang_notice.isHidden())
        card.app_language.setCurrentIndex(card.app_language.findData("en", screens.Qt.ItemDataRole.UserRole))
        self.assertFalse(card.lang_notice.isHidden())
        self.assertIn("English", card.lang_notice.text())
        self.assertIn("한국어", card.lang_notice.text())
        self.assertEqual(self.ctl.data.get("app_language"), "en")
        self.assertEqual(sp.stt_language.currentText(), "한국어")          # 두 언어는 독립이다
        card.app_language.setCurrentIndex(card.app_language.findData("ko", screens.Qt.ItemDataRole.UserRole))
        self.assertTrue(card.lang_notice.isHidden())

    def test_settings_window_has_no_language_widgets(self):
        self.ctl.open_settings()
        f = self.ctl._settings_form
        for name in ("app_language", "stt_language", "lang_notice", "provider", "source", "api_key", "claude_edit", "default_prompt"):
            self.assertFalse(hasattr(f, name), name)

    def test_notice_is_warning_line_height_30(self):                  # D-157, 시각 설계 7-12
        _sp, f = self._card()
        f.app_language.setCurrentIndex(f.app_language.findData("en", screens.Qt.ItemDataRole.UserRole))
        f.lang_notice.ensurePolished()
        self.assertGreaterEqual(f.lang_notice.sizeHint().height(), 30)

    def test_notice_background_painted_inside_doc_panel(self):        # D-157: doc_panel QLabel 규칙이 바탕을 덮지 않는다
        _sp, f = self._card()
        f.app_language.setCurrentIndex(f.app_language.findData("en", screens.Qt.ItemDataRole.UserRole))
        f.lang_notice.ensurePolished()
        f.lang_notice.setFixedSize(400, 40)         # 카드의 배치가 크기를 되돌리지 않게 한다
        img = f.lang_notice.grab().toImage()
        self.assertNotEqual(img.pixelColor(3, 20).alpha(), 0)
        self.assertEqual(img.pixelColor(200, 3).name(), img.pixelColor(380, 36).name())
        self.assertNotEqual(img.pixelColor(200, 3).name(), "#ffffff")
        self.assertEqual(img.pixelColor(0, 0).name(), img.pixelColor(200, 3).name())      # 결정 0140 3항: 모서리 둥글림 없음

    def test_elide_label_tooltip_from_constructor(self):              # D-159
        from nsu_kangs_rab.app import mainview
        lab = mainview._ElideLabel("Judgment · Answer")
        self.assertEqual(lab.toolTip(), "Judgment · Answer")


if __name__ == "__main__":
    unittest.main()
