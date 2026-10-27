"""음성 인식 언어 9개와 앱 언어 2개의 목록 (FR-16, 결정 0130 · 0133 · 0163 · 0167). Qt 없음.

원본은 기능 정의 FR-16 의 표(코드 · 자기 이름 · 한국어 이름 · English name)이다. 값이 없거나 목록에 없는 언어는 `ko` 로 읽는다.
"""
from __future__ import annotations

from typing import List, Tuple

DEFAULT = "ko"
APP_LANGUAGES = (("ko", "한국어"), ("en", "English"))      # (코드, 자기 이름, 한국어 이름, English name, 로캘) — FR-16 의 표(결정 0163 · 0167 5항: 아홉 언어, 언어 하나에 로캘 하나)
_TABLE = (
    ("ko", "한국어", "한국어", "Korean", "ko_KR"), ("en", "English", "영어", "English", "en_US"),
    ("ja", "日本語", "일본어", "Japanese", "ja_JP"), ("zh", "中文", "중국어(만다린)", "Chinese (Mandarin)", "zh_CN"),
    ("de", "Deutsch", "독일어", "German", "de_DE"), ("fr", "Français", "프랑스어", "French", "fr_FR"),
    ("es", "Español", "스페인어", "Spanish", "es_ES"), ("it", "Italiano", "이탈리아어", "Italian", "it_IT"),
    ("pt", "Português", "포르투갈어", "Portuguese", "pt_BR"),
)
# 지원을 중단한 14개 코드의 이름(NEW-59L). 저장된 값을 한국어로 바꾼 안내에만 쓴다.
_RETIRED = {
    "ca": ("카탈루냐어", "Catalan"), "ru": ("러시아어", "Russian"), "pl": ("폴란드어", "Polish"), "nl": ("네덜란드어", "Dutch"),
    "id": ("인도네시아어", "Indonesian"), "uk": ("우크라이나어", "Ukrainian"), "tr": ("튀르키예어", "Turkish"),
    "ms": ("말레이어", "Malay"), "fi": ("핀란드어", "Finnish"), "no": ("노르웨이어", "Norwegian"), "sv": ("스웨덴어", "Swedish"),
    "ro": ("루마니아어", "Romanian"), "vi": ("베트남어", "Vietnamese"), "sk": ("슬로바키아어", "Slovak"),
}
CODES = tuple(r[0] for r in _TABLE)
_BY_CODE = {r[0]: r for r in _TABLE}


def normalize_stt(value) -> str:
    """설정 값 → 음성 인식 언어 코드. 없거나 목록 밖이면 `ko`."""
    return value if isinstance(value, str) and value in _BY_CODE else DEFAULT


def locale(code: str) -> str:
    """언어 코드의 로캘(`SpeechTranscriber` 에 할당하는 값)."""
    return _BY_CODE[normalize_stt(code)][4]


def is_saved_value_valid(value) -> bool:
    """저장된 음성 인식 언어가 표의 코드인가."""
    return isinstance(value, str) and value in _BY_CODE


def retired_name(value, app_lang: str):
    """지원을 중단한 코드의 이름(앱 언어의 판). 그 코드가 아니면 None."""
    r = _RETIRED.get(value) if isinstance(value, str) else None
    return None if r is None else (r[1] if app_lang == "en" else r[0])


def normalize_app(value) -> str:
    return value if value in ("ko", "en") else DEFAULT


def self_name(code: str) -> str:
    return _BY_CODE[normalize_stt(code)][1]


def english_name(code: str) -> str:
    """모델에 주는 `[언어]` 블록의 언어 이름(영어 이름)."""
    return _BY_CODE[normalize_stt(code)][3]


def app_name(code: str, app_lang: str) -> str:
    """앱 언어의 이름: 앱 언어가 한국어이면 한국어 이름, English 이면 English name."""
    r = _BY_CODE[normalize_stt(code)]
    return r[3] if app_lang == "en" else r[2]


def display_text(code: str, app_lang: str) -> str:
    """"자기 이름 · 앱 언어의 이름". 두 이름이 같으면 한 번만 쓴다."""
    own, other = self_name(code), app_name(code, app_lang)
    return own if own == other else "%s · %s" % (own, other)


def sorted_codes(app_lang: str) -> List[str]:
    """앱 언어의 이름 순서(한국어 가나다 · English 알파벳, 대소문자 무시)."""
    return sorted(CODES, key=lambda c: app_name(c, app_lang).casefold())


def items(app_lang: str) -> List[Tuple[str, str]]:
    """드롭다운 항목 [(코드, 표시 문구)]."""
    return [(c, display_text(c, app_lang)) for c in sorted_codes(app_lang)]
