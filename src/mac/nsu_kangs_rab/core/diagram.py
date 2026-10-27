"""다이어그램 생성 (K-15; FR-9 다이어그램 항, `docs/plan/prompt-spec.md` 7절, 결정 0026 · 0027 · 0033 · 0048 · 0049).

Qt 를 가져오지 않는다. 일회성 `claude -p` 는 `oneshot_factory` 가 만든 `OneShot` 이 실행한다(정리 문서와 같은 부품).

- `check_external_refs(path)`: 생성한 SVG · HTML 의 외부 주소 검사(AC-FR9-15). 위반 목록을 반환한다.
- `build_prompt(inp)`: prompt-spec 7절의 요청 본문.
- `skill_state(plugin_dir)`: 앱에 포함한 사본이 쓸 수 있는지(AC-FR9-11).
- `DiagramPool`: 동시 상한(기본 3), 카드마다 하나, 취소(PID 로만 종료), 결과 확인은 파일의 존재로 한다.
"""
from __future__ import annotations
from .i18n import t as _t
from . import languages

import html
import json
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

DIAGRAM_DIR = "captures/diagrams"
MAX_CONCURRENT = 3
TIMEOUT_S = 180.0               # B-15
EFFORT = "medium"               # AC-FR9-7
TOOLS = ("Skill", "Read", "Write")
ALLOWED_KINDS = ("답변", "고찰", "트리거")   # 트리거는 본문이 있는 카드 모두(판단 4종, `can_diagram`)
TRIGGER_JUDGMENTS = ("질문", "질문 없음", "이미 답이 나온 질문", "미확인")

# 결과 상태
DONE, FAILED, VIOLATION, CANCELLED, OUTSIDE = "done", "failed", "violation", "cancelled", "outside"
REASON_VIOLATION = _t("diag.reason_violation")
REASON_OUTSIDE = _t("diag.reason_outside")
# `session.jsonl` 의 `diagram.result`. 실패는 만든 파일이 없으면 `path` 가 빈 문자열이다(AC-FR9-24)
RESULT_LABEL = {DONE: "완료", VIOLATION: "외부 자원 위반", FAILED: "실패", OUTSIDE: "실패"}
OUTSIDE_SUFFIXES = (".svg", ".html")     # 세션 폴더 안 허용된 위치 밖에 새로 생긴 결과 파일의 판별(AC-FR9-25, 임의)

_URL = re.compile(r"https?://", re.I)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
_CSS_IMPORT = re.compile(r"@import\s+(?:url\(\s*)?(['\"]?)([^'\")\s;]+)", re.I)


# ---------------------------------------------------------------------------------------------
# 외부 주소 검사 (AC-FR9-15)
# ---------------------------------------------------------------------------------------------
def _norm(v: str) -> str:
    """문자 참조와 퍼센트 인코딩을 풀어 낸 값(고정점까지, 최대 4회)."""
    cur = v or ""
    for _ in range(4):
        nxt = urllib.parse.unquote(html.unescape(cur))
        if nxt == cur:
            break
        cur = nxt
    return cur


def _external(target: str) -> bool:
    t = target.strip()
    return bool(_URL.match(t)) or t.startswith("//")      # 프로토콜 상대 주소도 외부이다(임의, CSS 의 url · @import 만)


