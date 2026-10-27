"""앱의 상태 기계와 상태별 활성 항목, 화면 밝기 선택, 상태 표시줄 문구 (K-11; FR-14 · FR-15 · FR-11 · FR-1).

Qt 를 가져오지 않는다. 화면(`app`)은 이 모듈이 계산한 값을 그대로 표시한다.

상태(FR-14 "세션 상태별 활성"): ① 첫 실행 고지(동의 전) ② 세션 시작 전 ③ 세션 중 ④ 종료 처리 중.
세션 종료는 앱 종료이므로 ④ 뒤에는 종료(`DONE`)만 있다(FR-11, 세션 시작 화면으로 돌아가지 않는다 AC-FR11-5).
"""
from __future__ import annotations
from .i18n import t as _t
from . import labels as _labels

import enum
import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Optional


class State(enum.Enum):
    FIRST_RUN = "first_run"          # ① 첫 실행 고지
    BEFORE_SESSION = "before"        # ② 세션 시작 전
    IN_SESSION = "in_session"        # ③ 세션 중
    ENDING = "ending"                # ④ 종료 처리 중
    DONE = "done"


_ALLOWED = {
    State.FIRST_RUN: (State.BEFORE_SESSION, State.DONE),     # 동의 · 창 닫기(종료)
    State.BEFORE_SESSION: (State.IN_SESSION, State.DONE),    # 시작 · 종료
    State.IN_SESSION: (State.ENDING, State.DONE),            # 세션 종료 흐름 · 강제 종료
    State.ENDING: (State.DONE,),                             # 완료 또는 취소 뒤 종료
    State.DONE: (),
}


class StateError(Exception):
    pass


class AppStateMachine:
    """`transition` 은 스레드 안전하다. 허용되지 않은 전이는 `StateError`(상태는 바뀌지 않는다).
    `on_change(old, new)` 는 잠금 밖에서 호출한다."""

    def __init__(self, *, first_run: bool, on_change: Optional[Callable] = None, emit: Optional[Callable] = None):
        self._state = State.FIRST_RUN if first_run else State.BEFORE_SESSION
        self._lock = threading.Lock()
        self._on_change, self._emit = on_change, emit

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def transition(self, new: State) -> State:
        with self._lock:
            old = self._state
            if new not in _ALLOWED[old]:
                raise StateError("%s → %s 는 허용되지 않는다" % (old.value, new.value))
            self._state = new
        if self._emit is not None:
            try:
                self._emit("app_state", old=old.value, new=new.value)
            except Exception:
                pass
        if self._on_change is not None:
            self._on_change(old, new)
        return new

    # 편의
    def acknowledge_first_run(self) -> State:
        return self.transition(State.BEFORE_SESSION)

    def start_session(self) -> State:
        return self.transition(State.IN_SESSION)

    def begin_ending(self) -> State:
        return self.transition(State.ENDING)

    def finish(self) -> State:
        return self.transition(State.DONE)


# ---- 첫 실행 고지의 동의 (B-18, AC-NF-1) ----
FIRST_RUN_NOTICE_VERSION = 1   # 고지 문구를 바꾸면 올린다(올리면 다시 표시한다)


def first_run_required(data) -> bool:
    """설정의 `first_run_ack` 가 현재 고지 판 번호와 같지 않으면(없음 포함) 고지를 표시한다."""
    try:
        return data.get("first_run_ack") != FIRST_RUN_NOTICE_VERSION
    except AttributeError:
        return True


# ---- 상태별 활성 항목 (FR-14 표, 합격 기준 AC-FR14-*) ----
# 값: (① 첫 실행 고지, ② 세션 시작 전, ③ 세션 중, ④ 종료 처리 중). "edit" 만 입력 칸 유무에 달려 있으므로 별도 규칙이다.
_ITEMS = {
    "app.about": (1, 1, 1, 1),
    "app.settings": (0, 1, 1, 1),
    "app.quit": (1, 1, 1, 1),
    "session.open_folder": (0, 0, 1, 1),
    "session.rebuild_summary": (0, 1, 0, 0),
    "session.pause": (0, 0, 1, 0),   # 수집 상태에 따른 규칙은 `transport_enabled`
    "session.play": (0, 0, 1, 0),
    "request.trigger": (0, 0, 1, 0),
    "request.capture": (0, 0, 1, 0),
    "window.main": (0, 1, 1, 1),
    "window.frame": (0, 1, 1, 0),
    "help.first_run_notice": (1, 1, 1, 1),
    "help.permissions": (0, 1, 1, 1),
}
_COL = {State.FIRST_RUN: 0, State.BEFORE_SESSION: 1, State.IN_SESSION: 2, State.ENDING: 3}


