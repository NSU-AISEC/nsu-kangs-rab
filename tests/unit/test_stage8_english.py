"""단계 8: 영어 화면 (AC-FR16-15). 문구를 모듈을 가져올 때 정하므로 `app_language=en` 인 별도 프로세스에서 실행한다."""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_CHILD = r'''
import json, re, sys, tempfile
from pathlib import Path
sys.path.insert(0, %(src)r); sys.path.insert(0, %(tests)r)
from nsu_kangs_rab.core import i18n
i18n.init("en")
import test_app_controller as TC
from PySide6.QtWidgets import QLabel, QPushButton, QWidget
H = re.compile(r"[ㄱ-ㆎ가-힣]")
out = {"hangul": [], "clipped": []}
from nsu_kangs_rab.core import labels
out["labels"] = [labels.title_label("(이름 없음)"), labels.kind_label("정리문서"), labels.kind_label("다이어그램")]

class T(TC.Base):
    def runTest(self):
        def scan(root, where):
            for w in root.findChildren(QWidget):
                if not isinstance(w, (QLabel, QPushButton)):
                    continue
                txt = w.text().replace("한국어", "")
                if H.search(txt):
                    out["hangul"].append([where, w.objectName(), w.text()])
                if w.isVisibleTo(root) and txt and not getattr(w, "wordWrap", lambda: False)() and w.width() > 0 \
                        and w.minimumSizeHint().width() > w.width() + 1:
                    out["clipped"].append([where, w.objectName(), w.text(), w.width(), w.minimumSizeHint().width()])
        from PySide6.QtWidgets import QApplication
        self.ctl.shell.resize(984, 564)          # 기본 안쪽 영역 960x540 과 액자
        self.ctl.shell.show()
        QApplication.processEvents()
        scan(self.ctl.shell, "start")
        self.ctl.open_settings()
        scan(self.ctl._settings_form, "settings")
        self.start()
        QApplication.processEvents()
        from nsu_kangs_rab.core import requests as R
        self.ctl.shell.session_page.ai.apply_card(R.Card(1, "트리거", R.STATE_ERROR,
                                                     text="x", t_wall="12:00:00", error=("rate_limit", "")), "add")
        QApplication.processEvents()
        scan(self.ctl.shell, "session")
import unittest
r = unittest.TextTestRunner(stream=open("/dev/null", "w")).run(T())
out["ok"] = r.wasSuccessful()
out["errors"] = [e[1][-400:] for e in r.errors + r.failures]
print("RESULT" + json.dumps(out, ensure_ascii=False))
'''


class EnglishScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        code = _CHILD % {"src": str(ROOT / "src" / "mac"), "tests": str(ROOT / "tests" / "unit")}
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
        m = re.search(r"RESULT(\{.*\})", p.stdout)
        if not m:
            raise AssertionError(p.stderr[-800:])
        cls.res = json.loads(m.group(1))

    def test_child_ran(self):
        self.assertTrue(self.res["ok"], self.res["errors"])

    def test_untitled_and_internal_kinds_in_english(self):
        self.assertEqual(self.res["labels"], ["(Untitled)", "Summary document", "Diagram"])

    def test_no_hangul_on_english_screens(self):
        self.assertEqual(self.res["hangul"], [])

    def test_no_clipped_labels(self):
        self.assertEqual(self.res["clipped"], [])


if __name__ == "__main__":
    unittest.main()
