"""진입점 조립(`core/runtime.py` · `core/inputparse.py` · `core/resources.py`): 조각 · 요청 · 응답 · 삭제의 세션 기록,
조립한 객체의 시작 전 상태(모델 호출 없음), 자원 복사본과 prompt-spec 의 일치 (AC-FR7-5 · 8 · 20, AC-FR10-3)."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))
sys.path.insert(0, str(ROOT / "tools"))

from nsu_kangs_rab.core import devopts, inputparse, resources  # noqa: E402
from nsu_kangs_rab.core import runtime as RT  # noqa: E402
from nsu_kangs_rab.core.context import ContextStore  # noqa: E402
from nsu_kangs_rab.core.types import Result, Segment, TextDelta  # noqa: E402


def seg(n, start, end, text="본문"):
    def w(x):
        return "2026-10-11T14:%02d:%02d.000+09:00" % (x // 60, x % 60)
    return Segment(n, w(start), w(end), float(start), float(end), text)


class FakeModel:
    def __init__(self, config=None, auth=None, on_event=None, **kw):
        self.config, self.auth, self.on_event, self.kw = config, auth, on_event, kw
        self.sent, self.pid, self.init = [], 4242, None
        self.started = self.closed = False

    def start(self):
        self.started = True
        return True

    def send(self, msg):
        self.sent.append(msg)
        return True

    def interrupt(self):
        return "int"

    def restart(self):
        return True

    def close(self):
        self.closed = True


class Log:
    def __init__(self):
        self.ev = []

    def emit(self, type_, **f):
        self.ev.append((type_, f))
        return True

    def session_start(self, **f):
        return self.emit("session_start", **f)

    def of(self, t):
        return [f for (x, f) in self.ev if x == t]


def read_jsonl(folder):
    return [json.loads(x) for x in (Path(folder) / "session.jsonl").read_text(encoding="utf-8").splitlines()]


PARAMS = {"provider": "claude_subscription", "model": "sonnet", "effort": "medium", "source": "system_sound",
          "kind": "수업", "title": "", "save_dir": ""}


class InputParseTest(unittest.TestCase):
    def test_commands_and_free_query(self):
        self.assertIsNone(inputparse.parse("   "))
        self.assertEqual(inputparse.parse("/답변").kind, "답변")
        self.assertEqual(inputparse.parse(" /고찰 ").kind, "트리거")   # 결정 0155: [고찰] 단추와 같은 요청
        self.assertEqual(inputparse.parse("/요약").kind, "요약")
        p = inputparse.parse("  정규화가 뭐지?  ")
        self.assertEqual((p.kind, p.text), ("자유질의", "정규화가 뭐지?"))

    def test_unknown_slash_is_not_sent(self):
        for s in ("/model opus", "/effort high", "/clear", "/compact", "/답변 3", "/"):
            p = inputparse.parse(s)
            self.assertTrue(p.unknown, s)
            self.assertIsNone(p.kind)


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Path(self.tmp.name) / "cfg"
        self.save = Path(self.tmp.name) / "save"
        self.cards, self.notices = [], []
        self.log = Log()
        self.models = []

        def factory(cfg, auth, on_event, **kw):
            m = FakeModel(cfg, auth, on_event, **kw)
            self.models.append(m)
            return m
        self.rt = RT.build_runtime(params=dict(PARAMS), data={}, devopts=devopts.parse([]), config_dir=self.cfg,
                                   save_base=str(self.save), claude_path="/x/claude", claude_is_script=False,
                                   parent_env={"PATH": "/usr/bin"}, procs=None, eventlog=self.log,
                                   context=ContextStore(), on_card=lambda c, ch: self.cards.append((c, ch)),
                                   on_notice=lambda k, i: self.notices.append((k, i)), today=date(2026, 10, 11),
                                   model_factory=factory)
        self.addCleanup(self.rt.close)
        self.model = self.models[0]

    def test_number_is_session_folder_number(self):          # 결정 0176 1항, AC-FR13-19 ① ② ③ ⑤ ⑦
        base = self.save / "n"

        def build(kind="수업", day=date(2026, 10, 12)):
            rt = RT.build_runtime(params=dict(PARAMS, kind=kind, save_dir=str(base)), data={}, devopts=devopts.parse([]),
                                  config_dir=self.cfg, save_base=str(base), claude_path="/x/claude", claude_is_script=False,
                                  parent_env={"PATH": "/usr/bin"}, procs=None, eventlog=self.log, context=ContextStore(),
                                  today=day, model_factory=lambda cfg, auth, on_event, **kw: FakeModel(cfg, auth, on_event, **kw))
            self.addCleanup(rt.close)
            return rt, read_jsonl(rt.folder)[0]["number"]
        r1, n1 = build()
        r2, n2 = build("회의")                                  # 종류를 섞어도 이어진다
        r3, n3 = build()
        self.assertEqual([r1.folder.name, r2.folder.name, r3.folder.name], ["2026-10-12", "2026-10-12-2", "2026-10-12-3"])
        self.assertEqual((n1, n2, n3), ("1", "2", "3"))         # 앞에 0을 붙이지 않는다
        import shutil
        r1.close()
        shutil.rmtree(r1.folder)                                  # 첫 폴더를 지우면 첫 빈 이름의 번호를 쓴다
        r4, n4 = build()
        self.assertEqual((r4.folder.name, n4), ("2026-10-12", "1"))

    def test_build_makes_header_and_session_start_without_model_call(self):
        recs = read_jsonl(self.rt.folder)
        self.assertEqual(len(recs), 1)
        h = recs[0]
        self.assertEqual((h["type"], h["v"], h["date"], h["source"], h["kind"], h["mode"]),
                         ("header", 1, "2026-10-11", "시스템 사운드", "수업", "화상"))
        self.assertEqual((h["title"], h["number"], h["effort"], h["materials"]), ("(이름 없음)", "1", "medium", []))
        self.assertEqual(self.rt.folder.name, "2026-10-11")
        self.assertTrue((self.rt.folder / "captures").is_dir())
        self.assertFalse(self.model.started)       # 만드는 것만으로 프로세스를 시작하지 않는다
        self.assertEqual(self.model.sent, [])
        ss = self.log.of("session_start")[0]
        self.assertEqual((ss["provider"], ss["model"], ss["prompt_source"], ss["dev_options"]),
                         ("claude_subscription", "sonnet", "app_default", []))
        self.assertIn("[사용자 문구]", self.model.kw["prompt_text"])
        self.assertTrue(self.model.kw["prompt_text"].startswith(resources.app_rules("ko")))

    def test_segment_goes_to_transcript_and_files_once(self):
        self.assertTrue(self.rt.on_segment(seg(1, 5, 9, "첫 조각")))
        self.assertFalse(self.rt.on_segment(seg(1, 5, 9, "첫 조각")))
        self.assertEqual(self.rt.transcript.count(), 1)
        txt = (self.rt.folder / "transcript.txt").read_text(encoding="utf-8")
        self.assertIn("첫 조각", txt)
        segs = [r for r in read_jsonl(self.rt.folder) if r["type"] == "segment"]
        self.assertEqual([(r["n"], r["text"]) for r in segs], [(1, "첫 조각")])

    def test_partial_open_section_closed_by_segment_and_close_open(self):
        from nsu_kangs_rab.core.types import PartialSegment
        self.rt.on_partial(PartialSegment("열린 문장", 10.0, 12.0), "2026-10-11T14:00:10.000+09:00", "2026-10-11T14:00:12.000+09:00")
        self.assertIsNotNone(self.rt.transcript.open_for(20.0))
        self.rt.on_segment(seg(2, 10, 12))                       # 확정이 오면 열린 구간이 닫힌다
        self.assertIsNone(self.rt.transcript.open_for(20.0))
        self.rt.on_partial(PartialSegment("또 열린", 13.0, 14.0), "2026-10-11T14:00:13.000+09:00", "2026-10-11T14:00:14.000+09:00")
        self.rt.close_open()                                     # 구간 실패 · 중단: 잠정을 버린다
        self.assertIsNone(self.rt.transcript.open_for(20.0))
        self.assertFalse([r for r in read_jsonl(self.rt.folder) if r["type"] == "segment" and r["n"] == 3])   # 잠정은 기록하지 않는다

    def test_free_query_request_response_records(self):
        self.assertTrue(self.rt.start())
        card = self.rt.submit("자유질의", text="정규화란?")
        self.assertEqual(card.n, 1)
        self.assertEqual(len(self.model.sent), 1)
        self.rt.on_model_event(TextDelta("답"))
        self.rt.on_model_event(Result(True, text="답한다.\n근거: 없음"))
        recs = read_jsonl(self.rt.folder)
        req = [r for r in recs if r["type"] == "request"][0]
        rsp = [r for r in recs if r["type"] == "response"][0]
        self.assertEqual((req["n"], req["kind"], req["input"]), (1, "자유질의", "정규화란?"))
        self.assertEqual((rsp["n"], rsp["status"], rsp["judgment"], rsp["text"]), (1, "완료", None, "답한다.\n근거: 없음"))
        self.assertEqual([ch for c, ch in self.cards if c.n == 1][0], "new")

    def test_answer_input_values_and_selected(self):
        self.rt.on_segment(seg(1, 1, 2))
        self.rt.submit("답변")
        self.rt.on_model_event(Result(True, text="x"))
        self.rt.submit("답변", selected=(3, 1, 2))
        self.rt.on_model_event(Result(True, text="x"))
        self.rt.submit("고찰")
        self.rt.on_model_event(Result(True, text="x"))
        self.rt.submit("요약")
        inputs = [r["input"] for r in read_jsonl(self.rt.folder) if r["type"] == "request"]
        self.assertEqual(inputs, ["/답변", "/답변 조각=1~3", "/고찰", "/요약"])

    def test_image_with_text_and_capture_memo_records(self):
        card = self.rt.submit("자유질의", text="이게 뭐지", images=(), capture_paths=(("captures/a.png", "붙여넣기"),),
                              record_input=None)
        self.rt.on_model_event(Result(True, text="x"))
        card2 = self.rt.submit("화면메모", capture_paths=(("captures/b.png", "캡처"),))
        recs = read_jsonl(self.rt.folder)
        caps = [(r["n"], r["path"], r["source"]) for r in recs if r["type"] == "capture"]
        self.assertEqual(caps, [(card.n, "captures/a.png", "붙여넣기"), (card2.n, "captures/b.png", "캡처")])
        reqs = {r["n"]: r["input"] for r in recs if r["type"] == "request"}
        self.assertEqual(reqs[card2.n], "captures/b.png")

    def test_request_line_written_when_sent_not_when_queued_d127(self):  # D-127, FR-10 `request`: 요청을 보낼 때
        self.rt.submit("자유질의", text="첫 질문")                    # 진행 중(응답 없음)
        queued = self.rt.submit("자유질의", text="대기 중으로 남을 질문")
        self.assertEqual(len(self.model.sent), 1)
        self.assertEqual([r["n"] for r in read_jsonl(self.rt.folder) if r["type"] == "request"], [1])
        self.rt.delete_card(queued.n)                                 # 보내기 전에 지운다
        recs = read_jsonl(self.rt.folder)
        self.assertEqual([r["n"] for r in recs if r["type"] == "request"], [1])
        self.assertEqual([(r["n"], r["state"]) for r in recs if r["type"] == "delete"], [(queued.n, "대기 중")])

    def test_queued_request_line_written_when_it_is_sent_d127(self):
        self.rt.submit("자유질의", text="첫")
        second = self.rt.submit("자유질의", text="둘째", capture_paths=(("captures/c.png", "캡처"),))
        self.assertEqual([r["type"] for r in read_jsonl(self.rt.folder)].count("capture"), 0)
        self.rt.on_model_event(Result(True, text="x"))               # 첫 응답 → 둘째를 보낸다
        recs = read_jsonl(self.rt.folder)
        self.assertEqual([r["n"] for r in recs if r["type"] == "request"], [1, second.n])
        self.assertEqual([r["n"] for r in recs if r["type"] == "capture"], [second.n])

    def test_trigger_judgment_line_recorded(self):
        self.rt.on_segment(seg(1, 1, 2))
        st = self.rt.trigger("button")
        self.assertEqual(st, "started")
        self.rt.on_model_event(Result(True, text='판단: 질문 | "정규화가 뭐지?"\n정규화는 …'))
        rsp = [r for r in read_jsonl(self.rt.folder) if r["type"] == "response"][0]
        self.assertEqual(rsp["judgment"], '판단: 질문 | "정규화가 뭐지?"')
        self.assertEqual(rsp["text"], "정규화는 …")
        req = [r for r in read_jsonl(self.rt.folder) if r["type"] == "request"][0]
        self.assertEqual((req["kind"], req["input"]), ("트리거", ""))

    def test_delete_waiting_and_active_cards_are_recorded(self):
        a = self.rt.submit("자유질의", text="a")      # 진행
        b = self.rt.submit("자유질의", text="b")      # 대기
        self.assertTrue(self.rt.delete_card(b.n))
        self.assertTrue(self.rt.delete_card(a.n))
        self.assertFalse(self.rt.delete_card(99))
        dels = [(r["n"], r["state"]) for r in read_jsonl(self.rt.folder) if r["type"] == "delete"]
        self.assertEqual(dels, [(b.n, "대기 중"), (a.n, "진행 중")])
        self.assertEqual(len(self.model.sent), 1)      # 대기 중이던 요청은 보내지 않았다

    def test_close_closes_model_and_files(self):
        self.rt.close()
        self.rt.close()
        self.assertTrue(self.model.closed)

    def test_no_model_call_without_request(self):
        self.rt.start()
        self.rt.on_segment(seg(1, 1, 2))
        self.assertEqual(self.model.sent, [])


class DevOptionsWiringTest(unittest.TestCase):
    def test_caps_reach_composer_and_manager(self):
        opts = devopts.parse(["--dev-request-image-bytes-cap", "123", "--dev-hidden-cap-s", "7", "--dev-final-wait-cap-s", "3",
                              "--dev-save-dir", "/will/be/ignored/for/test"])
        with tempfile.TemporaryDirectory() as d:
            opts.values["save_dir"] = str(Path(d) / "s")
            rt = RT.build_runtime(params=dict(PARAMS), data={}, devopts=opts, config_dir=Path(d) / "c", save_base=d,
                                  claude_path="/x/claude", claude_is_script=None, parent_env={}, procs=None,
                                  eventlog=Log(), context=ContextStore(), today=date(2026, 10, 11),
                                  model_factory=lambda *a, **k: FakeModel(*a, **k))
            try:
                self.assertEqual(rt.composer.request_image_bytes_cap, 123)
                self.assertEqual(rt.manager._hidden_limit, 7.0)
                self.assertEqual(rt.manager._final_cap, 3.0)
                self.assertTrue(str(rt.folder).startswith(str(Path(d) / "s")))
            finally:
                rt.close()


if __name__ == "__main__":
    unittest.main()
