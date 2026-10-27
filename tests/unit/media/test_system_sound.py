"""K-18 단위 시험(장치 없음): 보조 프로세스를 가짜 스크립트로 대신해 `SystemSoundSource` 의 연결 · 종료 · 오류 전달을 본다."""
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

import numpy as np

from nsu_kangs_rab.platform.audio import system_sound
from nsu_kangs_rab.core.appstate import START_FAILED_PREFIX as PREFIX
from nsu_kangs_rab.platform.audio.system_sound import SckBackend, SystemSoundSource


def write_helper(d, body):
    path = os.path.join(d, "helper.py")
    with open(path, "w") as f:
        f.write("#!%s\n" % sys.executable + textwrap.dedent(body))
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


STREAMING = """
import sys, time, struct
import numpy as np
x = (0.1 * np.sin(np.arange(4800) * 0.05)).astype('<f4')
st = np.stack([x, x], axis=1).astype('<f4').tobytes()
out = sys.stdout.buffer
for _ in range(20):
    out.write(st); out.flush(); time.sleep(0.05)
sys.stdin.buffer.read()      # 부모가 stdin 을 닫으면 끝난다
"""

PERMISSION = """
import sys
sys.stderr.write('{"error":"no_permission","detail":"denied"}\\n')
sys.exit(3)
"""


