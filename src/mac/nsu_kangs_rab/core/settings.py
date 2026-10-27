"""설정 파일의 읽기 · 병합 · 정리 · 쓰기 (K-02, B-01 · B-02 · A-08 · A-32).

- 읽기는 예외를 던지지 않는다(docs/plan/technical-plan.md 2-2절 3항). 깨진 파일 · 깨진 표는 `Notice` 로 알린다.
- 이 모듈은 키체인 · 네트워크 · 하위 프로세스를 쓰지 않는다. 설정에 API 키를 두지 않는다(AC-FR1-17).
"""
from __future__ import annotations
from .i18n import t as _t

import copy
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

ACTIVE_PROVIDERS = ("claude_subscription", "claude_api")  # AC-FR1-11 · AC-FR1-15
DEFAULT_PROVIDER = "claude_subscription"
DEFAULT_FAMILY = "sonnet"            # AC-FR1-20
EXCLUDED_EFFORTS = frozenset({"low", "max"})  # B-02 · AC-FR1-7

SOURCE_APP_DEFAULT = "app_default"
SOURCE_SETTINGS_DEFAULT = "settings_default"
SOURCE_SESSION_INPUT = "session_input"

DEFAULTS_PATH = Path(__file__).with_name("default_settings.json")


@dataclass(frozen=True)
class Notice:
    """사용자에게 알려야 하는 사실. `detail` 에 설정 값(키 등)을 넣지 않는다."""
    kind: str      # settings_unreadable | table_broken | provider_inactive | model_unknown | effort_reset
    detail: str


@dataclass
class LoadResult:
    data: dict
    notices: list = field(default_factory=list)
    file_found: bool = False


@dataclass(frozen=True)
class EffortTable:
    options: tuple          # `low` · `max` 를 뺀 단계(표의 순서)
    default: Optional[str]  # options 가 비면 None
    broken: Optional[str] = None  # 표가 깨졌으면 사유


@dataclass(frozen=True)
class Selection:
    provider: str
    family: str
    effort: Optional[str]   # None 이면 effort 를 고르는 입력을 숨기고 `claude` 에 전달하지 않는다(AC-FR1-9)
    efforts: tuple
    notices: tuple


def default_config_dir(home: Optional[str] = None) -> Path:
    """B-01: ~/Library/Application Support/ProfKangRAB"""
    return Path(home or os.path.expanduser("~")) / "Library" / "Application Support" / "ProfKangRAB"


def settings_path(config_dir) -> Path:
    return Path(config_dir) / "settings.json"


