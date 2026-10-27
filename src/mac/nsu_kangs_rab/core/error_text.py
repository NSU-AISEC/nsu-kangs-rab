"""오류 카드의 사유 · 조치 문구 (기능 정의 FR-9 "오류 카드의 사유와 조치" 표, AC-FR9-21).

Qt 를 가져오지 않는다. 종류는 `types.ERROR_KINDS` 의 닫힌 집합이다. 어느 문구에도 API 키 값 · 요청 본문을 넣지 않는다.
"""
from __future__ import annotations
from .i18n import t as _t

from typing import Optional

ERROR_TEXT = {
    "auth": (_t("err.error_text"),
             _t("err.error_text_2")),
    "no_claude": (_t("err.error_text_3"), _t("err.error_text_4")),
    "rate_limit": (_t("err.error_text_5"), _t("err.error_text_6")),
    "network": (_t("err.error_text_7"), _t("err.error_text_8")),
    "process_exit": (_t("err.error_text_9"),
                     _t("err.error_text_10")),
    "stt_fail": (_t("err.error_text_11"),
                 _t("err.error_text_12")),
    "audio_lost": (_t("ctl.on_audio_state_253"), _t("err.error_text_13")),
    "audio_start_failed": (_t("state.start_failed_prefix"),
                           _t("err.error_text_14")),
    "permission": (_t("err.error_text_15"),
                   _t("err.error_text_16")),
    "io": (_t("err.error_text_17"),
           _t("err.error_text_18")),
}


# `process_exit` 카드의 상세가 정확히 이 값이면 다시 시작이 실패한 경우이며 사유 줄이 이 문구가 된다(FR-9 표, D-109).
RESTART_FAILED = _t("err.restart_failed")


def reason_text(kind: str) -> str:
    return ERROR_TEXT.get(kind, (_t("err.reason_text_313"), ""))[0]


def action_text(kind: str) -> str:
    return ERROR_TEXT.get(kind, ("", _t("err.action_text_314")))[1]


def card_text(kind: str, detail: Optional[str] = None, guided: bool = False) -> str:
    """오류 카드의 표시 글: 사유, 조치, (처음 [재생] 전의 액자 캡처이면 NEW-45), 그리고 있으면 상세(한 줄). 상세는 앱이 가린 글이며 키 값을 담지 않는다."""
    if kind == "process_exit" and detail == RESTART_FAILED:
        return "\n".join(x for x in (RESTART_FAILED, action_text(kind)) if x)
    lines = [reason_text(kind), action_text(kind)]
    if guided and kind == "permission":
        lines.append(_t("newlang.new45"))          # 결정 0161 5항 · AC-FR12-7: 조치 문구 아래의 한 줄
    if detail:
        lines.append("(%s)" % detail)
    return "\n".join(x for x in lines if x)
