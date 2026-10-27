"""세션 폴더 · 세션 기록(`session.jsonl` · `session.md`) · 전사 문서(`transcript.txt`) (K-08; FR-10 · FR-13, 계획 2-4절 session).

- `SessionFolder.create(base, date)`: `<base>/YYYY-MM-DD/`, 이미 있으면 `-2`, `-3` … 순으로 `os.mkdir` 가 성공한 첫 이름(A-21).
  `captures/` 를 함께 만든다.
- `SessionLog`: 사건 하나를 `session.jsonl` 한 줄로 즉시 덧붙이고 `flush()` 한다(B-09, `fsync` 없음). `session.md` 도 같은 때 덧붙인다.
  이미 쓴 줄은 고치지 않는다. 첫 줄은 `header` 이어야 한다.
- `TranscriptFile`: `HH:MM:SS --> HH:MM:SS` 다음 줄에 본문, 빈 줄로 구분(AC-FR13-1). 조각마다 덧붙이고 `flush()` 한다.
- `read_jsonl`: 읽지 못하는 줄(강제 종료로 깨진 줄)은 무시하고 개수를 센다. `end` 가 없으면 마지막 `segment` 의 `end` 로 대신한다.

시각 문자열은 벽시계 `HH:MM:SS` 이다. 자정을 넘겨도 날짜 폴더는 시작 날짜로 유지되고 시각은 `00:00:05` 처럼 이어진다(AC-FR13-12).
핵심 모듈이므로 Qt 와 `platform` 을 가져오지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date as _date, datetime
from pathlib import Path
from typing import Callable, Optional

from .transcript import hms, one_line
from .types import Segment

SCHEMA_VERSION = 1
KINDS = ("트리거", "답변", "고찰", "요약", "자유질의", "화면메모")
SOURCES_IMG = ("캡처", "붙여넣기", "끌어다 놓기")
_TIME = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 사건 종류 → {필드: 검사}. 검사: "str" · "int" · "time" · "date" · "strlist" · ("enum", 값…) · ("optstr",)
SCHEMA: dict = {
    "header": {"v": "int", "date": "date", "provider": "str", "model": "str", "effort": "str",
               "source": ("enum", "시스템 사운드", "시스템 마이크"), "materials": "strlist",
               "kind": ("enum", "수업", "회의"), "title": "str", "number": "str",
               "mode": ("enum", "대면", "화상"), "start": "time"},
    "segment": {"n": "int", "start": "time", "end": "time", "text": "str"},
    "request": {"n": "int", "kind": ("enum",) + KINDS, "input": "str", "ts": "time"},
    "response": {"n": "int", "judgment": "optstr", "text": "str", "status": ("enum", "완료", "중단"), "ts": "time"},
    "capture": {"n": "int", "path": "relpath", "source": ("enum",) + SOURCES_IMG, "ts": "time"},
    "diagram": {"n": "int", "path": "relpath", "result": ("enum", "완료", "실패", "외부 자원 위반"), "ts": "time"},
    "delete": {"n": "int", "kind": ("enum",) + KINDS, "card_ts": "time", "state": ("enum", "진행 중", "대기 중", "완료"),
               "ts": "time"},
    "pause": {"state": ("enum", "시작", "끝"), "ts": "time"},          # 일시 정지의 시작 · 끝(결정 0147)
    "end": {"ts": "time"},
}
TYPES = tuple(SCHEMA)


class SessionRecordError(ValueError):
    pass


def _check(type_: str, fields: dict) -> None:
    spec = SCHEMA.get(type_)
    if spec is None:
        raise SessionRecordError("알 수 없는 사건 종류: %r" % (type_,))
    missing = [k for k in spec if k not in fields]
    extra = [k for k in fields if k not in spec]
    if missing or extra:
        raise SessionRecordError("%s 의 필드가 맞지 않는다: 없음=%s 더 있음=%s" % (type_, missing, extra))
    for k, rule in spec.items():
        v = fields[k]
        ok = True
        if rule == "str":
            ok = isinstance(v, str)
        elif rule == "int":
            ok = isinstance(v, int) and not isinstance(v, bool)
        elif rule == "time":
            ok = isinstance(v, str) and bool(_TIME.match(v))
        elif rule == "date":
            ok = isinstance(v, str) and bool(_DATE.match(v))
        elif rule == "strlist":
            ok = isinstance(v, list) and all(isinstance(x, str) for x in v)
        elif rule == "optstr":
            ok = v is None or isinstance(v, str)
        elif rule == "relpath":   # 세션 폴더 기준 상대 경로(AC-FR13-4: 산출물은 세션 폴더 안에만 둔다)
            if v == "" and type_ == "diagram" and fields.get("result") == "실패":
                continue          # 만든 파일이 없는 실패는 빈 문자열이다(AC-FR9-24)
            ok = (isinstance(v, str) and v != "" and not os.path.isabs(v)
                  and ".." not in Path(v.replace("\\", "/")).parts)
        elif isinstance(rule, tuple) and rule and rule[0] == "enum":
            ok = v in rule[1:]
        if not ok:
            raise SessionRecordError("%s.%s 의 값이 형식에 맞지 않는다: %r" % (type_, k, v))


class SessionFolder:
    @staticmethod
    def number(folder) -> int:
        """세션 폴더의 번호(차시, 결정 0176 1항): 이름이 `YYYY-MM-DD` 이면 1, `YYYY-MM-DD-n` 이면 n. 형식이 다르면 1."""
        m = re.match(r"^\d{4}-\d{2}-\d{2}(?:-(\d+))?$", Path(folder).name)
        return int(m.group(1)) if m and m.group(1) else 1

    @staticmethod
    def create(base, date) -> Path:
        """`date`: `datetime.date` 또는 `YYYY-MM-DD` 문자열(세션 시작 날짜). 반환: 만든 폴더."""
        name = date.isoformat() if isinstance(date, _date) else str(date)
        if not _DATE.match(name):
            raise ValueError("날짜 형식이 맞지 않는다: %r" % (date,))
        b = Path(base)
        b.mkdir(parents=True, exist_ok=True)
        n = 1
        while True:
            p = b / (name if n == 1 else "%s-%d" % (name, n))
            try:
                os.mkdir(p)           # 원자적: 두 앱이 겹쳐 시작해도 같은 이름을 얻지 못한다(A-21)
            except FileExistsError:
                n += 1
                continue
            (p / "captures").mkdir()
            return p


def _wall_hms() -> str:
    return datetime.now().astimezone().strftime("%H:%M:%S")


class SessionLog:
    """`session.jsonl` 과 `session.md`. 스레드 안전(잠금 하나로 줄 순서를 보장한다)."""

    def __init__(self, folder, *, wall: Callable[[], str] = _wall_hms):
        self.folder = Path(folder)
        self._wall = wall
        self._lock = threading.Lock()
        self._jsonl = open(self.folder / "session.jsonl", "a", encoding="utf-8", newline="\n")
        self._md = open(self.folder / "session.md", "a", encoding="utf-8", newline="\n")
        self._count = 0
        self._closed = False

    def append(self, type_: str, scope: Optional[str] = None, **fields) -> dict:
        """사건 한 줄을 쓴다. `header` 의 `v` 와 `ts` 는 주지 않으면 채운다. `scope`(요청의 맥락 범위)는 `session.md` 에만 쓴다.
        반환: 쓴 사건. 형식이 맞지 않으면 `SessionRecordError`(아무것도 쓰지 않는다)."""
        if type_ == "header":
            fields.setdefault("v", SCHEMA_VERSION)
        if "ts" in SCHEMA.get(type_, {}):
            fields.setdefault("ts", self._wall())
        _check(type_, fields)
        rec = {"type": type_, **fields}
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            if self._closed:
                raise SessionRecordError("닫힌 기록이다")
            if self._count == 0 and type_ != "header":
                raise SessionRecordError("첫 줄은 header 이어야 한다")
            if self._count > 0 and type_ == "header":
                raise SessionRecordError("header 는 첫 줄에만 쓴다")
            self._jsonl.write(line + "\n")
            self._jsonl.flush()
            self._md.write(_markdown(rec, scope))
            self._md.flush()
            self._count += 1
        return rec

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for f in (self._jsonl, self._md):
                try:
                    f.close()
                except OSError:
                    pass


def _quote(text: str) -> str:
    return "\n".join("> " + l for l in text.split("\n"))


def _markdown(r: dict, scope: Optional[str]) -> str:
    t = r["type"]
    if t == "header":
        mats = ", ".join(r["materials"]) if r["materials"] else "(없음)"
        return ("# %s — %s\n\n- 날짜: %s\n- 종류: %s\n- 방식: %s\n- 시작: %s\n- 제공자: %s\n- 모델: %s\n- effort: %s\n"
                "- 음성 소스: %s\n- 사전 지식: %s\n\n## 기록\n\n" % (
                    r["title"], r["number"], r["date"], r["kind"], r["mode"], r["start"], r["provider"], r["model"],
                    r["effort"], r["source"], mats))
    if t == "segment":
        return "- %s %s\n" % (r["start"], one_line(r["text"]))
    if t == "request":
        extra = " · 맥락 범위: %s" % scope if scope else ""
        return "\n### 요청 %d · %s · %s%s\n\n%s\n\n" % (r["n"], r["kind"], r["ts"], extra, _quote(r["input"]) if r["input"] else "(입력 없음)")
    if t == "response":
        head = "**응답 %d** (%s, %s)" % (r["n"], r["status"], r["ts"])
        if r["judgment"]:
            head += "\n\n판단: %s" % r["judgment"]
        return "%s\n\n%s\n\n" % (head, r["text"])
    if t == "capture":
        return "\n- 액자 캡처 %s · %s · %s · 요청 %d\n" % (r["ts"], r["path"], r["source"], r["n"])
    if t == "diagram":
        return "\n- 다이어그램 %s · %s · %s · 요청 %d\n" % (r["ts"], r["path"] or "(파일 없음)", r["result"], r["n"])
    if t == "delete":
        return "\n- [삭제된 카드] 요청 %d · %s · %s(%s) · 지운 시각 %s\n" % (r["n"], r["kind"], r["card_ts"], r["state"], r["ts"])
    if t == "pause":
        return "\n- 일시 정지 %s %s\n" % (r["state"], r["ts"])
    if t == "end":
        return "\n---\n종료 %s\n" % r["ts"]
    return ""


class TranscriptFile:
    """`transcript.txt`(FR-13). 조각이 확정될 때마다 덧붙이고 `flush()` 한다."""

    def __init__(self, folder):
        self._f = open(Path(folder) / "transcript.txt", "a", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self._seen: set = set()

    def append(self, seg: Segment) -> bool:
        """같은 번호의 조각은 한 번만 쓴다. 본문의 줄바꿈은 공백으로 바꾼다(빈 줄이 조각 구분이므로). 반환: 썼는지."""
        body = one_line(seg.text)
        with self._lock:
            if seg.n in self._seen or self._f.closed:
                return False
            self._seen.add(seg.n)
            self._f.write("%s --> %s\n%s\n\n" % (hms(seg.start_wall), hms(seg.end_wall), body))
            self._f.flush()
        return True

    def append_pause(self, start_hms: str, end_hms: str, text: str) -> None:
        """일시 정지 구간의 블록(결정 0147): `HH:MM:SS --> HH:MM:SS` 다음 줄에 `text`(예: "(일시 정지)"). 조각 번호를 쓰지 않는다."""
        with self._lock:
            if self._f.closed:
                return
            self._f.write("%s --> %s\n%s\n\n" % (start_hms, end_hms, one_line(text)))
            self._f.flush()

    def close(self) -> None:
        with self._lock:
            if not self._f.closed:
                self._f.close()


@dataclass(frozen=True)
class Recovered:
    end_substituted: bool            # `end` 줄이 없어 마지막 `segment` 의 `end` 로 대신했다
    end_time: Optional[str]          # 종료 시각(실제 `end.ts` 또는 대신한 값). 조각도 없으면 None
    ignored_lines: int               # 읽지 못해 무시한 줄 수
    ignored: tuple = field(default=())   # 무시한 줄의 번호(1부터)


def read_jsonl(path, emit: Optional[Callable] = None) -> tuple:
    """반환: (사건 목록, `Recovered`). 줄 하나를 JSON 객체로 읽지 못하면 그 줄을 무시한다.
    `emit(type, **fields)` 를 주면 무시한 줄마다 `session_line_ignored`(line) 를 남긴다(본문 없음)."""
    events, ignored = [], []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        data = f.read()
    for i, raw in enumerate(data.split("\n"), 1):
        if raw.strip() == "":
            continue
        try:
            o = json.loads(raw)
        except ValueError:
            o = None
        if not isinstance(o, dict) or not isinstance(o.get("type"), str):
            ignored.append(i)
            if emit is not None:
                try:
                    emit("session_line_ignored", line=i)
                except Exception:
                    pass
            continue
        events.append(o)
    end = next((e for e in reversed(events) if e["type"] == "end"), None)
    if end is not None:
        rec = Recovered(False, end.get("ts"), len(ignored), tuple(ignored))
    else:
        seg = next((e for e in reversed(events) if e["type"] == "segment"), None)
        rec = Recovered(True, seg.get("end") if seg else None, len(ignored), tuple(ignored))
    return events, rec
