"""K-07: 요청 대기열 · 카드 삭제 · 숨긴 응답 상한 · 재시작 · 판단 첫 줄 (AC-FR7-8 · 9 · 11 · 20 · 21, AC-FR8-5 · 7, AC-FR9-2 · 16 · 18 · 19, AC-FR12-4 · 13)."""
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import requests as R  # noqa: E402
from nsu_kangs_rab.core.transcript import Transcript  # noqa: E402
from nsu_kangs_rab.core.types import (Compacted, ControlResponse, Error, ProcessExited, Result,  # noqa: E402
                                      Segment, TextDelta)


def seg(n, start, end, text=None):
    def w(x):
        x = int(x)
        return "2026-10-11T14:%02d:%02d.000+09:00" % (x // 60, x % 60)
    return Segment(n, w(start), w(end), float(start), float(end), text if text is not None else "본문 %d" % n)


class FakeSession:
    def __init__(self):
        self.sent, self.interrupts, self.restarts = [], 0, 0
        self.pid = 1000
        self.send_ok = True
        self.interrupt_id = "int-1"      # None 이면 쓰지 못한 것
        self.restart_ok = True

    def send(self, msg):
        if not self.send_ok:
            return False
        self.sent.append(msg)
        return True

    def interrupt(self):
        self.interrupts += 1
        return self.interrupt_id

    def restart(self):
        self.restarts += 1
        self.pid += 1
        return self.restart_ok


class Log:
    def __init__(self):
        self.ev = []

    def emit(self, type_, **f):
        self.ev.append((type_, f))
        return True

    def of(self, t):
        return [f for (x, f) in self.ev if x == t]


def head(msg):
    return msg.blocks[0]["text"]


def wait_for(pred, timeout=3.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


class Base(unittest.TestCase):
    def setUp(self):
        self.s, self.log, self.tr = FakeSession(), Log(), Transcript()
        self.cards, self.notices = [], []
        self.m = self.mk()

    def mk(self, **kw):
        kw.setdefault("hidden_limit_s", 60.0)
        m = R.RequestManager(self.s, R.Composer(self.tr), eventlog=self.log,
                             on_card=lambda c, ch: self.cards.append((c.n, c.state, ch)),
                             on_notice=lambda k, i: self.notices.append((k, i)), **kw)
        self.addCleanup(m.close)
        return m

    def done(self, text="답", ok=True, **kw):
        self.m.on_model_event(Result(ok, text=text, **kw))


class Queue(Base):
    def test_fifo_one_at_a_time_next_after_result(self):  # AC-FR7-8 · AC-FR12-13 · A-14
        a = self.m.submit(R.Request("자유질의", input="첫째"))
        b = self.m.submit(R.Request("고찰"))
        c = self.m.submit(R.Request("요약"))
        self.assertEqual(len(self.s.sent), 1)                   # 앞의 응답이 끝나기 전에는 보내지 않는다
        self.assertEqual(self.m.queue_numbers(), [b.n, c.n])
        self.assertIn("번호=%d" % a.n, head(self.s.sent[0]))
        self.done()
        self.assertEqual(len(self.s.sent), 2)
        self.assertIn("종류=고찰", head(self.s.sent[1]))
        self.done()
        self.assertIn("종류=요약", head(self.s.sent[2]))
        self.assertEqual(self.m.queue_numbers(), [])

    def test_states_waiting_active_done(self):
        a = self.m.submit(R.Request("자유질의", input="q"))
        b = self.m.submit(R.Request("자유질의", input="q2"))
        st = {c.n: c.state for c in self.m.cards()}
        self.assertEqual(st, {a.n: "진행", b.n: "대기"})
        self.m.on_model_event(TextDelta("부분"))
        self.assertEqual(self.m.cards()[0].text, "부분")
        self.done("전체")
        st = {c.n: (c.state, c.text) for c in self.m.cards()}
        self.assertEqual(st[a.n], ("완료", "전체"))
        self.assertEqual(st[b.n][0], "진행")

    def test_trigger_ignored_while_in_flight(self):  # AC-FR7-9: 응답 진행 중에는 무시하고 알린다
        self.m.submit(R.Request("자유질의", input="q"))
        self.assertEqual(self.m.trigger(), "busy")
        self.assertEqual(len(self.s.sent), 1)
        self.assertEqual(self.notices[-1][0], "trigger_busy")
        self.assertEqual(self.log.of("trigger_held")[-1]["action"], "ignored")
        self.assertEqual(len(self.m.cards()), 1)       # 카드가 생기지 않는다

    def test_slash_like_requests_queue_during_response(self):  # 자유질의는 대기열에 쌓인다
        self.m.submit(R.Request("자유질의", input="a"))
        b = self.m.submit(R.Request("자유질의", input="/b"))
        self.assertEqual(self.m.queue_numbers(), [b.n])

    def test_trigger_starts_when_idle(self):
        self.tr.add(seg(1, 0, 5))
        self.assertEqual(self.m.trigger(), "started")
        self.assertIn("종류=트리거", head(self.s.sent[0]))
        self.assertFalse(self.log.of("request_sent")[0]["partial_included"])

    def test_send_failure_marks_error_and_requires_restart(self):
        self.s.send_ok = False
        c = self.m.submit(R.Request("자유질의", input="q"))
        self.assertEqual(self.m.cards()[0].state, "오류")
        self.assertEqual(self.log.of("request_done")[0]["terminal_reason"], "send_failed")
        self.s.send_ok = True
        self.m.submit(R.Request("자유질의", input="r"))
        # 다음 요청은 자동 재시작(D-065)을 스레드로 예약한다. 그 스레드가 끝나기를 기다려 시험의 restart 호출과 경합하지 않게 한다(D-203).
        end = time.time() + 5
        while time.time() < end and (self.m._auto_pending or self.m._restarting):
            time.sleep(0.01)
        if not self.s.sent:                              # 자동 재시작이 일어나지 않았으면 명시적 재시작이 필요하다
            self.assertTrue(self.m.restart("test"))
        self.assertEqual(len(self.s.sent), 1)             # 재시작 뒤 첫 요청이 한 번 나간다
        self.assertEqual(self.s.restarts, 1)              # 보내기 전에 재시작이 한 번 있었다(D-208)

    def test_error_result_marks_card_error_and_continues(self):
        self.m.submit(R.Request("자유질의", input="q"))
        self.m.submit(R.Request("자유질의", input="r"))
        self.done("", ok=False, error_kind="api", terminal_reason="x")
        st = [c.state for c in self.m.cards()]
        self.assertEqual(st, ["오류", "진행"])


class Delete(Base):
    def test_delete_waiting_not_sent(self):  # AC-FR9-19
        self.m.submit(R.Request("자유질의", input="a"))
        b = self.m.submit(R.Request("고찰"))
        c = self.m.submit(R.Request("요약"))
        self.assertTrue(self.m.delete_card(b.n))
        self.assertEqual(self.m.queue_numbers(), [c.n])
        self.done()
        self.assertEqual(len(self.s.sent), 2)
        self.assertIn("종류=요약", head(self.s.sent[1]))
        ev = self.log.of("card_deleted")[0]
        self.assertEqual((ev["request_n"], ev["phase"], ev["in_progress"], ev["card_kind"]), (b.n, "대기 중", False, "고찰"))

    def test_delete_active_hides_and_reads_to_result(self):  # AC-FR9-2
        a = self.m.submit(R.Request("자유질의", input="a"))
        b = self.m.submit(R.Request("고찰"))
        self.m.on_model_event(TextDelta("앞부분"))
        self.assertTrue(self.m.delete_card(a.n))
        self.assertEqual([c.n for c in self.m.cards()], [b.n])    # 숨긴 카드는 목록에 없다
        self.assertEqual(self.m.in_flight(), a.n)                 # 응답은 끝까지 읽는다
        self.assertEqual(len(self.s.sent), 1)                     # 다음 요청은 Result 뒤에
        before = len(self.cards)
        self.m.on_model_event(TextDelta("뒷부분"))
        self.assertEqual(len(self.cards), before)                 # 숨긴 응답은 표시하지 않는다
        self.done("전체")
        self.assertEqual([c.n for c in self.m.cards()], [b.n])    # 다시 나타나지 않는다
        d = self.log.of("request_done")[0]
        self.assertEqual((d["request_n"], d["hidden"], d["ok"]), (a.n, True, True))   # 완료는 기록한다
        self.assertEqual(len(self.s.sent), 2)
        self.assertEqual(self.log.of("card_deleted")[0]["in_progress"], True)
        self.assertEqual(self.log.of("card_deleted")[0]["phase"], "진행 중")

    def test_delete_done_and_error_removed(self):
        a = self.m.submit(R.Request("자유질의", input="a"))
        self.done()
        self.assertTrue(self.m.delete_card(a.n))
        self.assertEqual(self.m.cards(), [])
        self.assertEqual(self.log.of("card_deleted")[0]["phase"], "완료")
        self.assertFalse(self.m.delete_card(a.n))                 # 이미 없다

    def test_delete_without_confirmation_events_have_no_body(self):  # AC-FR9-16
        a = self.m.submit(R.Request("자유질의", input="비밀 본문"))
        self.m.delete_card(a.n)
        for t, f in self.log.ev:
            self.assertNotIn("비밀 본문", repr(f))
        self.assertIsNotNone(self.log.of("request_sent")[0]["input_sha256"])


class HiddenLimit(Base):
    def hide_active(self, **kw):
        self.m = self.mk(**kw)
        a = self.m.submit(R.Request("자유질의", input="a"))
        self.m.delete_card(a.n)
        return a

    def test_within_limit_no_interrupt(self):  # AC-FR9-18 ⒜
        self.hide_active(hidden_limit_s=0.3, interrupt_ack_s=0.3)
        self.m.on_model_event(TextDelta("x"))
        self.done()
        time.sleep(0.5)
        self.assertEqual(self.s.interrupts, 0)
        self.assertEqual(self.log.of("request_interrupted"), [])

    def test_over_limit_interrupt_then_ack_no_restart(self):  # ⒝
        a = self.hide_active(hidden_limit_s=0.05, interrupt_ack_s=5.0)
        self.assertTrue(wait_for(lambda: self.s.interrupts == 1))
        self.assertEqual(self.log.of("request_interrupted")[0]["request_n"], a.n)
        self.m.on_model_event(ControlResponse("int-1", True))
        self.done("", ok=False, terminal_reason="interrupted")
        self.assertEqual(self.s.restarts, 0)
        self.assertIsNone(self.m.in_flight())

    def test_no_ack_kills_and_restarts_then_resends_history(self):  # ⒞ · AC-FR8-6
        self.tr.add(seg(1, 0, 5))
        a = self.hide_active(hidden_limit_s=0.05, interrupt_ack_s=0.1)
        b = self.m.submit(R.Request("자유질의", input="b"))
        self.assertTrue(wait_for(lambda: self.s.restarts == 1))
        self.assertTrue(wait_for(lambda: len(self.s.sent) == 2))
        r = self.log.of("request_restart")[0]
        self.assertEqual((r["reason"], r["old_pid"], r["new_pid"], r["ok"]), ("interrupt_timeout", 1000, 1001, True))
        self.assertIn("[재전송]", head(self.s.sent[1]))            # 재시작 뒤 첫 요청에 전사 전체를 다시 보낸다
        self.assertEqual(self.m.in_flight(), b.n)

    def test_interrupt_write_failure_restarts_immediately(self):
        self.s.interrupt_id = None
        self.hide_active(hidden_limit_s=0.05, interrupt_ack_s=30.0)
        self.assertTrue(wait_for(lambda: self.s.restarts == 1))
        self.assertEqual(self.log.of("request_restart")[0]["reason"], "interrupt_failed")

    def test_result_before_limit_cancels_timers(self):
        self.hide_active(hidden_limit_s=0.2, interrupt_ack_s=0.2)
        self.done()
        time.sleep(0.5)
        self.assertEqual((self.s.interrupts, self.s.restarts), (0, 0))


class Exit(Base):
    def test_unexpected_exit_errors_card_and_waits_restart(self):
        a = self.m.submit(R.Request("자유질의", input="a"))
        self.m.submit(R.Request("자유질의", input="b"))
        self.m.on_model_event(ProcessExited(1, False))
        self.assertEqual(self.m.cards()[0].state, "오류")
        self.assertEqual(len(self.s.sent), 1)
        self.assertTrue(self.m.restart("process_exit"))
        self.assertEqual(len(self.s.sent), 2)

    def test_next_request_after_exit_restarts_with_resend_header(self):  # D-065 · AC-FR8-6
        self.tr.add(seg(1, 0, 5))
        self.m.submit(R.Request("고찰"))
        self.done()
        self.m.submit(R.Request("고찰"))
        self.m.on_model_event(ProcessExited(1, False))      # 응답 중 종료: 카드 오류
        self.assertEqual(self.s.restarts, 0)
        c = self.m.submit(R.Request("고찰"))                 # 다음 요청이 재시작을 일으킨다
        self.assertTrue(wait_for(lambda: self.s.restarts == 1 and len(self.s.sent) == 3))
        self.assertEqual(self.s.pid, 1001)
        self.assertIn("[재전송]", head(self.s.sent[2]))
        self.assertIn("번호=%d" % c.n, head(self.s.sent[2]))
        self.assertEqual(self.log.of("request_restart")[0]["reason"], "process_exit")
        self.done()
        self.m.submit(R.Request("고찰"))                     # 그다음 요청은 새 조각만
        self.assertNotIn("[재전송]", head(self.s.sent[3]))
        self.assertEqual(self.s.restarts, 1)

    def test_queued_request_at_exit_restarts_without_new_submit(self):  # D-065 재수정(R10): 종료 시점 대기열이 다음 요청이다
        self.m.submit(R.Request("자유질의", input="a"))
        b = self.m.submit(R.Request("자유질의", input="b"))      # 대기열
        self.m.on_model_event(ProcessExited(1, False))
        self.assertTrue(wait_for(lambda: self.s.restarts == 1 and len(self.s.sent) == 2))
        self.assertIn("번호=%d" % b.n, head(self.s.sent[1]))
        self.assertEqual(self.s.pid, 1001)

    def test_second_exit_with_queue_restarts_again(self):  # D-065 R5
        self.m.submit(R.Request("자유질의", input="a"))
        self.m.on_model_event(ProcessExited(1, False))
        self.m.submit(R.Request("자유질의", input="b"))
        self.assertTrue(wait_for(lambda: self.s.restarts == 1 and len(self.s.sent) == 2))
        c = self.m.submit(R.Request("자유질의", input="c"))      # b 진행 중, c 대기
        self.m.on_model_event(ProcessExited(1, False))
        self.assertTrue(wait_for(lambda: self.s.restarts == 2 and len(self.s.sent) == 3))
        self.assertIn("번호=%d" % c.n, head(self.s.sent[2]))

    def test_trigger_after_exit_is_not_ignored(self):  # D-065: 종료 뒤 트리거는 무시하지 않는다
        self.m.submit(R.Request("자유질의", input="a"))
        self.m.on_model_event(ProcessExited(1, False))
        self.assertEqual(self.m.trigger(), "started")
        self.assertTrue(wait_for(lambda: self.s.restarts == 1 and len(self.s.sent) == 2))
        self.assertEqual(self.log.of("trigger_held"), [])

    def test_restart_failure_after_exit_errors_waiting_cards(self):  # D-065
        self.m.submit(R.Request("자유질의", input="a"))
        self.m.on_model_event(ProcessExited(1, False))
        self.s.restart_ok = False
        c = self.m.submit(R.Request("자유질의", input="b"))
        self.assertTrue(wait_for(lambda: any(x.n == c.n and x.state == "오류" for x in self.m.cards())))
        self.assertEqual(self.s.restarts, 1)
        self.s.restart_ok = True                              # 다음 요청에서 다시 시도한다
        self.m.submit(R.Request("자유질의", input="c"))
        self.assertTrue(wait_for(lambda: self.s.restarts == 2 and len(self.s.sent) == 2))

    def test_expected_exit_ignored(self):
        self.m.submit(R.Request("자유질의", input="a"))
        self.m.on_model_event(ProcessExited(0, True))
        self.assertEqual(self.m.cards()[0].state, "진행")

    def test_compacted_resends_transcript_once(self):
        self.tr.add(seg(1, 0, 5))
        self.m.submit(R.Request("자유질의", input="a"))
        self.done()
        self.m.on_model_event(Compacted("auto", 100, 10))
        self.m.submit(R.Request("자유질의", input="b"))
        self.assertIn("[재전송]", head(self.s.sent[1]))
        self.done()
        self.m.submit(R.Request("자유질의", input="c"))
        self.assertNotIn("[재전송]", head(self.s.sent[2]))
        self.assertEqual(self.log.of("history_compacted")[0]["pre_tokens"], 100)


class Judgment(Base):
    def run_trigger(self, text):
        self.tr.add(seg(1, 0, 5))
        self.m.trigger()
        self.done(text)
        return self.m.cards()[0]

    def test_question(self):  # AC-FR7-20 형식
        c = self.run_trigger('판단: 질문 | "이 모델은 어떻게 학습합니까?"\n답변 본문')
        self.assertEqual((c.judgment, c.judgment_subject, c.text),
                         ("질문", "이 모델은 어떻게 학습합니까?", "답변 본문"))

    def test_already_answered(self):
        c = self.run_trigger('판단: 이미 답이 나온 질문 | "예전 질문"\n요약')
        self.assertEqual(c.judgment, "이미 답이 나온 질문")

    def test_no_question(self):
        c = self.run_trigger("판단: 질문 없음 | 환경 설정\n지금은 설명 중이다")
        self.assertEqual((c.judgment, c.judgment_subject, c.text), ("질문 없음", "환경 설정", "지금은 설명 중이다"))

    def test_unrecognized_is_unconfirmed_with_whole_body(self):  # AC-FR7-21
        c = self.run_trigger("그냥 답변이다\n둘째 줄")
        self.assertEqual((c.judgment, c.text), ("미확인", "그냥 답변이다\n둘째 줄"))

    def test_streaming_hides_first_line_until_it_ends(self):  # AC-FR9-22
        self.tr.add(seg(1, 0, 5))
        self.m.trigger()
        c = lambda: self.m.cards()[0]
        self.m.on_model_event(TextDelta('판단: 질문 | "이 모'))
        self.assertEqual((c().text, c().judgment), ("", None))
        self.m.on_model_event(TextDelta('델은?"\n답변 앞'))
        self.assertEqual((c().judgment, c().judgment_subject, c().text), ("질문", "이 모델은?", "답변 앞"))
        self.m.on_model_event(TextDelta('부분\n둘째'))
        self.assertEqual(c().text, "답변 앞부분\n둘째")
        self.assertNotIn("판단:", c().text)
        self.done('판단: 질문 | "이 모델은?"\n답변 앞부분\n둘째')
        self.assertEqual((c().judgment, c().text), ("질문", "답변 앞부분\n둘째"))

    def test_streaming_unconfirmed_restores_first_line(self):  # AC-FR9-22 · AC-FR7-21
        self.tr.add(seg(1, 0, 5))
        self.m.trigger()
        c = lambda: self.m.cards()[0]
        self.m.on_model_event(TextDelta("그냥 답"))
        self.assertEqual(c().text, "")
        self.m.on_model_event(TextDelta("변\n둘째"))
        self.assertEqual((c().judgment, c().text), ("미확인", "그냥 답변\n둘째"))
        self.done("그냥 답변\n둘째")
        self.assertEqual((c().judgment, c().text), ("미확인", "그냥 답변\n둘째"))

    def test_non_trigger_has_no_judgment(self):
        self.m.submit(R.Request("자유질의", input="q"))
        self.done('판단: 질문 | "x"\n본문')
        self.assertIsNone(self.m.cards()[0].judgment)


class TriggerHold(Base):
    def test_capture_busy_holds_then_runs(self):  # AC-FR12-4
        self.tr.add(seg(1, 0, 5))
        self.m.set_capture_busy(True)
        self.assertEqual(self.m.trigger(), "held")
        self.assertEqual(self.m.trigger(), "held")                # 하나만 보류한다
        self.assertEqual(self.s.sent, [])
        self.m.set_capture_busy(False)
        self.assertEqual(len(self.s.sent), 1)
        self.assertIn("종류=트리거", head(self.s.sent[0]))
        self.assertEqual(len(self.m.cards()), 1)

    def _capture_memo(self):
        self.m.set_capture_busy(True)
        card = self.m.submit(R.Request("화면메모"))
        self.m.track_capture(card.n)
        self.m.set_capture_busy(False)          # screencapture 는 끝났지만 화면 메모 요청이 진행 중이다
        return card

    def test_trigger_during_memo_in_flight_is_held_then_runs(self):  # D-114, AC-FR12-4 (tester F26)
        self.tr.add(seg(1, 0, 5))
        self._capture_memo()
        self.assertEqual(self.m.trigger(), "held")                # 응답 진행이지만 버리지 않는다
        self.assertEqual(len(self.s.sent), 1)
        self.done()
        self.assertEqual(len(self.s.sent), 2)
        self.assertIn("종류=트리거", head(self.s.sent[1]))
        order = [(t, f.get("action")) for (t, f) in self.log.ev if t in ("trigger_held", "request_done", "trigger_run")]
        names = [t for t, _ in order]
        self.assertLess(names.index("trigger_held"), names.index("request_done"))
        self.assertLess(names.index("request_done"), names.index("trigger_run"))      # 보류 → 메모 완료 → 실행
        self.assertEqual(order[0], ("trigger_held", "deferred"))

    def test_held_trigger_goes_before_queued_query_f27(self):  # D-115 (tester F27): 메모 진행 중 질의를 넣고 트리거
        self.tr.add(seg(1, 0, 5))
        self._capture_memo()
        self.m.submit(R.Request("자유질의", input="질의"))
        self.assertEqual(self.m.trigger(), "held")
        self.done()
        self.assertEqual(len(self.s.sent), 2)
        self.assertIn("종류=트리거", head(self.s.sent[1]))            # 화면메모 → 트리거
        self.done()
        self.assertEqual(len(self.s.sent), 3)
        self.assertIn("종류=자유질의", head(self.s.sent[2]))          # → 질의
        self.assertFalse([f for f in self.log.of("trigger_held") if f.get("action") == "ignored"])

    def test_held_trigger_goes_before_later_query_f28(self):  # D-115 (tester F28): 트리거 뒤 질의
        self.tr.add(seg(1, 0, 5))
        self._capture_memo()
        self.assertEqual(self.m.trigger(), "held")
        self.m.submit(R.Request("자유질의", input="질의"))
        self.done()
        self.assertIn("종류=트리거", head(self.s.sent[1]))
        self.done()
        self.assertIn("종류=자유질의", head(self.s.sent[2]))

    def test_held_trigger_not_dropped_when_query_in_flight_at_capture_end(self):  # D-115: 캡처 실패 + 질의 진행 중
        self.tr.add(seg(1, 0, 5))
        self.m.submit(R.Request("자유질의", input="진행"))
        self.m.submit(R.Request("자유질의", input="대기"))
        self.m.set_capture_busy(True)
        self.assertEqual(self.m.trigger(), "held")
        self.m.set_capture_busy(False)
        self.done()
        self.assertIn("종류=트리거", head(self.s.sent[1]))            # 버리지 않고 대기열의 질의보다 먼저 보낸다
        self.done()
        self.assertIn("종류=자유질의", head(self.s.sent[2]))

    def test_held_trigger_runs_after_memo_error(self):  # D-114: 화면 메모 오류 때에도 풀린다
        self.tr.add(seg(1, 0, 5))
        self._capture_memo()
        self.assertEqual(self.m.trigger(), "held")
        self.done("", ok=False, error_kind="api", terminal_reason="x")
        self.assertEqual(len(self.s.sent), 2)
        self.assertIn("종류=트리거", head(self.s.sent[1]))

    def test_held_trigger_runs_when_capture_fails_without_memo(self):  # D-114: 캡처 실패
        self.tr.add(seg(1, 0, 5))
        self.m.set_capture_busy(True)
        self.assertEqual(self.m.trigger(), "held")
        self.m.set_capture_busy(False)
        self.assertEqual(len(self.s.sent), 1)
        self.assertIn("종류=트리거", head(self.s.sent[0]))

    def test_trigger_busy_rule_unchanged_without_capture(self):  # FR-7: 캡처와 무관한 응답 진행 중에는 무시
        self.m.submit(R.Request("자유질의", input="q"))
        self.assertEqual(self.m.trigger(), "busy")

    def test_open_segment_waits_then_partial_after_cap(self):  # AC-FR7-14, 결정 0166
        s7 = seg(7, 1, 4)
        self.tr.set_open("끝나지 않은 문장", s7.start_wall, s7.end_wall, 1.0, 4.0)
        cuts = []
        m = self.mk(final_wait_cap_s=0.1, cut=lambda: cuts.append(1))
        self.m = m
        self.assertEqual(m.trigger(), "waiting")
        self.assertEqual(m.trigger(), "busy")                      # 기다리는 동안 다시 눌러도 무시
        self.assertTrue(wait_for(lambda: len(self.s.sent) == 1))
        self.assertEqual(cuts, [1])                                # 끊기 신호는 한 번이다
        self.assertIn("[잠정] 범위=", head(self.s.sent[0]))
        self.assertIn("끝나지 않은 문장", head(self.s.sent[0]))
        self.assertEqual(self.log.of("request_sent")[0]["partial_included"], True)
        self.assertIsNotNone(self.m.cards()[0].partial)            # 카드가 잠정 범위를 가진다(NEW-60)

    def test_second_trigger_ignored_while_waiting_d116(self):  # D-116: 확정을 기다리는 동안 다른 트리거는 무시한다
        s7 = seg(7, 0, 3)
        self.tr.set_open("열린 구간", s7.start_wall, s7.end_wall, 0.0, 3.0)
        self.m = self.mk(final_wait_cap_s=5.0)
        self.assertEqual(self.m.trigger("A"), "waiting")
        self.assertEqual(self.m.trigger("B"), "busy")
        self.assertEqual([f["reason"] for f in self.log.of("trigger_held") if f.get("action") == "ignored"][-1], "전사 처리 대기")
        self.tr.add(s7)                                             # 확정 도착 → A 전송
        self.assertTrue(wait_for(lambda: len(self.s.sent) == 1))
        self.assertNotIn("[잠정]", head(self.s.sent[0]))

    def test_final_arrived_before_cap_has_no_partial(self):
        s7 = seg(7, 1, 4)
        self.tr.set_open("열린 구간", s7.start_wall, s7.end_wall, 1.0, 4.0)
        self.m = self.mk(final_wait_cap_s=5.0)
        self.assertEqual(self.m.trigger(), "waiting")
        self.tr.add(s7)
        self.assertTrue(wait_for(lambda: len(self.s.sent) == 1))
        self.assertEqual(self.log.of("request_sent")[0]["partial_included"], False)
        self.assertIsNone(self.m.cards()[0].partial)


class DefectsD035D036(Base):
    def test_d035_deleted_error_card_not_updated_by_late_result(self):
        a = self.m.submit(R.Request("자유질의", input="a"))
        self.m.on_model_event(Error("network", "x"))
        self.assertTrue(self.m.delete_card(a.n))
        self.m.on_model_event(Result(False, text=""))
        self.assertEqual([c for c in self.cards if c[0] == a.n][-1][2], "removed")
        self.assertEqual(self.m.cards(), [])
        self.assertIsNone(self.m.in_flight())

    def test_d036_queue_enter_event_has_waiting_count(self):
        a = self.m.submit(R.Request("자유질의", input="a"))
        b = self.m.submit(R.Request("자유질의", input="b"))
        c = self.m.submit(R.Request("자유질의", input="c"))
        ev = self.log.of("queue_enter")
        self.assertEqual([(e["request_n"], e["waiting"], e["in_flight"]) for e in ev],
                         [(a.n, 1, False), (b.n, 1, True), (c.n, 2, True)])
        for e in ev:
            self.assertNotIn("input", e)

    def test_d036_request_sent_has_last30_segments(self):
        self.tr.add(seg(1, 0, 5))
        self.tr.add(seg(2, 6, 10))
        self.m.submit(R.Request("트리거", created_mono=12.0, t_trigger_mono=12.0))
        f = self.log.of("request_sent")[0]
        self.assertIn("last30_segments", f)
        self.assertGreaterEqual(f["last30_segments"], 1)
        self.assertIsNotNone(f["last30"])
        self.done()
        self.m.submit(R.Request("자유질의", input="q"))
        g = self.log.of("request_sent")[1]
        self.assertEqual((g["last30_segments"], g["last30"]), (0, None))

    def test_d036_judgment_event_has_kind_and_length_only(self):  # 결정 0062
        self.m.submit(R.Request("트리거"))
        self.done('판단: 질문 | "이것은 질문"')
        j = self.log.of("judgment")[0]
        self.assertEqual(j["judgment"], "질문")
        self.assertEqual(j["subject_chars"], len("이것은 질문"))
        self.assertNotIn("이것은 질문", repr(j))


class QueuedTriggerTime(Base):
    """AC-FR7-7 개정(Q-19): 대기열에서 늦게 나간 요청도 마지막 30초의 기점 T 는 요청한 시각이다."""

    def mk(self, **kw):
        self.now = [10.0]
        return super().mk(clock=lambda: self.now[0], **kw)

    def test_queued_request_uses_requested_time_as_t(self):
        self.tr.add(seg(1, 0, 5))
        self.m.submit(R.Request("자유질의", input="앞"))         # t=10 에 진행
        self.tr.add(seg(2, 8, 9))
        b = self.m.submit(R.Request("답변"))                     # t=10 에 요청, 대기
        self.assertEqual(self.m.queue_numbers(), [b.n])
        self.now[0] = 100.0                                      # 90초 뒤에 앞 요청이 끝난다
        self.tr.add(seg(3, 60, 70))                              # 요청한 뒤에 시작한 조각
        self.done()
        self.assertEqual(len(self.s.sent), 2)
        f = self.log.of("request_sent")[1]
        self.assertEqual(f["queued_s"], 90.0)
        self.assertEqual(f["last30_segments"], 2)                # 조각 1 · 2 (T=10 기준), 조각 3 은 제외

    def test_explicit_t_is_kept(self):
        r = R.Request("트리거", created_mono=5.0, t_trigger_mono=7.0)
        self.m.submit(r)
        self.assertEqual(r.t_trigger_mono, 7.0)


class Judge(unittest.TestCase):
    def test_parse_judgment_edge(self):
        self.assertEqual(R.parse_judgment('판단: 질문 | ""')[0], "미확인")
        self.assertEqual(R.parse_judgment("")[0], "미확인")
        self.assertEqual(R.parse_judgment("판단: 질문 없음 | ")[0], "미확인")


if __name__ == "__main__":
    unittest.main()
