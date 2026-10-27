"""전사 조각의 축적과 요청에 담을 범위의 계산 (K-06; FR-5 · FR-7 · FR-8, 계획 2-4절 transcript).

- 조각은 도착한 뒤 바뀌지 않는다. 번호 `n` 이 같은 조각은 한 번만 받는다(나중 것은 버린다).
- 시각은 단조 시계(`start_mono` · `end_mono`)로 비교하고, 표시용 벽시계 문자열은 그대로 보존한다.
- "보낸 조각" 의 집합을 이 객체가 가진다. 요청을 모델 프로세스에 실제로 전달한 뒤에만 `commit` 하므로,
  전달 전에 대기열에서 지워진 요청의 조각은 다음 요청에 다시 담긴다.
- 스레드: 모든 공개 메서드는 잠금 아래에서 실행된다(전사 작업 스레드와 호출 스레드가 함께 쓴다).
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from .types import Segment

LAST_WINDOW_S = 30.0
_NL = re.compile(r"\s*[\r\n]+\s*")


def one_line(text: str) -> str:
    """조각 본문의 줄바꿈을 공백 하나로 바꾼다(prompt-spec 4절)."""
    return _NL.sub(" ", text).strip()


def char_count(text: str) -> int:
    """NFC 정규화 뒤 코드 포인트 수(결정 0047)."""
    return len(unicodedata.normalize("NFC", text))


def hms(wall: str) -> str:
    """ISO 8601 벽시계 문자열에서 HH:MM:SS 를 꺼낸다. 형식이 다르면 문자열을 그대로 돌려준다."""
    m = re.search(r"(\d{2}:\d{2}:\d{2})", wall or "")
    return m.group(1) if m else (wall or "")


def compress_ids(ids: Iterable[int]) -> str:
    """번호 목록을 연속 구간으로 줄인다: [118,119,120,122] → `118~120,122`."""
    xs = sorted(set(ids))
    if not xs:
        return ""
    runs, a, b = [], xs[0], xs[0]
    for x in xs[1:]:
        if x == b + 1:
            b = x
        else:
            runs.append((a, b))
            a = b = x
    runs.append((a, b))
    return ",".join(str(a) if a == b else "%d~%d" % (a, b) for a, b in runs)


@dataclass(frozen=True)
class Delta:
    """요청 하나에 담을 조각들. `commit(delta)` 로 확정하기 전에는 보낸 것으로 치지 않는다."""
    segments: tuple            # 새 조각(번호 순). 발화 시작이 트리거 시각 이전인 것만
    last30: tuple              # 마지막 30초에 해당하는 조각(새 조각과 이력을 가리지 않는다)
    partial: Optional[tuple]   # 확정 대기 상한을 넘겨 요청에 넣는 잠정 문장 (본문, 시작 벽시계, 끝 벽시계). 없으면 None
    resend: tuple = ()         # 재시작 뒤 한 번 다시 보내는 이전 조각(번호 순)

    @property
    def new_range(self) -> Optional[tuple]:
        if not self.segments:
            return None
        return (min(s.start_wall for s in self.segments), max(s.end_wall for s in self.segments))

    @property
    def resend_range(self) -> Optional[tuple]:
        if not self.resend:
            return None
        return (min(s.start_wall for s in self.resend), max(s.end_wall for s in self.resend))

    @property
    def new_chars(self) -> int:
        return sum(char_count(one_line(s.text)) for s in self.segments)


class Transcript:
    def __init__(self):
        self._lock = threading.Lock()
        self._segs: dict = {}        # n -> Segment
        self._open: Optional[tuple] = None   # 진행 중 구간의 마지막 잠정: (본문, 시작 벽시계, 끝 벽시계, 시작 단조, 끝 단조). 저장 · 기록하지 않는다(결정 0166)
        self._open_cut = False       # 일시 정지로 끊긴 구간: 확정은 기다리되 확정이 없으면 그 잠정을 요청에 쓰지 않는다(AC-FR7-14 ⓖ)
        self._open_stale = False     # 끊긴 구간이 [재생] 뒤에도 남았다: 진행 중인 구간으로 보지 않는다(권고 62)
        self._cond = threading.Condition(self._lock)
        self._sent: set = set()      # 모델에 전달한 조각 번호
        self._resend_due = False

    # ---- 입력 ----
    def add(self, seg: Segment) -> bool:
        """조각을 더한다. 같은 번호가 있으면 버리고 False. 확정이 도착하면 진행 중 구간(잠정)은 끝난 것이다."""
        with self._cond:
            self._open = None
            self._open_cut = self._open_stale = False
            self._cond.notify_all()
            if seg.n in self._segs:
                return False
            self._segs[seg.n] = seg
            return True

    # ---- 진행 중 구간 (잠정, 결정 0166 · 0167) ----
    def set_open(self, text: str, start_wall: str, end_wall: str, start_mono: float, end_mono: float) -> None:
        """진행 중 구간의 마지막 잠정을 기억한다(최대 하나). 확정 · 구간 실패 · 끊김이 오면 `add` · `close_open` 이 지운다."""
        with self._cond:
            self._open = (text, start_wall, end_wall, float(start_mono), float(end_mono))
            self._open_cut = self._open_stale = False
            self._cond.notify_all()

    def close_open(self) -> None:
        """진행 중 구간이 확정 없이 끝났다(구간 실패 · 수집 중단 · 세션 종료 · 보조 프로세스 종료). 그 잠정은 요청에 쓰지 않는다."""
        with self._cond:
            self._open = None
            self._open_cut = self._open_stale = False
            self._cond.notify_all()

    def abandon_open(self) -> None:
        """일시 정지로 구간이 끊겼다: 끊기 신호(`C`)로 오는 확정은 계속 기다리지만(Q-48), 확정이 없으면 이 잠정은 요청에 쓰지 않는다."""
        with self._cond:
            if self._open is not None:
                self._open_cut = True

    def resume_open(self) -> None:
        """[재생] 으로 일시 정지가 끝났다: 끊긴 구간(`abandon_open`)이 남아 있으면 진행 중인 구간으로 보지 않는다. 끊기 신호는 이미 보냈고 그 구간에는 새 소리가 들어가지 않으므로 기다려도 얻는 것이 없다. 늦게 오는 확정은 `add` 가 조각으로 받는다(Q-48)."""
        with self._cond:
            if self._open is not None and self._open_cut:
                self._open_stale = True
                self._cond.notify_all()

    def partial_for(self, t_trigger_mono: float) -> Optional[tuple]:
        """요청에 `[잠정]` 으로 넣을 잠정: `open_for` 와 같되 일시 정지로 끊긴 구간은 None 이다."""
        with self._lock:
            o = self._open
            return o if o is not None and not self._open_cut and o[3] <= t_trigger_mono else None

    def open_for(self, t_trigger_mono: float) -> Optional[tuple]:
        """발화 시작이 트리거 시각 이전(포함)인 진행 중 구간의 마지막 잠정. 없으면 None."""
        with self._lock:
            o = self._open
            return o if o is not None and not self._open_stale and o[3] <= t_trigger_mono else None

    def wait_final(self, t_trigger_mono: float, remaining_s: float, cut=None, sleep=None) -> Optional[tuple]:
        """T 에 진행 중 구간이 있으면 `cut()`(끊기 신호)을 한 번 호출하고 확정을 `remaining_s` 초까지 기다린다.
        반환: 상한을 넘어서도 구간이 열려 있으면 마지막 잠정 `(본문, 시작 벽시계, 끝 벽시계, 시작 단조, 끝 단조)`, 확정이 오거나 끊겼거나
        진행 중 구간이 없으면 None. 확정은 `add` 로 들어가 있으므로 호출한 쪽이 `delta` 로 가져간다."""
        if self.open_for(t_trigger_mono) is None:
            return None
        if cut is not None:
            try:
                cut()
            except Exception:  # noqa: BLE001
                pass
        end = time.monotonic() + max(0.0, float(remaining_s))
        with self._cond:
            while True:
                o = self._open
                if o is None or self._open_stale or o[3] > t_trigger_mono:
                    return None
                left = end - time.monotonic()
                if left <= 0:
                    return None if self._open_cut else o
                self._cond.wait(left)

    def full(self) -> list:
        with self._lock:
            return [self._segs[n] for n in sorted(self._segs)]

    def get(self, n: int) -> Optional[Segment]:
        with self._lock:
            return self._segs.get(n)

    def count(self) -> int:
        with self._lock:
            return len(self._segs)

    def sent_ids(self) -> list:
        with self._lock:
            return sorted(self._sent)

    def accumulated_range(self) -> Optional[tuple]:
        """이력(모델에 전달한 조각)에 담긴 누적 범위: (시작 벽시계, 끝 벽시계). 없으면 None."""
        with self._lock:
            segs = [self._segs[n] for n in self._sent if n in self._segs]
        if not segs:
            return None
        return (min(s.start_wall for s in segs), max(s.end_wall for s in segs))

    # ---- 요청 구성 ----
    def delta(self, t_trigger_mono: float, partial: Optional[tuple] = None) -> Delta:
        """트리거 시각 T 에 대해 요청에 담을 조각을 계산한다(상태를 바꾸지 않는다).

        - 새 조각: 아직 전달하지 않았고 발화 시작이 T 이전(포함)인 조각. T 이후에 시작한 조각은 다음 요청으로 남는다.
        - 마지막 30초: 발화 시작이 T 이전이고 종료가 T-30 초보다 뒤인 조각(T 에 걸친 조각 포함).
        - `partial`: 확정 대기 상한을 넘겨 요청에 넣는 잠정 문장(`wait_final` 의 반환). 조각이 아니므로 번호가 없다.
        - 재시작 뒤 첫 요청이면 이전에 전달한 조각 전체를 `resend` 로 담는다.
        """
        with self._lock:
            ordered = [self._segs[n] for n in sorted(self._segs)]
            new = tuple(s for s in ordered if s.n not in self._sent and s.start_mono <= t_trigger_mono)
            last = tuple(s for s in ordered
                         if s.start_mono <= t_trigger_mono and s.end_mono > t_trigger_mono - LAST_WINDOW_S)
            resend = tuple(s for s in ordered if s.n in self._sent) if self._resend_due else ()
        pt = (partial[0], partial[1], partial[2]) if partial else None
        return Delta(new, last, pt, resend)

    def commit(self, delta: Delta) -> None:
        """요청을 모델 프로세스에 전달한 뒤 호출한다. 새 조각을 보낸 것으로 기록하고 재전송을 끝낸다."""
        with self._lock:
            self._sent.update(s.n for s in delta.segments)
            if delta.resend or self._resend_due:
                self._resend_due = False

    def mark_restart(self) -> None:
        """프로세스 재시작 또는 이력 압축 뒤: 다음 요청에 이전 조각 전체를 한 번 다시 담는다(FR-8)."""
        with self._lock:
            self._resend_due = True

    @property
    def resend_due(self) -> bool:
        with self._lock:
            return self._resend_due
