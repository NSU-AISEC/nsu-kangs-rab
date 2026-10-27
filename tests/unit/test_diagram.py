"""K-15 core/diagram.py: 외부 주소 검사 표, 풀(동시 상한 · 카드별 하나 · 취소 · 파일 확인), 사본 검사."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from nsu_kangs_rab.core import diagram as D
from nsu_kangs_rab.core.oneshot import Outcome

ROOT = Path(__file__).resolve().parents[2]
SVG_NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'


def svg(body="", ns=SVG_NS):
    return '<svg %s viewBox="0 0 10 10">%s</svg>' % (ns, body)


class CheckRefsTest(unittest.TestCase):
    def v(self, text):
        return D.check_external_refs_text(text)

    def test_allowed(self):
        self.assertEqual(self.v(svg('<text x="1" y="2">자세한 것은 https://example.com 을 본다</text>')), [])
        self.assertEqual(self.v(svg()), [])
        self.assertEqual(self.v(svg('<use xlink:href="#a"/><rect fill="url(#g)"/>')), [])
        self.assertEqual(self.v('<html><body><svg %s></svg></body></html>' % SVG_NS), [])

    def test_violations(self):
        cases = {
            "image href": svg('<image href="https://x.example/a.png"/>'),
            "xlink href": svg('<image xlink:href="HTTPS://x.example/a.png"/>'),
            "charref": svg('<image href="&#104;ttps://x.example/a.png"/>'),
            "percent": svg('<image href="%68ttps://x.example/a.png"/>'),
            "script fetch": svg('<script>fetch("https://x.example/")</script>'),
            "script import": svg('<script><![CDATA[ import("http://x.example/m.js") ]]></script>'),
            "css url": svg('<style>.a{background:url("https://x.example/b.png")}</style>'),
            "css import": svg("<style>@import 'https://x.example/s.css';</style>"),
            "style attr": svg('<rect style="fill:url(https://x.example/p)"/>'),
            "link tag": '<html><head><link rel="stylesheet" href="https://x.example/s.css"></head></html>',
            "ns plus attr": '<svg xmlns="http://www.w3.org/2000/svg"><image href="http://x.example/a"/></svg>',
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertTrue(self.v(text), name)

    def test_protocol_relative_only_in_css(self):
        self.assertTrue(self.v(svg('<style>.a{background:url(//x.example/b.png)}</style>')))
        self.assertEqual(self.v(svg('<text>//x.example</text>')), [])

    def test_file_unreadable_is_violation(self):
        self.assertTrue(D.check_external_refs("/nonexistent/x.svg"))

    def test_bundled_copy_templates_pass_xmlns_only(self):
        # 앱에 포함한 사본의 예시 하나(원 판의 템플릿)도 글꼴 링크가 없으므로 속성 위반이 없어야 한다
        ex = next((ROOT / "third_party" / "diagram-design" / "skills" / "diagram-design" / "assets").glob("example-*.html"), None)
        if ex is None:
            self.skipTest("사본이 없다")
        self.assertFalse([x for x in D.check_external_refs(ex) if "fonts." in x])


class OutsideFilesTest(unittest.TestCase):  # AC-FR9-25, W-29 · W-32
    def _outside(self, before, after):
        from types import SimpleNamespace
        fake = SimpleNamespace(_tree=lambda: set(after))
        return D.DiagramPool._outside_files(fake, SimpleNamespace(root_before=set(before)))

    def test_scope_of_outside_files(self):
        got = self._outside({"session.jsonl"}, {
            "session.jsonl",              # 세션 시작 때 있던 앱 기록 파일
            "x.txt",                      # ⒜ 세션 폴더 바로 아래의 새 파일
            ".DS_Store",                  # 운영체제 메타데이터
            "sub/note.txt",               # 하위 폴더의 .svg · .html 이 아닌 파일
            "sub/new.svg",                # ⒝
            "deep/a/b.html",              # ⒝
            "sub/.hidden.html",           # 점으로 시작하는 파일은 ⒝ 에도 대상이 아니다(W-32)
            "sub/._x.svg",
        })
        self.assertEqual(got, ["deep/a/b.html", "sub/new.svg", "x.txt"])


class PromptTest(unittest.TestCase):
    def test_prompt_format(self):
        p = D.build_prompt(D.DiagramInput(3, "답변", "14:31:40", "정규화란 무엇인가", "본문 첫 줄\n[줄머리 대괄호]\n끝"))
        lines = p.split("\n")
        self.assertEqual(lines[0], "[요청] 종류=다이어그램")
        self.assertIn("[카드]", lines)
        self.assertEqual(lines[lines.index("[카드]") + 1:lines.index("[카드]") + 4],
                         ["종류=답변", "요청 시각=14:31:40", "질문=정규화란 무엇인가"])
        self.assertTrue(p.endswith("본문=본문 첫 줄\n[줄머리 대괄호]\n끝"))

    def test_can_diagram(self):
        self.assertTrue(D.can_diagram("답변"))
        self.assertTrue(D.can_diagram("고찰"))
        self.assertTrue(D.can_diagram("트리거", "이미 답이 나온 질문"))
        for label in ("질문", "질문 없음", "이미 답이 나온 질문", "미확인"):     # AC-FR9-23 (D-049)
            self.assertTrue(D.can_diagram("트리거", label), label)
        self.assertFalse(D.can_diagram("트리거", None))
        for k in ("요약", "자유질의", "화면메모"):
            self.assertFalse(D.can_diagram(k, "질문"))

    def test_prompt_kind_mapping(self):  # AC-FR9-23
        self.assertEqual(D.prompt_kind("답변"), "답변")
        self.assertEqual(D.prompt_kind("고찰"), "고찰")
        self.assertEqual(D.prompt_kind("트리거", "질문"), "답변")
        self.assertEqual(D.prompt_kind("트리거", "질문 없음"), "고찰")
        self.assertEqual(D.prompt_kind("트리거", "이미 답이 나온 질문"), "이미 답이 나온 질문")
        self.assertEqual(D.prompt_kind("트리거", "미확인"), "답변")
        self.assertFalse(D.can_diagram("화면메모"))
        self.assertFalse(D.can_diagram("오류"))


class SkillStateTest(unittest.TestCase):
    def test_real_copy_ok(self):
        ok, why = D.skill_state(ROOT / "third_party" / "diagram-design")
        self.assertTrue(ok, why)

    def test_missing_and_broken(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse(D.skill_state(Path(t) / "none")[0])
            d = Path(t) / "p"
            (d / ".claude-plugin").mkdir(parents=True)
            (d / ".claude-plugin" / "plugin.json").write_text("{ broken")
            self.assertFalse(D.skill_state(d)[0])


class FakeOneShot:
    """가짜 일회성 프로세스: `script` 가 파일을 쓰고 결과를 정한다. `hold` 이면 취소될 때까지 기다린다."""
    instances: list = []

    def __init__(self, folder, script, hold=False, **kw):
        self.kw, self.folder, self.script, self.hold = kw, Path(folder), script, hold
        self.pid = 5000 + len(FakeOneShot.instances)
        self.prompt = None
        self.cancelled = False
        self._cb = None
        self._done = threading.Event()
        FakeOneShot.instances.append(self)

    def run(self, prompt, on_done):
        self.prompt, self._cb = prompt, on_done
        if self.hold:
            return True
        threading.Thread(target=self._go, daemon=True).start()
        return True

    def _go(self):
        out = self.script(self.folder / "captures" / "diagrams")
        self._finish(out)

    def _finish(self, o):
        if self._done.is_set():
            return
        self._done.set()
        self._cb(o)

    def cancel(self):
        self.cancelled = True
        d = self.folder / "captures" / "diagrams"
        (d / "partial.svg").write_text("<svg")          # 덜 만든 파일
        threading.Thread(target=lambda: self._finish(Outcome(False, cancelled=True)), daemon=True).start()


def ok_script(name="a.svg", body=None):
    def f(d):
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body or svg('<text>가</text>'), encoding="utf-8")
        (d / name.replace(".svg", ".html")).write_text("<html></html>", encoding="utf-8")
        return Outcome(True, text="완료: %s" % name)
    return f


class PoolTest(unittest.TestCase):
    def setUp(self):
        FakeOneShot.instances.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.events, self.records = [], []

        class Ev:
            def emit(s, t, **f):
                self.events.append((t, f))

        class Log:
            def append(s, t, **f):
                self.records.append((t, f))

        self.mk_script = ok_script()
        self.holds = False
        self.pool = D.DiagramPool(folder=self.folder, plugin_dir=ROOT / "third_party" / "diagram-design",
                                  oneshot_factory=self.factory, eventlog=Ev(), session_log=Log(),
                                  now_hms=lambda: "14:00:00")

    def factory(self, **kw):
        return FakeOneShot(self.folder, self.mk_script, hold=self.holds, **kw)

    def inp(self, n=1):
        return D.DiagramInput(n, "답변", "14:00:00", "질문", "본문")

    def run_one(self, n=1):
        got = []
        ev = threading.Event()
        self.pool.submit(self.inp(n), lambda r: (got.append(r), ev.set()))
        self.assertTrue(ev.wait(5))
        return got[0]

    def test_success_records_and_claims(self):
        r = self.run_one()
        self.assertEqual(r.status, D.DONE)
        self.assertEqual(r.rel, "captures/diagrams/a.svg")
        self.assertTrue(r.html.is_file())
        self.assertEqual(self.records, [("diagram", {"n": 1, "path": "captures/diagrams/a.svg", "result": "완료", "ts": "14:00:00"})])
        kw = FakeOneShot.instances[0].kw
        self.assertEqual(kw["effort"], "medium")
        self.assertEqual(kw["tools"], ("Skill", "Read", "Write"))
        self.assertEqual(kw["permission_mode"], "dontAsk")
        self.assertIsNone(kw["system_prompt"])
        allow = kw["settings_extra"]["permissions"]["allow"]
        self.assertTrue(allow[0].startswith("Edit(//") and allow[0].endswith("/captures/diagrams/**)"))
        self.assertTrue(allow[1].startswith("Read(//") and "diagram-design" in allow[1])
        self.assertEqual(kw["timeout_s"], 180.0)
        self.assertEqual(kw["cwd"], str(self.folder))
        self.assertTrue(FakeOneShot.instances[0].prompt.startswith("[요청] 종류=다이어그램"))

    def test_violation_keeps_file_and_logs(self):
        self.mk_script = ok_script("v.svg", svg('<image href="https://x.example/a.png"/>'))
        r = self.run_one()
        self.assertEqual(r.status, D.VIOLATION)
        self.assertTrue((self.folder / "captures/diagrams/v.svg").exists())
        self.assertEqual(self.records[0][1]["result"], "외부 자원 위반")
        self.assertIn("diagram_violation", [e[0] for e in self.events])

    def test_failure_records_failed_with_empty_path(self):  # AC-FR9-24
        self.mk_script = lambda d: Outcome(False, error_kind="timeout", detail="시간 초과")
        r = self.run_one()
        self.assertEqual((r.status, r.error_kind), (D.FAILED, "timeout"))
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.records[0][0], "diagram")
        self.assertEqual({k: self.records[0][1][k] for k in ("n", "path", "result")},
                         {"n": 1, "path": "", "result": "실패"})

    def test_no_file_is_failure_not_trusting_done_line(self):
        self.mk_script = lambda d: Outcome(True, text="완료: ghost.svg")
        r = self.run_one()
        self.assertEqual((r.status, r.error_kind), (D.FAILED, "no_file"))

    def test_html_without_suffix_name_in_text_uses_new_file(self):
        self.mk_script = lambda d: (ok_script("b.svg")(d), Outcome(True, text="끝"))[1]
        r = self.run_one()
        self.assertEqual(r.status, D.DONE)
        self.assertEqual(r.svg.name, "b.svg")

    def test_same_card_once_and_limit_three(self):
        self.holds = True
        for n in (1, 2, 3):
            self.assertIsNotNone(self.pool.submit(self.inp(n), lambda r: None))
        self.assertIsNone(self.pool.submit(self.inp(1), lambda r: None))      # 같은 카드
        ok, why = self.pool.can_start(4)
        self.assertFalse(ok)
        self.assertIn("3개", why)
        self.assertEqual(len(FakeOneShot.instances), 3)                        # 호출 수가 늘지 않는다
        self.assertEqual(self.pool.active_count(), 3)
        self.assertTrue(self.pool.cancel(2))
        for _ in range(100):
            if self.pool.active_count() == 2:
                break
            time.sleep(0.02)
        self.assertTrue(self.pool.can_start(4)[0])
        self.pool.cancel_all()

    def test_cancel_one_keeps_finished_files_and_other_partial(self):
        r = self.run_one(1)
        self.assertEqual(r.status, D.DONE)
        self.holds = True
        got = []
        self.pool.submit(self.inp(2), got.append)
        self.pool.submit(self.inp(3), got.append)
        self.assertTrue(self.pool.cancel(2))
        for _ in range(100):
            if self.pool.active_count() == 1:
                break
            time.sleep(0.02)
        self.assertTrue((self.folder / "captures/diagrams/a.svg").exists())   # 완료한 파일은 남는다
        self.assertTrue((self.folder / "captures/diagrams/partial.svg").exists())   # 다른 작업이 진행 중이면 지우지 않는다
        self.pool.cancel_all()

    def test_cancel_all_removes_partial_files(self):
        self.run_one(1)
        self.holds = True
        self.pool.submit(self.inp(2), lambda r: None)
        self.assertEqual(self.pool.cancel_all(), 1)
        d = self.folder / "captures/diagrams"
        self.assertTrue((d / "a.svg").exists())
        self.assertFalse((d / "partial.svg").exists())
        self.assertEqual(self.pool.active_count(), 0)

    def test_skill_broken_blocks(self):
        p = D.DiagramPool(folder=self.folder, plugin_dir=self.folder / "none", oneshot_factory=self.factory)
        ok, why = p.can_start(1)
        self.assertFalse(ok)
        self.assertIn("사본", why)
        self.assertIsNone(p.submit(self.inp(), lambda r: None))


if __name__ == "__main__":
    unittest.main()
