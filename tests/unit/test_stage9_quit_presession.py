"""D-161: 세션 시작 전 [취소] · ⌘Q · 창 닫기 · 종료 Apple 사건 · 첫 실행 고지 [종료] 에서 프로세스가 실제로 끝난다.
`app.quit()` 이 만드는 `QEvent.Quit` 를 `_QuitFilter` 가 거부하면 이벤트 루프가 끝나지 않으므로, 실제 이벤트 루프를 하위 프로세스로 돌린다."""
import subprocess
import sys
import unittest
from pathlib import Path

PROBE = Path(__file__).resolve().parent / "quit_loop_probe.py"


class QuitPreSessionTest(unittest.TestCase):
    def run_probe(self, mode):
        r = subprocess.run([sys.executable, str(PROBE), mode], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, f"{mode}: 루프가 끝나지 않았다 (코드 {r.returncode})\n{r.stderr[-800:]}")

    def test_cancel(self):
        self.run_probe("cancel")

    def test_request_quit(self):
        self.run_probe("request_quit")

    def test_close_window(self):
        self.run_probe("close")

    def test_quit_event(self):
        self.run_probe("quit_event")

    def test_first_run_quit(self):
        self.run_probe("first_run_quit")


if __name__ == "__main__":
    unittest.main()