def transport_enabled(capture_state: Optional[str], ending: bool = False) -> tuple:
    """(재생, 일시 정지, 정지) 활성 여부와 [재생] 강조 여부: FR-11 의 표(결정 0147 · 0150). 세션 메뉴의 "재생" · "일시 정지" 도 이 규칙이다.
    수집 상태가 아직 없으면 수집 전과 같다."""
    if ending:
        return (False, False, False, False)
    st = capture_state or COLLECT_BEFORE
    if st in (COLLECT_RUNNING, COLLECT_NO_INPUT):
        return (False, True, True, False)
    if st == COLLECT_STOPPED:
        return (False, False, True, False)
    return (True, False, True, True)            # 일시 정지 · 수집 전


def item_ids() -> tuple:
    return tuple(_ITEMS)


def is_active(item: str, state: State, *, has_input: bool = False) -> bool:
    """메뉴 · 상태 아이콘 항목의 활성 여부. `has_input`: 편집 항목에서 입력 칸이 있는지(①에만 의미가 있다)."""
    if item not in _ITEMS:
        raise KeyError(item)
    if state is State.DONE:
        return False
    v = _ITEMS[item][_COL[state]]
    if v is None:
        return bool(has_input)
    return bool(v)


def close_window_quits(state: State) -> bool:
    """메인 창의 닫기 단추 · ⌘W: 세션 시작 전(①②)에는 앱이 종료하고 세션 중 · 종료 처리 중에는 창만 닫는다(FR-14)."""
    return state in (State.FIRST_RUN, State.BEFORE_SESSION)


def resolve_quit(state: State) -> str:
    """종료 요청(⌘Q · 앱 종료)의 처리: 세션 시작 전은 `quit_now`, 세션 중은 종료 흐름 `end_flow`,
    종료 처리 중은 이미 진행 중이므로 `already_ending`(AC-FR14-9)."""
    if state in (State.FIRST_RUN, State.BEFORE_SESSION):
        return "quit_now"
    if state is State.IN_SESSION:
        return "end_flow"
    return "already_ending"


# ---- 화면 밝기 (FR-15) ----
APPEARANCE_SYSTEM, APPEARANCE_LIGHT, APPEARANCE_DARK = "system", "light", "dark"
# 수집 상태의 값(앱 전체의 원본). 메뉴 · 상태 아이콘의 표시 어휘는 `app/menus.menu_collect_state` 가 이 값에서 만든다(D-070)
COLLECT_RUNNING, COLLECT_NO_INPUT, COLLECT_STOPPED = "수집 중", "입력 없음", "중단"
COLLECT_PAUSED, COLLECT_BEFORE = "일시 정지", "수집 전"      # 결정 0147 · 0150 (표시 글은 `labels.capture_label`)
APPEARANCE_CHOICES = ((APPEARANCE_SYSTEM, _t("state.appearance_choices")), (APPEARANCE_LIGHT, _t("state.appearance_choices_2")), (APPEARANCE_DARK, _t("state.appearance_choices_3")))
SCHEME_LIGHT, SCHEME_DARK = "light", "dark"


def normalize_appearance(value) -> str:
    """설정 값을 선택지로 정리한다. 알 수 없는 값은 기본(시스템 설정 따르기)이다(AC-FR15-1)."""
    return value if value in (APPEARANCE_SYSTEM, APPEARANCE_LIGHT, APPEARANCE_DARK) else APPEARANCE_SYSTEM


def resolve_scheme(choice, system_scheme: Optional[str]) -> str:
    """앱이 그릴 화면 밝기. `system_scheme`: 운영체제(또는 시험 연결점)가 알려 준 `light` · `dark`, 모르면 None(밝게로 본다)."""
    c = normalize_appearance(choice)
    if c == APPEARANCE_LIGHT:
        return SCHEME_LIGHT
    if c == APPEARANCE_DARK:
        return SCHEME_DARK
    return SCHEME_DARK if system_scheme == SCHEME_DARK else SCHEME_LIGHT


# ---- 상태 표시줄 (FR-11) ----
FAMILY_LABELS = {"sonnet": "Sonnet", "opus": "Opus", "haiku": "Haiku"}
PROVIDER_LABELS = {"claude_subscription": _t("screens.providers"), "claude_api": "Claude API"}


def model_label(family: str, effort: Optional[str]) -> str:
    """AC-FR1-1: `계열 · effort`. effort 가 없으면(단계가 없는 계열) 계열만 쓴다."""
    name = FAMILY_LABELS.get(family, family)
    return "%s · %s" % (name, effort) if effort else name


@dataclass(frozen=True)
class StatusInputs:
    provider: str
    family: str
    effort: Optional[str]
    source: Optional[str] = None            # 음성 소스(장치) 이름
    capture_state: Optional[str] = None     # 수집 전 · 수집 중 · 입력 없음 · 일시 정지 · 중단
    materials: int = 0
    captures: int = 0
    stt_errors: int = 0
    stt_prep: Optional[str] = None          # 음성 인식 모델 준비 칩의 글(NEW-47 · 48). 준비하는 동안에만 값이 있다(결정 0167 3항)
    queue_waiting: int = 0
    activity: Optional[str] = None          # 요청 진행 중 · 정리 문서 만드는 중 · 오류


