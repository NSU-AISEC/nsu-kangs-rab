"""K-16: 종료 흐름 · 일회성 프로세스 (가짜 `claude` 만 쓴다; AC-FR13-5 ~ 9 · 14, AC-FR1-19 의 정리 문서 프로세스)."""
import json
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import cleanup_doc, endflow, llm  # noqa: E402
from nsu_kangs_rab.core.oneshot import OneShot  # noqa: E402
from nsu_kangs_rab.core.procs import Procs  # noqa: E402
from nsu_kangs_rab.core.types import Result, TextDelta  # noqa: E402

FAKE = ROOT / "tests" / "unit" / "fake_claude_k03.py"
HEADER = {"type": "header", "v": 1, "date": "2026-10-09", "provider": "claude_subscription", "model": "sonnet",
          "effort": "medium", "source": "시스템 사운드", "materials": [], "kind": "수업", "title": "수업",
          "number": "01", "mode": "대면", "start": "10:00:00"}


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.d = Path(self.td.name)
        self.folder = self.d / "2026-10-09"
        self.folder.mkdir()
        evs = [HEADER, {"type": "segment", "n": 1, "start": "10:00:05", "end": "10:00:07", "text": "본문"},
               {"type": "end", "ts": "10:30:00"}]
        (self.folder / "session.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in evs) + "\n",
                                                   encoding="utf-8")
        self.log = self.d / "fake.jsonl"
        self.procs = Procs()
        self.done = []
        self.cv = threading.Event()

    def wrapper(self, **fake):
        p = self.d / "claude"
        flags = ["--fake-log", str(self.log)]
        for k, v in fake.items():
            flags += ["--fake-" + k.replace("_", "-"), str(v)]
        p.write_text("#!/bin/sh\nexec %s %s %s \"$@\"\n" % (sys.executable, FAKE, " ".join("'%s'" % f for f in flags)))
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
        return str(p)

    def oneshot(self, claude, **kw):
        return OneShot(claude_path=claude, model="sonnet", auth=llm.Auth.SUBSCRIPTION, parent_env={"PATH": "/usr/bin:/bin"},
                       procs=self.procs, cwd=str(self.folder), run_dir=str(self.d / "run"), system_prompt="규칙", **kw)

    def on_done(self, r):
        self.done.append(r)
        self.cv.set()

    def wait(self, t=10.0):
        self.assertTrue(self.cv.wait(t), "종료 흐름이 끝나지 않았다")
        return self.done[0]

    def fake_log(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []


class HistoryLessTest(Base):
    def run_flow(self, claude, **kw):
        ef = endflow.EndFlow(folder=self.folder, doc_kind="수업", template="TEMPLATE-X")
        view = endflow.view_of(self.folder)
        shot = self.oneshot(claude, **kw)
        self.assertTrue(ef.run_history_less(view, shot, self.on_done))
        return ef

    def test_success_saves_document_and_args(self):  # AC-FR13-14 · AC-FR1-19
        self.run_flow(self.wrapper())
        r = self.wait()
        self.assertEqual(r.status, endflow.DONE, r)
        self.assertEqual(r.path.name, "lecture.md")
        self.assertEqual(r.path.read_text(encoding="utf-8").strip(), "ok")
        start = next(x for x in self.fake_log() if x["kind"] == "start")["argv"]
        self.assertEqual(start[start.index("--effort") + 1], "high")
        self.assertEqual(start.count("--settings"), 1)
        self.assertIn("--no-session-persistence", start)
        self.assertNotIn("--bare", start)
        self.assertIn("--system-prompt-file", start)
        msgs = [x["text"] for x in self.fake_log() if x["kind"] == "msg"]
        self.assertEqual(msgs[0], "/effort high")
        self.assertIn("[요청] 종류=정리문서 문서=수업 이력=없음", msgs[1])
        self.assertTrue(msgs[1].rstrip().endswith("TEMPLATE-X"))
        self.assertEqual(self.procs.live(), [])         # 프로세스가 남지 않는다

    def test_failure_keeps_session_log_and_rebuild_works(self):  # AC-FR13-8
        self.run_flow(self.wrapper(mode="rate_limit"))
        r = self.wait()
        self.assertEqual(r.status, endflow.FAILED)
        self.assertTrue((self.folder / "session.jsonl").exists())
        self.assertFalse((self.folder / "lecture.md").exists())
        self.done.clear()
        self.cv.clear()
        self.log.unlink()
        self.run_flow(self.wrapper())
        self.assertEqual(self.wait().status, endflow.DONE)

    def test_does_not_overwrite_existing_document(self):  # AC-FR13-14
        (self.folder / "lecture.md").write_text("기존", encoding="utf-8")
        self.run_flow(self.wrapper())
        r = self.wait()
        self.assertEqual(r.path.name, "lecture-2.md")
        self.assertEqual((self.folder / "lecture.md").read_text(encoding="utf-8"), "기존")

    def test_cancel_kills_by_pid_and_leaves_no_document(self):  # AC-FR13-5
        ef = self.run_flow(self.wrapper(mode="hang"))
        end = time.monotonic() + 5
        while time.monotonic() < end and not self.fake_log():
            time.sleep(0.02)
        ef.cancel()
        r = self.wait()
        self.assertEqual(r.status, endflow.CANCELLED)
        self.assertFalse((self.folder / "lecture.md").exists())
        end = time.monotonic() + 5
        while time.monotonic() < end and self.procs.live():
            time.sleep(0.05)
        self.assertEqual(self.procs.live(), [])

    def test_timeout(self):
        self.run_flow(self.wrapper(mode="hang"), timeout_s=0.5)
        r = self.wait()
        self.assertEqual((r.status, r.kind), (endflow.FAILED, "timeout"))


class FakeManager:
    def __init__(self, busy=False):
        self.busy = busy

    def in_flight(self):
        return 5 if self.busy else None

    def queue_numbers(self):
        return []


class FakeModel:
    def __init__(self, rt, effort_ok=True):
        self.rt, self.sent, self.efforts, self.effort_ok = rt, [], [], effort_ok

    def set_effort(self, level):
        self.efforts.append(level)
        if self.effort_ok:
            self.rt.on_model_event(Result(True, text="(command)", num_turns=0))
        return True

    def send(self, msg):
        self.sent.append(msg.blocks[0]["text"])
        self.rt.on_model_event(TextDelta("정리"))
        self.rt.on_model_event(Result(True, text="# 정리 문서", num_turns=1))
        return True

    def interrupt(self):
        return "x"


class FakeRuntime:
    def __init__(self, busy=False):
        self.manager = FakeManager(busy)
        self.model = FakeModel(self)
        self._listener = None
        self.forwarded = []

    def set_listener(self, fn):
        self._listener = fn

    def on_model_event(self, ev):
        if self._listener:
            self._listener(ev)
        else:
            self.forwarded.append(ev)


class ResidentTest(Base):
    def flow(self, rt, effort="medium"):
        ef = endflow.EndFlow(folder=self.folder, doc_kind="수업", template="T")
        self.assertTrue(ef.run_resident(rt, endflow.view_of(self.folder), effort, self.on_done))
        return ef

    def test_effort_high_then_request_then_save(self):  # AC-FR13-5 · 6 · 7
        rt = FakeRuntime()
        self.flow(rt)
        r = self.wait()
        self.assertEqual(r.status, endflow.DONE)
        self.assertEqual(rt.model.efforts, ["high"])
        self.assertTrue(rt.model.sent[0].startswith("[요청] 종류=정리문서 문서=수업\n"))
        self.assertNotIn("이력=없음", rt.model.sent[0])
        self.assertEqual(r.path.read_text(encoding="utf-8").strip(), "# 정리 문서")
        self.assertIsNone(rt._listener)                 # 해제했다
        self.assertEqual(rt.forwarded, [])

    def test_no_effort_switch_when_already_high(self):
        rt = FakeRuntime()
        self.flow(rt, effort="high")
        self.assertEqual(self.wait().status, endflow.DONE)
        self.assertEqual(rt.model.efforts, [])

    def test_busy_manager_is_detected(self):
        ef = endflow.EndFlow(folder=self.folder, doc_kind="수업", template="T")
        self.assertFalse(ef.can_use_resident(FakeRuntime(busy=True)))
        self.assertTrue(ef.can_use_resident(FakeRuntime()))

    def test_template_setting_is_used(self):  # AC-FR13-9
        self.assertEqual(endflow.template_for({"templates": {"lecture": "내 템플릿"}}, "수업"), "내 템플릿")
        self.assertNotEqual(endflow.template_for({}, "수업"), endflow.template_for({}, "회의"))
        self.assertIn("# <과목명>", endflow.template_for({"templates": {"lecture": " "}}, "수업"))


if __name__ == "__main__":
    unittest.main()
