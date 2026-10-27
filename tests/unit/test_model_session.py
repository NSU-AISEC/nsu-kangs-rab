"""K-03: 상주 프로세스의 실행 · 입출력 · 종료 · 인증 출처 검사 · 오류 분류 (가짜 `claude` 만 쓴다)."""
from dataclasses import replace
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import claude_locator, eventlog, llm, stream  # noqa: E402
from nsu_kangs_rab.core.model_session import ModelSession  # noqa: E402
from nsu_kangs_rab.core.procs import Procs  # noqa: E402
from nsu_kangs_rab.core.types import (Compacted, Compacting, ControlResponse, Error, Init, OutgoingMessage,  # noqa: E402
                                       ProcessExited, Result, TextDelta)

FAKE = ROOT / "tests" / "unit" / "fake_claude_k03.py"
KEY = "sk-ant-test-KEYKEYKEY"


def msg(text, n=1):
    return OutgoingMessage(n, ({"type": "text", "text": text},))


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.log_file = self.d / "fake.jsonl"
        self.events: list = []
        self.cv = threading.Condition()
        self.sessions: list = []
        self.procs = Procs()

    def tearDown(self):
        for s in self.sessions:
            s.close()
        self.td.cleanup()

    def wrapper(self, **fake):
        """`#!` 스크립트 형태의 가짜 `claude`. 반환: 경로."""
        p = self.d / ("claude-%d" % len(list(self.d.glob("claude-*"))))
        flags = ["--fake-log", str(self.log_file)]
        for k, v in fake.items():
            flags += ["--fake-" + k.replace("_", "-"), str(v)]
        p.write_text("#!/bin/sh\nexec %s %s %s \"$@\"\n" % (sys.executable, FAKE, " ".join("'%s'" % f for f in flags)))
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
        return str(p)

    def on_event(self, ev):
        with self.cv:
            self.events.append(ev)
            self.cv.notify_all()

    def wait_for(self, pred, timeout=8.0):
        end = time.monotonic() + timeout
        with self.cv:
            while True:
                for e in self.events:
                    if pred(e):
                        return e
                left = end - time.monotonic()
                if left <= 0:
                    self.fail("사건을 기다리다 시간 초과: %r" % (self.events,))
                self.cv.wait(left)

    def session(self, path, auth=llm.Auth.SUBSCRIPTION, key=None, parent_env=None, cfg_kw=None, **kw):
        cfg = llm.SessionConfig(claude_path=path, model="sonnet", effort="medium", **(cfg_kw or {}))
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.d)}
        env.update(parent_env or {})
        s = ModelSession(cfg, auth, self.on_event, procs=self.procs, parent_env=env, cwd=str(self.d), api_key=key,
                         stdin_wait_s=kw.pop("stdin_wait_s", 1.0), term_wait_s=kw.pop("term_wait_s", 1.0), **kw)
        self.sessions.append(s)
        return s

    def fake_log(self):
        if not self.log_file.exists():
            return []
        return [json.loads(l) for l in self.log_file.read_text(encoding="utf-8").splitlines()]

    def first_start(self):
        return [r for r in self.fake_log() if r["kind"] == "start"][0]


