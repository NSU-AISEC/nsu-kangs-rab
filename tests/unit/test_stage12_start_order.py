"""단계 12 (결정 0181): 시작 화면의 절 순서 · 번호 · 5번 절의 표시 조건 · 띠의 조치(스크롤과 초점) · 설정의 정리 문서 템플릿 카드.
AC-FR1-29 ~ 32 · AC-FR13-20 · R12-1 · R12-8."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_app_controller as TC  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QFrame, QLabel  # noqa: E402
from nsu_kangs_rab.app import screens  # noqa: E402

UR = screens.Qt.ItemDataRole.UserRole
_t = screens._t


def top(widget, form):
    return widget.mapTo(form, QPoint(0, 0)).y()


def title_labels(sp):
    """번호가 붙은 절 제목 라벨(`N. ...`)을 글에서 찾는다."""
    out = {}
    for lb in sp.findChildren(QLabel):
        t = lb.text()
        if t[:1].isdigit() and t[1:3] == ". " or t[:2].isdigit() and t[2:4] == ". ":
            out[t] = lb
    return out


class OrderTest(TC.Base):
    def _show(self, provider="claude_subscription", w=900, h=1400):
        sp = self.ctl.shell.start_page
        sp.provider.setCurrentIndex(sp.provider.findData(provider, UR))
        self.ctl.shell.show()
        sp.resize(w, h)
        sp.show()
        TC._app.processEvents()
        return sp

    def _expected(self, with_claude=True):
        names = [_t("newlang.new79"), _t("start.init___047"), _t("start.init___048"), _t("newlang.new81")]
        if with_claude:
            names.append(_t("setform.browse_claude_073"))
        names += [_t("start.init___049"), _t("newlang.new80"), _t("start.init___050"), _t("start.init___051")]
        return names

    def test_numbers_and_order_claude_provider(self):               # S12-1
        for provider in ("claude_subscription", "claude_api"):
            with self.subTest(provider=provider):
                sp = self._show(provider)
                labels = title_labels(sp)
                for t in self._expected():
                    self.assertIn(t, labels, t)
                self.assertTrue(labels[_t("setform.browse_claude_073")].isVisible())
                ys = [top(labels[t], sp) for t in self._expected()]
                self.assertEqual(ys, sorted(ys))
                # 6 · 7 은 위아래로 쌓인다(결정 0189, AC-FR1-33 ①): 7 이 6 보다 아래이다
                self.assertLess(top(labels[_t("start.init___049")], sp), top(labels[_t("newlang.new80")], sp))
        self.assertTrue(_t("newlang.new81").startswith("4. effort"))

    def test_card_texts_are_gone(self):
        sp = self._show()
        texts = {lb.text() for lb in sp.findChildren(QLabel)}
        from nsu_kangs_rab.core.strings import ko
        for key in ("newlang.new72", "newlang.new73", "newlang.new73K"):
            self.assertNotIn(key, ko.__dict__.get("STRINGS", ko.__dict__.get("STRINGS_KO", {})))
            self.assertFalse(any(key in str(k) for k in vars(ko) if k.isupper() and isinstance(vars(ko)[k], dict) and key in vars(ko)[k]))
        self.assertFalse([t for t in texts if t.startswith("앱 환경")])
        self.assertFalse(sp.findChildren(QFrame, "app_env_card"))

    def test_section5_hidden_for_other_provider_numbers_stay(self):   # R12-1
        sp = self._show()
        self.keys.set("sk-keep")
        # 가짜 활성 제공자: 제공자 목록에 claude 계열이 아닌 항목을 임시로 둔다
        sp.provider.addItem("fake", "fake_provider")
        sp.provider.setCurrentIndex(sp.provider.findData("fake_provider", UR))
        TC._app.processEvents()
        self.assertTrue(sp.claude_section.isHidden())
        labels = title_labels(sp)
        for t in self._expected(with_claude=False):
            self.assertIn(t, labels, t)                                   # 다른 절의 번호는 그대로이다
        self.assertEqual(self.keys.get(), "sk-keep")                      # 키는 지우지 않는다
        sp.provider.setCurrentIndex(sp.provider.findData("claude_api", UR))
        TC._app.processEvents()
        self.assertFalse(sp.claude_section.isHidden())

    def test_api_row_only_for_api(self):
        sp = self._show("claude_subscription")
        self.assertTrue(sp.claude_section.key_group.isHidden())
        sp = self._show("claude_api")
        self.assertFalse(sp.claude_section.key_group.isHidden())
        self.assertFalse(any(lb.text().startswith("Claude API") and lb.text()[:1].isdigit() for lb in sp.findChildren(QLabel)))


class BannerRevealTest(TC.Base):
    """AC-FR1-32: 5번 절 안에 조치가 있는 띠가 새로 나타날 때만 스크롤하고 초점을 옮긴다."""
    def _open(self):
        sp = self.ctl.shell.start_page
        self.ctl.shell.show()
        sp.resize(900, 520)                                              # 5번 절이 처음에는 보이지 않을 만큼 낮은 창
        sp.show()
        TC._app.processEvents()
        return sp

    def _visible_fully(self, sp):
        sec = sp.claude_section
        vp = sp.scroll.viewport()
        y = sec.mapTo(vp, QPoint(0, 0)).y()
        return y >= 0 and y + sec.height() <= vp.height() + 1

    def test_key_missing_scrolls_and_focuses_key_field(self):
        sp = self._open()
        sp.provider.setCurrentIndex(sp.provider.findData("claude_api", UR))
        self.ctl.refresh_start_check()
        TC._app.processEvents()
        TC._app.processEvents()
        self.assertTrue(self._visible_fully(sp))
        self.assertTrue(sp.claude_section.api_key.hasFocus())
        self.assertEqual(sp.claude_section.api_key.property("keywarn"), True)    # 초점이 있어도 경고 테두리를 유지한다

    def test_once_per_banner_and_again_after_it_reappears(self):
        sp = self._open()
        sp.provider.setCurrentIndex(sp.provider.findData("claude_api", UR))
        self.ctl.refresh_start_check()
        TC._app.processEvents()
        TC._app.processEvents()
        sp.scroll.verticalScrollBar().setValue(0)                         # 사용자가 위로 올린다
        self.ctl.refresh_start_check()                                    # 같은 띠가 그대로 있다
        TC._app.processEvents()
        TC._app.processEvents()
        self.assertEqual(sp.scroll.verticalScrollBar().value(), 0)
        sp.provider.setCurrentIndex(sp.provider.findData("claude_subscription", UR))
        self.ctl.refresh_start_check()                                    # 띠가 사라진다
        sp.provider.setCurrentIndex(sp.provider.findData("claude_api", UR))
        self.ctl.refresh_start_check()                                    # 다시 나타난다
        TC._app.processEvents()
        TC._app.processEvents()
        self.assertTrue(self._visible_fully(sp))

    def test_browse_to_unusable_file_scrolls_to_section_end_d212(self):
        """[찾아보기…] 로 실행할 수 없는 파일을 고르면(설명 줄이 같은 호출 안에서 바뀐다) 5번 절 아래 끝까지 스크롤한다(D-212)."""
        import tempfile
        from PySide6.QtWidgets import QFileDialog
        sp = self._open()
        bad = Path(tempfile.mkdtemp()) / ("긴 폴더 이름 " * 12 + "not-exec")
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("x", encoding="utf-8")
        self.addCleanup(lambda: (bad.unlink(), bad.parent.rmdir()))
        orig = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(bad), ""))
        self.addCleanup(lambda: setattr(QFileDialog, "getOpenFileName", orig))
        from nsu_kangs_rab.core import claude_locator
        real = self.ctl.deps.find_claude
        self.ctl.deps.find_claude = lambda configured, *a, **k: (
            None if configured else claude_locator.Found("/bin/echo", False, "path"))     # 지정한 경로는 실행할 수 없다
        self.addCleanup(lambda: setattr(self.ctl.deps, "find_claude", real))
        sp.scroll.verticalScrollBar().setValue(0)
        sp.title.setFocus()
        TC._app.processEvents()
        sp.claude_section.claude_browse.click()
        TC._app.processEvents()
        TC._app.processEvents()
        self.assertFalse(sp.banner.isHidden())
        self.assertTrue(self._visible_fully(sp))

    def test_other_banners_do_not_move(self):
        sp = self._open()
        sp.show_problem("저장 폴더를 만들 수 없습니다", "조치", blocking=False)
        TC._app.processEvents()
        TC._app.processEvents()
        self.assertEqual(sp.scroll.verticalScrollBar().value(), 0)
        self.assertFalse(sp.claude_section.claude_edit.hasFocus())
        self.assertFalse(sp.claude_section.api_key.hasFocus())


class TemplateCardTest(TC.Base):
    """AC-FR13-20: 정리 문서 템플릿 절은 카드 하나와 구역 사이의 선 하나이다."""
    def _form(self):
        self.ctl.open_settings()
        f = self.ctl._settings_form
        f.resize(700, 900)
        f.show()
        TC._app.processEvents()
        return f

    def test_single_card_and_dividers(self):
        f = self._form()
        cards = f.findChildren(QFrame, "template_card")
        self.assertEqual(len(cards), 1)
        for ed in f.template_edits.values():
            self.assertEqual(ed.frameShape(), QFrame.Shape.NoFrame)
            self.assertIs(ed.parentWidget().parentWidget(), cards[0])
        self.assertEqual(len(f.template_dividers), 2)
        self.assertEqual(len(f.findChildren(QFrame, "template_divider")), 2)
        self.assertTrue(f.templates_reset.isVisible())

    def test_focus_property_follows_editor(self):
        f = self._form()
        ed = f.template_edits["수업"]
        ed.focus_changed.emit(True)
        self.assertEqual(f.template_caps["수업"].property("focused"), True)
        self.assertEqual(f.template_dividers["수업"].property("focused"), True)
        self.assertNotEqual(f.template_caps["회의"].property("focused"), True)
        ed.focus_changed.emit(False)
        self.assertNotEqual(f.template_caps["수업"].property("focused"), True)


class LocalesThreadTest(TC.Base):
    """D-213: 제어기가 지워진 뒤 `stt-locales` 데몬 스레드의 emit 이 예외를 스레드 밖으로 내보내지 않는다."""
    def test_emit_after_destroy_does_not_raise_out_of_thread(self):
        import threading

        class DeadSignal:
            def emit(self, *_a):
                raise RuntimeError("Signal source has been deleted")

        class DeadBridge:
            done = DeadSignal()

        caught = []
        old_hook = threading.excepthook
        threading.excepthook = lambda args: caught.append(args)
        self.addCleanup(lambda: setattr(threading, "excepthook", old_hook))
        self.ctl.deps.list_locales = lambda cmd, timeout: ["ko-KR"]
        self.ctl._locales_bridge = DeadBridge()
        self.ctl._stt_locales_loading = False
        self.ctl._load_locales()
        for t in threading.enumerate():
            if t.name == "stt-locales":
                t.join(5)
        self.assertEqual(caught, [])

    def test_gc_is_off_in_worker_and_restored_after_load_d222(self):
        """작업 스레드가 도는 동안 가비지 수집을 끄고(다른 스레드에서 Qt 객체가 지워지는 것을 막는다) 불러오기가 끝나면 신호 처리와 상관없이 되돌린다(D-222 · D-223)."""
        import gc
        import threading
        seen = []
        self.ctl.deps.list_locales = lambda cmd, timeout: (seen.append(gc.isenabled()), ["ko-KR"])[1]
        self.ctl._stt_locales_loading = False
        gc.enable()
        self.addCleanup(gc.enable)
        self.ctl._load_locales()
        for t in threading.enumerate():
            if t.name == "stt-locales":
                t.join(5)
        self.assertEqual(seen, [False])
        self.assertTrue(gc.isenabled())                 # 이벤트를 처리하지 않아도 켜져 있다(D-223)
        for _ in range(5):
            TC._app.processEvents()
        self.assertEqual(self.ctl._stt_locales, {"ko-KR"})

    def test_gc_restored_when_signal_is_never_handled_d223(self):
        """완료 신호가 전달되지 않아도(제어기가 지워졌거나 신호 대기열이 처리되지 않아도) 수집 상태가 돌아온다."""
        import gc
        import threading

        class DeadBridge:
            class done:
                @staticmethod
                def emit(_):
                    raise RuntimeError("deleted")
        self.ctl.deps.list_locales = lambda cmd, timeout: ["ko-KR"]
        self.ctl._locales_bridge = DeadBridge()
        self.ctl._stt_locales_loading = False
        gc.enable()
        self.addCleanup(gc.enable)
        self.ctl._load_locales()
        for t in threading.enumerate():
            if t.name == "stt-locales":
                t.join(5)
        self.assertTrue(gc.isenabled())

    def test_gc_restored_when_lookup_raises_and_stays_off_if_it_was_off_d223(self):
        import gc
        import threading

        def boom(cmd, timeout):
            raise OSError("x")
        self.ctl.deps.list_locales = boom
        self.addCleanup(gc.enable)
        for before in (True, False):
            gc.enable() if before else gc.disable()
            self.ctl._stt_locales_loading = False
            self.ctl._load_locales()
            for t in threading.enumerate():
                if t.name == "stt-locales":
                    t.join(5)
            self.assertEqual(gc.isenabled(), before)


def tearDownModule():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
