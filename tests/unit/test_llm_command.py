"""K-01: llm.build_command · clean_env 의 단위 시험 (ENV-1, AC-FR1-13 · AC-FR1-19 의 함수 수준)."""
import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import llm  # noqa: E402
from nsu_kangs_rab.core.llm import (  # noqa: E402
    Auth, AuthConfigError, CommandConfigError, Kind, SessionConfig, build_command, clean_env)

AUTH_VARS = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_PROFILE",
             "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
             "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_IDENTITY_TOKEN_FILE"]
ALLOWED_5 = ["PATH", "HOME", "LC_ALL", "https_proxy", "NODE_EXTRA_CA_CERTS"]
MUST_BE_ABSENT = AUTH_VARS + ["ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_X", "CLAUDECODE",
                              "CLAUDE_PID", "CLAUDE_EFFORT", "CMUX_SURFACE_ID", "CMUX_SOCKET_PATH", "FOO_ACTIVE"]


def parent_env():
    env = {n: "secret-%s" % n for n in AUTH_VARS}
    env["ANTHROPIC_API_KEY"] = "X"
    env.update({n: "v" for n in ["ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_X", "CLAUDECODE",
                                 "CLAUDE_PID", "CLAUDE_EFFORT", "CMUX_SURFACE_ID", "CMUX_SOCKET_PATH", "FOO_ACTIVE"]})
    env.update({n: "/v/" + n for n in ALLOWED_5})
    return env