def wait_for(cond, sec=6.0):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class SystemSoundTest(unittest.TestCase):
    def test_blocks_converted_and_pid_terminated_on_stop(self):
        with tempfile.TemporaryDirectory() as d:
            be = SckBackend(write_helper(d, STREAMING))
            from nsu_kangs_rab.platform.audio.mic_source import MicSource
            m = MicSource(be, source_name="system", tick_s=0.02, poll_s=10)
            blocks, states = [], []
            m.start(blocks.append, lambda s, dt="": states.append((s, dt)))
            self.assertTrue(wait_for(lambda: sum(b.samples.size for b in blocks) >= 16000))
            self.assertEqual(states[0][0], "수집 중")
            self.assertTrue(all(b.samples.dtype == np.float32 for b in blocks))
            pid = be.streams[0].pid
            self.assertIsNotNone(pid)
            self.assertTrue(pid_alive(pid))
            m.stop()
            self.assertTrue(wait_for(lambda: not pid_alive(pid), 5))
            self.assertEqual(states[-1][0], "종료")
            self.assertEqual(len(be.streams), 1)

    def test_permission_failure_is_reported_as_stall_reason(self):
        with tempfile.TemporaryDirectory() as d:
            be = SckBackend(write_helper(d, PERMISSION))
            from nsu_kangs_rab.platform.audio.mic_source import MicSource
            m = MicSource(be, source_name="system", tick_s=0.02, retry_s=0.3, poll_s=10)
            states = []
            m.start(lambda b: None, lambda s, dt="": states.append((s, dt)))
            self.assertTrue(wait_for(lambda: ("중단", "화면 기록 권한이 없습니다") in states))
            self.assertEqual(be.last_detail, "denied")   # 원래 오류 문자열이 남는다
            m.stop()

    def test_no_permission_is_not_restarted(self):
        """AC-FR3-11 · D-056: 종료 코드 3 이면 다시 시작하지 않는다(시작 횟수 1). 다른 종료는 재시작한다."""
        with tempfile.TemporaryDirectory() as d:
            counter = os.path.join(d, "count")
            body = PERMISSION.replace("import sys\n", "import sys\nopen(%r, 'a').write('x')\n" % counter)
            be = SckBackend(write_helper(d, body))
            from nsu_kangs_rab.platform.audio.mic_source import MicSource
            m = MicSource(be, source_name="system", tick_s=0.02, retry_s=0.2, poll_s=10)
            states = []
            m.start(lambda b: None, lambda s, dt="": states.append((s, dt)))
            self.assertTrue(wait_for(lambda: ("중단", "화면 기록 권한이 없습니다") in states))
            time.sleep(1.5)                       # 재시도 간격(0.2 s)의 몇 배
            m.stop()
            with open(counter) as f:
                self.assertEqual(len(f.read()), 1)
            self.assertEqual(len(be.streams), 1)
            self.assertTrue(be.no_retry())

    def test_other_exit_is_restarted(self):
        with tempfile.TemporaryDirectory() as d:
            counter = os.path.join(d, "count")
            # 첫 음성 블록을 낸 뒤 종료 코드 4 로 끝난다 (D-194: 첫 블록 뒤의 종료만 다시 시작한다)
            body = ("import sys\nopen(%r, 'a').write('x')\n"
                    "sys.stdout.buffer.write(b'\\0' * 1600); sys.stdout.buffer.flush()\n"
                    "sys.stderr.write('{\"error\":\"stream_error\",\"detail\":\"x\"}\\n')\nsys.exit(4)\n" % counter)
            be = SckBackend(write_helper(d, body))
            from nsu_kangs_rab.platform.audio.mic_source import MicSource
            m = MicSource(be, source_name="system", tick_s=0.02, retry_s=0.2, poll_s=10)
            m.start(lambda b: None, lambda s, dt="": None)
            self.assertTrue(wait_for(lambda: len(be.streams) >= 3))
            m.stop()
            self.assertFalse(be.no_retry())

    def test_exit4_before_first_block_is_start_failure_not_restarted(self):
        """D-194: 첫 블록 전에 종료 코드 4 · 0 으로 끝난 시도는 시작 실패이다: 접두어가 붙고 다시 시작하지 않는다."""
        from nsu_kangs_rab.core.appstate import START_FAILED_PREFIX
        from nsu_kangs_rab.platform.audio.mic_source import MicSource
        for code, err in ((4, "{\"error\":\"stream_error\",\"detail\":\"x\"}"), (0, "")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as d:
                counter = os.path.join(d, "count")
                body = ("import sys\nopen(%r, 'a').write('x')\nsys.stderr.write(%r + '\\n')\nsys.exit(%d)\n" % (counter, err, code))
                be = SckBackend(write_helper(d, body))
                states = []
                m = MicSource(be, source_name="system", tick_s=0.02, retry_s=0.2, poll_s=10)
                m.start(lambda b: None, lambda s, dt="": states.append((s, dt)))
                self.assertTrue(wait_for(lambda: any(s == "중단" for s, _ in states)))
                time.sleep(1.0)                                   # retry_s 의 5배: 다시 시작했다면 스트림이 늘어난다
                m.stop()
                self.assertEqual(len(be.streams), 1)
                stopped = [dt for s, dt in states if s == "중단"]
                self.assertTrue(stopped[0].startswith(START_FAILED_PREFIX + ": "), stopped)

    def test_missing_helper_reports_and_does_not_crash(self):
        be = SckBackend("/nonexistent/sck_audio")
        from nsu_kangs_rab.platform.audio.mic_source import MicSource
        m = MicSource(be, tick_s=0.02, retry_s=0.3)
        states = []
        m.start(lambda b: None, lambda s, dt="": states.append((s, dt)))
        self.assertTrue(wait_for(lambda: ("중단", PREFIX + ": 수집 보조 프로그램이 없습니다") in states))
        time.sleep(1.0)                           # 재시도 간격(0.3 s)의 몇 배: 더 열지 않는다
        m.stop()
        self.assertEqual(len(be.streams), 0)
        self.assertTrue(be.no_retry())
        self.assertEqual(len([x for x in states if x[0] == "중단"]), 1)

    def _run_exit(self, code, reason):
        with tempfile.TemporaryDirectory() as d:
            counter = os.path.join(d, "count")
            body = ("import sys\nopen(%r, 'a').write('x')\n"
                    "sys.stderr.write('{\"error\":\"%s\",\"detail\":\"d\"}\\n')\nsys.exit(%d)\n" % (counter, reason, code))
            be = SckBackend(write_helper(d, body))
            from nsu_kangs_rab.platform.audio.mic_source import MicSource
            m = MicSource(be, source_name="system", tick_s=0.02, retry_s=0.2, poll_s=10)
            states = []
            m.start(lambda b: None, lambda s, dt="": states.append((s, dt)))
            self.assertTrue(wait_for(lambda: any(x[0] == "중단" for x in states)))
            time.sleep(1.2)
            m.stop()
            with open(counter) as f:
                n = len(f.read())
            return states, n, be

    def test_start_failed_exit1_classified_and_not_restarted(self):
        states, n, be = self._run_exit(1, "start_failed")
        self.assertIn(("중단", PREFIX + ": 수집을 시작하지 못했습니다"), states)
        self.assertEqual(n, 1)
        self.assertTrue(be.no_retry())

    def test_no_display_exit2_classified_and_not_restarted(self):
        states, n, be = self._run_exit(2, "no_display")
        self.assertIn(("중단", PREFIX + ": 화면을 찾지 못했습니다"), states)
        self.assertEqual(n, 1)

    def test_no_permission_has_no_start_failed_prefix(self):
        states, n, be = self._run_exit(3, "no_permission")
        self.assertIn(("중단", "화면 기록 권한이 없습니다"), states)
        self.assertFalse([x for x in states if x[1].startswith(PREFIX)])

    def test_not_executable_helper_is_start_failed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "helper")
            open(path, "w").write("x")            # 실행 권한이 없는 파일
            be = SckBackend(path)
            from nsu_kangs_rab.platform.audio.mic_source import MicSource
            m = MicSource(be, source_name="system", tick_s=0.02, retry_s=0.2, poll_s=10)
            states = []
            m.start(lambda b: None, lambda s, dt="": states.append((s, dt)))
            self.assertTrue(wait_for(lambda: any(x[1].startswith(PREFIX) for x in states)))
            time.sleep(0.8)
            m.stop()
            self.assertEqual(len(be.streams), 1)
            self.assertTrue(be.no_retry())

    def test_mic_source_halts_when_backend_has_no_default_and_no_retry(self):
        from nsu_kangs_rab.platform.audio.mic_source import MicSource

        class B:
            n = 0
            def default_input(self):
                B.n += 1
                return None
            def no_retry(self):
                return True
            def last_error(self):
                return "x"
        m = MicSource(B(), tick_s=0.02, retry_s=0.1, poll_s=10)
        m.start(lambda b: None, lambda s, dt="": None)
        time.sleep(0.8)
        m.stop()
        self.assertEqual(B.n, 1)

    def test_factory_returns_mic_source_with_system_name(self):
        src = SystemSoundSource("/nonexistent/sck_audio")
        self.assertEqual(src._source, "system")

    def test_single_stream(self):
        with tempfile.TemporaryDirectory() as d:
            src = SystemSoundSource(write_helper(d, STREAMING), tick_s=0.02, poll_s=10)
            blocks = []
            src.start(blocks.append)
            src.start(blocks.append)   # 무시된다
            self.assertTrue(wait_for(lambda: blocks))
            src.stop()
            self.assertEqual(len(src._backend.streams), 1)

    def test_swift_source_keeps_stream_reference(self):
        """원본 존재 검사일 뿐이다: 지역 변수 `SCStream` 이 해제되면 첫 버퍼 뒤 수집이 멈춘다(2026-10-12 실기에서 발견).
        동작의 증거는 실기 실행(sessions/k18)이며 단위 시험은 이 회귀 표시만 막는다."""
        src = os.path.join(os.path.dirname(system_sound.__file__), "native", "sck_audio.swift")
        with open(src, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("var keepAlive: SCStream?", text)
        self.assertIn("keepAlive = stream", text)

    def test_build_helper_calls_swiftc(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            out = system_sound.build_helper(os.path.join(d, "x", "h"), run=lambda cmd, check: calls.append(cmd))
        self.assertEqual(calls[0][0], "swiftc")
        self.assertTrue(calls[0][-1].endswith("h"))


if __name__ == "__main__":
    unittest.main()
