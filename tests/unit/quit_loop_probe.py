"""D-161 시험 보조: 실제 이벤트 루프(`QApplication.exec`)를 돌려 세션 시작 전 종료 경로가 루프를 끝내는지 본다.
사용: quit_loop_probe.py <경로>   경로: cancel | request_quit | close | quit_event | first_run_quit
종료 코드: 0 = 루프가 스스로 끝남, 9 = 제한 시간(3초) 안에 끝나지 않아 시험이 강제로 끝냄."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "mac"))
import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nsu_kangs_rab.app import controller as C  # noqa: E402
from nsu_kangs_rab.core import appstate, claude_locator  # noqa: E402

mode = sys.argv[1]
app = QApplication([])
tmp = tempfile.TemporaryDirectory()
cfg = Path(tmp.name) / "cfg"
cfg.mkdir()
if mode != "first_run_quit":
    (cfg / "settings.json").write_text(json.dumps({"first_run_ack": appstate.FIRST_RUN_NOTICE_VERSION}))
deps = C.Deps(environ={"PATH": ""}, find_claude=lambda *a, **k: claude_locator.Found("/bin/echo", False, "settings"),
              open_url=lambda u: True)
ctl = C.AppController(app, ["--dev-config-dir", str(cfg)], deps)
ctl.show()
sh = ctl.shell
actions = {
    "cancel": lambda: sh.start_page.cancel_requested.emit(),
    "request_quit": sh.request_quit,
    "close": sh.close,
    "quit_event": lambda: app.sendEvent(app, QEvent(QEvent.Type.Quit)),
    "first_run_quit": lambda: sh.first_run_page.quit_requested.emit(),
}
QTimer.singleShot(200, actions[mode])
QTimer.singleShot(3000, lambda: app.exit(9))
sys.exit(app.exec())
