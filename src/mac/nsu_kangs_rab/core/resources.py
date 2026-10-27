"""앱 자원의 글: 앱 규칙 블록과 기본 세션 프롬프트 (`docs/plan/prompt-spec.md` 2 · 3절의 복사본).

원본은 prompt-spec 이고 `resources/*.txt` 는 `tools/sync_prompt_resources.py` 로 갱신한 복사본이다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

_DIR = Path(__file__).with_name("resources")


def _read(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


LANGUAGE_PLACEHOLDER = "{앱이 세션의 음성 인식 언어에 따라 아래 두 판 중 하나를 넣는다}"


def language_block(language: str) -> str:
    """`[언어]` 블록의 본문(prompt-spec 2절). 한국어는 문어체 규칙이 있는 판이고, 그 밖의 언어는 영어 이름을 넣은 판이다."""
    from . import languages
    code = languages.normalize_stt(language)
    if code == "ko":
        return _read("language_ko.txt")
    return _read("language_other.txt").replace("{language}", languages.english_name(code))


def app_rules(language: Optional[str] = None) -> str:
    """앱 규칙 블록. `language`(세션의 음성 인식 언어 코드)를 주면 끝의 `[언어]` 블록을 채운다. 주지 않으면 원본 그대로이다."""
    text = _read("app_rules.txt")
    if language is None:
        return text
    assert text.count(LANGUAGE_PLACEHOLDER) == 1
    return text.replace(LANGUAGE_PLACEHOLDER, language_block(language))


def default_session_prompt(app_language: Optional[str] = None) -> str:
    """기본 세션 프롬프트. 앱 언어의 판을 쓴다(FR-16, 결정 0133)."""
    from . import i18n
    lang = app_language or i18n.language()
    return _read("default_session_prompt_en.txt" if lang == "en" else "default_session_prompt.txt")


def _template(base: str, app_language: Optional[str]) -> str:
    """정리 문서 틀. 앱 언어가 영어이고 영어 판 자원이 있으면 그것을, 아니면 한국어 판을 쓴다(영어 판 문구는 design 의 prompt-spec 8-1 · 8-2)."""
    from . import i18n
    lang = app_language or i18n.language()
    if lang == "en":
        try:
            return _read(base + "_en.txt")
        except OSError:
            pass
    return _read(base + ".txt")


def lecture_template(app_language: Optional[str] = None) -> str:
    return _template("lecture_template", app_language)


def meeting_template(app_language: Optional[str] = None) -> str:
    return _template("meeting_template", app_language)


def diagram_plugin_dir():
    """앱에 포함한 diagram-design 사본의 경로(결정 0048). 개발 트리는 저장소의 `third_party/diagram-design` 이다.
    포장한 앱의 위치는 K-17 에서 정한다(패키지 옆의 `third_party` 를 먼저 찾는다)."""
    import sys
    from pathlib import Path
    here = Path(__file__).resolve()
    frozen = Path(sys._MEIPASS) if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None) else None
    for base in ((frozen,) if frozen is not None else ()) + (here.parents[1], here.parents[4] if len(here.parents) > 4 else here.parents[-1]):
        c = base / "third_party" / "diagram-design"
        if c.is_dir():
            return c
    return here.parents[1] / "third_party" / "diagram-design"


def bundled_helper_path():
    """묶은 앱에 미리 빌드해 넣은 시스템 사운드 보조 프로그램의 경로(결정 0065 3항). 묶은 앱이 아니면 None 이다.
    PyInstaller 의 `--add-binary <실행 파일>:helper` 로 넣으면 `sys._MEIPASS/helper/sck_audio` 에 놓인다."""
    import sys
    base = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    if not base:
        return None
    return Path(base) / "helper" / "sck_audio"


def bundled_stt_helper_path():
    """묶은 앱에 미리 빌드해 넣은 음성 인식 보조 프로그램(`stt_speech`)의 경로(결정 0162). 묶은 앱이 아니면 None 이다.
    PyInstaller 의 `--add-binary <실행 파일>:helper` 로 넣으면 `sys._MEIPASS/helper/stt_speech` 에 놓인다."""
    import sys
    base = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    if not base:
        return None
    return Path(base) / "helper" / "stt_speech"


def about_image_path() -> Path:
    """앱 정보 창의 이미지(결정 0043 3 · 5항). 해시 기록은 `resources/ASSETS.json` 이다."""
    return _DIR / "about_image.png"


def menubar_icon_path(state: str, px: int) -> Path:
    """메뉴 막대 상태 아이콘(결정 0085, 시각 설계 7-13). `state` 는 none · session · warn, `px` 는 18(@1x) 또는 36(@2x)."""
    if state not in ("none", "session", "warn") or px not in (18, 36):
        raise ValueError("메뉴 막대 아이콘이 없다: %r %r" % (state, px))
    return _DIR / "menubar" / ("face_%s_%d.png" % (state, px))


def app_icon_source_path() -> Path:
    """앱 아이콘의 원본 1024px 그림(결정 0043 4 · 5항, 후보 b_hair)."""
    return _DIR / "app_icon_source.png"
