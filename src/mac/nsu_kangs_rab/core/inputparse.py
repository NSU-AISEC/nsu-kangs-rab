"""입력창의 글을 요청으로 해석한다 (FR-7: 슬래시 명령 · 자유 질의, AC-FR7-5 · 앱 명령이 아닌 `/` 문장).

- `/답변` · `/고찰` · `/요약` 은 앱 명령이다. `/고찰` · `/reflect` 는 [고찰] 단추와 같은 요청(종류 트리거, 입력 "")이다(결정 0157 3항). 명령 뒤의 글은 받지 않는다(임의: 명령은 이름만이고, 뒤에 글이 있으면 알 수 없는 명령으로 본다).
- `/` 로 시작하는 그 밖의 문장은 `claude` 에 보내지 않고 "알 수 없는 명령" 을 표시한다.
- 그 밖의 글은 자유 질의이다. 앞뒤 공백만 지운다(본문은 그대로, 사용자가 쓴 글을 바꾸지 않는다).
"""
from __future__ import annotations
from .i18n import t as _t

from dataclasses import dataclass
from typing import Optional

# 영문 별칭은 어느 앱 언어 · 음성 인식 언어에서나 같은 요청이다(결정 0130 5-3항)
COMMANDS = {"/답변": "답변", "/고찰": "트리거", "/요약": "요약", "/answer": "답변", "/reflect": "트리거", "/summary": "요약"}
UNKNOWN_COMMAND_NOTICE = _t("input.unknown_command_notice")


@dataclass(frozen=True)
class Parsed:
    kind: Optional[str]          # 요청 종류. 알 수 없는 명령이면 None
    text: str = ""               # 자유 질의의 글(그 밖의 종류는 빈 문자열)
    command: Optional[str] = None   # 앱 명령이면 그 이름(`/답변` …)
    unknown: bool = False


def parse(raw: str) -> Optional[Parsed]:
    """빈 글이면 None."""
    s = raw.strip()
    if not s:
        return None
    if s.startswith("/"):
        if s in COMMANDS:
            return Parsed(COMMANDS[s], command=s)
        return Parsed(None, unknown=True)
    return Parsed("자유질의", text=s)