class Parser(unittest.TestCase):
    def test_events(self):
        P = stream.parse_line
        self.assertEqual(P(json.dumps({"type": "system", "subtype": "init", "model": "m", "apiKeySource": "none", "claude_code_version": "2"})),
                         [Init("m", "none", "2")])
        self.assertEqual(P('{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"가"}}}'), [TextDelta("가")])
        r = P('{"type":"result","subtype":"success","is_error":false,"result":"ok","terminal_reason":"completed","usage":{"output_tokens":3}}')[0]
        self.assertEqual((r.ok, r.text, r.terminal_reason, r.usage["output_tokens"]), (True, "ok", "completed", 3))
        self.assertEqual(P('{"type":"system","subtype":"status","status":"compacting"}'), [Compacting()])
        self.assertEqual(P('{"type":"system","subtype":"compact_boundary","compact_metadata":{"trigger":"manual","pre_tokens":10,"post_tokens":4}}'),
                         [Compacted("manual", 10, 4)])
        self.assertEqual(P('{"type":"control_response","response":{"subtype":"success","request_id":"a"}}'), [ControlResponse("a", True)])

    def test_unknown_and_garbage_are_ignored(self):
        for line in ("", "not json", "[1]", '{"type":"assistant"}', '{"type":"system","subtype":"hook_started"}', '{"type":"stream_event","event":{"type":"ping"}}'):
            self.assertEqual(stream.parse_line(line), [])

    def test_error_classification(self):
        C = stream.classify_text
        self.assertEqual(C("Claude usage limit reached. Your limit will reset at 3am"), "rate_limit")
        self.assertEqual(C("Invalid API key · Please run /login"), "auth")
        self.assertEqual(C("API Error: Unable to connect to API (ECONNREFUSED)"), "network")
        self.assertIsNone(C("뭔가 알 수 없는 오류"))
        self.assertIsNone(C(""))
        r = stream.parse_line('{"type":"result","subtype":"error_during_execution","is_error":true,"result":"rate limit exceeded"}')[0]
        self.assertEqual((r.ok, r.error_kind), (False, "rate_limit"))


class Locator(Base):
    def test_order_and_script_flag(self):
        real = self.d / "bin"
        real.mkdir()
        exe = real / "claude"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        f = claude_locator.find_claude(str(exe), {"PATH": ""})
        self.assertEqual((f.path, f.is_script, f.source), (str(exe), True, "settings"))
        f = claude_locator.find_claude(None, {"PATH": "/nonexistent:" + str(real)})
        self.assertEqual((f.source, f.is_script), ("path", True))
        f = claude_locator.find_claude(None, {"PATH": ""}, login_shell=lambda: str(exe))
        self.assertEqual(f.source, "login_shell")
        f = claude_locator.find_claude(None, {"PATH": ""}, known_dirs=[str(real)])
        self.assertEqual(f.source, "known_dir")
        self.assertIsNone(claude_locator.find_claude(None, {"PATH": ""}, known_dirs=[str(self.d / "x")]))
        self.assertIsNone(claude_locator.find_claude(str(self.d / "missing"), {"PATH": str(real)}))  # 지정했는데 없으면 다른 곳을 찾지 않는다
        binf = real / "native"
        binf.write_bytes(b"\xcf\xfa\xed\xfe")
        binf.chmod(0o755)
        self.assertFalse(claude_locator.find_claude(str(binf), {}).is_script)