class CleanEnv(unittest.TestCase):
    def test_subscription_equals_input_intersect_allowlist(self):
        env = parent_env()
        out = clean_env(env, Auth.SUBSCRIPTION, "Y")
        expected = {k for k in env if llm._allowed(k)}
        self.assertEqual(set(out) - TELEMETRY, expected)   # 부분집합이 아니라 같음 (ENV-1). 앱이 넣는 두 변수(0055)는 따로
        self.assertEqual(set(out) - TELEMETRY, set(ALLOWED_5))
        for n in MUST_BE_ABSENT:
            self.assertNotIn(n, out)
        self.assertNotIn("Y", out.values())            # 구독이면 키를 받아도 넣지 않는다

    def test_api_adds_only_the_key(self):
        env = parent_env()
        out = clean_env(env, Auth.API, "Y")
        self.assertEqual(set(out) - TELEMETRY, set(ALLOWED_5) | {"ANTHROPIC_API_KEY"})
        self.assertEqual(out["ANTHROPIC_API_KEY"], "Y")
        for n in MUST_BE_ABSENT:
            if n != "ANTHROPIC_API_KEY":
                self.assertNotIn(n, out)

    def test_api_without_key_raises(self):
        for key in (None, ""):
            with self.assertRaises(AuthConfigError) as cm:
                clean_env(parent_env(), Auth.API, key)
            self.assertNotIn("secret-", str(cm.exception))

    def test_input_is_not_modified(self):
        for auth, key in ((Auth.SUBSCRIPTION, "Y"), (Auth.API, "Y"), (Auth.API, None), (Auth.API, "")):
            env = parent_env()
            before = copy.deepcopy(env)
            try:
                clean_env(env, auth, key)
            except AuthConfigError:
                pass
            self.assertEqual(env, before)

    def test_result_is_a_new_dict(self):
        env = parent_env()
        out = clean_env(env, Auth.SUBSCRIPTION)
        out["X"] = "1"
        self.assertNotIn("X", env)

    def test_all_allowed_names_and_prefix(self):
        env = {n: "1" for n in llm.ALLOWED_NAMES}
        env.update({"LC_CTYPE": "ko_KR.UTF-8", "LC_MESSAGES": "C", "LCX": "no", "CLAUDE_CODE_ENTRYPOINT": "x"})
        out = clean_env(env, Auth.SUBSCRIPTION)
        self.assertEqual(set(out) - TELEMETRY, set(llm.ALLOWED_NAMES) | {"LC_CTYPE", "LC_MESSAGES"})

    def test_empty_env(self):
        self.assertEqual(clean_env({}, Auth.SUBSCRIPTION), TELEMETRY_OFF)
        self.assertEqual(clean_env({}, Auth.API, "Y"), dict(TELEMETRY_OFF, ANTHROPIC_API_KEY="Y"))

    def test_telemetry_off_always_set_regardless_of_user_values(self):  # 결정 0055
        for user in ({}, {"DISABLE_TELEMETRY": "0", "DISABLE_ERROR_REPORTING": ""}, {"DISABLE_TELEMETRY": "1"}):
            for auth, key in ((Auth.SUBSCRIPTION, None), (Auth.API, "Y")):
                out = clean_env(user, auth, key)
                self.assertEqual(out["DISABLE_TELEMETRY"], "1")
                self.assertEqual(out["DISABLE_ERROR_REPORTING"], "1")

    def test_nonessential_traffic_not_set(self):  # 결정 0055 2항
        out = clean_env({"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}, Auth.SUBSCRIPTION)
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", out)


TELEMETRY_OFF = {"DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1"}
TELEMETRY = set(TELEMETRY_OFF)


def cfg(**kw):
    base = dict(claude_path="/x/claude", model="sonnet", effort="medium")
    base.update(kw)
    return SessionConfig(**base)


class BuildCommand(unittest.TestCase):
    def test_resident_core_args(self):
        cmd = build_command(cfg(system_prompt_file="/run/p.txt"))
        self.assertEqual(cmd[0], "/x/claude")
        self.assertEqual(cmd[1], "-p")
        self.assertEqual(cmd[cmd.index("--input-format") + 1], "stream-json")
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "medium")
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--no-session-persistence", cmd)
        self.assertEqual(cmd[cmd.index("--system-prompt-file") + 1], "/run/p.txt")
        self.assertNotIn("--system-prompt", cmd)

    def test_no_bare_one_settings_and_refuse(self):
        for c in (cfg(), cfg(kind=Kind.ONESHOT, tools=("Skill", "Read", "Write"),
                             settings_extra={"permissions": {"allow": ["Edit(//a/**)"]}, "crossSessionInbound": "accept"},
                             plugin_dir="/p", permission_mode="dontAsk")):
            cmd = build_command(c)
            self.assertNotIn("--bare", cmd)
            self.assertEqual(cmd.count("--settings"), 1)
            self.assertEqual(cmd.count("--session-id"), 0)
            self.assertEqual(cmd.count("--no-session-persistence"), 1)
            s = json.loads(cmd[cmd.index("--settings") + 1])
            self.assertEqual(s["crossSessionInbound"], "refuse")   # extra 가 덮지 못한다

    def test_oneshot_args(self):
        cmd = build_command(cfg(kind=Kind.ONESHOT, tools=("Skill", "Read", "Write"), plugin_dir="/p",
                                permission_mode="dontAsk", settings_extra={"permissions": {"allow": ["Edit(//a/**)"]}}))
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Skill,Read,Write")
        self.assertEqual(cmd[cmd.index("--plugin-dir") + 1], "/p")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(json.loads(cmd[cmd.index("--settings") + 1])["permissions"]["allow"], ["Edit(//a/**)"])

    def test_resident_ignores_tools(self):
        cmd = build_command(cfg(tools=("Read",), plugin_dir="/p", permission_mode="dontAsk"))
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertNotIn("--plugin-dir", cmd)
        self.assertNotIn("--permission-mode", cmd)

    def test_effort_omitted_when_none(self):
        self.assertNotIn("--effort", build_command(cfg(effort=None)))

    def test_system_prompt_string_fallback(self):
        cmd = build_command(cfg(system_prompt="규칙"))
        self.assertEqual(cmd[cmd.index("--system-prompt") + 1], "규칙")
        self.assertNotIn("--system-prompt-file", cmd)

    def test_system_prompt_limit(self):
        build_command(cfg(system_prompt="a" * 100_000))
        with self.assertRaises(CommandConfigError):
            build_command(cfg(system_prompt="a" * 100_001))

    def test_long_session_prompt_not_truncated(self):
        """AC-FR2-11 의 인자 구성: 한글 2만 자가 인자에서 잘리지 않는다 (문자열 경로 전문, 파일 경로는 경로만)."""
        text = "가" * 20_000
        cmd = build_command(cfg(system_prompt=text))
        self.assertEqual(cmd[cmd.index("--system-prompt") + 1], text)
        cmd = build_command(cfg(system_prompt_file="/run/p.txt"))
        self.assertEqual(cmd[cmd.index("--system-prompt-file") + 1], "/run/p.txt")
        self.assertNotIn("--system-prompt", cmd)

    def test_both_prompts_rejected(self):
        with self.assertRaises(CommandConfigError):
            build_command(cfg(system_prompt="a", system_prompt_file="/f"))

    def test_partial_messages_flag(self):
        self.assertIn("--include-partial-messages", build_command(cfg()))
        self.assertNotIn("--include-partial-messages", build_command(cfg(include_partial_messages=False)))


class FakeClaudeReceivesArgs(unittest.TestCase):
    """가짜 `claude` 가 실제로 받은 인자 · 환경으로 대조한다 (K-01: 가짜 `claude` 가 받은 인자로 대조)."""

    def test_args_and_env_seen_by_process(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "seen.json"
            fake = Path(d) / "claude"
            fake.write_text("#!%s\nimport json,os,sys\njson.dump({'argv':sys.argv[1:],'env':sorted(os.environ)},open(%r,'w'))\n"
                            % (sys.executable, str(out)))
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = clean_env(dict(parent_env(), PATH=os.environ.get("PATH", "/usr/bin")), Auth.API, "Y")
            cmd = build_command(cfg(claude_path=str(fake), system_prompt_file="/r/p"))
            subprocess.run(cmd, env=env, check=True, stdin=subprocess.DEVNULL)
            seen = json.loads(out.read_text())
            self.assertEqual(seen["argv"], cmd[1:])
            self.assertEqual(seen["argv"].count("--settings"), 1)
            self.assertIn("-p", seen["argv"])
            self.assertNotIn("--bare", seen["argv"])
            for n in MUST_BE_ABSENT:
                if n != "ANTHROPIC_API_KEY":
                    self.assertNotIn(n, seen["env"])
            self.assertIn("ANTHROPIC_API_KEY", seen["env"])
            self.assertIn("PATH", seen["env"])


class Static(unittest.TestCase):
    def test_core_does_not_import_qt_or_platform(self):
        for p in (ROOT / "src" / "mac" / "nsu_kangs_rab" / "core").glob("*.py"):
            t = p.read_text(encoding="utf-8")
            for bad in ("PySide6", "nsu_kangs_rab.platform", "from ..platform", "import sounddevice", "mlx"):
                self.assertNotIn(bad, t, "%s: %s" % (p.name, bad))

    def test_no_claude_credential_access_or_sdk(self):
        for p in (ROOT / "src" / "mac" / "nsu_kangs_rab" / "core").glob("*.py"):
            t = p.read_text(encoding="utf-8")
            for bad in (".credentials.json", "claude_agent_sdk", "claude-agent-sdk", "setup-token", "Claude Code-credentials", '"--bare"'):
                self.assertNotIn(bad, t, "%s: %s" % (p.name, bad))


if __name__ == "__main__":
    unittest.main()