def status_items(s: StatusInputs) -> list:
    """상태 표시줄의 (이름, 값) 목록. 세션 동안 제공자 · 모델 · effort 는 입력이 같으면 같은 값이다(AC-FR1-3)."""
    items = [("provider", PROVIDER_LABELS.get(s.provider, s.provider)), ("model", model_label(s.family, s.effort))]
    if s.source:
        items.append(("source", _t("state.status_items_277") % s.source))      # AC-FR3-1: "입력: 시스템 사운드"
    if s.capture_state:
        items.append(("capture_state", _labels.capture_label(s.capture_state)))
    items.append(("materials", _t("state.status_items_278") % s.materials))      # 기능 정의 FR-2 · 5절 화면 예시
    items.append(("captures", _t("state.status_items_279") % s.captures))
    items.append(("stt_errors", _t("state.status_items_280") % s.stt_errors))     # 결정 0068 3항: 0 이어도 늘 표시한다
    items.append(("queue", _t("state.status_items_282") % s.queue_waiting))
    if s.stt_prep:
        items.append(("stt_prep", s.stt_prep))      # 결정 0167 3항: "전사 처리 대기" 항목은 없고 준비 칩만 있다(AC-FR11-2). 칩이 "요청 진행 중" 알약보다 먼저이다(FR-11)
    if s.activity:
        items.append(("activity", s.activity))
    return items


def status_text(s: StatusInputs) -> str:
    return " · ".join(v for _, v in status_items(s))


# ---- 입력 레벨 막대 (AC-FR3-10, 시각 사양 8절 상태 표시줄) ----
LEVEL_CELLS = 6
LEVEL_FLOOR_DBFS = -60.0        # 이 값 이하는 0칸(M6: 방 소음 -63.9 dBFS). 측정하지 않은 제안이다(기술 계획 5절)
LEVEL_STEP_DB = 10.0            # 칸 하나의 폭


def level_to_cells(rms_dbfs: Optional[float], collecting: bool) -> int:
    """입력 RMS(dBFS)를 막대의 칸 수(0 ~ 6)로 바꾼다. 수집 중이 아니면 0 이다."""
    if not collecting or rms_dbfs is None or rms_dbfs <= LEVEL_FLOOR_DBFS:
        return 0
    return max(0, min(LEVEL_CELLS, int(-(-(rms_dbfs - LEVEL_FLOOR_DBFS) // LEVEL_STEP_DB))))


# ---- 전사 창 위의 상태 띠 (AC-FR3-2 · AC-FR3-11, 기술 계획 K-12 · K-20) ----
BANNER_NO_INPUT_TITLE = _t("state.banner_no_input_title")
BANNER_NO_INPUT_CAUSES = (_t("state.banner_no_input_causes"),
                          _t("state.banner_no_input_causes_2"),
                          _t("state.banner_no_input_causes_3"))
BANNER_STOPPED_TITLE = _t("ctl.on_audio_state_253")
BANNER_PERMISSION_REASON = _t("state.banner_permission_reason")
# 음성 수집 시작 실패(D-083): 제목과 조치 설명. 단추는 없다(다시 시도해도 같아서 스스로 이어진다는 오해를 만든다).
START_FAILED_PREFIX = _t("state.start_failed_prefix")
BANNER_START_FAILED_TITLE = START_FAILED_PREFIX
BANNER_START_FAILED_TEXT = _t("state.banner_start_failed_text")


@dataclass(frozen=True)
class Banner:
    title: str
    description: str


def capture_banner(state: Optional[str], detail: str = "", permission_denied: bool = False) -> Optional[Banner]:
    """수집 상태에서 전사 창 위의 띠를 정한다. 수집 중단이 입력 없음보다 우선하며(AC-FR3-2), 정상이면 None 이다.
    두 띠 모두 단추가 없다(입력 없음: 기능 정의 FR-3 예외. 권한 없음: AC-FR3-11)."""
    if state == "중단":
        if detail.startswith(START_FAILED_PREFIX):
            return Banner(BANNER_START_FAILED_TITLE, BANNER_START_FAILED_TEXT)
        if permission_denied:
            return Banner(BANNER_STOPPED_TITLE, BANNER_PERMISSION_REASON)
        return Banner(BANNER_STOPPED_TITLE, _t("state.capture_banner_290") % detail if detail else "")
    if state == "입력 없음":
        return Banner(BANNER_NO_INPUT_TITLE, " · ".join("%d. %s" % (i, c) for i, c in enumerate(BANNER_NO_INPUT_CAUSES, 1)))
    return None
