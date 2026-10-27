"""K-02: settings · eventlog · devopts 의 단위 시험 (AC-FR1-5 · 6 · 7 · 9 · 12 · 15 · 20, AC-FR2-5 의 설정 부분, 5-1절 필드)."""
import copy
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import devopts, eventlog, settings as S  # noqa: E402


def write(d, name, obj):
    p = Path(d) / name
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


class Settings(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = self.td.name

    def tearDown(self):
        self.td.cleanup()

    def test_first_run_defaults(self):  # AC-FR1-20
        r = S.load_settings(Path(self.d) / "settings.json")
        self.assertFalse(r.file_found)
        sel = S.resolve_selection(r.data)
        self.assertEqual((sel.provider, sel.family, sel.effort), ("claude_subscription", "sonnet", "medium"))
        self.assertEqual(sel.efforts, ("medium", "high", "xhigh"))
        self.assertEqual(sel.notices, ())

    def test_removed_stt_model_last_key_is_harmless(self):  # M-3: 기본값에서 뺀 `stt_model_last` 가 옛 설정 파일에 있어도 문제없다
        self.assertNotIn("stt_model_last", S.load_defaults())
        path = Path(self.d) / "settings.json"
        path.write_text(json.dumps({"stt_model_last": {"id": "x"}, "model": "sonnet"}), encoding="utf-8")
        r = S.load_settings(path)
        self.assertEqual(r.notices, [])
        self.assertEqual(S.resolve_selection(r.data).family, "sonnet")
        ok, _ = S.update_settings(path, {"model": "sonnet"})
        self.assertTrue(ok)

    def test_selection_persists_across_save_and_load(self):  # AC-FR1-5 · AC-FR1-20
        p = Path(self.d) / "sub" / "settings.json"
        data = S.load_settings(p).data
        data["model"], data["effort"] = "opus", "high"
        self.assertEqual(S.save_settings(p, data), (True, ""))
        sel = S.resolve_selection(S.load_settings(p).data)
        self.assertEqual((sel.family, sel.effort), ("opus", "high"))
        self.assertEqual([n for n in os.listdir(p.parent) if n.endswith(".tmp")], [])

    def test_merge_keeps_default_keys_and_unknown_keys(self):
        p = write(self.d, "settings.json", {"model": "haiku", "future_key": {"a": 1}})
        r = S.load_settings(p)
        self.assertEqual(r.data["model"], "haiku")
        self.assertIn("providers", r.data)
        self.assertEqual(r.data["future_key"], {"a": 1})
        ok, _ = S.save_settings(p, r.data)
        self.assertEqual(json.loads(p.read_text())["future_key"], {"a": 1})

    def test_low_and_max_are_removed(self):  # AC-FR1-6 · AC-FR1-7
        t = {"providers": {"claude_subscription": {"families": {"sonnet": {"efforts": ["low", "medium", "high", "xhigh", "max"], "default": "low"}}}}}
        r = S.load_settings(write(self.d, "s.json", t))
        tb = S.effort_table(r.data, "claude_subscription", "sonnet")
        self.assertEqual(tb.options, ("medium", "high", "xhigh"))
        self.assertEqual(tb.default, "medium")  # 기본값 low 가 빠졌으므로 첫 단계

    def test_table_edit_changes_list(self):  # AC-FR1-7 · AC-FR1-12
        t = {"providers": {"claude_api": {"families": {"sonnet": {"efforts": ["high"], "default": "high"}}}}}
        data = S.load_settings(write(self.d, "s.json", t)).data
        self.assertEqual(S.effort_table(data, "claude_api", "sonnet").options, ("high",))
        self.assertEqual(S.effort_table(data, "claude_subscription", "sonnet").options, ("medium", "high", "xhigh"))

    def test_no_steps_family_hides_effort(self):  # AC-FR1-9
        for efforts in ([], ["low", "max"]):
            data = S.load_settings(write(self.d, "s.json", {"model": "haiku", "providers": {"claude_subscription": {"families": {"haiku": {"efforts": efforts}}}}})).data
            sel = S.resolve_selection(data)
            self.assertEqual((sel.family, sel.effort, sel.efforts), ("haiku", None, ()))

    def test_single_step_family(self):
        data = S.load_settings(write(self.d, "s.json", {"effort": "high", "providers": {"claude_subscription": {"families": {"sonnet": {"efforts": ["low", "high"]}}}}})).data
        sel = S.resolve_selection(data)
        self.assertEqual((sel.efforts, sel.effort), (("high",), "high"))

    def test_broken_table_does_not_raise_and_hides_effort(self):  # AC-FR1-9
        for bad in ("가나다", {"efforts": "high"}, {"efforts": [1, 2]}):
            data = S.load_settings(write(self.d, "s.json", {"providers": {"claude_subscription": {"families": {"sonnet": bad}}}})).data
            sel = S.resolve_selection(data)
            self.assertIsNone(sel.effort)
            self.assertEqual([n.kind for n in sel.notices], ["table_broken"])

    def test_broken_file_falls_back_to_defaults(self):
        for content in ("{not json", "[1,2]", ""):
            r = S.load_settings(write(self.d, "s.json", content))
            self.assertEqual([n.kind for n in r.notices], ["settings_unreadable"])
            self.assertEqual(S.resolve_selection(r.data).family, "sonnet")

    def test_remembered_effort_not_in_table_is_reset_and_notified(self):  # AC-FR1-9
        data = S.load_settings(write(self.d, "s.json", {"effort": "low"})).data
        sel = S.resolve_selection(data)
        self.assertEqual(sel.effort, "medium")
        self.assertEqual([n.kind for n in sel.notices], ["effort_reset"])

    def test_inactive_provider_reverts_to_subscription(self):  # AC-FR1-15
        for prov in ("chatgpt_api", "gemini_subscription", 5):
            data = S.load_settings(write(self.d, "s.json", {"provider": prov})).data
            sel = S.resolve_selection(data)
            self.assertEqual(sel.provider, "claude_subscription")
            self.assertEqual([n.kind for n in sel.notices], ["provider_inactive"])
        sel = S.resolve_selection(S.load_settings(write(self.d, "s.json", {"provider": "claude_api"})).data)
        self.assertEqual((sel.provider, sel.notices), ("claude_api", ()))

    def test_unknown_model_family_resets(self):
        sel = S.resolve_selection(S.load_settings(write(self.d, "s.json", {"model": "gpt"})).data)
        self.assertEqual(sel.family, "sonnet")
        self.assertEqual([n.kind for n in sel.notices], ["model_unknown"])

    def test_inputs_not_modified(self):
        data = S.load_defaults()
        before = copy.deepcopy(data)
        S.resolve_selection(data)
        S.with_overrides(data, save_dir="/x")
        self.assertEqual(data, before)
        d2 = {"model": "opus"}
        b2 = copy.deepcopy(d2)
        S.load_settings(Path(self.d) / "none.json", defaults=S.load_defaults())
        self.assertEqual(d2, b2)

    def test_overrides_are_not_saved(self):
        base = S.load_defaults()
        o = S.with_overrides(base, save_dir="/tmp/x")
        self.assertEqual(o["save_dir"], "/tmp/x")
        self.assertIsNone(base["save_dir"])

    def test_save_failure_returns_false(self):
        f = write(self.d, "file", "x")
        ok, why = S.save_settings(f / "settings.json", {})
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_no_api_key_field_in_defaults(self):  # AC-FR1-17 의 정적 부분
        text = S.DEFAULTS_PATH.read_text(encoding="utf-8").lower()
        for w in ("api_key", "apikey", "secret", "token"):
            self.assertNotIn(w, text)

    def test_session_prompt_source(self):  # AC-FR2-5
        data = S.load_defaults()
        self.assertEqual(S.resolve_session_prompt(data, None, "앱 기본"), (S.SOURCE_APP_DEFAULT, "앱 기본"))
        self.assertEqual(S.resolve_session_prompt(data, "  ", "앱 기본")[0], S.SOURCE_APP_DEFAULT)
        data["default_session_prompt"] = "설정 문구"
        self.assertEqual(S.resolve_session_prompt(data, None, "앱 기본"), (S.SOURCE_SETTINGS_DEFAULT, "설정 문구"))
        self.assertEqual(S.resolve_session_prompt(data, "수업 입력", "앱 기본"), (S.SOURCE_SESSION_INPUT, "수업 입력"))
        self.assertEqual(len(S.text_sha256("가")), 64)


class DevOpts(unittest.TestCase):
    def test_parse_values_names_and_rest(self):
        o = devopts.parse(["--dev-speed", "4", "--other", "--dev-final-wait-cap-s=1.5", "--dev-stt-helper", "/h",
                           "--dev-config-dir", "/t", "x"])
        self.assertEqual(o.get("speed"), 4.0)
        self.assertEqual(o.get("final_wait_cap_s"), 1.5)
        self.assertEqual(o.get("stt_helper"), "/h")
        self.assertEqual(o.get("config_dir"), "/t")
        self.assertEqual(o.names, ["--dev-speed", "--dev-final-wait-cap-s", "--dev-stt-helper", "--dev-config-dir"])
        self.assertEqual(o.rest, ["--other", "x"])
        self.assertEqual(o.errors, [])

    def test_empty_means_no_names(self):
        o = devopts.parse([])
        self.assertEqual((o.names, o.values, o.errors, o.rest), ([], {}, [], []))

    def test_errors_do_not_apply(self):
        o = devopts.parse(["--dev-nope", "1", "--dev-speed", "0", "--dev-appearance", "blue", "--dev-char-cap",
                           "--dev-image-cap", "6"])
        self.assertEqual(o.names, ["--dev-image-cap"])
        self.assertEqual(o.values, {"image_cap": 6})
        self.assertEqual({n for n, _ in o.errors}, {"--dev-nope", "--dev-speed", "--dev-appearance", "--dev-char-cap"})
        self.assertNotIn("1", [w for _, w in o.errors])  # 값은 사유에 넣지 않는다

    def test_input_not_modified_and_all_options_have_prefix(self):
        argv = ["--dev-speed", "2"]
        devopts.parse(argv)
        self.assertEqual(argv, ["--dev-speed", "2"])
        self.assertTrue(all(k.startswith("--dev-") for k in devopts.OPTIONS))
        self.assertEqual(len(devopts.OPTIONS), 23)      # 묶음 6: --dev-diagram-timeout-s, 액자: --dev-capture-fake, 모델 내려받기: --dev-stt-model-home · -endpoint · -free-bytes · -free-bytes-file, 액자: --dev-frame-method-missing 을 더했다. 단계 10: --dev-clock-file(세션 시계 주입), --dev-final-wait-cap-s · --dev-stt-helper · --dev-stt-helper-scenario 를 더하고 --dev-pending-cap-s · --dev-stt-fail* · --dev-stt-model-* 6개를 없앴다

    def test_duplicate_name_once_last_value_wins(self):
        o = devopts.parse(["--dev-speed", "1", "--dev-speed", "3"])
        self.assertEqual((o.names, o.get("speed")), (["--dev-speed"], 3.0))


class EventLogTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = self.td.name

    def tearDown(self):
        self.td.cleanup()

    def mk(self, *a, **kw):
        lg = eventlog.EventLog(*a, **kw)
        self.addCleanup(lg.close)
        return lg

    def lines(self, log):
        return [json.loads(l) for l in Path(log.path).read_text(encoding="utf-8").splitlines()]

    def test_path_and_fields(self):
        log = self.mk(self.d, pid=4242, now=lambda: dt.datetime(2026, 10, 11, 21, 5, 9))
        self.assertEqual(log.path.name, "events-20261011-210509-4242.jsonl")
        self.assertTrue(log.emit("capture_start", source="mic", rate=16000))
        rec = self.lines(log)[0]
        self.assertEqual(rec["type"], "capture_start")
        self.assertIsInstance(rec["t_mono"], float)
        self.assertRegex(rec["t_wall"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$")
        self.assertEqual(rec["rate"], 16000)

    def test_session_start_fields(self):  # 5-1절 세션 시작 행
        log = self.mk(self.d)
        log.session_start(kind="수업", save_dir="/d", claude_path="/x/claude", claude_is_script=True, provider="claude_subscription",
                          auth="subscription", model="sonnet", effort="medium", audio_source="mic",
                          prompt_source="session_input", prompt_sha256="ab" * 32, materials=["a.md"], dev_options=["--dev-speed"])
        r = self.lines(log)[0]
        for k in ("kind", "save_dir", "claude_path", "claude_is_script", "provider", "auth", "model", "effort",
                  "audio_source", "prompt_source", "prompt_sha256", "materials", "dev_options"):
            self.assertIn(k, r)
        self.assertIs(r["claude_is_script"], True)
        self.assertEqual(r["dev_options"], ["--dev-speed"])
        log2 = self.mk(self.d, pid=1)
        log2.session_start(kind="회의", save_dir="/d", claude_path=None, claude_is_script=None, provider="p", auth="a",
                           model="m", effort=None, audio_source=None, prompt_source="app_default", prompt_sha256="0")
        self.assertEqual(self.lines(log2)[0]["dev_options"], [])

    def test_body_and_key_fields_dropped(self):
        log = self.mk(self.d)
        log.emit("request", text="전사 본문", api_key="K1", input="x", n=3, text_sha256="ab", text_chars=5)
        r = self.lines(log)[0]
        for k in ("text", "api_key", "input"):
            self.assertNotIn(k, r)
        self.assertEqual((r["n"], r["text_sha256"], r["text_chars"]), (3, "ab", 5))
        self.assertEqual(r["dropped_fields"], ["api_key", "input", "text"])
        self.assertNotIn("전사 본문", Path(log.path).read_text(encoding="utf-8"))

    def test_registered_secret_is_redacted(self):  # AC-FR1-17 의 이벤트 로그 부분
        log = self.mk(self.d)
        log.register_secret("sk-test-123")
        log.emit("error", kind="auth", detail="실패 sk-test-123 입니다", nested={"a": ["x sk-test-123"]})
        raw = Path(log.path).read_text(encoding="utf-8")
        self.assertNotIn("sk-test-123", raw)
        self.assertEqual(self.lines(log)[0]["detail"], eventlog.REDACTED)

    def test_reserved_names_cannot_be_overwritten(self):
        log = self.mk(self.d)
        log.emit("a", t_mono="x", type="b")
        r = self.lines(log)[0]
        self.assertEqual(r["type"], "a")
        self.assertIsInstance(r["t_mono"], float)

    def test_keeps_latest_20_files(self):
        base = dt.datetime(2026, 10, 11, 9, 0, 0)
        for i in range(25):
            lg = eventlog.EventLog(self.d, pid=i, now=lambda i=i: base + dt.timedelta(seconds=i))
            lg.emit("x")
            lg.close()
        names = sorted(p.name for p in (Path(self.d) / "logs").glob("events-*.jsonl"))
        self.assertEqual(len(names), 20)
        self.assertTrue(names[0].startswith("events-20261011-090005"))
        self.assertTrue(names[-1].startswith("events-20261011-090024"))

    def test_same_second_same_pid_does_not_overwrite(self):
        n = lambda: dt.datetime(2026, 10, 11, 9, 0, 0)
        a = self.mk(self.d, pid=7, now=n)
        a.emit("one")
        b = self.mk(self.d, pid=7, now=n)
        b.emit("two")
        self.assertNotEqual(a.path, b.path)
        self.assertEqual(self.lines(a)[0]["type"], "one")

    def test_failure_does_not_raise(self):
        f = Path(self.d) / "file"
        f.write_text("x")
        log = self.mk(f)  # logs 폴더를 만들 수 없다
        self.assertTrue(log.failed)
        self.assertFalse(log.emit("x"))

    def test_unserializable_value_does_not_raise(self):
        log = self.mk(self.d)
        self.assertTrue(log.emit("x", v=object()))
        self.assertEqual(self.lines(log)[0].get("error"), "unserializable")

    def test_concurrent_emits_are_whole_lines(self):
        log = self.mk(self.d)
        def w(k):
            for i in range(200):
                log.emit("c", k=k, i=i)
        ts = [threading.Thread(target=w, args=(k,)) for k in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(self.lines(log)), 800)

    def test_no_forbidden_dependencies(self):
        for name in ("settings.py", "eventlog.py", "devopts.py"):
            t = (ROOT / "src/mac/nsu_kangs_rab/core" / name).read_text(encoding="utf-8")
            for bad in ("PySide6", "keyring", "subprocess", "nsu_kangs_rab.platform"):
                self.assertNotIn(bad, t, "%s: %s" % (name, bad))


class DefectFixesTest(unittest.TestCase):
    """D-027(저장 실패를 예외로 내지 않는다) · D-028(중첩에서 떨어뜨린 필드의 흔적) · update_settings."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_save_unserializable_returns_false_and_leaves_no_tmp(self):
        path = self.dir / "settings.json"
        ok, why = S.save_settings(path, {"save_dir": Path("/tmp/x")})
        self.assertFalse(ok)
        self.assertEqual(why, "TypeError")
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_save_failure_keeps_previous_file(self):
        path = self.dir / "settings.json"
        self.assertTrue(S.save_settings(path, {"a": 1})[0])
        self.assertFalse(S.save_settings(path, {"a": object()})[0])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual([p.name for p in self.dir.iterdir()], ["settings.json"])

    def test_dropped_nested_fields_listed_with_dotted_paths(self):
        log = eventlog.EventLog(self.dir)
        self.addCleanup(log.close)
        log.emit("nested", payload={"text": "본문", "token": "t", "ok": 1, "deep": {"content": "c", "n": 2}},
                 items=[{"key": "k", "v": 1}])
        rec = json.loads(Path(log.path).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["payload"], {"ok": 1, "deep": {"n": 2}})
        self.assertEqual(rec["items"], [{"v": 1}])
        self.assertEqual(rec["dropped_fields"],
                         sorted(["payload.text", "payload.token", "payload.deep.content", "items[0].key"]))

    def test_top_level_and_nested_drops_are_merged(self):
        log = eventlog.EventLog(self.dir)
        self.addCleanup(log.close)
        log.emit("mix", text="본문", p={"input": 1})
        rec = json.loads(Path(log.path).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["dropped_fields"], ["p.input", "text"])
        self.assertNotIn("text", rec)

    def test_no_dropped_fields_key_when_clean(self):
        log = eventlog.EventLog(self.dir)
        self.addCleanup(log.close)
        log.emit("clean", p={"a": {"b": 1}})
        rec = json.loads(Path(log.path).read_text(encoding="utf-8").splitlines()[-1])
        self.assertNotIn("dropped_fields", rec)

    def test_update_writes_only_user_keys_and_changes(self):
        path = self.dir / "settings.json"
        path.write_text(json.dumps({"claude_path": "/x/claude", "ui": {"a": 1, "b": 2}}), encoding="utf-8")
        ok, _ = S.update_settings(path, {"ui": {"b": 3}, "save_dir": "/d"})
        self.assertTrue(ok)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"claude_path": "/x/claude", "ui": {"a": 1, "b": 3}, "save_dir": "/d"})

    def test_update_without_file_writes_changes_only(self):
        path = self.dir / "sub" / "settings.json"
        self.assertTrue(S.update_settings(path, {"provider": "claude_api"})[0])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"provider": "claude_api"})

    def test_update_refuses_to_overwrite_corrupt_file(self):
        path = self.dir / "settings.json"
        path.write_text("{broken", encoding="utf-8")
        ok, why = S.update_settings(path, {"a": 1})
        self.assertFalse(ok)
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_update_does_not_mutate_inputs(self):
        path = self.dir / "settings.json"
        ch = {"ui": {"b": [1, 2]}}
        S.update_settings(path, ch)
        self.assertEqual(ch, {"ui": {"b": [1, 2]}})


if __name__ == "__main__":
    unittest.main()
