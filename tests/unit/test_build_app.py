"""tools/build_app.py 의 묶음 이름 (결정 0095, D-130). PyInstaller 는 실행하지 않는다."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import build_app as B  # noqa: E402


class BundleNameTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(B.APP_BUNDLE_DIR, "Prof. Kang's RAB.app")
        self.assertEqual(B.APP_FILE_NAME, "ProfKangRAB")             # 실행 파일 이름은 그대로(권한 유지)

    def test_rename_bundle_in_path_with_space_and_apostrophe(self):
        with tempfile.TemporaryDirectory(prefix="rab o'k ") as out:
            exe = Path(out) / "ProfKangRAB.app" / "Contents" / "MacOS" / "ProfKangRAB"
            exe.parent.mkdir(parents=True)
            exe.write_text("x")
            new = B.rename_bundle(out)
            self.assertEqual(os.path.basename(new), "Prof. Kang's RAB.app")
            self.assertFalse((Path(out) / "ProfKangRAB.app").exists())
            self.assertTrue((Path(new) / "Contents" / "MacOS" / "ProfKangRAB").is_file())   # 실행 파일 이름 유지
            self.assertEqual(new, B.bundle_path(out))

    def test_rename_replaces_existing_bundle(self):
        with tempfile.TemporaryDirectory() as out:
            old = Path(out) / "Prof. Kang's RAB.app" / "old.txt"
            old.parent.mkdir()
            old.write_text("old")
            (Path(out) / "ProfKangRAB.app").mkdir()
            B.rename_bundle(out)
            self.assertFalse(old.exists())

    def test_remove_onedir_keeps_bundle_untouched(self):       # 단계 4 C
        with tempfile.TemporaryDirectory() as out:
            exe = Path(out) / "ProfKangRAB.app" / "Contents" / "MacOS" / "ProfKangRAB"
            exe.parent.mkdir(parents=True)
            exe.write_text("bundle")
            (Path(out) / "ProfKangRAB" / "_internal").mkdir(parents=True)
            (Path(out) / "ProfKangRAB" / "ProfKangRAB").write_text("onedir")
            self.assertTrue(B.remove_onedir(out))
            self.assertEqual(sorted(os.listdir(out)), ["ProfKangRAB.app"])
            self.assertEqual(exe.read_text(), "bundle")
            self.assertFalse(B.remove_onedir(out))                 # 두 번째는 할 일이 없다

    def test_remove_onedir_does_nothing_without_bundle(self):
        with tempfile.TemporaryDirectory() as out:
            (Path(out) / "ProfKangRAB").mkdir()
            self.assertFalse(B.remove_onedir(out))                 # 묶음이 없으면 지우지 않는다
            self.assertTrue((Path(out) / "ProfKangRAB").is_dir())

    def test_localized_names_written(self):
        with tempfile.TemporaryDirectory() as app:
            B.write_localized_names(app)
            t = (Path(app) / "Contents" / "Resources" / "ko.lproj" / "InfoPlist.strings").read_text(encoding="utf-8")
            self.assertIn('"CFBundleDisplayName" = "Prof. Kang\'s RAB";', t)


if __name__ == "__main__":
    unittest.main()
