"""D-085: 묶은 앱에서 multiprocessing 자식이 앱 전체를 다시 실행하지 않게 하는 보호의 시험."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[2] / "src" / "mac")


class MpGuardTest(unittest.TestCase):
    def _run(self, code):
        env = dict(os.environ, PYTHONPATH=SRC)
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env)

    def test_resource_tracker_argv_runs_tracker_not_app(self):
        # 자식 형태의 인자(`-c from multiprocessing.resource_tracker import main;main(<fd>)`)는 tracker 만 실행하고 끝난다.
        r = self._run(
            "import os, sys; rfd, wfd = os.pipe(); os.close(wfd);"
            "sys.argv = ['app', '-B', '-S', '-I', '-c', 'from multiprocessing.resource_tracker import main;main(%d)' % rfd];"
            "import nsu_kangs_rab; nsu_kangs_rab.main(); sys.exit(99)")
        self.assertEqual(r.returncode, 0, r.stderr)        # tracker 가 끝나고 SystemExit(0). 앱이 시작되었다면 99 이거나 Qt 오류


if __name__ == "__main__":
    unittest.main()
