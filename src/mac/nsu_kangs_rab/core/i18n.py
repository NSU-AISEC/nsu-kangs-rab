"""앱 화면 문구 표 (결정 0131, FR-16 "앱 언어", Qt 없음).

- 문구는 `core/strings/ko.py` · `core/strings/en.py` 의 `STRINGS`(키 → 서식 문자열)에 있다. 두 판의 키 집합은 같다(시험이 검사한다).
- 서식은 문구의 원문 형식을 그대로 둔다(`%d` · `%s` · `%02d` · `%.0f`, 이름 있는 `{limit}`). 호출하는 쪽이 `t("키") % 값` 또는
  `t("키").format(limit=값)` 로 채운다(문구 표는 값을 채우지 않는다. 한국어 판의 문자열이 지금 소스와 글자 단위로 같아야 하기 때문이다).
- 앱 언어는 앱을 시작할 때 한 번 정한다. 문구를 모듈 상수에 두는 코드가 있으므로 `init` 은 문구를 쓰는 모듈을 가져오기 전에 호출한다
  (`nsu_kangs_rab.main` 이 설정 파일에서 읽는다). `t` 가 먼저 불리면 그 순간 한국어로 굳고, 이후 다른 언어로 `init` 하면 오류이다.
"""
from __future__ import annotations

import json
import os
from typing import Optional

LANGUAGES = ("ko", "en")
DEFAULT = "ko"

_lang: Optional[str] = None
_table: Optional[dict] = None


def _load(lang: str) -> dict:
    if lang == "en":
        from .strings import en
        return en.STRINGS
    from .strings import ko
    return ko.STRINGS


def normalize(value) -> str:
    """설정의 값을 앱 언어로 읽는다. 없거나 알 수 없는 값이면 한국어이다(AC-FR16-1, 결정 0129 4항)."""
    return value if value in LANGUAGES else DEFAULT


def init(lang) -> str:
    """앱 언어를 정한다. 같은 값으로 다시 부르는 것은 허용하고, 이미 다른 언어로 정해졌으면 `RuntimeError` 이다."""
    global _lang, _table
    lang = normalize(lang)
    if _lang is not None and _lang != lang:
        raise RuntimeError("앱 언어가 이미 %s 로 정해졌다(%s 로 바꿀 수 없다)" % (_lang, lang))
    if _lang is None:
        _lang, _table = lang, _load(lang)
    return _lang


def language() -> str:
    """지금 쓰는 앱 언어. 아직 정해지지 않았으면 한국어로 정한다."""
    if _lang is None:
        init(DEFAULT)
    return _lang  # type: ignore[return-value]


def t(key: str) -> str:
    """키의 문구(서식 문자열). 없는 키는 `KeyError` 이다(조용히 다른 언어로 대신하지 않는다)."""
    if _table is None:
        init(DEFAULT)
    return _table[key]  # type: ignore[index]


def t_for(lang, key: str) -> str:
    """지정한 언어의 문구(앱 언어와 따로 정한 언어로 쓰는 글에 쓴다: 전사 문서는 음성 인식 언어를 따른다, NEW-4)."""
    return _load(normalize(lang))[key]


def tn(key: str, n: int) -> str:
    """수량 문구: `n == 1` 이고 `<키>.one` 이 있으면 그 문구, 아니면 `<키>`."""
    if n == 1:
        one = key + ".one"
        if _table is None:
            init(DEFAULT)
        if one in _table:  # type: ignore[operator]
            return _table[one]  # type: ignore[index]
    return t(key)


def lang_of_settings_file(path) -> str:
    """설정 파일의 `app_language` 만 가볍게 읽는다(앱 시작 때 문구를 쓰는 모듈을 가져오기 전). 읽지 못하면 한국어."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return normalize(data.get("app_language")) if isinstance(data, dict) else DEFAULT
    except (OSError, ValueError):
        return DEFAULT


def init_from_argv(argv) -> str:
    """진입점용: `--dev-config-dir` 가 있으면 그 폴더, 없으면 기본 설정 폴더의 `settings.json` 에서 읽어 `init` 한다."""
    cfg = None
    for i, a in enumerate(argv):
        if a == "--dev-config-dir" and i + 1 < len(argv):
            cfg = argv[i + 1]
        elif a.startswith("--dev-config-dir="):
            cfg = a.split("=", 1)[1]
    if cfg is None:
        cfg = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "ProfKangRAB")
    return init(lang_of_settings_file(os.path.join(cfg, "settings.json")))
