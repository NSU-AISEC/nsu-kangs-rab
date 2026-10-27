"""K-12 메인 창 내용의 시험 (QT_QPA_PLATFORM=offscreen, 창을 띄우지 않는다)."""
import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from nsu_kangs_rab.app import mainview, shell
from nsu_kangs_rab.core import requests as R
from nsu_kangs_rab.core.types import Segment

_app = QApplication.instance() or QApplication([])


def tearDownModule():
    # 남은 deleteLater 와 순환 참조를 모듈이 끝나기 전에 처리한다(인터프리터 종료 때 순서가 어긋나 경고가 나는 것을 막는다)
    import gc
    for _ in range(3):
        _app.processEvents()
        QCoreApplication.sendPostedEvents(None, 0)
        gc.collect()


def seg(n, text="그래서 이 방법은"):
    return Segment(n, "2026-10-11T13:36:%02d.000+09:00" % (n % 60), "2026-10-11T13:36:%02d.900+09:00" % (n % 60),
                   float(n), n + 0.9, text)


def card(n=1, kind="트리거", state=R.STATE_ACTIVE, text="", **kw):
    return R.Card(n, kind, state, text=text, t_wall="2026-10-11T13:37:05.000+09:00", **kw)


class MainVerdictTest(unittest.TestCase):
    """main-verdict: D-096(전사 행 색) · D-097(오류 알약) · D-098(표시줄 항목 감춤) · D-099(마지막 30초 면)."""

    def test_recent_rows_are_marked_by_age(self):  # D-099
        from datetime import datetime, timedelta, timezone
        v = mainview.TranscriptView()
        v.now_fn = lambda: datetime(2026, 10, 11, 13, 36, 59, tzinfo=timezone(timedelta(hours=9)))
        v.add_segment(seg(10, "오래된 조각"))   # 13:36:10
        v.add_segment(seg(40, "최근 조각"))     # 13:36:40
        flags = [v.is_recent(v.model().index(i, 0)) for i in range(2)]
        self.assertEqual(flags, [False, True])

    def test_delegate_uses_scheme_colors(self):  # D-096
        from nsu_kangs_rab.app import theme
        _app.setProperty("rab_scheme", "dark")
        try:
            got = mainview._SegmentDelegate._colors()
        finally:
            _app.setProperty("rab_scheme", None)
        tk = theme.tokens("dark")
        self.assertEqual(got, (tk["mute"], tk["body"]))   # D-096b: 본문은 body

    def test_error_card_kind_pill_is_error_colored(self):  # D-097
        w = mainview.CardWidget(card(1, "트리거"))
        self.assertEqual(w.kind_label.objectName(), "badge")
        w.update_card(card(1, "트리거", R.STATE_ERROR, error=("limit_exceeded", "")))
        self.assertEqual(w.kind_label.objectName(), "badge_error")

    def test_status_bar_hides_low_priority_items_whole(self):  # D-098
        from nsu_kangs_rab.app import screens
        from nsu_kangs_rab.core import appstate
        bar = screens.StatusBar()
        s = appstate.StatusInputs(provider="claude_subscription", family="sonnet", effort="medium", source="시스템 사운드",
                                  capture_state="수집 중", materials=3, captures=4, stt_errors=2,
                                  queue_waiting=1, activity="요청 진행 중")
        bar.show_inputs(s)
        bar.resize(1280, 32)
        bar._fit()
        self.assertTrue(all(lb.isVisibleTo(bar) for lb in bar._labels))
        self.assertFalse(bar.more.isVisibleTo(bar))
        bar.resize(500, 32)
        bar._fit()
        shown = [n for n, lb in zip(bar._names, bar._labels) if lb.isVisibleTo(bar)]
        self.assertIn("capture_state", shown)
        self.assertIn("activity", shown)
        self.assertIn("stt_errors", shown)
        self.assertNotIn("captures", shown)            # 가장 낮은 우선순위부터 감춘다
        self.assertTrue(bar.more.isVisibleTo(bar))
        self.assertIn("캡처 4", bar.more.toolTip())


