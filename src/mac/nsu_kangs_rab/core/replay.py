"""전사 재생 입력(`--dev-replay PATH`, 기술 계획 5절 "전사 재생 입력"; D-066).

STT 뒤 · 축적 앞에서 `Segment` 를 주입한다. 음성 수집 · STT 를 대신한다. 형식은 JSON Lines(한 줄에 객체 하나)이다.

| 키 | 뜻 |
|---|---|
| `start`, `end` | 발화의 시작 · 끝(초, 재생 시작을 0 으로 한다). 필수 |
| `text` | 전사 본문. 필수 |
| `arrive_after_ms` | 발화가 끝난 뒤 확정(`Segment`)이 도착하기까지의 지연(밀리초, 기본 0). 확정 전의 잠정 문장은 내지 않는다 |
| `start_wall`, `end_wall` | 선택. ISO 8601 시각. 자정을 넘는 세션(AC-FR13-12)이나 시각을 고정할 때 쓴다. 없으면 재생을 시작한
  벽시계에 `start` · `end` 를 더한다 |

조각 번호는 줄 순서의 1, 2, 3, … 이다. 재생 속도는 `--dev-speed X`(1 이 실시간, 기본 1)로 나눈다(`speed` 로 전달).
줄의 형식이 틀리면 그 줄은 건너뛰고 `on_error` 로 알린다.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from .types import Segment


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="milliseconds")


def load(path: str) -> tuple:
    """(항목 목록, 오류 문구 목록). 항목: dict(start, end, text, arrive_after_ms, start_wall, end_wall)."""
    items, errors = [], []
    with open(path, encoding="utf-8") as fh:
        for no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                o = json.loads(line)
                it = {"start": float(o["start"]), "end": float(o["end"]), "text": str(o["text"]),
                      "arrive_after_ms": float(o.get("arrive_after_ms", 0) or 0),
                      "start_wall": o.get("start_wall"), "end_wall": o.get("end_wall")}
                if it["end"] < it["start"] or it["arrive_after_ms"] < 0:
                    raise ValueError("구간 또는 지연이 올바르지 않다")
                for k in ("start_wall", "end_wall"):
                    if it[k] is not None:
                        datetime.fromisoformat(str(it[k]))
            except (KeyError, TypeError, ValueError) as e:
                errors.append("%d행: %s" % (no, type(e).__name__))
                continue
            items.append(it)
    return items, errors


class ReplayFeeder:
    """재생 스레드 하나. `stop()` 은 대기를 깨우고 `join()` 은 끝나기를 기다린다. `SttPipeline` 과 같은 `stop` · `join`."""

    def __init__(self, items: list, speed: float = 1.0, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], datetime] = datetime.now):
        self._items = items
        self._speed = float(speed) if speed and speed > 0 else 1.0
        self._clock, self._wall = clock, wall
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, on_segment: Callable) -> None:
        self._thread = threading.Thread(target=self._run, args=(on_segment,), daemon=True, name="replay")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _wait_until(self, mono_t: float) -> bool:
        """`mono_t` 까지 기다린다. 멈춤이 오면 False."""
        while True:
            left = mono_t - self._clock()
            if left <= 0:
                return not self._stop.is_set()
            if self._stop.wait(min(left, 0.2)):
                return False

    def _run(self, on_segment) -> None:
        t0, w0 = self._clock(), self._wall()
        events = []   # (도착 단조 시각, 순서, 종류, 값)
        for n, it in enumerate(self._items, 1):
            start_m, end_m = t0 + it["start"] / self._speed, t0 + it["end"] / self._speed
            arrive_m = end_m + it["arrive_after_ms"] / 1000.0 / self._speed
            sw = it["start_wall"] or _iso(w0 + timedelta(seconds=it["start"]))
            ew = it["end_wall"] or _iso(w0 + timedelta(seconds=it["end"]))
            seg = Segment(n, sw, ew, start_m, end_m, it["text"])
            events.append((arrive_m, 1, "segment", seg))
        events.sort(key=lambda e: (e[0], e[1]))
        for at, _o, kind, value in events:
            if not self._wait_until(at):
                return
            try:
                on_segment(value)
            except Exception:
                pass
