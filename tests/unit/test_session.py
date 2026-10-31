"""K-08: 세션 폴더 · session.jsonl (AC-FR10-1~5 · 7, AC-FR13-4 · 12). 결정 0196: session.md · transcript.txt 는 만들지 않는다."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import session as S  # noqa: E402
from nsu_kangs_rab.core.types import Segment  # noqa: E402


def seg(n, sw, ew, text="본문"):
    return Segment(n, "2026-10-11T%s.000+09:00" % sw, "2026-10-11T%s.000+09:00" % ew, float(n), float(n) + 1, text)


HEADER = dict(date="2026-10-11", provider="구독", model="sonnet", effort="medium", source="시스템 마이크",
              materials=["a.md", "b.pdf"], kind="수업", title="데이터: 입문\n2반", number="3차시", mode="대면",
              start="13:15:00")


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.base = Path(self.td.name) / "ProfKangRAB"

    def folder(self):
        return S.SessionFolder.create(self.base, "2026-10-11")

    def lines(self, folder):
        return (folder / "session.jsonl").read_text(encoding="utf-8").split("\n")[:-1]


class Folder(Base):
    def test_create_and_suffixes_without_overwrite(self):  # AC-FR13-4 · A-21
        a = self.folder()
        (a / "transcript.txt").write_text("기존", encoding="utf-8")
        b = self.folder()
        c = self.folder()
        self.assertEqual([p.name for p in (a, b, c)], ["2026-10-11", "2026-10-11-2", "2026-10-11-3"])
        self.assertTrue((a / "captures").is_dir())
        self.assertEqual((a / "transcript.txt").read_text(encoding="utf-8"), "기존")

    def test_race_two_creators_get_distinct_folders(self):
        out, lock = [], threading.Lock()

        def run():
            p = self.folder()
            with lock:
                out.append(p.name)
        ts = [threading.Thread(target=run) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(set(out)), 8)

    def test_bad_date(self):
        with self.assertRaises(ValueError):
            S.SessionFolder.create(self.base, "10/11")

    def test_number_from_folder_name(self):                  # 결정 0176 1항: 차시 = 폴더 번호
        a, b, c = self.folder(), self.folder(), self.folder()
        self.assertEqual([S.SessionFolder.number(p) for p in (a, b, c)], [1, 2, 3])
        self.assertEqual(S.SessionFolder.number("/x/2026-10-11-12"), 12)
        self.assertEqual(S.SessionFolder.number("/x/잘못된 이름"), 1)


class Log(Base):
    def open(self):
        f = self.folder()
        self.log = S.SessionLog(f, wall=lambda: "13:20:00")
        self.addCleanup(self.log.close)
        return f

    def test_header_first_line_with_all_fields(self):  # AC-FR10-3 · AC-FR10-4
        f = self.open()
        self.log.append("header", **HEADER)
        first = self.lines(f)[0]
        o = json.loads(first)
        self.assertEqual(o["type"], "header")
        for k in ("v",) + tuple(HEADER):
            self.assertIn(k, o)
        self.assertEqual(o["v"], 1)
        self.assertEqual(o["title"], "데이터: 입문\n2반")      # 원문 그대로
        self.log.append("segment", n=1, start="13:15:05", end="13:15:07", text="안녕")
        self.log.append("end")
        ls = self.lines(f)
        self.assertEqual(ls[0], first)                          # 첫 줄의 바이트가 같다
        self.assertEqual(json.loads(ls[-1])["type"], "end")
        self.assertNotIn("\r", "\n".join(ls))
        self.assertEqual(len(ls), 3)                            # 한 사건은 항상 한 줄

    def test_first_line_must_be_header_and_only_once(self):
        self.open()
        with self.assertRaises(S.SessionRecordError):
            self.log.append("segment", n=1, start="13:15:05", end="13:15:07", text="x")
        self.log.append("header", **HEADER)
        with self.assertRaises(S.SessionRecordError):
            self.log.append("header", **HEADER)

    def test_schema_rejects_bad_events_and_writes_nothing(self):
        f = self.open()
        self.log.append("header", **HEADER)
        n = len(self.lines(f))
        bad = [("request", dict(n=1, kind="없는종류", input="x")),
               ("request", dict(n=1, kind="자유질의")),
               ("response", dict(n=1, judgment=None, text="t", status="실패")),
               ("capture", dict(n=2, path="/abs/x.png", source="캡처")),
               ("capture", dict(n=2, path="../x.png", source="캡처")),
               ("delete", dict(n=3, kind="고찰", card_ts="13:20:00", state="없는상태")),
               ("diagram", dict(n=2, path="", result="완료")),
               ("segment", dict(n="1", start="13:15:05", end="13:15:07", text="x")),
               ("unknown", {})]
        for t, kw in bad:
            with self.assertRaises(S.SessionRecordError, msg=t):
                self.log.append(t, **kw)
        self.assertEqual(len(self.lines(f)), n)

    def test_all_event_types_roundtrip(self):  # 여덟 가지
        f = self.open()
        self.log.append("header", **HEADER)
        self.log.append("segment", n=1, start="13:15:05", end="13:15:07", text="조각")
        self.log.append("request", n=1, kind="트리거", input="")
        self.log.append("response", n=1, judgment='판단: 질문 | "x?"', text="본문", status="완료")
        self.log.append("capture", n=2, path="captures/c1.png", source="캡처")
        self.log.append("diagram", n=3, path="captures/diagrams/d.svg", result="완료")
        self.log.append("delete", n=4, kind="고찰", card_ts="13:21:00", state="대기 중")
        self.log.append("pause", state="시작", ts="13:22:00")
        self.log.append("end")
        ev, rec = S.read_jsonl(f / "session.jsonl")
        self.assertEqual([e["type"] for e in ev], list(S.TYPES))
        self.assertEqual((rec.end_substituted, rec.end_time, rec.ignored_lines), (False, "13:20:00", 0))
        req = ev[2]
        self.assertEqual(req["ts"], "13:20:00")
        self.assertNotIn("scope", req)                          # 맥락 범위는 기록하지 않는다(결정 0196 4항)
        with self.assertRaises(S.SessionRecordError):           # `scope` 는 더 이상 특별한 인자가 아니라 알 수 없는 필드이다
            self.log.append("request", n=2, kind="트리거", input="", scope="1~3")

    def test_response_text_roundtrips_exactly(self):  # AC-FR10-7
        f = self.open()
        self.log.append("header", **HEADER)
        text = '줄1\n[대괄호] 줄\n## 제목\n삭제: 가짜\n종료: 가짜\n"따옴표" \\ 역슬래시'
        self.log.append("response", n=1, judgment=None, text=text, status="완료")
        self.log.append("end")
        ev, _ = S.read_jsonl(f / "session.jsonl")
        self.assertEqual(ev[1]["text"], text)
        self.assertEqual(len(self.lines(f)), 3)

    def test_files_only_in_session_folder(self):  # AC-FR10-2
        f = self.open()
        self.log.append("header", **HEADER)
        self.log.append("segment", n=1, start="13:15:05", end="13:15:07", text="조각")
        self.log.close()
        self.assertEqual(sorted(p.name for p in f.iterdir()), ["captures", "session.jsonl"])      # 결정 0196: session.md · transcript.txt 없음
        self.assertFalse(hasattr(S, "TranscriptFile"))
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["2026-10-11"])

    def test_forced_kill_keeps_lines(self):  # AC-FR10-1: 프로세스를 SIGKILL 해도 줄이 남는다
        f = self.folder()
        code = ("import sys, os, signal; sys.path.insert(0, %r)\n"
                "from nsu_kangs_rab.core import session as S\n"
                "from nsu_kangs_rab.core.types import Segment\n"
                "L = S.SessionLog(sys.argv[1])\n"
                "L.append('header', **%r)\n"
                "L.append('segment', n=1, start='13:15:05', end='13:15:07', text='남아야 한다')\n"
                "L.append('request', n=1, kind='자유질의', input='q')\n"
                "os.kill(os.getpid(), signal.SIGKILL)\n") % (str(ROOT / "src" / "mac"), HEADER)
        r = subprocess.run([sys.executable, "-c", code, str(f)], capture_output=True)
        self.assertEqual(r.returncode, -9)
        ev, rec = S.read_jsonl(f / "session.jsonl")
        self.assertEqual([e["type"] for e in ev], ["header", "segment", "request"])
        self.assertTrue(rec.end_substituted)
        self.assertEqual(rec.end_time, "13:15:07")
        self.assertIn("남아야 한다", (f / "session.jsonl").read_text(encoding="utf-8"))

    def test_concurrent_appends_keep_whole_lines(self):
        f = self.open()
        self.log.append("header", **HEADER)

        def w(k):
            for i in range(50):
                self.log.append("segment", n=k * 100 + i, start="13:15:05", end="13:15:07", text="가" * 200)
        ts = [threading.Thread(target=w, args=(k,)) for k in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        ev, rec = S.read_jsonl(f / "session.jsonl")
        self.assertEqual((len(ev), rec.ignored_lines), (201, 0))


class Read(Base):
    def test_broken_last_line_ignored_and_reported(self):  # AC-FR10-6 의 읽기 부분
        f = self.folder()
        p = f / "session.jsonl"
        good = [json.dumps({"type": "header", **HEADER}, ensure_ascii=False),
                json.dumps({"type": "segment", "n": 1, "start": "13:15:05", "end": "13:15:07", "text": "a"}, ensure_ascii=False),
                json.dumps({"type": "segment", "n": 2, "start": "13:16:00", "end": "13:16:09", "text": "b"}, ensure_ascii=False)]
        p.write_text("\n".join(good) + '\n{"type":"response","n":1,"text":"깨', encoding="utf-8")
        seen = []
        ev, rec = S.read_jsonl(p, emit=lambda t, **k: seen.append((t, k)))
        self.assertEqual(len(ev), 3)
        self.assertEqual((rec.end_substituted, rec.end_time, rec.ignored_lines, rec.ignored), (True, "13:16:09", 1, (4,)))
        self.assertEqual(seen, [("session_line_ignored", {"line": 4})])

    def test_no_segments_no_end(self):
        f = self.folder()
        (f / "session.jsonl").write_text(json.dumps({"type": "header", **HEADER}) + "\n", encoding="utf-8")
        ev, rec = S.read_jsonl(f / "session.jsonl")
        self.assertEqual((rec.end_substituted, rec.end_time), (True, None))

    def test_non_object_lines_ignored(self):
        f = self.folder()
        (f / "session.jsonl").write_text('[1,2]\n"x"\n{"a":1}\n{"type":"end","ts":"14:00:00"}\n', encoding="utf-8")
        ev, rec = S.read_jsonl(f / "session.jsonl")
        self.assertEqual(([e["type"] for e in ev], rec.ignored_lines, rec.end_time), (["end"], 3, "14:00:00"))


class Midnight(Base):
    def test_midnight_keeps_start_date_folder_and_wall_times(self):  # AC-FR13-12
        f = S.SessionFolder.create(self.base, "2026-10-11")
        log = S.SessionLog(f)
        self.addCleanup(log.close)
        log.append("header", **HEADER)
        log.append("segment", n=1, start="23:59:58", end="23:59:59", text="자정 전")
        log.append("segment", n=2, start="00:00:05", end="00:00:07", text="자정 뒤")
        self.assertEqual(f.name, "2026-10-11")
        data = (f / "session.jsonl").read_text(encoding="utf-8")
        self.assertIn('"start":"23:59:58","end":"23:59:59","text":"자정 전"', data)
        self.assertIn('"start":"00:00:05","end":"00:00:07","text":"자정 뒤"', data)


if __name__ == "__main__":
    unittest.main()
