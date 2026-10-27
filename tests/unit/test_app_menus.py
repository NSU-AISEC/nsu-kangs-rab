"""K-13 메뉴 막대 · 상태 아이콘 · 창 닫기 (AC-FR14-1~10 중 offscreen 으로 확인할 수 있는 부분)."""
import os
import unittest
from PySide6.QtCore import QSize

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app import menus, shell
from nsu_kangs_rab.core import appstate

S = appstate.State
_app = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])
    _app.setQuitOnLastWindowClosed(False)


def tearDownModule():
    # 부모 없는 QMenuBar · QSystemTrayIcon 을 이 모듈 안에서 정리한다. 뒤 모듈의 gc 때 지연 파괴되어 SIGSEGV 가 나던 것을 막는다(전체 실행 크래시, master 의 suite-crash)
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent
    for _ in range(3):
        gc.collect()
        _app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class StructureTest(unittest.TestCase):
    def test_four_menus_and_items(self):
        st = menus.menu_structure()
        self.assertEqual([t for t, _ in st], [menus.APP_MENU, "세션", "창", "도움말"])
        flat = [l for _t, ls in st for l in ls]
        self.assertNotIn("새 세션", flat)
        self.assertNotIn("보기", [t for t, _ in st])
        d = dict(st)
        self.assertEqual(d["세션"], ["폴더 열기", "정리 문서 다시 만들기…", "일시 정지", "재생"])
        self.assertNotIn("요청", d)                        # 결정 0155: 요청 메뉴를 없앴다(AC-FR14-1)
        self.assertEqual(d["도움말"], ["첫 실행 안내 다시 보기", "필요한 권한 확인…"])

    def test_mac_app_menu_translator_gives_table_names(self):  # D-079
        from PySide6.QtCore import QCoreApplication
        tr = menus.install_mac_menu_translator(_app)
        try:
            got = {s: QCoreApplication.translate("MAC_APPLICATION_MENU", s) for s in menus.MAC_APP_MENU_TEXT}
            self.assertEqual(got["About %1"], "앱 정보")
            self.assertEqual(got["Preferences..."], "설정…")
            self.assertEqual(got["Hide Others"], "다른 앱 숨기기")
            self.assertEqual(got["Show All"], "모두 보기")
            self.assertEqual(got["Quit %1"], "종료")
            self.assertEqual(QCoreApplication.translate("MAC_APPLICATION_MENU", "Other"), "Other")   # 없는 문구는 원문
        finally:
            _app.removeTranslator(tr)

    def test_native_items_not_added_on_cocoa(self):  # D-078: macOS 에서는 숨기기 등을 메뉴에 또 더하지 않는다
        from unittest import mock
        from PySide6.QtGui import QGuiApplication
        with mock.patch.object(QGuiApplication, "platformName", return_value="cocoa"):
            c = menus.MenuController()
        app_menu = [a.text() for a in c.menubar.actions()[0].menu().actions()]
        self.assertEqual(app_menu, ["앱 정보", "설정…", "종료"])
        self.assertIn("app.hide", c.actions)                 # 동작 id 는 그대로 있다
        c2 = menus.MenuController()                          # offscreen 은 표의 여섯 항목을 모두 둔다
        self.assertEqual(len(c2.menubar.actions()[0].menu().actions()), 6)

    def test_ids_cover_state_table(self):
        ids = {c for _t, items in menus.MENU_SPEC for c, _l, _s in items}
        ids |= {c for c, _l in menus.REQUEST_ACTIONS}      # 결정 0156: 메뉴에 없는 동작은 키로만 받는다
        for cid in appstate.item_ids():
            if cid != "edit":
                self.assertIn(cid, ids)

    def test_shortcuts(self):
        c = menus.MenuController(trigger_key="F2", capture_key="F3")
        self.assertEqual(c.actions["app.quit"].shortcut().toString(), "Ctrl+Q")
        self.assertEqual(c.actions["request.trigger"].shortcut().toString(), "F2")
        self.assertEqual(c.actions["request.capture"].shortcut().toString(), "F3")
        c.set_trigger_key("F5")
        self.assertEqual(c.actions["request.trigger"].shortcut().toString(), "F5")
        c.set_capture_key("")
        self.assertEqual(c.actions["request.capture"].shortcut().toString(), "")


