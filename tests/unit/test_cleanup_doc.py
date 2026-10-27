"""K-16: 정리 문서 요청 구성 · 저장 (prompt-spec 8 · 8-3-1절, AC-FR13-7 · 13 · 14, AC-FR10-6)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import cleanup_doc as D  # noqa: E402
from nsu_kangs_rab.core.session import read_jsonl  # noqa: E402

HEADER = {"type": "header", "v": 1, "date": "2026-10-09", "provider": "claude_subscription", "model": "sonnet",
          "effort": "medium", "source": "시스템 사운드", "materials": [], "kind": "수업", "title": "데이터 관리 입문",
          "number": "03", "mode": "화상", "start": "13:15:00"}


def lines(*evs, end=True, garbage=False):
    out = [json.dumps(e, ensure_ascii=False) for e in evs]
    if end:
        out.append(json.dumps({"type": "end", "ts": "14:58:11"}))
    s = "\n".join(out) + "\n"
    if garbage:
        s += '{"type":"segment","n":9,"sta'
    return s


EVENTS = [
    HEADER,
    {"type": "segment", "n": 1, "start": "13:15:05", "end": "13:15:09", "text": "정규화가\n필요하다"},
    {"type": "segment", "n": 2, "start": "13:15:10", "end": "13:15:20", "text": "[표지] 처럼 시작"},
    {"type": "request", "n": 31, "kind": "트리거", "input": "", "ts": "14:32:07"},
    {"type": "response", "n": 31, "judgment": '판단: 질문 | "정규화를 안 하면 어떤 문제가 생길까요"', "text": "중복이 생긴다.\n[참고] 줄",
     "status": "완료", "ts": "14:32:15"},
    {"type": "request", "n": 32, "kind": "자유질의", "input": "BCNF 가\n뭔지", "ts": "14:34:30"},
    {"type": "response", "n": 32, "judgment": None, "text": "답", "status": "중단", "ts": "14:34:40"},
    {"type": "request", "n": 33, "kind": "화면메모", "input": "captures/capture-143511.png", "ts": "14:35:11"},
    {"type": "response", "n": 33, "judgment": None, "text": "메모", "status": "완료", "ts": "14:35:20"},
    {"type": "capture", "n": 33, "path": "captures/capture-143511.png", "source": "캡처", "ts": "14:35:11"},
    {"type": "capture", "n": 20, "path": "captures/capture-142005.png", "source": "캡처", "ts": "14:20:05"},
    {"type": "diagram", "n": 31, "path": "captures/diagrams/a.svg", "result": "완료", "ts": "14:31:40"},
    {"type": "diagram", "n": 31, "path": "captures/diagrams/bad.svg", "result": "실패", "ts": "14:31:50"},
    {"type": "delete", "n": 33, "kind": "화면메모", "card_ts": "14:35:11", "state": "진행 중", "ts": "14:36:00"},
    {"type": "delete", "n": 35, "kind": "답변", "card_ts": "14:40:02", "state": "대기 중", "ts": "14:40:03"},
]


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)

    def view(self, events=EVENTS, **kw):
        p = self.dir / "session.jsonl"
        p.write_text(lines(*events, **kw), encoding="utf-8")
        ev, rec = read_jsonl(p)
        return D.session_view(ev, rec)


class RequestTest(Base):
    def test_history_less_layout(self):  # 8-3-1절 순서
        t = D.build_request(self.view(), "수업", "TEMPLATE", history=False).split("\n")
        self.assertEqual(t[0], "[요청] 종류=정리문서 문서=수업 이력=없음")
        self.assertEqual(t[1], "[세션] 과목명=데이터 관리 입문 차시=03 방식=화상 시작=2026-10-09 13:15 종료=14:58")
        self.assertEqual(t[2], "[재전송] 범위=13:15:05~13:15:20 조각=1~2")
        self.assertEqual(t[3], "1 13:15:05-13:15:09 정규화가 필요하다")
        self.assertEqual(t[-2:], ["[템플릿]", "TEMPLATE"])
        order = [i for i, x in enumerate(t) if x.startswith(("[캡처]", "[다이어그램]", "[삭제된 카드]", "[질의응답]"))]
        self.assertEqual(order, sorted(order))

    def test_deleted_cards_excluded_from_files_and_qa(self):  # AC-FR13-13 · 14
        t = D.build_request(self.view(), "수업", "T", history=False)
        self.assertIn("[캡처] 14:20:05 captures/capture-142005.png", t)
        self.assertNotIn("[캡처] 14:35:11", t)                        # 지운 카드의 캡처
        self.assertIn("[다이어그램] 14:31:40 captures/diagrams/a.svg", t)
        self.assertNotIn("bad.svg", t.replace("[다이어그램]", ""))   # 실패한 다이어그램은 목록에 없다
        self.assertIn("[삭제된 카드] 요청=33 종류=화면메모 시각=14:35:11 파일=captures/capture-143511.png", t)
        self.assertIn("[삭제된 카드] 요청=35 종류=답변 시각=14:40:02", t)
        self.assertNotIn("[질의응답] 요청=33", t)
        self.assertIn("[질의응답] 요청=31 시각=14:32:07 종류=트리거", t)

    def test_qa_input_rules_and_escape(self):
        t = D.build_request(self.view(), "수업", "T", history=False).split("\n")
        i = t.index("[질의응답] 요청=31 시각=14:32:07 종류=트리거")
        self.assertEqual(t[i + 1], "[입력] 질문: 정규화를 안 하면 어떤 문제가 생길까요")
        self.assertEqual(t[i + 2], "[응답]")
        self.assertEqual(t[i + 3], '판단: 질문 | "정규화를 안 하면 어떤 문제가 생길까요"')
        self.assertIn("\\[참고] 줄", t)                                  # 줄 머리 `[` 이스케이프
        j = t.index("[질의응답] 요청=32 시각=14:34:30 종류=자유질의 상태=중단")
        self.assertEqual(t[j + 1], "[입력] BCNF 가 뭔지")                # 줄바꿈은 공백

    def test_history_path_has_no_resend_or_qa(self):  # 8절
        t = D.build_request(self.view(), "수업", "T", history=True)
        self.assertTrue(t.startswith("[요청] 종류=정리문서 문서=수업\n[세션]"))
        self.assertNotIn("[재전송]", t)
        self.assertNotIn("[질의응답]", t)
        self.assertIn("[삭제된 카드] 요청=35", t)
        self.assertIn("[캡처] 14:20:05", t)

    def test_end_missing_and_broken_last_line(self):  # AC-FR10-6
        v = self.view(end=False, garbage=True)
        self.assertEqual(v.ignored_lines, 1)
        self.assertTrue(v.end_substituted)
        s = D.session_line(v, "수업")
        self.assertIn("종료=13:15", s)                                   # 마지막 segment 의 end 13:15:20
        self.assertTrue(s.endswith("종료대체=예"))

    def test_no_header_no_segments(self):
        v = self.view([{"type": "request", "n": 1, "kind": "요약", "input": "/요약", "ts": "10:00:00"}], end=False)
        self.assertIsNone(v.header)
        t = D.build_request(v, "회의", "T", history=False)
        self.assertIn("문서=회의", t)
        self.assertIn("[재전송] 없음", t)
        self.assertIn("과목명=(이름 없음)", t)


class SaveTest(Base):
    def test_never_overwrites(self):  # AC-FR13-14
        a = D.save_document(self.dir, "수업", "첫째")
        b = D.save_document(self.dir, "수업", "둘째")
        c = D.save_document(self.dir, "회의", "회의")
        self.assertEqual((a.name, b.name, c.name), ("lecture.md", "lecture-2.md", "meeting.md"))
        self.assertEqual(a.read_text(encoding="utf-8"), "첫째\n")
        self.assertEqual(D.next_document_path(self.dir, "수업").name, "lecture-3.md")


if __name__ == "__main__":
    unittest.main()