class TranscriptTest(unittest.TestCase):
    def test_1000_segments_last_visible(self):  # AC-FR5-1
        v = mainview.TranscriptView()
        v.resize(400, 300)
        v.show()
        t0 = time.monotonic()
        for i in range(1000):
            v.add_segment(seg(i + 1, "조각 %d" % (i + 1)))
        self.assertLess(time.monotonic() - t0, 5.0)
        self.assertEqual(v.count_segments(), 1000)
        self.assertIn("조각 1000", v.last_text())
        _app.processEvents()
        self.assertTrue(v._at_bottom())
        v.hide()

    def test_scrolled_up_position_is_kept(self):  # AC-FR5-2
        v = mainview.TranscriptView()
        v.resize(400, 200)
        v.show()
        for i in range(100):
            v.add_segment(seg(i + 1))
        _app.processEvents()
        bar = v.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        pos = bar.value()
        self.assertFalse(v._at_bottom())
        v.add_segment(seg(101))
        _app.processEvents()
        self.assertEqual(bar.value(), pos)
        bar.setValue(bar.maximum())      # 맨 아래로 돌아오면 다시 따라간다
        v.add_segment(seg(102))
        _app.processEvents()
        self.assertTrue(v._at_bottom())
        v.hide()

    def test_time_only_on_first_line_and_selection(self):
        v = mainview.TranscriptView()
        v.add_segment(seg(1, "가"))
        v.add_segment(seg(2, "나"))
        self.assertTrue(v.item(0).text().startswith("13:36:01"))
        v.item(1).setSelected(True)
        v.item(0).setSelected(True)
        self.assertEqual(v.selected_numbers(), (1, 2))