def _css_hits(css: str) -> list:
    n = _norm(css)
    hits = [m.group(2) for m in _CSS_URL.finditer(n) if _external(m.group(2))]
    hits += [m.group(2) for m in _CSS_IMPORT.finditer(n) if _external(m.group(2))]
    return hits


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.violations: list = []
        self._cur: Optional[str] = None

    def _add(self, where: str, value: str) -> None:
        self.violations.append("%s: %s" % (where, value.strip().replace("\n", " ")[:120]))

    def handle_starttag(self, tag, attrs):
        for name, val in attrs:
            if val is None:
                continue
            if name == "xmlns" or name.startswith("xmlns:"):
                continue                                   # 네임스페이스 선언은 검사하지 않는다
            if _URL.search(_norm(val)):
                self._add("속성 %s@%s" % (tag, name), val)
            elif name == "style":
                for h in _css_hits(val):
                    self._add("속성 style@%s" % tag, h)
        if tag in ("script", "style"):
            self._cur = tag

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in ("script", "style"):
            self._cur = None

    def handle_endtag(self, tag):
        if tag == self._cur:
            self._cur = None

    def handle_data(self, data):
        if self._cur == "script":
            if _URL.search(_norm(data)):
                m = _URL.search(_norm(data))
                self._add("script", _norm(data)[max(0, m.start() - 10):m.start() + 60])
        elif self._cur == "style":
            for h in _css_hits(data):
                self._add("style", h)
        # 그 밖의 본문 글(텍스트 노드)은 검사하지 않는다


def check_external_refs_text(text: str) -> list:
    p = _Scan()
    try:
        p.feed(text)
        p.close()
    except Exception:
        p.violations.append("구문 분석 실패")
    return p.violations


def check_external_refs(path) -> list:
    """파일의 외부 주소 위반 목록. 읽지 못하면 위반으로 본다(표시하지 않는 쪽)."""
    try:
        text = Path(path).read_bytes().decode("utf-8", errors="replace")
    except OSError as e:
        return ["읽지 못함: %s" % type(e).__name__]
    return check_external_refs_text(text)


# ---------------------------------------------------------------------------------------------
# 요청 · 사본
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DiagramInput:
    card_n: int
    kind: str            # 답변 | 고찰 | 이미 답이 나온 질문
    ts: str              # 요청 시각 HH:MM:SS
    question: str
    body: str
    language: str = "ko"      # 세션의 음성 인식 언어 코드(FR-16): 다이어그램 안의 글의 언어


def can_diagram(kind: str, judgment_label: Optional[str] = None) -> bool:
    """다이어그램 버튼을 두는 카드: 답변 · 고찰, 그리고 본문이 있는 모든 트리거 카드(판단이 질문 · 질문 없음 ·
    이미 답이 나온 질문 · 미확인, AC-FR9-6 · AC-FR9-23, D-049). 본문의 유무는 호출한 쪽이 본다."""
    if kind in ("답변", "고찰"):
        return True
    return kind == "트리거" and judgment_label in TRIGGER_JUDGMENTS


def prompt_kind(kind: str, judgment_label: Optional[str] = None) -> str:
    """일회성 프로세스의 `[카드] 종류=` 값(AC-FR9-23): 답변 · 고찰은 그대로, 트리거는 판단이 질문 → 답변,
    질문 없음 → 고찰, 이미 답이 나온 질문 → 이미 답이 나온 질문, 미확인 → 답변."""
    if kind != "트리거":
        return kind
    return {"질문 없음": "고찰", "이미 답이 나온 질문": "이미 답이 나온 질문"}.get(judgment_label or "", "답변")


def build_prompt(inp: DiagramInput) -> str:
    return "\n".join([
        "[요청] 종류=다이어그램",
        "아래 카드의 내용을 가장 잘 보여 주는 형식의 다이어그램을 diagram-design 스킬로 만든다.",
        "- 카드에 없는 사실, 수치, 인명을 더하지 않는다.",
        "- 다이어그램 안의 글은 %s 로 쓴다. 한국어이면 문어체의 짧은 명사구나 평서문이고, 다른 언어는 그 언어의 짧은 명사구나 평서문이다." % languages.english_name(inp.language),
        '- 파일은 "captures/diagrams/" 아래에만 만든다. 형식은 SVG 와 원본 HTML 이다.',
        "- 웹 글꼴을 쓰지 않고 시스템 글꼴만 쓴다. 외부 주소(`http://` · `https://`)로 글꼴 · 스타일 · 스크립트 · 이미지를 불러오지 않는다.",
        "- 마지막에 만든 파일의 이름을 한 줄로 알리는 외에는 설명을 쓰지 않는다.",
        "[카드]",
        "종류=%s" % inp.kind,
        "요청 시각=%s" % inp.ts,
        "질문=%s" % " ".join((inp.question or "").split()),
        "본문=" + (inp.body or ""),
    ])


