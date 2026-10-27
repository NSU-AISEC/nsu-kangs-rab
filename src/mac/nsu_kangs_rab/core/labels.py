"""내부 값(세션 기록 · 요청 머리에 한국어로 남는 값)을 화면 문구로 바꾼다 (FR-16, 결정 0131).

내부 값은 앱 언어와 관계없이 한국어 그대로이다(기록 · 모델 입력의 형식이므로). 화면에 보일 때만 이 모듈로 문구표를 거친다.
표에 없는 값은 그대로 돌려준다(사용자가 정한 이름 등).
"""
from __future__ import annotations

from .i18n import t

_KIND = {"트리거": "label.kind_trigger", "답변": "label.kind_answer", "고찰": "label.kind_reflection", "요약": "label.kind_summary",
         "자유질의": "label.kind_free_question", "정리문서": "newlang.new9", "다이어그램": "newlang.new10", "화면메모": "label.kind_screen_note", "오류": "label.kind_error"}
_JUDGMENT = {"질문": "label.judgment_question", "질문 없음": "label.judgment_no_question",
             "이미 답이 나온 질문": "label.judgment_answered", "미확인": "label.judgment_unconfirmed"}
_DOC = {"수업": "label.doc_lecture", "회의": "label.doc_meeting"}
_SOURCE = {"캡처": "label.src_capture", "끌어다 놓기": "label.src_drop", "붙여넣기": "label.paste"}
_RESULT = {"완료": "label.result_done", "진행 중": "label.result_running", "실패": "label.result_failed",
           "외부 자원 위반": "label.result_violation", "중단": "label.stopped", "대기 중": "label.state_waiting"}

_CAPTURE = {"수집 중": "label.capture_running", "입력 없음": "label.capture_no_input", "중단": "label.stopped", "장치 변경": "label.device_changed",
            "일시 정지": "pause.new23", "수집 전": "before.new33"}


def _look(table: dict, value):
    key = table.get(value)
    return t(key) if key else value


def kind_label(kind: str) -> str:
    return _look(_KIND, kind)


def judgment_label(j: str) -> str:
    return _look(_JUDGMENT, j)


def doc_kind_label(kind: str) -> str:
    return _look(_DOC, kind)


def source_label(src: str) -> str:
    return _look(_SOURCE, src)


def result_label(r: str) -> str:
    return _look(_RESULT, r)


def capture_label(state: str) -> str:
    return _look(_CAPTURE, state)


UNTITLED = "(이름 없음)"          # 세션 기록 머리 · 요청 머리에 저장하는 내부 값(앱 언어와 관계없다)


def title_label(title: str) -> str:
    """화면에 보이는 과목명(회의명). 비워서 저장된 내부 값만 앱 언어의 문구로 바꾸고 사용자가 정한 이름은 그대로 둔다."""
    return t("newlang.new8") if title == UNTITLED else title
