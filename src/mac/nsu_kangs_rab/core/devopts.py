"""개발 옵션(`--dev-*`)의 파서 (K-02, docs/plan/technical-plan.md 5절 · B-22).

- 제품 화면에는 없다. 알 수 없는 `--dev-` 옵션과 잘못된 값은 적용하지 않고 `errors` 에 남긴다(앱을 종료하지 않는다).
- 이벤트 로그에는 `names`(적용한 옵션의 이름)만 남긴다. 값은 남기지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

PREFIX = "--dev-"


def _pos_int(s: str) -> int:
    v = int(s)
    if v < 1:
        raise ValueError
    return v


def _nonneg_int(s: str) -> int:
    v = int(s)
    if v < 0:
        raise ValueError
    return v


def _pos_float(s: str) -> float:
    v = float(s)
    if not v > 0:
        raise ValueError
    return v


def _int_list(s: str) -> tuple:
    out = tuple(_pos_int(x) for x in s.split(","))
    if not out:
        raise ValueError
    return out


def _choice(*names: str) -> Callable[[str], str]:
    def f(s: str) -> str:
        if s not in names:
            raise ValueError
        return s
    return f


def _text(s: str) -> str:
    if not s:
        raise ValueError
    return s


# 옵션 이름 → (결과 키, 값 변환). 5절 표의 옵션과 같다.
OPTIONS: dict = {
    "--dev-audio-file": ("audio_file", _text),
    "--dev-speed": ("speed", _pos_float),
    "--dev-replay": ("replay", _text),
    "--dev-save-dir": ("save_dir", _text),
    "--dev-appearance": ("appearance", _choice("light", "dark")),
    "--dev-hidden-cap-s": ("hidden_cap_s", _pos_float),
    "--dev-diagram-timeout-s": ("diagram_timeout_s", _pos_float),
    "--dev-char-cap": ("char_cap", _pos_int),
    "--dev-image-cap": ("image_cap", _pos_int),
    "--dev-file-size-cap-bytes": ("file_size_cap_bytes", _pos_int),
    "--dev-image-bytes-cap": ("image_bytes_cap", _pos_int),
    "--dev-request-image-bytes-cap": ("request_image_bytes_cap", _pos_int),
    "--dev-registered-image-bytes-cap": ("registered_image_bytes_cap", _pos_int),
    "--dev-stt-helper": ("stt_helper", _text),                            # 5-1절 가짜 음성 인식 보조 프로세스: 앱이 시작하는 `stt_speech` 를 이 실행 파일로 바꾼다(같은 인자)
    "--dev-stt-helper-scenario": ("stt_helper_scenario", _text),          # 가짜에 `--scenario <JSON 파일>` 을 덧붙인다
    "--dev-final-wait-cap-s": ("final_wait_cap_s", _pos_float),
    "--dev-clock-file": ("clock_file", _text),                            # 5-1절 세션 시계 주입: 화면 시계의 시각 원천을 이 파일(실수 한 줄, 단조 시계 초)로 바꾼다
    "--dev-control": ("control", _text),
    "--dev-key-account": ("key_account", _text),
    "--dev-config-dir": ("config_dir", _text),
    "--dev-frame-method-missing": ("frame_method_missing", _choice("on")),    # 5-1절 "액자 비활성화 메서드 없음 가장": 메서드가 없는 macOS 의 동작으로 액자를 움직인다(AC-FR12-20 ⓕ)
    "--dev-claude-search": ("claude_search", _choice("none")),    # 5-1절 "claude 자동 찾기 대상 비움": PATH · 로그인 셸 · 알려진 위치를 모두 비워 자동으로는 찾지 못하게 한다(AC-FR1-28 ④ ⑤, 설정 값은 그대로 쓴다)
    "--dev-capture-fake": ("capture_fake", _text),      # 액자 캡처의 `screencapture` 대신 이 PNG 를 출력 경로에 쓰고 명령을 `<PNG>.commands.jsonl` 에 기록한다(C1)
}


@dataclass
class DevOptions:
    values: dict = field(default_factory=dict)   # 결과 키 → 변환한 값
    names: list = field(default_factory=list)    # 적용한 옵션 이름(입력 순서, 중복 없음). 이벤트 로그의 `dev_options`
    errors: list = field(default_factory=list)   # (옵션 이름, 사유). 값은 담지 않는다
    rest: list = field(default_factory=list)     # 개발 옵션이 아닌 인자(순서 유지)

    def get(self, key: str, default=None):
        return self.values.get(key, default)


def parse(argv: Sequence[str]) -> DevOptions:
    """`argv`(프로그램 이름을 뺀 인자 목록)에서 개발 옵션을 읽는다. 입력을 바꾸지 않는다. `--opt=값` 도 받는다."""
    out = DevOptions()
    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if not a.startswith(PREFIX):
            out.rest.append(a)
            continue
        name, eq, inline = a.partition("=")
        spec = OPTIONS.get(name)
        if spec is None:
            out.errors.append((name, "알 수 없는 개발 옵션"))
            continue
        if eq:
            raw: Optional[str] = inline
        elif i < len(args) and not args[i].startswith(PREFIX):
            raw = args[i]
            i += 1
        else:
            raw = None
        if raw is None:
            out.errors.append((name, "값이 없다"))
            continue
        key, conv = spec
        try:
            value = conv(raw)
        except (ValueError, TypeError):
            out.errors.append((name, "값이 올바르지 않다"))
            continue
        out.values[key] = value
        if name not in out.names:
            out.names.append(name)
    return out
