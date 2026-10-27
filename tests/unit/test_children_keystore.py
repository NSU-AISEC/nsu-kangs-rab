"""K-04: PID 상태 파일 · 고아 정리(B-10, AC-FR11-1 · 3)와 API 키 보관(B-13, AC-FR1-11 · 16 · 17)."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))

from nsu_kangs_rab.core import api_key_store as aks  # noqa: E402
from nsu_kangs_rab.core import children  # noqa: E402
from nsu_kangs_rab.core.procs import Procs  # noqa: E402


def spawn_sleep(ignore_term=False):
    code = "import signal,time\n%stime.sleep(60)" % ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "")
    p = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    for _ in range(100):  # SIGTERM 무시 설정이 끝나기를 기다린다
        if children.process_started(p.pid):
            break
        time.sleep(0.02)
    time.sleep(0.15 if ignore_term else 0)
    return p


def wait_gone(p, timeout=5.0):
    try:
        p.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.procs_to_kill = []
        self.addCleanup(self._kill)

    def _kill(self):
        for p in self.procs_to_kill:
            if p.poll() is None:
                os.kill(p.pid, signal.SIGKILL)  # 시험이 시작한 PID 만
                p.wait()

    def mk(self, ignore_term=False):
        p = spawn_sleep(ignore_term)
        self.procs_to_kill.append(p)
        return p

    def test_add_writes_entry_with_modes(self):
        p = self.mk()
        reg = children.ChildRegistry(self.tmp.name)
        self.assertTrue(reg.add(p.pid, "claude", "/x/claude"))
        data = json.loads(reg.path.read_text(encoding="utf-8"))
        e = data["children"][0]
        self.assertEqual((e["pid"], e["role"], e["argv0"]), (p.pid, "claude", "/x/claude"))
        self.assertEqual(e["started"], children.process_started(p.pid))
        self.assertEqual(oct(reg.path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(reg.dir.stat().st_mode & 0o777), "0o700")
        self.assertEqual([x.name for x in reg.dir.iterdir()], ["children.json"])  # 임시 파일이 남지 않는다

    def test_add_dead_pid_is_not_recorded(self):
        reg = children.ChildRegistry(self.tmp.name, started=lambda pid: None)
        self.assertFalse(reg.add(99999, "claude", "x"))
        self.assertEqual(reg.entries(), [])

    def test_procs_on_change_records_and_removes(self):
        reg = children.ChildRegistry(self.tmp.name)
        procs = Procs(on_change=reg.on_change)
        h = procs.spawn([sys.executable, "-c", "import time; time.sleep(60)"], {"PATH": os.environ["PATH"]},
                        self.tmp.name, "claude")
        pid = h.pid
        try:
            ents = reg.entries()
            self.assertEqual([(e["pid"], e["role"]) for e in ents], [(pid, "claude")])
            self.assertEqual(ents[0]["argv0"], sys.executable)
        finally:
            procs.terminate(h, stdin_wait_s=0.2, term_wait_s=2.0)
            procs.reap(h)
            for f in (h.popen.stdin, h.popen.stdout, h.popen.stderr):
                if f:
                    f.close()
        self.assertEqual(reg.entries(), [])  # AC-FR11-1: 정상 종료 뒤 남은 항목이 없다
        self.assertIsNone(children.process_started(pid))

    def test_corrupt_state_file_is_empty(self):
        reg = children.ChildRegistry(self.tmp.name)
        reg.dir.mkdir(parents=True)
        reg.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(reg.entries(), [])
        self.assertEqual(children.cleanup_orphans(self.tmp.name), [])

    def test_cleanup_terminates_matching_orphan(self):
        p = self.mk()
        children.ChildRegistry(self.tmp.name).add(p.pid, "claude", "x")
        events = []
        res = children.cleanup_orphans(self.tmp.name, emit=lambda t, **f: events.append((t, f)))
        self.assertEqual([r["result"] for r in res], ["terminated"])
        self.assertTrue(wait_gone(p))
        self.assertEqual(events[0][0], "orphan_cleanup")
        self.assertEqual(events[0][1]["pid"], p.pid)
        self.assertEqual(children.ChildRegistry(self.tmp.name).entries(), [])  # 상태 파일을 비운다

    def test_cleanup_skips_mismatched_start_time(self):
        p = self.mk()
        reg = children.ChildRegistry(self.tmp.name, started=lambda pid: "Mon Jan  1 00:00:00 2001")
        reg.add(p.pid, "claude", "x")
        res = children.cleanup_orphans(self.tmp.name)
        self.assertEqual([r["result"] for r in res], ["skipped_mismatch"])
        time.sleep(0.3)
        self.assertIsNone(p.poll())  # 건드리지 않았다
        self.assertEqual(children.ChildRegistry(self.tmp.name).entries(), [])

    def test_cleanup_gone_and_self(self):
        reg = children.ChildRegistry(self.tmp.name, started=lambda pid: "T")
        reg.add(4000001, "claude", "x")
        reg.add(os.getpid(), "claude", "y")
        sent = []
        res = children.cleanup_orphans(self.tmp.name, started=lambda pid: None if pid == 4000001 else "T",
                                       kill=lambda pid, sig: sent.append((pid, sig)))
        self.assertEqual({r["pid"]: r["result"] for r in res}, {4000001: "gone", os.getpid(): "skipped_self"})
        self.assertEqual(sent, [])

    def test_cleanup_kills_when_term_is_ignored(self):
        p = self.mk(ignore_term=True)
        children.ChildRegistry(self.tmp.name).add(p.pid, "claude", "x")
        res = children.cleanup_orphans(self.tmp.name, term_wait_s=0.5)
        self.assertEqual([r["result"] for r in res], ["killed"])
        self.assertTrue(wait_gone(p))

    def test_cleanup_never_signals_other_pid(self):
        sent = []
        reg = children.ChildRegistry(self.tmp.name, started=lambda pid: "T")
        reg.add(4000002, "claude", "x")
        children.cleanup_orphans(self.tmp.name, started=lambda pid: "T" if not sent else None,
                                 kill=lambda pid, sig: sent.append((pid, sig)), sleep=lambda s: None)
        self.assertEqual({pid for pid, _ in sent}, {4000002})

    def test_stale_prompt_files_removed_only(self):
        run = Path(self.tmp.name) / "run"
        (run / "cwd").mkdir(parents=True)
        (run / "system-prompt-aaa.txt").write_text("x")
        (run / "system-prompt-bbb.txt").write_text("y")
        (run / "keep.txt").write_text("z")
        removed = children.remove_stale_prompt_files(self.tmp.name)
        self.assertEqual(sorted(removed), ["system-prompt-aaa.txt", "system-prompt-bbb.txt"])
        self.assertEqual(sorted(p.name for p in run.iterdir()), ["cwd", "keep.txt"])
        self.assertEqual(children.remove_stale_prompt_files(Path(self.tmp.name) / "none"), [])

    def test_no_name_based_kill_in_sources(self):
        d = Path(children.__file__).parent
        for name in ("children.py", "api_key_store.py", "procs.py"):
            text = (d / name).read_text(encoding="utf-8")
            for bad in ("pkill", "killall"):
                self.assertNotIn(bad, text.replace("`" + bad + "`", ""))  # 주석의 인용은 제외


class RecordingBackend:
    def __init__(self, fail=None):
        self.calls, self.data, self.fail = [], {}, fail

    def _go(self, kind, *a):
        self.calls.append((kind,) + a)
        if self.fail:
            raise self.fail
    def get_password(self, s, u):
        self._go("get", s, u)
        return self.data.get((s, u))

    def set_password(self, s, u, p):
        self._go("set", s, u)  # 키 값은 기록하지 않는다
        self.data[(s, u)] = p

    def delete_password(self, s, u):
        self._go("delete", s, u)
        if (s, u) not in self.data:
            raise PasswordDeleteError("not found") from NotFound("x")
        del self.data[(s, u)]


class PasswordDeleteError(Exception):
    pass


class NotFound(Exception):  # keyring.backends.macOS.api.NotFound 와 같은 이름
    pass


class KeychainDenied(Exception):
    pass


KEY = "sk-ant-TEST-KEY-0123456789"


class ApiKeyStoreTest(unittest.TestCase):
    def test_delete_only_not_found_returns_false(self):  # D-031
        class Wrap(RecordingBackend):
            def __init__(self, cause):
                super().__init__()
                self.cause = cause

            def delete_password(self, s, u):
                err = PasswordDeleteError("Can't delete password in keychain")
                if self.cause is None:
                    raise err
                raise err from self.cause

        self.assertFalse(aks.ApiKeyStore(backend=Wrap(NotFound("x"))).delete())
        self.assertFalse(aks.ApiKeyStore(backend=Wrap(None)).delete())  # 원인을 붙이지 않는 백엔드의 "없음"
        for cause in (KeychainDenied("denied"), RuntimeError("other")):
            with self.assertRaises(aks.ApiKeyStoreError, msg=repr(cause)):
                aks.ApiKeyStore(backend=Wrap(cause)).delete()

    def test_set_get_delete_roundtrip_with_fixed_service(self):
        b = RecordingBackend()
        s = aks.ApiKeyStore(backend=b)
        self.assertIsNone(s.get())
        self.assertFalse(s.has())
        s.set("  " + KEY + " \n")
        self.assertEqual(s.get(), KEY)
        self.assertTrue(s.has())
        self.assertTrue(s.delete())
        self.assertIsNone(s.get())
        self.assertFalse(s.delete())  # 원래 없던 항목
        self.assertEqual({(c[1], c[2]) for c in b.calls}, {("ProfKangRAB.ClaudeAPIKey", "default")})
        self.assertEqual(aks.SERVICE, "ProfKangRAB.ClaudeAPIKey")

    def test_account_override_changes_account_only(self):
        b = RecordingBackend()
        aks.ApiKeyStore(backend=b, account="test-acct").set(KEY)
        self.assertEqual(b.calls, [("set", "ProfKangRAB.ClaudeAPIKey", "test-acct")])

    def test_empty_key_and_account_rejected(self):
        s = aks.ApiKeyStore(backend=RecordingBackend())
        for bad in ("", "   ", None):
            with self.assertRaises(aks.ApiKeyStoreError):
                s.set(bad)
        with self.assertRaises(aks.ApiKeyStoreError):
            aks.ApiKeyStore(backend=RecordingBackend(), account=" ")

    def test_key_never_in_repr_or_errors(self):
        b = RecordingBackend(fail=RuntimeError("denied for " + KEY))
        s = aks.ApiKeyStore(backend=b)
        self.assertNotIn(KEY, repr(s))
        for fn in (s.get, s.delete, lambda: s.set(KEY)):
            with self.assertRaises(aks.ApiKeyStoreError) as cm:
                fn()
            self.assertNotIn(KEY, str(cm.exception))
            self.assertIsNone(cm.exception.__cause__)
            self.assertIn("RuntimeError", str(cm.exception))

    def test_non_macos_backend_from_factory_is_refused(self):
        class PlaintextKeyring:
            pass
        s = aks.ApiKeyStore(backend_factory=PlaintextKeyring)
        with self.assertRaises(aks.ApiKeyStoreError):
            s.get()

    def test_macos_backend_from_factory_is_accepted(self):
        MacBackend = type("Keyring", (RecordingBackend,), {"__module__": "keyring.backends.macOS"})
        s = aks.ApiKeyStore(backend_factory=MacBackend)
        s.set(KEY)
        self.assertEqual(s.get(), KEY)

    def test_default_factory_without_keyring_raises_store_error(self):
        try:
            import keyring  # noqa: F401
            self.skipTest("keyring 이 설치되어 있다")
        except ImportError:
            pass
        with self.assertRaises(aks.ApiKeyStoreError):
            aks.ApiKeyStore().get()

    def test_source_has_no_subprocess_keychain_access(self):
        text = Path(aks.__file__).read_text(encoding="utf-8")
        for bad in ("subprocess", "-generic-password", "-w ", ".credentials", "Claude Code-credentials"):
            self.assertNotIn(bad, text)


class KillAllTest(unittest.TestCase):  # 결정 0172 2항: 종료 상한이 지나면 기록된 PID 만 SIGKILL 한다
    def test_kill_all_signals_only_matching_started(self):
        d = tempfile.mkdtemp()
        calls = []
        reg = children.ChildRegistry(d, started=lambda pid: {101: "A", 102: "B"}.get(pid))
        reg.add(101, "stt_speech", "x")
        reg.add(102, "claude", "y")
        reg._started = lambda pid: {101: "A", 102: "다른 시각"}.get(pid)     # 102 는 PID 가 재사용되었다
        sent = reg.kill_all(kill=lambda pid, sig: calls.append((pid, sig)))
        self.assertEqual(sent, [101])
        self.assertEqual(calls, [(101, signal.SIGKILL)])

    def test_kill_all_empty_registry(self):
        reg = children.ChildRegistry(tempfile.mkdtemp())
        self.assertEqual(reg.kill_all(kill=lambda *_: self.fail("신호를 보내지 않는다")), [])


if __name__ == "__main__":
    unittest.main()
