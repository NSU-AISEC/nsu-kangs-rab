"""정리 문서의 요청 구성과 저장 (K-16; FR-13, `docs/plan/prompt-spec.md` 8 · 8-3-1절, 계획 2-4절 `rebuild_request`).

Qt 와 `platform` 을 가져오지 않는다. 이 모듈은 프로세스를 시작하지 않고 모델을 호출하지 않는다.

- `session_view(events, recovered)`: `read_jsonl` 의 결과를 요청을 만들 값으로 정리한다.
- `build_request(view, doc_kind, template, history)`: 요청 메시지의 본문(텍스트 하나).
  `history=True` 는 상주 이력이 있는 경로(8절, `[재전송]` · `[질의응답]` 없음), `False` 는 이력이 없는 경로(8-3-1절).
- `save_document(folder, doc_kind, text)`: `lecture.md` · `meeting.md` 로 저장한다. 이미 있으면 덮어쓰지 않고 `lecture-2.md` 처럼 번호를 붙인다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .context import escape_lines
from .transcript import compress_ids, one_line

DOC_FILE = {"수업": "lecture", "회의": "meeting"}
MODES = ("대면", "화상")
UNKNOWN_MODE = "(미기재)"
UNNAMED = "(이름 없음)"


@dataclass
class Header:
    kind: str = "수업"
    title: str = UNNAMED
    number: str = UNKNOWN_MODE
    mode: str = UNKNOWN_MODE
    date: str = ""
    start: str = ""


@dataclass
class View:
    header: Optional[Header]
    segments: list = field(default_factory=list)      # (n, start, end, text)
    requests: dict = field(default_factory=dict)      # n → request 사건
    responses: dict = field(default_factory=dict)     # n → response 사건
    deletes: list = field(default_factory=list)       # delete 사건(기록 순서)
    captures: list = field(default_factory=list)      # capture 사건
    diagrams: list = field(default_factory=list)      # diagram 사건
    end: Optional[str] = None
    end_substituted: bool = False
    ignored_lines: int = 0

    @property
    def deleted_ns(self) -> set:
        return {d.get("n") for d in self.deletes}


def session_view(events: Sequence[dict], recovered) -> View:
    v = View(None)
    for e in events:
        t = e.get("type")
        if t == "header" and v.header is None:
            v.header = Header(kind=e.get("kind") or "수업", title=(e.get("title") or UNNAMED),
                              number=e.get("number") or UNKNOWN_MODE, mode=e.get("mode") or UNKNOWN_MODE,
                              date=e.get("date") or "", start=e.get("start") or "")
        elif t == "segment":
            v.segments.append((e.get("n"), e.get("start", ""), e.get("end", ""), e.get("text", "")))
        elif t == "request":
            v.requests[e.get("n")] = e
        elif t == "response":
            v.responses[e.get("n")] = e
        elif t == "delete":
            v.deletes.append(e)
        elif t == "capture":
            v.captures.append(e)
        elif t == "diagram":
            v.diagrams.append(e)
    v.segments.sort(key=lambda s: s[0])
    v.end = getattr(recovered, "end_time", None)
    v.end_substituted = bool(getattr(recovered, "end_substituted", False))
    v.ignored_lines = int(getattr(recovered, "ignored_lines", 0) or 0)
    return v


def _hm(t: str) -> str:
    return t[:5] if t else ""


def session_line(v: View, doc_kind: str) -> str:
    h = v.header or Header()
    mode = h.mode if h.mode in MODES else UNKNOWN_MODE
    start = ("%s %s" % (h.date, _hm(h.start))).strip()
    line = "[세션] 과목명=%s 차시=%s 방식=%s 시작=%s 종료=%s" % (
        one_line(h.title) or UNNAMED, one_line(h.number) or UNKNOWN_MODE, mode, start, _hm(v.end or ""))
    if v.end_substituted:
        line += " 종료대체=예"
    return line


def _kept_files(v: View) -> tuple:
    gone = v.deleted_ns
    caps = ["[캡처] %s %s" % (c.get("ts", ""), c.get("path", "")) for c in v.captures if c.get("n") not in gone]
    dias = ["[다이어그램] %s %s" % (d.get("ts", ""), d.get("path", ""))
            for d in v.diagrams if d.get("n") not in gone and d.get("result") == "완료"]
    return caps, dias


def _deleted_lines(v: View) -> list:
    out = []
    for d in v.deletes:
        n = d.get("n")
        files = [e.get("path") for e in list(v.captures) + list(v.diagrams) if e.get("n") == n and e.get("path")]
        line = "[삭제된 카드] 요청=%s 종류=%s 시각=%s" % (n, d.get("kind", ""), d.get("card_ts", ""))
        for f in files:
            line += " 파일=%s" % f
        out.append(line)
    return out


def _input_text(req: dict, resp: Optional[dict]) -> str:
    kind = req.get("kind")
    inp = req.get("input", "") or ""
    if kind == "트리거":
        j = (resp or {}).get("judgment")
        if not j:
            return "(판단 표시 없음)"
        m = re.match(r'^판단:\s*(이미 답이 나온 질문|질문 없음|질문)\s*\|\s*(.*)$', j)
        if not m:
            return "(판단 표시 없음)"
        label, subject = m.group(1), m.group(2).strip()
        if label == "질문 없음":
            return "질문 없음 (주제: %s)" % subject
        return "질문: %s" % subject.strip('"')
    if kind == "화면메모":
        return "액자 캡처 %s" % inp
    return one_line(inp)


def _qa_blocks(v: View) -> list:
    gone = v.deleted_ns
    out = []
    for n in sorted(v.requests):
        if n in gone or n not in v.responses:
            continue
        req, resp = v.requests[n], v.responses[n]
        head = "[질의응답] 요청=%s 시각=%s 종류=%s" % (n, req.get("ts", ""), req.get("kind", ""))
        if resp.get("status") == "중단":
            head += " 상태=중단"
        body = resp.get("text", "") or ""
        if resp.get("judgment"):
            body = resp["judgment"] + ("\n" + body if body else "")
        out += [head, "[입력] " + escape_lines(_input_text(req, resp)), "[응답]", escape_lines(body)]
    return out


def build_request(v: View, doc_kind: str, template: str, history: bool) -> str:
    """요청 메시지의 텍스트. `doc_kind` 는 `수업` 또는 `회의`. `history` 는 상주 이력이 있는 경로이다."""
    head = "[요청] 종류=정리문서 문서=%s" % doc_kind + ("" if history else " 이력=없음")
    lines = [head, session_line(v, doc_kind)]
    if not history:
        if v.segments:
            first, last = v.segments[0], v.segments[-1]
            lines.append("[재전송] 범위=%s~%s 조각=%s" % (first[1], last[2], compress_ids(s[0] for s in v.segments)))
            lines += ["%d %s-%s %s" % (n, a, b, one_line(t)) for (n, a, b, t) in v.segments]
        else:
            lines.append("[재전송] 없음")
    caps, dias = _kept_files(v)
    lines += caps + dias + _deleted_lines(v)
    if not history:
        lines += _qa_blocks(v)
    lines += ["[템플릿]", template]
    return "\n".join(lines)


def next_document_path(folder, doc_kind: str) -> Path:
    base = DOC_FILE.get(doc_kind, "lecture")
    d = Path(folder)
    p = d / (base + ".md")
    i = 2
    while p.exists():
        p = d / ("%s-%d.md" % (base, i))
        i += 1
    return p


def save_document(folder, doc_kind: str, text: str) -> Path:
    """덮어쓰지 않는다. 이미 있으면 `lecture-2.md` · `lecture-3.md` … 으로 저장한다(`O_EXCL` 로 경쟁을 막는다)."""
    d = Path(folder)
    base = DOC_FILE.get(doc_kind, "lecture")
    i = 1
    while True:
        p = d / ("%s.md" % base if i == 1 else "%s-%d.md" % (base, i))
        try:
            fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            i += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        return p
