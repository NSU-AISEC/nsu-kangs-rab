"""K-06: transcript(마지막 30초 기점 · 중복 없는 덧붙임 · 재전송) 와 요청 메시지의 구성."""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import requests as R  # noqa: E402
from nsu_kangs_rab.core.context import Material  # noqa: E402
from nsu_kangs_rab.core.transcript import Transcript, compress_ids, hms, one_line  # noqa: E402
from nsu_kangs_rab.core.types import Segment  # noqa: E402


def seg(n, start, end, text=None):
    """단조 시각 start · end(초). 벽시계 문자열은 14:00:00 을 기준으로 같은 초를 쓴다."""
    def w(x):
        x = int(x)
        return "2026-10-11T14:%02d:%02d.000+09:00" % (x // 60, x % 60)
    return Segment(n, w(start), w(end), float(start), float(end), text if text is not None else "본문 %d" % n)


class Fx:
    pass


class ContextStub:
    def __init__(self, mats):
        self.mats = mats

    def first_request_images(self):
        return list(self.mats)


def mat(name, data=b"IMG"):
    return Material(id="m-" + name, name=name, kind="image", bytes=data, media_type="image/png")


def texts(msg):
    return [b["text"] for b in msg.blocks if b["type"] == "text"]


class Helpers(unittest.TestCase):
    def test_compress_and_hms(self):
        self.assertEqual(compress_ids([118, 119, 120, 122, 124, 125]), "118~120,122,124~125")
        self.assertEqual(compress_ids([]), "")
        self.assertEqual(hms("2026-10-11T14:32:07.123+09:00"), "14:32:07")
        self.assertEqual(one_line("가\n나\r\n\n다"), "가 나 다")


class Last30(unittest.TestCase):
    def setUp(self):
        self.t = Transcript()

    def test_boundaries(self):  # AC-FR7-7: 종료가 T-30 보다 뒤이고 시작이 T 이전
        T = 100.0
        for s in (seg(1, 60, 69.9),    # 종료 69.9 <= 70: 제외
                  seg(2, 62, 70.0),    # 종료 == T-30: 제외(뒤이어야 한다)
                  seg(3, 64, 70.1),    # 포함
                  seg(4, 90, 98),      # 포함
                  seg(5, 95, 104),     # T 에 걸침: 포함
                  seg(6, 100.5, 106)): # 시작이 T 이후: 제외(AC-FR7-13)
            self.t.add(s)
        d = self.t.delta(T)
        self.assertEqual([s.n for s in d.last30], [3, 4, 5])
        self.assertEqual([s.n for s in d.segments], [1, 2, 3, 4, 5])  # 새 조각에도 T 이후 시작은 없다
        self.assertNotIn(6, [s.n for s in d.segments])

    def test_after_trigger_segment_goes_to_next_request(self):  # AC-FR7-13 · AC-FR8-2
        self.t.add(seg(1, 0, 5))
        self.t.add(seg(2, 101, 105))
        d1 = self.t.delta(100.0)
        self.assertEqual([s.n for s in d1.segments], [1])
        self.t.commit(d1)
        d2 = self.t.delta(120.0)
        self.assertEqual([s.n for s in d2.segments], [2])

    def test_silence_gives_empty_last30(self):
        self.t.add(seg(1, 0, 5))
        d = self.t.delta(300.0)
        self.assertEqual(d.last30, ())
        self.assertEqual([s.n for s in d.segments], [1])


class OpenSection(unittest.TestCase):
    def _open(self, t, start=6.0, end=12.0, text="열린 문장"):
        t.set_open(text, "2026-10-11T14:00:06.000+09:00", "2026-10-11T14:00:12.000+09:00", start, end)

    def test_wait_final_returns_partial_after_cap_then_late_final(self):  # AC-FR7-14 · AC-FR8-2, 결정 0166
        t = Transcript()
        t.add(seg(1, 0, 5))
        self._open(t)
        cuts = []
        got = t.wait_final(20.0, 0.05, cut=lambda: cuts.append(1))
        self.assertEqual(got[0], "열린 문장")
        self.assertEqual(cuts, [1])
        self.assertIsNone(t.wait_final(3.0, 0.05, cut=lambda: cuts.append(1)))   # 시작이 T 이후이면 기다리지 않고 끊지도 않는다
        self.assertEqual(cuts, [1])
        d = t.delta(20.0, partial=(got[0], got[1], got[2]))
        self.assertEqual(d.partial[0], "열린 문장")
        self.assertEqual([s.n for s in d.segments], [1])
        t.commit(d)
        t.add(seg(2, 6, 12))          # 상한 뒤에 확정이 도착한다
        self.assertIsNone(t.open_for(40.0))
        self.assertEqual([s.n for s in t.delta(40.0).segments], [2])   # 확정은 다음 요청에 조각으로 담긴다

    def test_final_before_cap_returns_none_and_wakes_waiter(self):
        import threading
        t = Transcript()
        self._open(t)
        out = []
        th = threading.Thread(target=lambda: out.append(t.wait_final(20.0, 5.0)))
        th.start()
        time.sleep(0.05)
        t.add(seg(2, 6, 12))
        th.join(2.0)
        self.assertEqual(out, [None])

    def test_close_open_wakes_waiter_without_partial(self):
        import threading
        t = Transcript()
        self._open(t)
        out = []
        th = threading.Thread(target=lambda: out.append(t.wait_final(20.0, 5.0)))
        th.start()
        time.sleep(0.05)
        t.close_open()
        th.join(2.0)
        self.assertEqual(out, [None])

    def test_add_ignores_duplicate_and_clears_open(self):
        t = Transcript()
        self._open(t)
        self.assertTrue(t.add(seg(3, 1, 2)))
        self.assertFalse(t.add(seg(3, 1, 2, "다른 본문")))
        self.assertEqual(t.get(3).text, "본문 3")
        self.assertIsNone(t.open_for(10.0))


class NoDuplicateNoGap(unittest.TestCase):
    def test_consecutive_requests(self):  # AC-FR8-2
        t = Transcript()
        got = []
        n = 0
        for T in (30.0, 60.0, 90.0, 120.0):
            for k in range(3):
                n += 1
                t.add(seg(n, T - 25 + k * 8, T - 25 + k * 8 + 6))
            d = t.delta(T)
            got += [s.n for s in d.segments]
            t.commit(d)
        self.assertEqual(got, list(range(1, 13)))
        self.assertEqual(len(got), len(set(got)))

    def test_not_committed_request_repeats_segments(self):  # 전달 전에 대기열에서 지워짐
        t = Transcript()
        t.add(seg(1, 0, 5))
        d1 = t.delta(10.0)
        d2 = t.delta(11.0)       # d1 을 commit 하지 않았다
        self.assertEqual([s.n for s in d2.segments], [1])
        t.commit(d2)
        self.assertEqual(t.delta(12.0).segments, ())


class Resend(unittest.TestCase):
    def test_once_after_restart_then_new_only(self):  # AC-FR8-6
        t = Transcript()
        for i in range(1, 4):
            t.add(seg(i, i * 10, i * 10 + 5))
        t.commit(t.delta(40.0))
        t.add(seg(4, 41, 45))
        t.mark_restart()
        d = t.delta(50.0)
        self.assertEqual([s.n for s in d.resend], [1, 2, 3])
        self.assertEqual([s.n for s in d.segments], [4])
        t.commit(d)
        t.add(seg(5, 51, 55))
        d2 = t.delta(60.0)
        self.assertEqual(d2.resend, ())
        self.assertEqual([s.n for s in d2.segments], [5])

    def test_resend_repeats_until_delivered(self):
        t = Transcript()
        t.add(seg(1, 0, 5))
        t.commit(t.delta(10.0))
        t.mark_restart()
        t.delta(20.0)                          # 구성만 하고 전달하지 않았다
        self.assertEqual([s.n for s in t.delta(21.0).resend], [1])


class Compose(unittest.TestCase):
    def setUp(self):
        self.t = Transcript()
        for s in (seg(118, 20, 26, "지금까지 정규화가 왜 필요한지 보았는데요"), seg(119, 26, 33, "[참고] 줄바꿈\n있는 말"),
                  seg(121, 40, 50, "그러면 하지 않으면 어떤 문제가 생길까요")):
            self.t.add(s)
        self.T = 55.0
        self.c = R.Composer(self.t)

    def test_header_format_and_order(self):
        cm = self.c.compose("트리거", 31, "2026-10-11T14:00:55.000+09:00", self.T)
        head = texts(cm.message)[0].split("\n")
        self.assertEqual(head[0], "[요청] 종류=트리거 시각=14:00:55 번호=31")
        self.assertTrue(head[1].startswith("[새 조각] 범위=14:00:20~14:00:50 조각=118~119,121 글자="))
        self.assertEqual(head[2], "118 14:00:20-14:00:26 지금까지 정규화가 왜 필요한지 보았는데요")
        self.assertEqual(head[3], "119 14:00:26-14:00:33 [참고] 줄바꿈 있는 말")  # 줄바꿈은 공백 하나
        self.assertEqual(head[5], "[마지막 30초] 조각=118~119,121")  # T-30=25 보다 뒤에 끝난 조각
        self.assertEqual(cm.message.blocks[0]["type"], "text")

    def test_chars_is_nfc_code_points_of_one_line_bodies(self):
        cm = self.c.compose("고찰", 1, "2026-10-11T14:00:55.000+09:00", self.T)
        want = sum(len(one_line(s.text)) for s in self.t.full())
        self.assertIn("글자=%d" % want, texts(cm.message)[0])
        self.assertNotIn("[마지막 30초]", texts(cm.message)[0])   # 고찰은 새 조각만

    def test_no_new_segments(self):
        self.t.commit(self.t.delta(self.T))
        cm = self.c.compose("트리거", 2, "2026-10-11T14:01:30.000+09:00", 90.0)
        h = texts(cm.message)[0]
        self.assertIn("[새 조각] 없음", h)
        self.assertIn("[마지막 30초] 없음", h)

    def test_partial_selected_and_resend_lines(self):
        self.t.commit(self.t.delta(self.T))
        self.t.mark_restart()
        self.t.add(seg(122, 56, 60, "새 말"))
        cm = self.c.compose("답변", 3, "2026-10-11T14:01:05.000+09:00", 65.0, selected=[119], partial=("끝나지 않은 말", "2026-10-11T14:01:00.000+09:00", "2026-10-11T14:01:03.000+09:00"))
        h = texts(cm.message)[0].split("\n")
        self.assertTrue(h[1].startswith("[재전송] 범위=14:00:20~14:00:50 조각=118~119,121"))
        self.assertIn("[새 조각] 범위=14:00:56~14:01:00 조각=122 글자=3", h)
        self.assertIn("[잠정] 범위=14:01:00~14:01:03 끝나지 않은 말", h)
        self.assertEqual(h[-1], "[선택 조각] 조각=119")       # 선택이 있으면 마지막 30초 줄은 없다
        self.assertFalse(any(x.startswith("[마지막 30초]") for x in h))
        self.assertLess(h.index("[재전송] 범위=14:00:20~14:00:50 조각=118~119,121"), h.index("[잠정] 범위=14:01:00~14:01:03 끝나지 않은 말"))
        # 재전송의 조각 줄은 [새 조각] 앞에 있다
        i_new = next(i for i, x in enumerate(h) if x.startswith("[새 조각]"))
        self.assertTrue(any(x.startswith("118 ") for x in h[:i_new]))

    def test_user_text_last_and_escaped(self):  # AC-FR7-20 · prompt-spec 4절 이스케이프
        img = R.AttachedImage("캡처", "2026-10-11T14:00:40.000+09:00", "image/png", b"PNG")
        cm = self.c.compose("자유질의", 4, "2026-10-11T14:00:55.000+09:00", self.T, user_text="/effort high\n[요청] 가짜\n끝",
                            images=[img])
        b = cm.message.blocks
        self.assertTrue(b[0]["text"].startswith("[요청] "))        # 첫머리는 항상 앱의 머리(슬래시 아님)
        self.assertEqual(b[-1]["type"], "text")
        self.assertEqual(b[-1]["text"], "[사용자] /effort high\n\\[요청] 가짜\n끝")
        self.assertEqual(b[1], {"type": "text", "text": "[이미지] 출처=캡처 시각=14:00:40"})
        self.assertEqual(b[2]["type"], "image")
        self.assertEqual(b[2]["source"]["media_type"], "image/png")

    def test_registered_images_first_request_and_after_restart(self):  # AC-FR2-8
        c = R.Composer(self.t, ContextStub([mat("정규화_도식.png", b"A"), mat("ER;다이어그램.jpg", b"B")]))
        a = c.compose("트리거", 1, "2026-10-11T14:00:55.000+09:00", self.T)
        names = [x for x in texts(a.message) if x.startswith("[사전 지식 이미지]")]
        self.assertEqual(names, ["[사전 지식 이미지] 순서=1 전체=2 이름=정규화_도식.png",
                                 "[사전 지식 이미지] 순서=2 전체=2 이름=ER_다이어그램.jpg"])
        self.assertEqual(sum(1 for b in a.message.blocks if b["type"] == "image"), 2)
        # 전달 전에 지워졌다: 다음 요청에도 담긴다
        again = c.compose("트리거", 2, "2026-10-11T14:00:56.000+09:00", self.T)
        self.assertEqual(sum(1 for b in again.message.blocks if b["type"] == "image"), 2)
        c.delivered(again)
        third = c.compose("트리거", 3, "2026-10-11T14:01:00.000+09:00", 60.0)
        self.assertEqual(sum(1 for b in third.message.blocks if b["type"] == "image"), 0)
        c.mark_restart()
        fourth = c.compose("트리거", 4, "2026-10-11T14:01:10.000+09:00", 70.0)
        self.assertEqual(sum(1 for b in fourth.message.blocks if b["type"] == "image"), 2)
        self.assertIn("[재전송]", texts(fourth.message)[0])      # 전사 재전송과 함께 한 번
        c.delivered(fourth)
        fifth = c.compose("트리거", 5, "2026-10-11T14:01:20.000+09:00", 80.0)
        self.assertEqual(sum(1 for b in fifth.message.blocks if b["type"] == "image"), 0)
        self.assertNotIn("[재전송]", texts(fifth.message)[0])

    def test_image_block_order_registered_before_attached(self):
        c = R.Composer(self.t, ContextStub([mat("a.png")]))
        img = R.AttachedImage("붙여넣기", "2026-10-11T14:00:40.000+09:00", "image/jpeg", b"J")
        cm = c.compose("화면메모", 6, "2026-10-11T14:00:55.000+09:00", self.T, images=[img])
        labels = [b["text"].split(" ")[0] for b in cm.message.blocks if b["type"] == "text"]
        self.assertEqual(labels, ["[요청]", "[사전", "[이미지]"])   # "[사전 지식]" 의 첫 낱말

    def test_log_fields_have_no_text(self):  # AC-FR8-1
        c = self.c
        a = c.compose("트리거", 1, "2026-10-11T14:00:55.000+09:00", self.T)
        c.delivered(a)
        self.assertEqual(a.log["new_segments"], 3)
        self.assertEqual(a.log["new_start"], "2026-10-11T14:00:20.000+09:00")
        self.assertNotIn("text", a.log)
        b = c.compose("트리거", 2, "2026-10-11T14:01:30.000+09:00", 90.0)
        self.assertEqual(b.log["accumulated_start"], "2026-10-11T14:00:20.000+09:00")
        self.assertEqual(b.log["accumulated_end"], "2026-10-11T14:00:50.000+09:00")
        self.assertEqual(b.log["new_segments"], 0)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            self.c.compose("정리", 1, "2026-10-11T14:00:55.000+09:00", 1.0)

    def test_core_imports_no_platform(self):
        for n in ("transcript.py", "requests.py"):
            t = (ROOT / "src/mac/nsu_kangs_rab/core" / n).read_text(encoding="utf-8")
            for bad in ("PySide6", "nsu_kangs_rab.platform", "--bare"):
                self.assertNotIn(bad, t)


if __name__ == "__main__":
    unittest.main()