class TextMenuLanguageTest(unittest.TestCase):
    """D-160: 입력 칸의 오른쪽 클릭 메뉴 항목 이름이 앱 언어를 따른다."""

    def labels(self, lang):
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit
        from nsu_kangs_rab.core import i18n
        from unittest import mock
        tr = menus.install_text_menu_translator(_app)
        patch = mock.patch.object(i18n, "_lang", lang)          # 앱 언어는 프로세스당 한 번 정해지므로 값만 바꾼다
        patch.start()
        try:
            out = []
            for w in (QLineEdit("a"), QPlainTextEdit("a")):
                m = w.createStandardContextMenu()
                out.append([a.text().split("\t")[0] for a in m.actions() if a.text()])
            return out
        finally:
            patch.stop()
            _app.removeTranslator(tr)

    def test_korean(self):
        for got in self.labels("ko"):
            self.assertEqual(got, ["실행 취소", "다시 실행", "오려내기", "복사", "붙여넣기", "삭제", "모두 선택"])

    def test_english_keeps_qt_names(self):
        for got in self.labels("en"):
            self.assertEqual(got, ["&Undo", "&Redo", "Cu&t", "&Copy", "&Paste", "Delete", "Select All"])


class ActivityTest(unittest.TestCase):
    def test_per_state(self):
        c = menus.MenuController()
        for state in (S.FIRST_RUN, S.BEFORE_SESSION, S.IN_SESSION, S.ENDING):
            c.refresh(state, has_input=True)
            for cid in appstate.item_ids():
                if cid not in c.actions or cid in ("session.pause", "session.play"):
                    continue                                    # 편집 항목은 결정 0153 으로 없앴고, 두 항목은 수집 상태가 정한다
                self.assertEqual(c.actions[cid].isEnabled(), appstate.is_active(cid, state), (cid, state))

    def test_no_edit_menu_actions(self):
        c = menus.MenuController()
        self.assertFalse([cid for cid in c.actions if cid.startswith("edit")])
        self.assertNotIn("session.end", c.actions)

    def test_pause_play_follow_capture_state(self):
        c = menus.MenuController()
        for cs, want in (("수집 중", (False, True)), ("일시 정지", (True, False)), ("수집 전", (True, False)),
                         ("중단", (False, False))):
            c.set_status(S.IN_SESSION, 0, cs)
            c.refresh(S.IN_SESSION)
            self.assertEqual((c.actions["session.play"].isEnabled(), c.actions["session.pause"].isEnabled()), want, cs)
        c.refresh(S.BEFORE_SESSION)
        self.assertFalse(c.actions["session.pause"].isEnabled())
        self.assertFalse(c.actions["session.play"].isEnabled())

    def test_tray_parity(self):
        c = menus.MenuController()
        for state in (S.BEFORE_SESSION, S.IN_SESSION, S.ENDING):
            c.refresh(state)
            for cid, a in c._tray_actions.items():
                self.assertEqual(a.isEnabled(), c.actions[cid].isEnabled(), (cid, state))

    def test_command_signal_same_for_menu_and_tray(self):
        c = menus.MenuController()
        c.refresh(S.IN_SESSION)
        got = []
        c.command.connect(got.append)
        c.actions["request.trigger"].trigger()
        c._tray_actions["request.trigger"].trigger()
        self.assertNotIn("app.quit", c._tray_actions)               # 결정 0152: 상태 아이콘 메뉴에 "종료" 가 없다
        self.assertEqual(got, ["request.trigger", "request.trigger"])