def load_defaults() -> dict:
    with open(DEFAULTS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _merge(base: Any, over: Any) -> Any:
    """사전은 키별로 병합하고 그 밖(목록 · 값)은 `over` 가 바꾼다. 입력을 바꾸지 않는다."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = {k: copy.deepcopy(v) for k, v in base.items()}
        for k, v in over.items():
            out[k] = _merge(base[k], v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(over)


def load_settings(path, defaults: Optional[Mapping] = None) -> LoadResult:
    """기본값과 사용자 파일을 병합해 반환한다. 파일이 없으면 기본값이다(AC-FR1-20). 예외를 던지지 않는다."""
    base = copy.deepcopy(dict(defaults)) if defaults is not None else load_defaults()
    notices: list = []
    found = False
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        found = True
        user = json.loads(raw)
        if not isinstance(user, dict):
            raise ValueError("최상위가 사전이 아니다")
    except FileNotFoundError:
        return LoadResult(base, notices, False)
    except (OSError, ValueError) as e:  # json.JSONDecodeError 는 ValueError 이다
        notices.append(Notice("settings_unreadable", _t("settings.load_settings_385") % type(e).__name__))
        return LoadResult(base, notices, found)
    return LoadResult(_merge(base, user), notices, True)


def save_settings(path, data: Mapping) -> tuple:
    """임시 파일 뒤 이름 변경으로 쓴다(B-01). 반환: (성공, 사유). 예외를 던지지 않는다."""
    p = Path(path)
    tmp = None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=str(p.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        return True, ""
    except (OSError, TypeError, ValueError) as e:  # 직렬화할 수 없는 값(D-027)도 예외로 내지 않는다
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False, type(e).__name__


def update_settings(path, changes: Mapping) -> tuple:
    """사용자 파일에 원래 있던 키와 `changes`(사용자가 바꾼 값)만 쓴다. 기본값 전체를 쓰지 않는다(master 기술 기본값).

    이후 판의 기본값(예: effort 표)이 바뀌면 사용자가 바꾸지 않은 항목에 반영되게 하려는 것이다.
    병합은 사전 단위(중첩 사전은 키별)이며 목록 · 스칼라는 `changes` 의 값이 대체한다. 반환: (성공, 사유).
    사용자 파일이 없으면 `changes` 만 쓰고, 읽지 못하는 파일(깨짐)은 덮어쓰지 않고 실패로 반환한다.
    """
    existing: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, dict):
            return False, "NotADict"
        existing = loaded
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        return False, type(e).__name__
    return save_settings(path, _deep_update(existing, changes))


def _deep_update(base: Mapping, changes: Mapping) -> dict:
    out = copy.deepcopy(dict(base))
    for k, v in changes.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _deep_update(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def with_overrides(data: Mapping, **values) -> dict:
    """이 실행 동안만 쓰는 값(개발 옵션 `--dev-save-dir` 등). 저장하지 않는 사본을 반환한다."""
    out = copy.deepcopy(dict(data))
    out.update(values)
    return out


def effort_table(data: Mapping, provider: str, family: str) -> EffortTable:
    """B-02: `providers.<id>.families.<계열>` 의 `efforts` · `default`. `low` · `max` 는 읽을 때 뺀다."""
    try:
        fam = data["providers"][provider]["families"][family]
    except (KeyError, TypeError):
        return EffortTable((), None, _t("settings.effort_table_386"))
    if not isinstance(fam, dict):
        return EffortTable((), None, _t("settings.effort_table_387"))
    efforts = fam.get("efforts", [])
    if not isinstance(efforts, list) or not all(isinstance(e, str) for e in efforts):
        return EffortTable((), None, _t("settings.effort_table_388"))
    seen: list = []
    for e in efforts:
        if e not in EXCLUDED_EFFORTS and e not in seen:
            seen.append(e)
    if not seen:
        return EffortTable((), None, None)  # 단계가 없는 계열과 같다(AC-FR1-9)
    d = fam.get("default")
    default = d if isinstance(d, str) and d in seen else seen[0]
    return EffortTable(tuple(seen), default, None)


def families(data: Mapping, provider: str) -> tuple:
    try:
        fams = data["providers"][provider]["families"]
        return tuple(k for k in fams if isinstance(k, str)) if isinstance(fams, dict) else ()
    except (KeyError, TypeError):
        return ()


def resolve_selection(data: Mapping) -> Selection:
    """기억한 제공자 · 모델 · effort 를 표에 맞춰 정리한다(AC-FR1-5 · 9 · 15 · 20)."""
    notices: list = []
    provider = data.get("provider")
    if provider not in ACTIVE_PROVIDERS:
        notices.append(Notice("provider_inactive", _t("settings.resolve_selection_389")))
        provider = DEFAULT_PROVIDER
    fams = families(data, provider)
    family = data.get("model")
    if family not in fams:
        if family is not None and fams:
            notices.append(Notice("model_unknown", _t("settings.resolve_selection_390")))
        family = DEFAULT_FAMILY if DEFAULT_FAMILY in fams or not fams else fams[0]
    tbl = effort_table(data, provider, family)
    if tbl.broken:
        notices.append(Notice("table_broken", _t("settings.resolve_selection_391") % tbl.broken))
    remembered = data.get("effort")
    effort: Optional[str] = None
    if tbl.options:
        if remembered in tbl.options:
            effort = remembered
        else:
            effort = tbl.default
            if remembered is not None:
                notices.append(Notice("effort_reset", _t("settings.resolve_selection_392")))
    return Selection(provider, family, effort, tbl.options, tuple(notices))


def resolve_session_prompt(data: Mapping, session_input: Optional[str], app_default: str) -> tuple:
    """AC-FR2-5: (출처, 본문). 설정의 기본 문구(비었으면 앱 자원의 기본 문구)를 기준으로 한다.
    세션 입력이 비었거나 공백 · 줄바꿈만이면 기준을 쓴다. 세션 입력이 기준과 줄바꿈 통일(\\r\\n · \\r → \\n) 뒤 글자까지 같으면
    기준의 출처와 본문을 쓴다(결정 0120: 칸에 기본 문구가 미리 들어 있으므로 고치지 않은 입력은 기본 문구이다).
    다르면 세션 입력이다."""
    d = data.get("default_session_prompt")
    if isinstance(d, str) and d.strip():
        base_src, base = SOURCE_SETTINGS_DEFAULT, d
    else:
        base_src, base = SOURCE_APP_DEFAULT, app_default
    if session_input is None or not session_input.strip():
        return base_src, base
    if _unify_newlines(session_input) == _unify_newlines(base):
        return base_src, base
    return SOURCE_SESSION_INPUT, session_input


def _unify_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
