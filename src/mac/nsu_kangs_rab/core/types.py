"""모듈 사이에서 주고받는 자료형 중 `llm` 계층의 것 (docs/plan/technical-plan.md 2-2 · 2-3절)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

ERROR_KINDS = ("auth", "no_claude", "rate_limit", "network", "process_exit", "stt_fail", "audio_lost", "audio_start_failed", "permission", "io")


@dataclass(frozen=True)
class Error:
    """모듈은 예외 대신 이것을 콜백으로 낸다. `detail` 에 키 · 본문을 넣지 않는다."""
    kind: str
    detail: str = ""

    def __post_init__(self):
        if self.kind not in ERROR_KINDS:
            raise ValueError("닫힌 집합 밖의 오류 종류: %r" % (self.kind,))


@dataclass(frozen=True)
class Init:
    model: Optional[str]
    api_key_source: Optional[str]
    version: Optional[str]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Result:
    ok: bool
    usage: dict = field(default_factory=dict)
    stop_reason: Optional[str] = None
    terminal_reason: Optional[str] = None
    text: str = ""
    error_kind: Optional[str] = None  # `ok` 가 거짓이고 원인을 분류할 수 있을 때만
    num_turns: Optional[int] = None   # 모델 호출이 없는 지역 명령의 Result 는 0 (판별용)


@dataclass(frozen=True)
class Compacting:
    pass


@dataclass(frozen=True)
class Compacted:
    trigger: Optional[str]
    pre_tokens: Optional[int]
    post_tokens: Optional[int]


@dataclass(frozen=True)
class ControlResponse:
    request_id: Optional[str]
    ok: bool


@dataclass(frozen=True)
class ProcessExited:
    code: Optional[int]
    expected: bool = False  # close() 로 종료했으면 참


@dataclass(frozen=True)
class OutgoingMessage:
    request_n: int
    blocks: tuple  # 텍스트 블록과 base64 이미지 블록의 목록(B-05)


# ---- 경계를 넘는 자료형 (계획 2-3절; 결정 0053 3항: core 는 platform 을 가져오지 않는다) ----
@dataclass(frozen=True)
class Segment:
    """`stt` → `transcript` · `session`. 도착한 뒤 바뀌지 않는다(FR-5)."""
    n: int
    start_wall: str  # ISO 8601, 밀리초
    end_wall: str
    start_mono: float
    end_mono: float
    text: str


@dataclass(frozen=True)
class PartialSegment:
    """잠정 전사(결정 0166). `stt` → `transcript`. 표시 전용이며 `transcript` · `session.jsonl` · 세션 문서에 넣지 않는다."""
    text: str
    start_mono: float
    end_mono: float


SOURCE_CAPTURE = "캡처"
SOURCE_PASTE = "붙여넣기"
SOURCE_DROP = "끌어다 놓기"
CAPTURE_SOURCES = (SOURCE_CAPTURE, SOURCE_PASTE, SOURCE_DROP)


@dataclass(frozen=True)
class CaptureItem:
    """`capture` → `requests` · `session`."""
    path: str
    source: str
    width: int
    height: int
    sent_width: int
    sent_height: int
    sha256: str
    t_wall: str