class AIViewTest(unittest.TestCase):
    def test_card_lifecycle_and_hidden(self):
        v = mainview.AIView()
        v.apply_card(card(1, state=R.STATE_WAITING), "new")
        v.apply_card(card(1, text="응답"), "update")
        self.assertEqual(v.card_numbers(), (1,))
        self.assertEqual(v.card(1).body.text(), "응답")
        v.apply_card(card(1, state=R.STATE_HIDDEN, text="응답"), "update")   # 숨긴 응답은 다시 나타나지 않는다
        self.assertEqual(v.card_numbers(), ())
        v.apply_card(card(1, text="응답 2"), "update")   # 숨긴 뒤에 갱신이 와도 다시 나타나지 않는다(AC-FR9-2 ⑤)
        self.assertEqual(v.card_numbers(), ())
        v.apply_card(card(2), "new")
        v.apply_card(card(2), "removed")
        self.assertEqual(v.card_numbers(), ())

    def test_partial_range_line(self):  # AC-FR7-14, NEW-60
        v = mainview.AIView()
        v.apply_card(card(1, partial=("14:01:00", "14:01:03")), "new")
        c = v.card(1)
        self.assertFalse(c.partial_line.isHidden())
        self.assertEqual(c.partial_line.text(), "확정되기 전의 문장을 이 요청에 포함했습니다: 14:01:00 ~ 14:01:03")
        v.apply_card(card(3), "new")
        self.assertTrue(v.card(3).partial_line.isHidden())
        self.assertEqual(v.card(3).partial_line.text(), "")

    def test_judgment_lines(self):  # AC-FR7-1
        self.assertEqual(mainview.judgment_line(card(judgment="질문", judgment_subject="이건 왜 그럴까요?")),
                         '판단: 질문 "이건 왜 그럴까요?"')
        self.assertEqual(mainview.judgment_line(card(judgment="질문 없음", judgment_subject="학습 방법")),
                         "판단: 질문 없음 · 학습 방법")
        self.assertEqual(mainview.judgment_line(card(judgment="이미 답이 나온 질문", judgment_subject="왜?")),
                         '판단: 이미 답이 나온 질문 "왜?"')
        self.assertEqual(mainview.judgment_line(card(judgment=R.JUDGMENT_UNCONFIRMED)), "판단: 미확인")
        self.assertIsNone(mainview.judgment_line(card(kind="답변")))

    def test_plain_text_no_markdown_rendering(self):  # AC-FR9-14
        v = mainview.AIView()
        txt = "# 제목\n**굵게** `코드` <b>x</b>\n- 항목"
        v.apply_card(card(1, text=txt), "new")
        lbl = v.card(1).body
        self.assertEqual(lbl.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(lbl.text(), txt)

    def test_time_and_delete_button(self):  # AC-FR9-5 · AC-FR9-16
        v = mainview.AIView()
        got = []
        v.card_delete_requested.connect(got.append)
        v.apply_card(card(7, kind="답변", text="A"), "new")
        w = v.card(7)
        self.assertEqual(w.time_label.text(), "13:37:05")
        self.assertEqual(w.delete.accessibleName(), "카드 지우기")
        w.delete.click()
        self.assertEqual(got, [7])

    def test_judgment_is_plain_text(self):  # AC-FR9-14 · D-038
        from PySide6.QtCore import Qt
        v = mainview.AIView()
        v.apply_card(card(3, judgment="답함", judgment_subject="<b>굵게</b>"), "new")
        w = v.card(3)
        self.assertEqual(w.judgment.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<b>굵게</b>", w.judgment.text())

    def test_dropped_attachments_shown_with_reason(self):  # AC-FR7-23
        v = mainview.AIView()
        v.apply_card(card(4, kind="자유질의", dropped=("a.png", "b.png")), "new")
        w = v.card(4)
        self.assertFalse(w.dropped.isHidden())
        self.assertIn("a.png", w.dropped.text())
        self.assertIn("b.png", w.dropped.text())
        self.assertIn("요청 크기", w.dropped.text())
        v.apply_card(card(5, kind="자유질의"), "new")
        self.assertTrue(v.card(5).dropped.isHidden())

    def test_error_card(self):
        v = mainview.AIView()
        v.apply_card(card(2, state=R.STATE_ERROR, error=("rate_limit", "한도 초과")), "new")
        w = v.card(2)
        self.assertFalse(w.error.isHidden())
        self.assertIn("한도 초과", w.error.text())


class InputBarTest(unittest.TestCase):
    def setUp(self):
        self._bars = []

    def tearDown(self):
        # 부모 없는 위젯을 인터프리터 종료 때 파괴하면 간헐적으로 비정상 종료한다 (D-037). 시험 안에서 정리한다.
        from PySide6.QtCore import QCoreApplication, QEvent
        for w in self._bars:
            w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._bars.clear()

    def _bar(self, *a):
        b = mainview.InputBar(*a)
        self._bars.append(b)
        return b

    def test_submit_korean_and_buttons(self):  # AC-FR7-2 · AC-FR7-19
        b = self._bar()
        out = []
        b.submitted.connect(out.append)
        b.edit.setText("이건 왜 그럴까요? ㅎㅏㄴ")
        b.edit.returnPressed.emit()
        self.assertEqual(out, ["이건 왜 그럴까요? ㅎㅏㄴ"])
        self.assertEqual(b.edit.text(), "")
        b.edit.setText("   ")
        b.edit.returnPressed.emit()
        self.assertEqual(len(out), 1)
        self.assertFalse(hasattr(b, "settings"))           # 결정 0089: 메인 창에 설정 단추가 없다
        for name in ("trigger", "capture", "trigger_clicked", "capture_clicked", "set_trigger_key"):
            self.assertFalse(hasattr(b, name), name)       # 결정 0155: 입력창 옆의 단추를 없앴다

    def _paste(self, bar, build):
        """합성 클립보드(QMimeData)를 놓고 입력란에 ⌘V 를 보낸다. 반환: (파일 경로 목록, 이미지 바이트 목록)."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QGuiApplication, QKeyEvent
        files, images = [], []
        bar.files_pasted.connect(files.append)         # D-133: 파일 URL 의 붙여넣기는 files_pasted(출처 붙여넣기)
        dropped = []
        bar.files_dropped.connect(dropped.append)
        self._dropped = dropped
        bar.image_pasted.connect(images.append)
        md = build()
        self._keep_md = md                                   # 클립보드가 가리키는 동안 파이썬 쪽 참조를 유지한다
        self.addCleanup(QGuiApplication.clipboard().clear)   # 시험이 끝나면 비운다(남은 데이터가 뒤의 processEvents 에서 해제되며 충돌했다)
        QGuiApplication.clipboard().setMimeData(md)
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        QGuiApplication.sendEvent(bar.edit, ev)
        return files, images

    def test_paste_file_url_first_ignores_image_and_text(self):  # AC-FR7-26 ⒜ ⒡
        from PySide6.QtCore import QMimeData, QUrl
        from PySide6.QtGui import QColor, QImage
        b = self._bar()
        b.edit.setText("원래 글")

        def build():
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile("/tmp/a.png")])
            img = QImage(8, 8, QImage.Format.Format_RGB32)
            img.fill(QColor("blue"))
            md.setImageData(img)               # 파일 아이콘을 흉내 낸 이미지 데이터
            md.setText("a.png")
            return md
        files, images = self._paste(b, build)
        self.assertEqual(files, [["/tmp/a.png"]])
        self.assertEqual(images, [])
        self.assertEqual(b.edit.text(), "원래 글")

    def test_paste_image_data_with_text_inserts_only_image(self):  # AC-FR7-26 ⒝
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QColor, QImage
        b = self._bar()

        def build():
            md = QMimeData()
            img = QImage(8, 8, QImage.Format.Format_RGB32)
            img.fill(QColor("red"))
            md.setImageData(img)
            md.setText("그림 이름")
            md.setHtml("<b>그림 이름</b>")
            return md
        files, images = self._paste(b, build)
        self.assertEqual(files, [])
        self.assertEqual(len(images), 1)
        self.assertEqual(b.edit.text(), "")

    def test_paste_text_only_goes_to_input(self):  # AC-FR7-26 ⒠
        from PySide6.QtCore import QMimeData
        b = self._bar()

        def build():
            md = QMimeData()
            md.setText("붙인 글")
            return md
        files, images = self._paste(b, build)
        self.assertEqual((files, images), ([], []))
        self.assertEqual(b.edit.text(), "붙인 글")

    def test_chips_removed_one_by_one(self):  # AC-FR7-16
        b = self._bar()
        gone = []
        b.chip_removed.connect(gone.append)
        b.add_chip("a", "화면1.png")
        b.add_chip("b", "화면2.png")
        self.assertEqual(b.chips(), ("a", "b"))
        b._chips["a"].click()
        self.assertEqual(gone, ["a"])
        self.assertEqual(b.chips(), ("b",))

    def test_chip_thumbnail_icon_and_accessible_name(self):  # AC-FR7-16 · D-039
        from PySide6.QtCore import QBuffer, QByteArray
        from PySide6.QtGui import QColor, QImage
        img = QImage(40, 20, QImage.Format.Format_RGB32)
        img.fill(QColor("red"))
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        b = self._bar()
        b.add_chip("a", "화면1.png", bytes(ba))
        b.add_chip("n", "없음.png")
        self.assertFalse(b._chips["a"].icon().isNull())
        self.assertTrue(b._chips["n"].icon().isNull())
        self.assertEqual(b._chips["a"].accessibleName(), "첨부 빼기: 화면1.png")


class BridgeTest(unittest.TestCase):
    def test_cross_thread_post_is_nonblocking_and_delivered(self):
        sv = mainview.SessionView()
        done = threading.Event()

        def worker():
            for i in range(50):
                sv.bridge.post_segment(seg(i + 1))
            sv.bridge.post_card(card(1, text="x"), "new")
            done.set()

        th = threading.Thread(target=worker)
        th.start()
        th.join(5)
        self.assertTrue(done.is_set())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (sv.transcript.count_segments() == 50 and sv.ai.card_numbers()):
            QCoreApplication.processEvents()
        self.assertEqual(sv.transcript.count_segments(), 50)
        self.assertEqual(sv.ai.card_numbers(), (1,))


class ShellIntegrationTest(unittest.TestCase):
    def test_shell_has_session_view(self):
        from nsu_kangs_rab.core import settings
        w = shell.MainShell(settings.load_defaults(), "/tmp/x", None, first_run=False)
        self.assertIsInstance(w.session_page, mainview.SessionView)
        w.session_started()
        self.assertIs(w.stack.currentWidget(), w.session_page)


if __name__ == "__main__":
    unittest.main()


class ImageCaptionTest(unittest.TestCase):  # AC-FR7-27, 시각 설계 7-6
    def test_size_formats(self):
        from nsu_kangs_rab.app import mainview as MV
        from PySide6.QtCore import QBuffer, QByteArray
        from PySide6.QtGui import QImage
        img = QImage(20, 10, QImage.Format.Format_RGB32)
        img.fill(0)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        data = bytes(ba)
        t = MV.image_info_text(data, "캡처")
        self.assertTrue(t.startswith("20×10 px · ") and t.endswith(" KB · 캡처"), t)
        self.assertIn("1 KB", t)                                   # 1 KB 미만은 1 KB
        fake = lambda n: data[:0] + b"\0" * n                      # noqa: E731 (크기 표기만 본다)
        self.assertTrue(MV.image_info_text(fake(1536), "x").endswith("2 KB · x"))     # 정수 반올림(1.5 → 2)
        self.assertTrue(MV.image_info_text(fake(1024 * 1024 + 104858), "x").endswith("1.1 MB · x"))
        for size, want in ((1023, "1 KB"), (1, "1 KB"), (1048064, "1.0 MB"), (1048575, "1.0 MB"),
                           (1310720, "1.3 MB"), (1048576, "1.0 MB"), (1572864, "1.5 MB")):         # D-128
            self.assertTrue(MV.image_info_text(fake(size), "x").endswith("%s · x" % want), size)
        self.assertTrue(MV.image_info_text(fake(1047552), "x").endswith("1023 KB · x"))             # 1,047,552 B = 1023 KB 정확
        self.assertEqual((MV.CARD_THUMB_W, MV.CARD_THUMB_H), (144, 96))


class ReflectHeaderTest(unittest.TestCase):
    """결정 0155 ~ 0157: AI 창 머리 행의 [고찰] · 카메라 단추, 카드 알약."""

    def setUp(self):
        self.v = mainview.SessionView()
        self.v.resize(800, 600)
        self._keep = self.v

    def tearDown(self):
        self.v.deleteLater()

    def test_header_buttons_and_texts(self):                    # 결정 0176 2항: 그림 + 키 표기, 도움말은 기능 이름만
        v = self.v
        v.set_request_keys("F2", "", "")
        self.assertEqual(v.btn_reflect.text(), "F2")
        self.assertFalse(v.btn_reflect.icon().isNull())
        self.assertEqual(v.btn_capture.text(), "")                  # 키가 지정되지 않으면 그림만(28 정사각)
        self.assertEqual(v.btn_capture.width(), 28)
        self.assertFalse(v.btn_capture.icon().isNull())
        v.set_request_keys("", "", "")
        self.assertEqual(v.btn_reflect.text(), "")
        self.assertEqual(v.btn_reflect.width(), 28)
        self.assertEqual(v.btn_reflect.toolTip(), "고찰")
        self.assertEqual(v.btn_capture.toolTip(), "액자 캡처")

    def test_capture_key_shown_when_assigned(self):
        v = self.v
        v.set_request_keys("F2", "", "\u2325\u2318K")
        self.assertEqual(v.btn_capture.text(), "\u2325\u2318K")
        self.assertGreater(v.btn_capture.width(), 28)
        self.assertEqual(v.btn_capture.toolTip(), "액자 캡처")       # 키는 도움말에 더하지 않는다

    def test_tooltips_are_names_only(self):
        v = self.v
        v.set_request_keys("F2", "Page Up", "Page Down")
        self.assertEqual(v.btn_reflect.toolTip(), "고찰")
        self.assertEqual(v.btn_capture.toolTip(), "액자 캡처")
        self.assertEqual(v.btn_reflect.accessibleName(), "고찰")

    def test_keys_hidden_camera_first_then_reflect(self):       # FS 373 · AC-FR7-19: 카메라 키 표기 → 고찰 키 표기 순
        v = self.v
        orig = v.ai_head.width
        try:
            v.ai_head.width = lambda: 100000
            v.set_request_keys("F2", "", "\u2325\u2318K")
            self.assertEqual((v.btn_reflect.text(), v.btn_capture.text()), ("F2", "\u2325\u2318K"))
            v.ai_head.width = lambda: 330
            v.set_request_keys("F2", "", "\u2325\u2318K")
            self.assertEqual((v.btn_reflect.text(), v.btn_capture.text()), ("F2", ""))
            v.ai_head.width = lambda: 100
            v.set_request_keys("F2", "", "\u2325\u2318K")
            self.assertEqual((v.btn_reflect.text(), v.btn_capture.text()), ("", ""))
            self.assertFalse(v.btn_reflect.icon().isNull())
        finally:
            v.ai_head.width = orig

    def test_buttons_emit_and_disable_when_ending(self):
        v = self.v
        ev = []
        v.reflect_clicked.connect(lambda: ev.append("r"))
        v.capture_clicked.connect(lambda: ev.append("c"))
        v.btn_reflect.click()
        v.btn_capture.click()
        self.assertEqual(ev, ["r", "c"])
        v.set_request_buttons_enabled(False)
        self.assertFalse(v.btn_reflect.isEnabled())
        self.assertFalse(v.btn_capture.isEnabled())
        v.set_request_buttons_enabled(True)
        self.assertTrue(v.btn_reflect.isEnabled() and v.btn_capture.isEnabled())

    def test_trigger_card_has_no_pill_in_any_state(self):          # 기준은 요청 종류이다(판단 줄의 유무가 아니다)
        for state in (R.STATE_WAITING, R.STATE_ACTIVE, R.STATE_DONE):
            w = mainview.CardWidget(card(1, "트리거", state))
            self.assertFalse(w.kind_label.isVisibleTo(w), state)
        w = mainview.CardWidget(card(1, "트리거"))
        w.update_card(card(1, "트리거", R.STATE_ERROR, error=("limit_exceeded", "")))
        self.assertTrue(w.kind_label.isVisibleTo(w))                # 오류 카드는 "오류" 알약을 둔다
        w2 = mainview.CardWidget(card(2, "답변"))
        self.assertTrue(w2.kind_label.isVisibleTo(w2))

    def test_diagram_button_has_drawn_icon(self):
        w = mainview.CardWidget(card(1, "답변", R.STATE_DONE))
        self.assertNotEqual(w.diagram_button.text(), "▦")
        self.assertFalse(w.diagram_button.icon().isNull())


class FollowSlackTest(unittest.TestCase):
    """D-167 · D-168: 따라가기 판정 여유 24px, 앱이 만든 카드는 위로 스크롤한 위치를 바꾸지 않는다."""

    def _view(self):
        v = mainview.AIView()
        v.resize(400, 300)
        v.show()
        for i in range(1, 12):
            v.apply_card(card(i, "답변", R.STATE_DONE, text="줄\n" * 12), "new")
        for _ in range(5):
            _app.processEvents()
        self.assertGreater(v.verticalScrollBar().maximum(), 200)
        self.addCleanup(v.deleteLater)
        return v

    def test_slack_is_24px(self):
        v = self._view()
        bar = v.verticalScrollBar()
        self.assertEqual(v.FOLLOW_SLACK, 24)
        bar.setValue(bar.maximum() - 10)
        self.assertTrue(v._at_bottom())
        bar.setValue(bar.maximum() - 60)
        self.assertFalse(v._at_bottom())

    def test_app_made_card_keeps_scroll_position(self):
        v = self._view()
        bar = v.verticalScrollBar()
        bar.setValue(bar.maximum() - 300)
        _app.processEvents()
        before = bar.value()
        v.apply_card(card(-1, "오류", R.STATE_ERROR, error=("audio_start_failed", "")), "new_app")
        _app.processEvents()
        self.assertEqual(bar.value(), before)
        bar.setValue(bar.maximum())
        _app.processEvents()
        v.apply_card(card(-2, "오류", R.STATE_ERROR, error=("audio_start_failed", "")), "new_app")
        _app.processEvents()
        self.assertLessEqual(bar.maximum() - bar.value(), 24)