class FrameAndTrayTest(unittest.TestCase):
    def test_frame_toggle_text(self):
        c = menus.MenuController()
        self.assertEqual(c.actions["window.frame"].text(), "액자 보이기")
        c.set_frame_visible(True)
        self.assertEqual(c.actions["window.frame"].text(), "액자 숨기기")
        self.assertEqual(c._tray_actions["window.frame"].text(), "액자 숨기기")
        c.set_frame_visible(False)
        self.assertEqual(c._tray_actions["window.frame"].text(), "액자 보이기")

    def test_status_line_and_dot(self):
        self.assertEqual(menus.tray_status_text(S.BEFORE_SESSION), "세션 없음")
        self.assertEqual(menus.tray_status_text(S.IN_SESSION, 4350, menus.COLLECT_ACTIVE), "세션 중 01:12:30 · 수집 중")
        self.assertIsNone(menus.tray_dot(S.BEFORE_SESSION))
        self.assertEqual(menus.tray_dot(S.IN_SESSION, menus.COLLECT_ACTIVE), "info")
        self.assertEqual(menus.tray_dot(S.IN_SESSION, menus.COLLECT_ERROR), "warn")
        c = menus.MenuController()
        c.set_status(S.IN_SESSION, 5, menus.COLLECT_STOPPED)
        self.assertEqual(c.dot, "warn")
        self.assertFalse(c.status_action.isEnabled())
        self.assertIn("수집 중단", c.status_action.text())
        c.set_status(S.BEFORE_SESSION)
        self.assertIsNone(c.dot)

    def test_menubar_icon_is_cartoon_face_by_state_d122(self):  # AC-FR14-5 · 결정 0085 · D-122
        import hashlib
        from PySide6.QtGui import QImage
        want = {  # 결정 0122: 사각형 배경색 판(기준 그림 sessions/icon/menubar4/make_bg18.py 의 출력)의 RGBA 8비트 바이트열 sha256 앞 16자
            ("none", 18): "2140608721fe67f6", ("none", 36): "29d23c2a2721237d",
            ("session", 18): "a22c25c98e04d4b4", ("session", 36): "5d3d00e3dc489efd",
            ("warn", 18): "72b65a39767526bc", ("warn", 36): "3b8b7ea5a3bad4f8"}
        bg = {"none": "#8e8e93", "session": "#2d8cf0", "warn": "#d97706"}
        from nsu_kangs_rab.core import resources
        for (state, px), h in want.items():
            img = QImage(str(resources.menubar_icon_path(state, px))).convertToFormat(QImage.Format_RGBA8888)
            self.assertEqual((img.width(), img.height()), (px, px))
            self.assertEqual(img.pixelColor(0, 0).alpha(), 0)                      # 귀퉁이 바깥은 투명
            if px == 36:
                self.assertEqual(img.pixelColor(px // 2, 1).name(), bg[state])     # 상태는 배경색이다
            self.assertEqual(hashlib.sha256(bytes(img.constBits())[:img.sizeInBytes()]).hexdigest()[:16], h, (state, px))
        ic = menus._icon(None)
        self.assertFalse(ic.isMask())                                    # 템플릿이 아니다
        self.assertEqual(ic.actualSize(QSize(18, 18)), QSize(18, 18))
        imgs = {d: menus._icon(d).pixmap(QSize(18, 18)).toImage() for d in (None, "info", "warn")}
        self.assertNotEqual(imgs[None], imgs["info"])                    # 상태마다 다른 그림
        self.assertNotEqual(imgs["info"], imgs["warn"])
        for d in (None, "info", "warn"):
            self.assertFalse(menus._icon(d).isMask(), d)
        self.assertFalse(hasattr(menus, "DOT_COLORS"))                   # 상태 점이 없다
        c = menus.MenuController()
        c.set_status(S.IN_SESSION, 5, menus.COLLECT_ACTIVE)
        self.assertEqual(c.dot, "info")

    def test_tray_menu_items(self):
        c = menus.MenuController()
        texts = [a.text() for a in c.tray_menu.actions() if not a.isSeparator()]
        self.assertEqual(texts[1:], ["고찰", "액자 캡처", "액자 보이기", "앱 창 열기"])
        self.assertTrue(c.tray.icon() is not None and not c.tray.icon().isNull())


class ShellCloseTest(unittest.TestCase):
    def _shell(self, first_run=False):
        return shell.MainShell({}, "/tmp", None, first_run=first_run)

    def test_close_quits_before_session(self):
        for fr in (True, False):
            s = self._shell(fr)
            got = []
            s.quit_requested.connect(lambda: got.append(1))
            s.close()
            self.assertEqual(got, [1])

    def test_close_in_session_keeps_app_and_reopens(self):
        s = self._shell()
        s.session_started()
        got = []
        s.quit_requested.connect(lambda: got.append(1))
        s.show()
        s.close()
        self.assertEqual(got, [])
        self.assertFalse(s.isVisible())
        self.assertEqual(s.machine.state, S.IN_SESSION)
        s.show_main_window()
        self.assertTrue(s.isVisible())
        s.close()

    def test_quit_and_end_flow(self):
        s = self._shell()
        q, e = [], []
        s.quit_requested.connect(lambda: q.append(1))
        s.end_flow_requested.connect(lambda: e.append(1))
        self.assertFalse(s.request_end_session())
        self.assertEqual(s.request_quit(), "quit_now")
        self.assertEqual((q, e), ([1], []))
        s.session_started()
        self.assertEqual(s.request_quit(), "end_flow")
        self.assertTrue(s.request_end_session())
        self.assertEqual((q, e), ([1], [1, 1]))

class ClickActivateTest(unittest.TestCase):  # D-131
    def test_press_on_main_window_activates_only_when_app_inactive(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QPushButton, QWidget
        win, other = QWidget(), QWidget()
        btn = QPushButton("x", win)
        stray = QPushButton("y", other)                 # 액자 · 손잡이 창처럼 대상이 아닌 창
        state = {"active": False}
        calls = []
        f = menus.ClickActivateFilter(win, is_active=lambda: state["active"], activate=lambda: calls.append(1))

        def press(w):
            ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(2, 2), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier)
            return f.eventFilter(w, ev)
        self.assertFalse(press(btn))                    # 사건을 소비하지 않는다(AC-FR7-24: 첫 클릭에 단추가 실행된다)
        self.assertEqual(calls, [1])
        press(win)
        self.assertEqual(len(calls), 2)
        press(stray)                                    # 다른 창은 다루지 않는다
        self.assertEqual(len(calls), 2)
        state["active"] = True
        press(btn)                                      # 이미 활성이면 하지 않는다
        self.assertEqual(len(calls), 2)
        win.deleteLater()
        other.deleteLater()


if __name__ == "__main__":
    unittest.main()