def skill_state(plugin_dir) -> tuple:
    """(정상 여부, 사유). 사본이 없거나 깨졌으면 버튼을 비활성으로 둔다(AC-FR9-11)."""
    d = Path(plugin_dir)
    if not d.is_dir():
        return False, _t("diag.skill_state_407")
    pj = d / ".claude-plugin" / "plugin.json"
    try:
        json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, _t("diag.skill_state_408")
    skill = d / "skills" / "diagram-design" / "SKILL.md"
    try:
        if skill.stat().st_size <= 0:
            return False, _t("diag.skill_state_409")
    except OSError:
        return False, _t("diag.skill_state_409")
    return True, ""


# ---------------------------------------------------------------------------------------------
# 풀
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DiagramResult:
    card_n: int
    status: str                      # done | failed | violation | cancelled
    svg: Optional[Path] = None       # 절대 경로
    html: Optional[Path] = None
    rel: Optional[str] = None        # 세션 폴더 기준 상대 경로(svg)
    violations: tuple = ()
    error_kind: Optional[str] = None
    detail: str = ""


class Job:
    def __init__(self, card_n: int, inp: DiagramInput):
        self.card_n = card_n
        self.inp = inp
        self.before: set = set()
        self.root_before: set = set()      # 시작 때 세션 폴더 안의 모든 파일(상대 경로), AC-FR9-25
        self.start_mono = 0.0
        self.oneshot = None
        self.done = False
        self.cancelled = False

    @property
    def pid(self) -> Optional[int]:
        return getattr(self.oneshot, "pid", None)


