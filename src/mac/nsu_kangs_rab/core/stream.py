"""`claude -p --output-format stream-json` 의 줄을 사건으로 바꾼다 (B-05, K-03).

알 수 없는 줄 · 종류는 사건을 내지 않는다(빈 목록). 예외를 던지지 않는다.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .types import Compacted, Compacting, ControlResponse, Init, Result, TextDelta

_RATE = ("rate limit", "rate_limit", "usage limit", "limit reached", "quota", "too many requests", "overloaded")
_AUTH = ("not logged in", "/login", "please run /login", "invalid api key", "authentication", "unauthorized",
         "oauth", "credit balance", "api key")
# 숫자 상태 코드는 단어 경계로 맞춘다(`req_…4291…` · `…401abc` 같은 식별자를 오분류하지 않는다)
_RATE_NUM = re.compile(r"(?<![0-9A-Za-z_])429(?![0-9A-Za-z_])")
_AUTH_NUM = re.compile(r"(?<![0-9A-Za-z_])401(?![0-9A-Za-z_])")
_NET = ("network", "econn", "enotfound", "etimedout", "unable to connect", "fetch failed", "connection",
        "timed out", "timeout", "dns", "socket")


def classify_text(text: Optional[str]) -> Optional[str]:
    """오류 문구에서 종류를 추정한다(문서에 없는 문구는 분류하지 못하고 None). 한도 · 인증 · 네트워크 순."""
    if not text:
        return None
    low = text.lower()
    for kind, words, num in (("rate_limit", _RATE, _RATE_NUM), ("auth", _AUTH, _AUTH_NUM), ("network", _NET, None)):
        if any(w in low for w in words) or (num is not None and num.search(low)):
            return kind
    return None


def parse_line(line: str) -> list:
    try:
        o = json.loads(line)
    except (ValueError, TypeError):
        return []
    if not isinstance(o, dict):
        return []
    t, sub = o.get("type"), o.get("subtype")
    if t == "system":
        if sub == "init":
            return [Init(o.get("model"), o.get("apiKeySource"), o.get("claude_code_version"))]
        if sub == "status" and o.get("status") == "compacting":
            return [Compacting()]
        if sub == "compact_boundary":
            m = o.get("compact_metadata") or {}
            return [Compacted(m.get("trigger"), m.get("pre_tokens"), m.get("post_tokens"))]
        return []
    if t == "stream_event":
        ev = o.get("event") or {}
        if ev.get("type") == "content_block_delta":
            d = ev.get("delta") or {}
            if d.get("type") == "text_delta" and isinstance(d.get("text"), str):
                return [TextDelta(d["text"])]
        return []
    if t == "result":
        ok = not o.get("is_error") and o.get("subtype") in (None, "success")
        text = o.get("result") if isinstance(o.get("result"), str) else ""
        kind = None if ok else classify_text(text)
        return [Result(ok, o.get("usage") or {}, o.get("stop_reason"), o.get("terminal_reason"), text, kind,
                       o.get("num_turns") if isinstance(o.get("num_turns"), int) else None)]
    if t == "control_response":
        r = o.get("response") or {}
        return [ControlResponse(r.get("request_id"), r.get("subtype") == "success")]
    return []