class Running(Base):
    def test_normal_roundtrip_effort_and_args(self):  # AC-FR1-8, AC-FR1-19
        s = self.session(self.wrapper(), cfg_kw={"system_prompt": "규칙"})
        self.assertTrue(s.start())
        self.assertTrue(s.send(msg("[요청] 종류=트리거\n안녕")))
        r = self.wait_for(lambda e: isinstance(e, Result))
        self.assertTrue(r.ok)
        self.assertIsInstance(self.wait_for(lambda e: isinstance(e, Init)), Init)
        self.assertTrue(any(isinstance(e, TextDelta) for e in self.events))
        a = self.first_start()["argv"]
        self.assertEqual(a[a.index("--effort") + 1], "medium")
        self.assertEqual(a.count("--settings"), 1)
        self.assertEqual(a.count("--no-session-persistence"), 1)
        self.assertEqual(a[a.index("--tools") + 1], "")
        self.assertIn("-p", a)
        self.assertNotIn("--bare", a)
        msgs = [r["text"] for r in self.fake_log() if r["kind"] == "msg"]
        self.assertEqual(msgs, ["/effort medium", "[요청] 종류=트리거\n안녕"])  # Q11: 첫 메시지는 `/effort`. 질의는 그대로(머리는 K-06 의 몫)

    def test_set_effort_is_a_bare_command_message(self):
        s = self.session(self.wrapper())
        s.start()
        s.send(msg("a"))
        self.wait_for(lambda e: isinstance(e, Result))
        self.assertTrue(s.set_effort("high"))
        time.sleep(0.4)
        texts = [r["text"] for r in self.fake_log() if r["kind"] == "msg"]
        self.assertEqual(texts[-1], "/effort high")

    def test_interrupt_request_shape_and_response(self):
        s = self.session(self.wrapper())
        s.start()
        s.send(msg("a"))
        self.wait_for(lambda e: isinstance(e, Result))
        rid = s.interrupt()
        cr = self.wait_for(lambda e: isinstance(e, ControlResponse))
        self.assertEqual((cr.request_id, cr.ok), (rid, True))
        ctl = [r for r in self.fake_log() if r["kind"] == "control"][0]["msg"]
        self.assertEqual(ctl["request"], {"subtype": "interrupt", "cancel_queued": True})
        self.assertEqual(ctl["type"], "control_request")

    def test_cmux_like_wrapper_adds_nothing_under_clean_env(self):
        """감싼 스크립트(활성 조건이 환경 변수)를 `claude_path` 로 지정해도 앱이 만든 환경에서는 인자가 더해지지 않는다."""
        sock = self.d / "cmux.sock"
        sock.write_text("")
        real = self.wrapper()
        cmux = self.d / "cmux-claude"
        cmux.write_text('#!/bin/sh\nif [ -n "$CMUX_SURFACE_ID" ] && [ -e "$CMUX_SOCKET_PATH" ]; then\n'
                        '  exec %s --session-id 11111111-1111-1111-1111-111111111111 --settings \'{"hooks":{}}\' "$@"\nfi\nexec %s "$@"\n' % (real, real))
        cmux.chmod(0o755)
        cmux_env = {"CMUX_SURFACE_ID": "S", "CMUX_SOCKET_PATH": str(sock)}
        # 대조: 환경이 그대로 남으면 (감싼 스크립트가 일하면) 인자가 더해진다
        import subprocess
        subprocess.run([str(cmux), "-p"], env=dict(os.environ, **cmux_env), stdin=subprocess.DEVNULL, check=True)
        raw_args = self.first_start()["argv"]
        self.assertIn("--session-id", raw_args)
        self.log_file.unlink()
        # 앱이 만든 환경
        s = self.session(str(cmux), parent_env=cmux_env)
        self.assertTrue(s.start())
        s.send(msg("x"))
        self.wait_for(lambda e: isinstance(e, Result))
        st = self.first_start()
        self.assertNotIn("--session-id", st["argv"])
        self.assertEqual(st["argv"].count("--settings"), 1)
        self.assertNotIn("CMUX_SURFACE_ID", st["env_names"])
        self.assertNotIn("CMUX_SOCKET_PATH", st["env_names"])

    def test_script_claude_starts_without_warning_and_is_logged(self):  # AC-FR1-21
        path = self.wrapper()
        found = claude_locator.find_claude(path, {})
        self.assertTrue(found.is_script)
        log = eventlog.EventLog(self.d / "cfg", pid=1)
        self.addCleanup(log.close)
        s = self.session(found.path, eventlog=log)
        self.assertTrue(s.start())
        s.send(msg("x"))
        self.wait_for(lambda e: isinstance(e, Result))
        self.assertFalse([e for e in self.events if isinstance(e, Error)])
        log.session_start(kind="수업", save_dir="/d", claude_path=found.path, claude_is_script=found.is_script,
                          provider="claude_subscription", auth="subscription", model="sonnet", effort="medium",
                          audio_source=None, prompt_source="app_default", prompt_sha256="0")
        recs = [json.loads(l) for l in Path(log.path).read_text().splitlines()]
        ss = [r for r in recs if r["type"] == "session_start"][0]
        self.assertEqual((ss["claude_path"], ss["claude_is_script"]), (path, True))

    def test_long_prompt_file_is_whole_private_and_removed(self):  # AC-FR2-11
        text = "가나다라" * 5000
        run = self.d / "run"
        s = self.session(self.wrapper(), prompt_text=text, run_dir=str(run))
        self.assertTrue(s.start())
        s.send(msg("x"))
        self.wait_for(lambda e: isinstance(e, Result))
        import hashlib
        p = self.first_start()["prompt_file"]
        self.assertEqual(p["sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(p["mode"], "0o600")
        self.assertEqual(stat.S_IMODE(os.stat(run).st_mode), 0o700)
        self.assertNotIn(text[:20], json.dumps(self.first_start()["argv"], ensure_ascii=False))  # 인자에 본문이 없다
        s.close()
        self.assertEqual(list(run.glob("system-prompt-*")), [])

    def test_long_prompt_string_fallback(self):  # AC-FR2-11 의 대체 경로
        import hashlib
        text = "가" * 20000
        s = self.session(self.wrapper(), cfg_kw={"system_prompt": text})
        s.start()
        s.send(msg("x"))
        self.wait_for(lambda e: isinstance(e, Result))
        st = self.first_start()
        self.assertEqual((st["prompt_arg_len"], st["prompt_arg_sha256"]), (20000, hashlib.sha256(text.encode()).hexdigest()))


class Auth(Base):
    def test_subscription_with_matching_source(self):
        s = self.session(self.wrapper())
        s.start()
        s.send(msg("x"))
        init = self.wait_for(lambda e: isinstance(e, Init))
        self.assertEqual(init.api_key_source, "none")
        self.wait_for(lambda e: isinstance(e, Result))
        self.assertFalse(s.rejected)

    def test_mismatch_refuses_and_terminates_by_pid(self):  # AC-FR1-14
        s = self.session(self.wrapper(source="apiKeyHelper"))
        s.start()
        pid = s.pid
        s.send(msg("x"))
        err = self.wait_for(lambda e: isinstance(e, Error))
        self.assertEqual(err.kind, "auth")
        self.assertIn("apiKeyHelper", err.detail)
        self.wait_for(lambda e: isinstance(e, ProcessExited))
        self.assertTrue(s.rejected)
        self.assertFalse([e for e in self.events if isinstance(e, Result)])
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertEqual([e.kind for e in self.events if isinstance(e, Error)], ["auth"])  # 종료 오류가 겹치지 않는다

    def test_api_requires_key_name_source(self):
        s = self.session(self.wrapper(), auth=llm.Auth.API, key=KEY)
        s.start()
        s.send(msg("x"))
        self.assertEqual(self.wait_for(lambda e: isinstance(e, Init)).api_key_source, "ANTHROPIC_API_KEY")
        self.wait_for(lambda e: isinstance(e, Result))
        self.assertIn("ANTHROPIC_API_KEY", self.first_start()["env_names"])
        self.assertNotIn(KEY, json.dumps(self.first_start()["argv"]))

    def test_api_but_source_none_refuses(self):
        s = self.session(self.wrapper(source="none"), auth=llm.Auth.API, key=KEY)
        s.start()
        s.send(msg("x"))
        self.assertEqual(self.wait_for(lambda e: isinstance(e, Error)).kind, "auth")

    def test_api_without_key_does_not_start(self):
        s = self.session(self.wrapper(), auth=llm.Auth.API, key=None)
        self.assertFalse(s.start())
        self.assertEqual(self.events[0].kind, "auth")
        self.assertFalse(self.log_file.exists())  # 프로세스를 시작하지 않았다

    def test_key_not_in_errors_or_event_log(self):  # AC-FR1-17 의 일부
        log = eventlog.EventLog(self.d / "cfg", pid=2)
        self.addCleanup(log.close)
        s = self.session(self.wrapper(mode="exit_now", stderr="Invalid API key @KEY@ · Please run /login"),
                         auth=llm.Auth.API, key=KEY, eventlog=log)
        s.start()
        err = self.wait_for(lambda e: isinstance(e, Error))
        self.assertEqual(err.kind, "auth")
        self.assertNotIn(KEY, err.detail)
        self.wait_for(lambda e: isinstance(e, ProcessExited))
        self.assertNotIn(KEY, Path(log.path).read_text(encoding="utf-8"))


class InitFirst(Base):
    """Q11: 질의는 init 의 인증 출처 검사를 통과한 뒤에만 나간다. 국소 명령 Result 는 사용자에게 내지 않는다."""

    def texts(self):
        return [r["text"] for r in self.fake_log() if r["kind"] == "msg"]

    def test_first_message_is_effort_and_query_follows_init(self):
        s = self.session(self.wrapper())
        s.start()
        s.send(msg("질의"))  # start 직후: init 전에 보낸 질의는 보류한다
        self.wait_for(lambda e: isinstance(e, Result))
        self.assertEqual(self.texts(), ["/effort medium", "질의"])
        kinds = [type(e).__name__ for e in self.events]
        self.assertLess(kinds.index("Init"), kinds.index("Result"))

    def test_local_command_result_hidden(self):
        s = self.session(self.wrapper())
        s.start()
        self.wait_for(lambda e: isinstance(e, Init))
        time.sleep(0.4)
        self.assertEqual([e for e in self.events if isinstance(e, Result)], [])  # `/effort` 의 Result 는 숨긴다
        s.send(msg("질의"))
        self.wait_for(lambda e: isinstance(e, Result))
        self.assertEqual(len([e for e in self.events if isinstance(e, Result)]), 1)

    def test_first_query_result_shown_when_effort_gives_no_result(self):  # X8: num_turns == 0 으로 판별
        s = self.session(self.wrapper(no_local_result=1))
        s.start()
        s.send(msg("질의"))
        r = self.wait_for(lambda e: isinstance(e, Result))
        self.assertEqual((r.ok, r.text, r.num_turns), (True, "ok", 1))
        self.assertEqual(len([e for e in self.events if isinstance(e, Result)]), 1)
        s.send(msg("둘째"))
        self.wait_for(lambda e: isinstance(e, Result) and e is not r)
        self.assertEqual(len([e for e in self.events if isinstance(e, Result)]), 2)

    def test_mismatch_sends_zero_queries(self):
        s = self.session(self.wrapper(source="apiKeyHelper"))
        s.start()
        s.send(msg("질의"))
        self.wait_for(lambda e: isinstance(e, ProcessExited))
        self.assertEqual(self.texts(), ["/effort medium"])
        self.assertEqual([e for e in self.events if isinstance(e, Result)], [])
        self.assertTrue(s.rejected)
        recs = [r for r in self.fake_log()]
        self.assertFalse([r for r in recs if r["kind"] == "msg" and r["text"] != "/effort medium"])

    def test_without_effort_mismatch_uses_sigkill_by_pid(self):
        s = self.session(self.wrapper(source="apiKeyHelper"))
        s.config = replace(s.config, effort=None)  # `/effort` 를 쓸 수 없는 경로
        calls = []
        orig_kill, orig_term = self.procs.kill, self.procs.terminate
        self.procs.kill = lambda h: (calls.append(("kill", h.pid)), orig_kill(h))[1]
        self.procs.terminate = lambda *a, **k: (calls.append(("terminate", a[0].pid)), orig_term(*a, **k))[1]
        s.start()
        pid = s.pid
        s.send(msg("질의"))
        self.wait_for(lambda e: isinstance(e, ProcessExited))
        self.assertEqual(calls[0], ("kill", pid))
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_close_before_init_drops_queue(self):
        s = self.session(self.wrapper(mode="ignore_stdin"))
        s.start()
        self.assertTrue(s.send(msg("질의")))
        s.close()
        self.assertEqual([r for r in self.fake_log() if r["kind"] == "msg"], [])


class Failures(Base):
    def test_exits_immediately(self):
        s = self.session(self.wrapper(mode="exit_now", stderr="boom: something broke"))
        s.start()
        err = self.wait_for(lambda e: isinstance(e, Error))
        self.assertEqual(err.kind, "process_exit")
        self.assertIn("boom", err.detail)
        pe = self.wait_for(lambda e: isinstance(e, ProcessExited))
        self.assertEqual((pe.code, pe.expected), (1, False))

    def test_missing_executable(self):  # AC-FR1-4 의 찾지 못함
        s = self.session(str(self.d / "nope"))
        self.assertFalse(s.start())
        self.assertEqual(self.events[0].kind, "no_claude")

    def test_rate_limit_is_reported_and_session_survives(self):  # AC-FR9-4
        s = self.session(self.wrapper(mode="rate_limit"))
        s.start()
        s.send(msg("x"))
        err = self.wait_for(lambda e: isinstance(e, Error))
        self.assertEqual(err.kind, "rate_limit")
        r = self.wait_for(lambda e: isinstance(e, Result))
        self.assertFalse(r.ok)
        self.assertTrue(s.send(msg("y")))  # 앱은 종료하지 않고 프로세스도 살아 있다

    def test_network_error_then_recovery(self):  # AC-FR9-3
        s = self.session(self.wrapper(mode="fail_first", fail_n=1, error_text="API Error: Unable to connect (ECONNREFUSED)"))
        s.start()
        s.send(msg("a"))
        self.assertEqual(self.wait_for(lambda e: isinstance(e, Error)).kind, "network")
        self.wait_for(lambda e: isinstance(e, Result) and not e.ok)
        s.send(msg("b"))
        self.wait_for(lambda e: isinstance(e, Result) and e.ok)

    def test_request_timeout(self):
        s = self.session(self.wrapper(mode="hang"), request_timeout_s=0.4)
        s.start()
        s.send(msg("x"))
        err = self.wait_for(lambda e: isinstance(e, Error))
        self.assertEqual(err.kind, "network")
        self.assertIn("시간 초과", err.detail)

    def test_send_after_exit_reports_process_exit(self):
        s = self.session(self.wrapper(mode="exit_now"))
        s.start()
        self.wait_for(lambda e: isinstance(e, ProcessExited))
        self.events.clear()
        self.assertFalse(s.send(msg("x")))
        self.assertEqual(self.events[0].kind, "process_exit")


class D029(Base):
    """D-029 · D-030: 프로세스마다 상태, 손자가 파이프를 쥐어도 재시작이 지연되지 않는다, B-23 필드, 분류."""

    def _kill_grandchildren(self):
        for r in self.fake_log():
            if r["kind"] == "grandchild":
                try:
                    os.kill(r["pid"], 9)
                except OSError:
                    pass

    def test_restart_with_grandchild_holding_pipe_is_fast_and_clean(self):
        s = self.session(self.wrapper(grandchild=1), prompt_text="P" * 10, run_dir=str(self.d), drain_grace_s=0.3)
        self.addCleanup(self._kill_grandchildren)
        s.start()
        s.send(msg("a"))
        self.wait_for(lambda e: isinstance(e, Result))
        old = s.pid
        t0 = time.monotonic()
        self.assertTrue(s.restart())
        self.assertLess(time.monotonic() - t0, 3.0)
        self.assertNotEqual(s.pid, old)
        new_prompt = s._run.prompt_file
        self.assertIsNotNone(new_prompt)
        time.sleep(1.5)  # 이전 프로세스의 늦은 정리가 새 자원을 건드리는지 본다
        self.assertTrue(os.path.exists(new_prompt))
        s.send(msg("b"))
        self.wait_for(lambda e: isinstance(e, Result) and e.ok)
        exited = [e for e in self.events if isinstance(e, ProcessExited)]
        self.assertEqual(len(exited), 1)  # 이전 프로세스 하나뿐, 늦은 것이 더 오지 않는다
        self.assertTrue(exited[0].expected)

    def test_restart_does_not_cancel_new_timer(self):
        s = self.session(self.wrapper(mode="hang", grandchild=1), request_timeout_s=1.0, drain_grace_s=0.2)
        self.addCleanup(self._kill_grandchildren)
        s.start()
        s.restart()
        s.send(msg("x"))
        e = self.wait_for(lambda e: isinstance(e, Error) and e.kind == "network", timeout=5)
        self.assertEqual(e.kind, "network")

    def test_event_fields_b23(self):
        d = self.d / "ev"
        d.mkdir()
        log = eventlog.EventLog(str(d))
        s = self.session(self.wrapper(), eventlog=log)
        s.start()
        s.send(msg("a"))
        self.wait_for(lambda e: isinstance(e, Result))
        old = s.pid
        s.restart()
        new = s.pid
        s.close()
        log.close()
        recs = []
        for f in sorted(d.rglob("*.jsonl")):
            recs += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        by = {}
        for r in recs:
            by.setdefault(r.get("type"), []).append(r)
        pr = by["process_restart"][0]
        pr = pr.get("payload", pr)
        self.assertEqual((pr["old_pid"], pr["new_pid"]), (old, new))
        pe = [r.get("payload", r) for r in by["process_exit"]]
        self.assertTrue(all("expected" in p and "pid" in p and "code" in p for p in pe))
        self.assertTrue(pe[0]["expected"])

    def test_auth_mismatch_fields(self):
        d = self.d / "ev2"
        d.mkdir()
        log = eventlog.EventLog(str(d))
        s = self.session(self.wrapper(source="ANTHROPIC_API_KEY"), eventlog=log)
        s.start()
        s.send(msg("a"))
        self.wait_for(lambda e: isinstance(e, ProcessExited))
        log.close()
        recs = []
        for f in sorted(d.rglob("*.jsonl")):
            recs += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        am = [r.get("payload", r) for r in recs if r.get("type") == "auth_mismatch"][0]
        self.assertEqual(am["auth"], "subscription")
        self.assertEqual(am["api_key_source"], "ANTHROPIC_API_KEY")

    def test_numeric_tokens_use_word_boundaries(self):
        self.assertIsNone(stream.classify_text("req_011CT4291abc failed"))
        self.assertIsNone(stream.classify_text("id 14010 done"))
        self.assertEqual(stream.classify_text("HTTP 429 Too"), "rate_limit")
        self.assertEqual(stream.classify_text("status: 401."), "auth")

    def test_stderr_classification_only_on_immediate_exit(self):
        # 즉시 종료: 표준 오류로 분류한다
        s = self.session(self.wrapper(mode="exit_now", stderr="Not logged in · Please run /login"))
        s.start()
        e = self.wait_for(lambda e: isinstance(e, Error))
        self.assertEqual(e.kind, "auth")
        # 사건을 받은 뒤의 종료: 표준 오류의 문구와 무관하게 process_exit
        self.events.clear()
        s2 = self.session(self.wrapper(grandchild=0))
        s2.start()
        s2.send(msg("a"))
        self.wait_for(lambda e: isinstance(e, Result))
        s2._run.stderr.append("rate limit 429")
        os.kill(s2.pid, 9)
        e = self.wait_for(lambda e: isinstance(e, Error) and e.kind in ("process_exit", "rate_limit"))
        self.assertEqual(e.kind, "process_exit")


class Lifecycle(Base):
    def test_close_terminates_by_pid_and_is_expected(self):
        s = self.session(self.wrapper())
        s.start()
        s.send(msg("x"))
        self.wait_for(lambda e: isinstance(e, Result))
        pid = s.pid
        s.close()
        pe = self.wait_for(lambda e: isinstance(e, ProcessExited))
        self.assertTrue(pe.expected)
        self.assertEqual([e for e in self.events if isinstance(e, Error)], [])
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertEqual(self.procs.live(), [])

    def test_close_escalates_to_sigterm_and_sigkill(self):  # B-06
        for ignore_term in ("0", "1"):
            s = self.session(self.wrapper(mode="ignore_stdin", ignore_term=ignore_term), stdin_wait_s=0.3, term_wait_s=0.5)
            s.start()
            time.sleep(0.3)
            pid = s.pid
            t0 = time.monotonic()
            s.close()
            self.assertLess(time.monotonic() - t0, 8)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_restart_new_pid_and_old_gone(self):
        s = self.session(self.wrapper())
        s.start()
        s.send(msg("a"))
        self.wait_for(lambda e: isinstance(e, Result))
        old = s.pid
        self.events.clear()
        self.assertTrue(s.restart())
        self.assertNotEqual(s.pid, old)
        with self.assertRaises(ProcessLookupError):
            os.kill(old, 0)
        s.send(msg("b"))
        self.wait_for(lambda e: isinstance(e, Result) and e.ok)
        self.assertEqual(len([r for r in self.fake_log() if r["kind"] == "start"]), 2)

    def test_core_has_no_qt_or_forbidden_names(self):
        for n in ("types.py", "stream.py", "procs.py", "claude_locator.py", "model_session.py"):
            t = (ROOT / "src/mac/nsu_kangs_rab/core" / n).read_text(encoding="utf-8")
            for bad in ("PySide6", "nsu_kangs_rab.platform", "pkill", "killall", ".credentials.json", "claude_agent_sdk", "setup-token"):
                self.assertNotIn(bad, t, "%s: %s" % (n, bad))
            self.assertNotIn("--bare", t)


if __name__ == "__main__":
    unittest.main()