class DiagramPool:
    """`oneshot_factory(**kw) -> OneShot`: kw 는 `cwd` · `effort` · `tools` · `plugin_dir` · `permission_mode` ·
    `settings_extra` · `timeout_s` · `purpose` · `system_prompt`(None) 이다."""

    def __init__(self, *, folder, plugin_dir, oneshot_factory: Callable, eventlog=None, session_log=None,
                 max_concurrent: int = MAX_CONCURRENT, timeout_s: float = TIMEOUT_S,
                 now_hms: Optional[Callable[[], str]] = None):
        self.folder = Path(folder)
        self.plugin_dir = Path(plugin_dir)
        self._factory = oneshot_factory
        self._log = eventlog
        self._session_log = session_log
        self.max_concurrent = max(1, int(max_concurrent))
        self._timeout = timeout_s
        self._now = now_hms or (lambda: time.strftime("%H:%M:%S"))
        self._mu = threading.Lock()
        self._jobs: dict = {}               # card_n → Job (진행 중)
        self._claimed: set = set()          # 이미 결과로 가져간 파일 이름
        self.out_dir = self.folder / DIAGRAM_DIR

    # ---- 조회 ----
    def active_count(self) -> int:
        with self._mu:
            return len(self._jobs)

    def is_busy(self, card_n: int) -> bool:
        with self._mu:
            return card_n in self._jobs

    def can_start(self, card_n: int) -> tuple:
        ok, why = skill_state(self.plugin_dir)
        if not ok:
            return False, why
        with self._mu:
            if card_n in self._jobs:
                return False, _t("diag.can_start_410")
            if len(self._jobs) >= self.max_concurrent:
                return False, _t("diag.can_start_411") % self.max_concurrent
        return True, ""

    # ---- 시작 · 취소 ----
    def submit(self, inp: DiagramInput, on_done: Callable[[DiagramResult], None]) -> Optional[Job]:
        ok, _why = self.can_start(inp.card_n)
        if not ok:
            return None
        job = Job(inp.card_n, inp)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        job.before = self._listing()
        job.root_before = self._tree()
        job.start_mono = time.monotonic()
        allow = ["Edit(/%s/**)" % str(self.out_dir.resolve()), "Read(/%s/**)" % str(self.plugin_dir.resolve())]
        with self._mu:
            if inp.card_n in self._jobs or len(self._jobs) >= self.max_concurrent:
                return None
            self._jobs[inp.card_n] = job
        try:
            job.oneshot = self._factory(
                cwd=str(self.folder), effort=EFFORT, tools=TOOLS, plugin_dir=str(self.plugin_dir.resolve()),
                permission_mode="dontAsk", settings_extra={"permissions": {"allow": allow}},
                timeout_s=self._timeout, purpose="diagram", system_prompt=None)
            started = job.oneshot.run(build_prompt(inp), lambda o: self._on_outcome(job, o, on_done))
        except Exception as e:
            self._emit("diagram_end", n=inp.card_n, status=FAILED, error_kind="io", detail=type(e).__name__)
            with self._mu:
                self._jobs.pop(inp.card_n, None)
            on_done(DiagramResult(inp.card_n, FAILED, error_kind="io", detail=_t("diag.submit_412")))
            return job
        self._emit("diagram_start", n=inp.card_n, pid=job.pid, started=bool(started))
        return job

    def cancel(self, card_n: int) -> bool:
        """그 카드의 프로세스를 PID 로 종료한다. 이미 만든 파일은 지우지 않는다(AC-FR9-17)."""
        with self._mu:
            job = self._jobs.get(card_n)
        if job is None:
            return False
        job.cancelled = True
        job.oneshot.cancel()
        return True

    def cancel_all(self) -> int:
        """세션 종료(AC-FR11-4): 모든 진행 중 작업의 프로세스를 끝내고 덜 만든 파일을 지운다."""
        with self._mu:
            jobs = list(self._jobs.values())
        for j in jobs:
            j.cancelled = True
            try:
                j.oneshot.cancel()
            except Exception:
                pass
        # 프로세스가 끝난 뒤(콜백이 `_jobs` 를 비운다) 남은 새 파일을 지운다
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and self.active_count():
            time.sleep(0.02)
        # 가장 이른 작업의 시작 전 목록이 기준이다(교집합). 둘째 작업의 `before` 에는 첫째의 덜 만든 파일이 들어 있다(D-053)
        self._remove_partial(set.intersection(*[set(j.before) for j in jobs]) if jobs else set())
        return len(jobs)

    # ---- 내부 ----
    def _listing(self) -> set:
        try:
            return {p.name for p in self.out_dir.iterdir() if p.is_file()}
        except OSError:
            return set()

    def _tree(self) -> set:
        """세션 폴더 아래 모든 파일의 상대 경로(허용된 위치 `captures/diagrams/` 는 제외한다)."""
        out = set()
        try:
            base = self.folder
            for p in base.rglob("*"):
                try:
                    if not p.is_file():
                        continue
                    rel = p.relative_to(base)
                except (OSError, ValueError):
                    continue
                if rel.parts[:2] == ("captures", "diagrams"):
                    continue
                out.add(rel.as_posix())
        except OSError:
            pass
        return out

    def _outside_files(self, job: Job) -> list:
        """생성 중 `captures/diagrams/` 밖에 새로 생긴 파일: ⒜ 세션 폴더 바로 아래의 새 파일, ⒝ 위치와 관계없는 새 .svg · .html.
        점으로 시작하는 파일(`.DS_Store` 등 운영체제의 메타데이터)은 대상이 아니다(AC-FR9-25, W-29 · W-32)."""
        new = self._tree() - job.root_before
        out = []
        for rel in sorted(new):
            parts = rel.split("/")
            if parts[-1].startswith("."):
                continue
            if len(parts) == 1 or rel.lower().endswith(OUTSIDE_SUFFIXES):
                out.append(rel)
        return out

    def _remove_partial(self, before: set) -> None:
        with self._mu:
            claimed = set(self._claimed)
        for n in self._listing() - before - claimed:
            try:
                (self.out_dir / n).unlink()
            except OSError:
                pass

    def _pick(self, job: Job, text: str) -> Optional[Path]:
        """결과 파일. 완료 줄의 이름을 믿지 않고 파일의 존재로 확인한다. 이름이 없으면 새 .svg 하나로 대신한다."""
        m = re.search(r"([^\s/\\:]+\.svg)\b", text or "")
        if m and (self.out_dir / m.group(1)).is_file():
            return self.out_dir / m.group(1)
        with self._mu:
            claimed = set(self._claimed)
        new = [self.out_dir / n for n in sorted(self._listing() - job.before - claimed) if n.lower().endswith(".svg")]
        if not new:
            return None
        return max(new, key=lambda p: p.stat().st_mtime)

    def _on_outcome(self, job: Job, o, on_done) -> None:
        n = job.card_n
        res = self._resolve(job, o)
        with self._mu:
            self._jobs.pop(n, None)
            for f in (res.svg, res.html):
                if f is not None:
                    self._claimed.add(f.name)
        job.done = True
        if res.status == CANCELLED:
            with self._mu:
                others = bool(self._jobs)
            if not others:
                self._remove_partial(job.before)
        else:
            self._record(res)
        if res.status == OUTSIDE:
            self._emit("diagram_outside_file", n=n, reason=REASON_OUTSIDE, rel=list(res.violations))
        if res.status == VIOLATION:
            self._emit("diagram_violation", n=n, rel=res.rel, count=len(res.violations),
                       locations=[v[:80] for v in res.violations[:5]])
        self._emit("diagram_end", n=n, status=res.status, error_kind=res.error_kind,
                   violations=len(res.violations), rel=res.rel)
        try:
            on_done(res)
        except Exception:
            pass

    def _resolve(self, job: Job, o) -> DiagramResult:
        n = job.card_n
        if job.cancelled or getattr(o, "cancelled", False):
            return DiagramResult(n, CANCELLED)
        outside = self._outside_files(job)
        if outside:
            # 그 파일은 지우지 않는다. 카드에는 표시하지 않고 사유와 [다시 만들기] 를 둔다(AC-FR9-25)
            return DiagramResult(n, OUTSIDE, violations=tuple(outside[:5]), error_kind="outside_file", detail=REASON_OUTSIDE)
        if not o.ok:
            return DiagramResult(n, FAILED, error_kind=o.error_kind or "unknown", detail=(o.detail or "")[:200])
        svg = self._pick(job, o.text)
        if svg is None:
            return DiagramResult(n, FAILED, error_kind="no_file", detail=_t("diag.resolve_413"))
        html_path = svg.with_suffix(".html")
        html_p = html_path if html_path.is_file() else None
        viol = tuple(check_external_refs(svg) + (check_external_refs(html_p) if html_p else []))
        rel = "%s/%s" % (DIAGRAM_DIR, svg.name)
        if viol:
            return DiagramResult(n, VIOLATION, svg=svg, html=html_p, rel=rel, violations=viol,
                                 error_kind="external_ref", detail=REASON_VIOLATION)
        return DiagramResult(n, DONE, svg=svg, html=html_p, rel=rel)

    def _record(self, res: DiagramResult) -> None:
        label = RESULT_LABEL.get(res.status)
        if label is None or self._session_log is None:
            return              # 취소는 기록하지 않는다
        try:
            # 실패는 만든 파일이 없으므로 `path` 가 빈 문자열이다(AC-FR9-24, 키는 항상 있다)
            self._session_log.append("diagram", n=res.card_n, path=res.rel or "", result=label, ts=self._now())
        except Exception:
            pass

    def _emit(self, type_: str, **f) -> None:
        if self._log is not None:
            try:
                self._log.emit(type_, **f)
            except Exception:
                pass
