"""K-11(화면 없는 부분): 상태 기계 · 상태별 활성 항목 · 화면 밝기 선택 · 상태 표시줄 (AC-FR1-1 · 3, AC-FR11-5, AC-FR14-*, AC-FR15-1 · 3)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "mac"))

from nsu_kangs_rab.core import appstate as A  # noqa: E402
from nsu_kangs_rab.core.appstate import State  # noqa: E402


class Machine(unittest.TestCase):
    def test_first_run_flow(self):
        seen, ev = [], []
        m = A.AppStateMachine(first_run=True, on_change=lambda o, n: seen.append((o, n)),
                              emit=lambda t, **f: ev.append((t, f)))
        self.assertEqual(m.state, State.FIRST_RUN)
        m.acknowledge_first_run()
        m.start_session()
        m.begin_ending()
        m.finish()
        self.assertEqual([n for _, n in seen], [State.BEFORE_SESSION, State.IN_SESSION, State.ENDING, State.DONE])
        self.assertEqual(ev[0], ("app_state", {"old": "first_run", "new": "before"}))

    def test_not_first_run_starts_before_session(self):
        self.assertEqual(A.AppStateMachine(first_run=False).state, State.BEFORE_SESSION)

    def test_illegal_transitions_do_not_change_state(self):  # AC-FR11-5: 종료 뒤 시작 화면으로 돌아가지 않는다
        m = A.AppStateMachine(first_run=False)
        m.start_session()
        for bad in (State.BEFORE_SESSION, State.FIRST_RUN, State.IN_SESSION):
            with self.assertRaises(A.StateError):
                m.transition(bad)
        self.assertEqual(m.state, State.IN_SESSION)
        m.begin_ending()
        m.finish()
        with self.assertRaises(A.StateError):
            m.transition(State.BEFORE_SESSION)

    def test_quit_from_pre_session_states(self):
        for first in (True, False):
            m = A.AppStateMachine(first_run=first)
            m.finish()
            self.assertEqual(m.state, State.DONE)

    def test_forced_end_from_session(self):
        m = A.AppStateMachine(first_run=False)
        m.start_session()
        m.finish()
        self.assertEqual(m.state, State.DONE)


class Items(unittest.TestCase):
    TABLE = {  # FR-14 표의 ①②③④ (None = 입력 칸에 따름)
        "app.about": "○○○○", "app.settings": "×○○○", "app.quit": "○○○○",
        "session.open_folder": "××○○", "session.rebuild_summary": "×○××", "session.pause": "××○×", "session.play": "××○×",
        "request.trigger": "××○×", 
        "request.capture": "××○×", "window.main": "×○○○", "window.frame": "×○○×",
        "help.first_run_notice": "○○○○", "help.permissions": "×○○○",
    }

    def test_table_matches_spec(self):
        states = (State.FIRST_RUN, State.BEFORE_SESSION, State.IN_SESSION, State.ENDING)
        for item, row in self.TABLE.items():
            for st, ch in zip(states, row):
                self.assertEqual(A.is_active(item, st), ch == "○", "%s %s" % (item, st))

    def test_every_item_covered_and_no_new_session(self):
        self.assertEqual(set(A.item_ids()), set(self.TABLE))   # 결정 0153: 편집 항목이 없다
        self.assertFalse(any("new" in i for i in A.item_ids()))   # AC-FR14-1: 새 세션 항목이 없다

    def test_done_everything_inactive(self):
        self.assertFalse(any(A.is_active(i, State.DONE) for i in A.item_ids()))

    def test_unknown_item(self):
        with self.assertRaises(KeyError):
            A.is_active("nope", State.IN_SESSION)

    def test_close_window_rule(self):
        self.assertTrue(A.close_window_quits(State.FIRST_RUN))
        self.assertTrue(A.close_window_quits(State.BEFORE_SESSION))
        self.assertFalse(A.close_window_quits(State.IN_SESSION))
        self.assertFalse(A.close_window_quits(State.ENDING))


class Appearance(unittest.TestCase):
    def test_choices_and_default(self):  # AC-FR15-1
        self.assertEqual([l for _, l in A.APPEARANCE_CHOICES], ["시스템 설정 따르기", "밝은 화면", "어두운 화면"])
        self.assertEqual(A.normalize_appearance(None), "system")
        self.assertEqual(A.normalize_appearance("무슨값"), "system")

    def test_follow_system_switches_live(self):  # AC-FR15-3
        self.assertEqual(A.resolve_scheme("system", "light"), "light")
        self.assertEqual(A.resolve_scheme("system", "dark"), "dark")
        self.assertEqual(A.resolve_scheme("system", "light"), "light")
        self.assertEqual(A.resolve_scheme("system", None), "light")

    def test_fixed_choices_ignore_system(self):
        for sys_ in ("light", "dark", None):
            self.assertEqual(A.resolve_scheme("light", sys_), "light")
            self.assertEqual(A.resolve_scheme("dark", sys_), "dark")


class Status(unittest.TestCase):
    def test_model_label(self):  # AC-FR1-1
        self.assertEqual(A.model_label("sonnet", "medium"), "Sonnet · medium")
        self.assertEqual(A.model_label("opus", "xhigh"), "Opus · xhigh")
        self.assertEqual(A.model_label("haiku", None), "Haiku")

    def test_text_stable_for_same_inputs(self):  # AC-FR1-3
        s = A.StatusInputs("claude_subscription", "sonnet", "medium", source="시스템 마이크", capture_state="수집 중")
        self.assertEqual(A.status_text(s), A.status_text(s))
        self.assertIn("Sonnet · medium", A.status_text(s))
        self.assertIn("Claude 구독", A.status_text(s))

    def test_optional_items_and_latency(self):
        base = A.StatusInputs("claude_api", "sonnet", "high", materials=2, captures=1)
        # 결정 0068 3항: 전사 오류 · 요청 대기는 0 이어도 늘 표시한다. 처리 대기 · 활동은 있을 때만이다
        self.assertEqual([k for k, _ in A.status_items(base)], ["provider", "model", "materials", "captures", "stt_errors", "queue"])
        self.assertEqual(dict(A.status_items(base))["stt_errors"], "전사 오류 0회")
        self.assertEqual(dict(A.status_items(base))["queue"], "요청 대기열 0")
        s = A.StatusInputs("claude_api", "sonnet", "high", stt_errors=1, queue_waiting=2,
                           activity="요청 진행 중", stt_prep="음성 인식 모델을 준비하는 중이다 (41%)")
        d = dict(A.status_items(s))
        self.assertEqual(d["stt_errors"], "전사 오류 1회")
        self.assertNotIn("pending", d)                        # 결정 0167 3항: 전사 처리 대기 항목은 없다
        self.assertEqual(d["stt_prep"], "음성 인식 모델을 준비하는 중이다 (41%)")
        keys = [k for k, _ in A.status_items(s)]
        self.assertLess(keys.index("stt_prep"), keys.index("activity"))       # 준비 칩이 요청 진행 중보다 먼저이다
        self.assertEqual(d["queue"], "요청 대기열 2")


class Persistence(unittest.TestCase):
    def test_ack_and_appearance_round_trip(self):  # B-18 · AC-FR15-1(기억) · AC-NF-1
        import tempfile
        from nsu_kangs_rab.core import settings
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            r = settings.load_settings(path)
            self.assertFalse(r.file_found)
            self.assertTrue(A.first_run_required(r.data))        # 설정 파일이 없는 첫 실행
            ok, _ = settings.update_settings(path, {"first_run_ack": A.FIRST_RUN_NOTICE_VERSION, "appearance": "dark"})
            self.assertTrue(ok)
            r2 = settings.load_settings(path)
            self.assertFalse(A.first_run_required(r2.data))
            self.assertEqual(A.normalize_appearance(r2.data.get("appearance")), "dark")
            ok, _ = settings.update_settings(path, {"first_run_ack": A.FIRST_RUN_NOTICE_VERSION - 1})
            self.assertTrue(A.first_run_required(settings.load_settings(path).data))   # 판 번호가 다르면 다시 표시한다

    def test_unknown_settings_value_is_default_appearance(self):
        self.assertEqual(A.normalize_appearance("sepia"), "system")
        self.assertEqual(A.normalize_appearance(None), "system")


class LevelCellsTest(unittest.TestCase):  # AC-FR3-10
    def test_mapping(self):
        f = A.level_to_cells
        self.assertEqual([f(v, True) for v in (-120.0, -80.0, -60.0, -59.9, -50.0, -49.9, -10.0, -0.1, 0.0)],
                         [0, 0, 0, 1, 1, 2, 5, 6, 6])
        self.assertEqual(f(-5.0, False), 0)           # 수집 중이 아니면 0
        self.assertEqual(f(None, True), 0)


if __name__ == "__main__":
    unittest.main()
