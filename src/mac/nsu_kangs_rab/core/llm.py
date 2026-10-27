"""`claude -p` 하위 프로세스의 명령줄과 환경을 만드는 순수 함수 (K-01).

- 기준: docs/plan/technical-plan.md 2-4절(llm.py), B-04(환경 허용 목록), A-01 · A-02 · A-28,
  docs/plan/functional-spec.md AC-FR1-13 · AC-FR1-19.
- 이 모듈은 프로세스를 시작하지 않고 파일 · 키체인 · 네트워크에 접근하지 않는다.
- 값(API 키 · 환경 값)은 기록하지 않는다. 오류 메시지에도 값을 넣지 않는다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Optional, Sequence

CROSS_SESSION_REFUSE = {"crossSessionInbound": "refuse"}  # 결정 0033

# B-04: 부모 환경에서 복사해도 되는 이름. 이 밖의 이름은 알 수 없는 것도 복사하지 않는다.
ALLOWED_NAMES = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TZ", "LANG", "LANGUAGE",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
})
ALLOWED_PREFIXES = ("LC_",)

API_KEY_ENV = "ANTHROPIC_API_KEY"


class Auth(Enum):
    SUBSCRIPTION = "subscription"
    API = "api"


class Kind(Enum):
    RESIDENT = "resident"   # 상주 프로세스: 도구를 모두 끈다
    ONESHOT = "oneshot"     # 다이어그램 · 정리 문서: 필요한 도구만 연다


class AuthConfigError(Exception):
    """고른 인증 방식으로 실행할 수 없는 설정. 값은 메시지에 넣지 않는다."""


class CommandConfigError(Exception):
    """명령줄을 만들 수 없는 설정(예: 시스템 프롬프트가 인자 길이 한계를 넘음)."""


@dataclass(frozen=True)
class SessionConfig:
    claude_path: str
    model: str
    effort: Optional[str] = None
    kind: Kind = Kind.RESIDENT
    system_prompt_file: Optional[str] = None   # A-28: 기본 경로
    system_prompt: Optional[str] = None        # A-28: 대체 경로(`--system-prompt-file` 를 받지 않는 판)
    tools: Sequence[str] = ()                  # ONESHOT 만. RESIDENT 는 항상 ""
    plugin_dir: Optional[str] = None           # ONESHOT 만
    settings_extra: Optional[Mapping[str, object]] = None  # 하나의 --settings JSON 에 합친다
    permission_mode: Optional[str] = None      # ONESHOT 만 (예: dontAsk)
    include_partial_messages: bool = True


SYSTEM_PROMPT_ARG_LIMIT = 100_000  # A-28 (M8-G1: 100,000자 통과, 500,000자 `Argument list too long`)


def build_settings_json(extra: Optional[Mapping[str, object]] = None) -> str:
    """`--settings` 로 줄 JSON 하나. `crossSessionInbound` 는 항상 `refuse` 이고 extra 가 덮지 못한다."""
    merged: dict = dict(extra or {})
    merged["crossSessionInbound"] = CROSS_SESSION_REFUSE["crossSessionInbound"]
    return json.dumps(merged, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def build_command(config: SessionConfig) -> list[str]:
    """`claude` 의 인자 목록을 반환한다(첫 원소는 `config.claude_path`).

    구독 로그인을 읽지 못하는 간소화 옵션을 쓰지 않는다(인증 원칙 3항). `--settings` 는 하나뿐이다(AC-FR1-19).
    """
    c = config
    if c.system_prompt_file and c.system_prompt is not None:
        raise CommandConfigError("system_prompt_file 과 system_prompt 는 함께 줄 수 없다")
    cmd = [c.claude_path, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
           "--verbose", "--model", c.model]
    if c.effort:
        cmd += ["--effort", c.effort]
    cmd += ["--setting-sources", "", "--strict-mcp-config"]
    cmd += ["--settings", build_settings_json(c.settings_extra)]
    if c.kind is Kind.RESIDENT:
        cmd += ["--tools", ""]
    else:
        cmd += ["--tools", ",".join(c.tools)]
        if c.permission_mode:
            cmd += ["--permission-mode", c.permission_mode]
        if c.plugin_dir:
            cmd += ["--plugin-dir", c.plugin_dir]
    if c.include_partial_messages:
        cmd += ["--include-partial-messages"]
    cmd += ["--no-session-persistence"]
    if c.system_prompt_file:
        cmd += ["--system-prompt-file", c.system_prompt_file]
    elif c.system_prompt is not None:
        if len(c.system_prompt) > SYSTEM_PROMPT_ARG_LIMIT:
            raise CommandConfigError("시스템 프롬프트가 인자 길이 한계(%d자)를 넘는다" % SYSTEM_PROMPT_ARG_LIMIT)
        cmd += ["--system-prompt", c.system_prompt]
    return cmd


def _allowed(name: str) -> bool:
    return name in ALLOWED_NAMES or name.startswith(ALLOWED_PREFIXES)


# 결정 0055: 앱이 넣는 원격 측정 · 오류 보고 거부 변수. `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` 은 넣지 않는다.
TELEMETRY_OFF = {"DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1"}


def clean_env(env: Mapping[str, str], auth: Auth, api_key: Optional[str] = None) -> dict[str, str]:
    """하위 프로세스의 환경을 반환한다 (B-04 허용 목록 방식).

    비어 있는 사전에서 시작해 허용한 이름만 `env` 에서 복사한다. API 이면 `api_key` 를
    `ANTHROPIC_API_KEY` 로 더하고, 구독이면 `api_key` 를 받아도 넣지 않는다.
    API 인데 키가 `None` 또는 빈 문자열이면 `AuthConfigError`(조용히 구독으로 실행하지 않는다).
    `env` 는 바꾸지 않는다.
    """
    if auth is Auth.API and not api_key:
        raise AuthConfigError("API 방식을 골랐으나 보관한 키가 없다")
    out = {k: v for k, v in env.items() if _allowed(k)}
    out.update(TELEMETRY_OFF)  # 결정 0055: 사용자 값과 관계없이 항상 넣는다
    if auth is Auth.API:
        out[API_KEY_ENV] = api_key  # type: ignore[assignment]
    return out
