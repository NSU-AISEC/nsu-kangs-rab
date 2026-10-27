"""K-07 통합: 실제 `ModelSession` + 가짜 `claude`(hang 모드)로 숨긴 응답 상한의 interrupt 경로 (모델 호출 없음)."""
import os
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src" / "mac"))

from test_model_session import Base, msg  # noqa: E402,F401
from nsu_kangs_rab.core import requests as R  # noqa: E402
from nsu_kangs_rab.core.transcript import Transcript  # noqa: E402
from nsu_kangs_rab.core.types import Segment  # noqa: E402


def wait_for(pred, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


class Log:
    def __init__(self):
        self.ev = []

    def emit(self, t, **f):
        self.ev.append((t, f))
        return True

    def of(self, t):
        return [f for (x, f) in self.ev if x == t]


class HiddenInterrupt(Base):
    def make_session(self, hidden_s, ack_s, **fake):
        """`ModelSession` 은 생성할 때 `on_event` 를 받으므로 관리자를 늦게 연결하는 중계를 둔다."""
        holder = {}

        def relay(ev):
            self.on_event(ev)
            m = holder.get("m")
            if m is not None:
                m.on_model_event(ev)
        path = self.wrapper(mode="hang", **fake)
        from nsu_kangs_rab.core import llm
        from nsu_kangs_rab.core.model_session import ModelSession
        cfg = llm.SessionConfig(claude_path=path, model="sonnet", effort="medium")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.d)}
        s = ModelSession(cfg, llm.Auth.SUBSCRIPTION, relay, procs=self.procs, parent_env=env, cwd=str(self.d),
                         stdin_wait_s=1.0, term_wait_s=1.0)
        self.sessions.append(s)
        self.mgr_log, self.tr = Log(), Transcript()
        self.m = R.RequestManager(s, R.Composer(self.tr), eventlog=self.mgr_log, hidden_limit_s=hidden_s,
                                  interrupt_ack_s=ack_s)
        holder["m"] = self.m
        self.addCleanup(self.m.close)
        s.start()
        return s

    def msgs(self):
        return [r for r in self.fake_log() if r["kind"] == "msg" and not r["text"].startswith("/")]

    def test_ack_path_interrupt_without_restart(self):  # AC-FR9-18 ⒝
        s = self.make_session(0.2, 5.0)
        pid0 = s.pid
        a = self.m.submit(R.Request("자유질의", input="긴 질문"))
        self.assertTrue(wait_for(lambda: len(self.msgs()) == 1))
        self.m.delete_card(a.n)
        self.assertTrue(wait_for(lambda: self.mgr_log.of("request_interrupted")))
        self.assertTrue(wait_for(lambda: [r for r in self.fake_log() if r["kind"] == "control"]))
        ctl = [r for r in self.fake_log() if r["kind"] == "control"][0]["msg"]
        self.assertEqual(ctl["request"], {"subtype": "interrupt", "cancel_queued": True})
        self.assertTrue(wait_for(lambda: self.m.in_flight() is None))
        self.assertEqual(self.mgr_log.of("request_restart"), [])
        self.assertEqual(s.pid, pid0)
        self.assertEqual(self.m.cards(), [])
        d = self.mgr_log.of("request_done")[0]
        self.assertEqual((d["hidden"], d["interrupted"], d["ok"]), (True, True, False))

    def test_no_ack_path_kills_pid_and_restarts(self):  # AC-FR9-18 ⒞ · AC-FR8-6
        s = self.make_session(0.2, 0.3, no_ack=1)
        self.tr.add(Segment(1, "2026-10-11T14:00:00.000+09:00", "2026-10-11T14:00:05.000+09:00", 0.0, 5.0, "본문"))
        pid0 = s.pid
        a = self.m.submit(R.Request("자유질의", input="첫 질문"))
        b = self.m.submit(R.Request("자유질의", input="둘째 질문"))
        self.assertTrue(wait_for(lambda: len(self.msgs()) == 1))
        self.m.delete_card(a.n)
        self.assertTrue(wait_for(lambda: self.mgr_log.of("request_restart"), 10.0))
        r = self.mgr_log.of("request_restart")[0]
        self.assertEqual((r["reason"], r["old_pid"], r["ok"]), ("interrupt_timeout", pid0, True))
        self.assertNotEqual(r["new_pid"], pid0)
        self.assertTrue(wait_for(lambda: len(self.msgs()) == 2))      # 대기하던 요청이 새 프로세스로 간다
        self.assertIn("[재전송]", self.msgs()[1]["text"])               # 전사 전체를 다시 보낸다
        self.assertEqual(self.m.in_flight(), b.n)
        try:
            os.kill(pid0, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        self.assertFalse(alive)                                        # 기록한 PID 의 프로세스가 끝났다


if __name__ == "__main__":
    unittest.main()
