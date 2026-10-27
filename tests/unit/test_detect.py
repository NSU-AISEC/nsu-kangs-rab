"""detect.py 단위 시험. 실행: python3 -m unittest discover -s tests/unit

사례는 docs/plan/question-detection.md 5절 · 3-8절 · 7-1절에서 어구를 옮긴 것이다 (전사본 원문을 싣지 않는다).
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "mac"))

from nsu_kangs_rab.detect import QuestionGate, is_question  # noqa: E402

Q = [
    "개인 정보는 정말 없어지는 걸까요?",
    "벡터 데이터베이스에는 무엇이 남나요?",
    "임베딩 정보를 어떻게 지울 수 있습니까?",
    "이 모델은 어떤 데이터로 학습했을까?",
    "그 다음에 무슨 일이 생길까요?",
    "가명 처리는 언제 하는 겁니까?",
    "왜 이런 결과가 나왔을까요?",
]


class TestIsQuestionTrue(unittest.TestCase):
    CASES = [
        # (본문, 규칙)
        ("인공지능을 학습시키기 위해서 뭘 씁니까?", "S1 (5절 140행)"),
        ("개인 정보는 정말 없어지는 걸까요?", "S1 (155행)"),
        ("그 다음 뭐에 남을까?", "S1 (272행)"),
        ("뭉개도 개인 정보가 될 때가 뭐죠?", "S1 · 의문사 있는 E1 어구 (350행)"),
        ("이때 무슨 이슈가 생겼을까.", "S3 (1121행)"),
        ("어떤 걸 저장해야 되냐.", "S3 (1046행)"),
        ("앞에서 가명 처리 했습니까? 이렇게 질문하면 안 돼요. 그러면 어떻게 질문한 게 좋겠어요.", "S4 (2087행)"),
        ("어떻게 질문하면 좋을까요", "S2 물음표 없음 (1031행)"),
        ("무엇을 해야 합니까", "S2 -ㅂ니까"),
        ("저장된 건 무엇인지 알 수 있나요?", "A11: E10 은 문장 끝이 S1 이면 적용하지 않는다"),
        ("왜 그래요?", "A7: 의문사 있으면 3자 이상"),
        ("그렇게 하면 되지?", "A9: -지? 는 제외하지 않는다"),
        ("이게 정말 가능한가요", "S2 -ㄴ가요"),
        ("그건 아닙니까.", "S2: 거 아닙니까 형이 아니면 E5 가 아니다"),
        ("이거 안 되지 않나요?", "A8: 않나요 는 E5 에서 뺀다"),
        ("무엇이 문제입니까?", "S1"),
        ("What is the problem here?", "영문 S1"),
        ("앞 문장은 설명입니다. 그러면 뭘 할까요?", "다문장 중 하나라도 질문"),
        ("그 개념이 뭐냐하면 이거예요?", "A11: 문장 끝이 S1 이면 E10 미적용"),
        ("개인정보가 어떻게 보이죠?", "A5: E2 어구가 끝이어도 앞부분이 8자 이상이면 제외하지 않는다"),
        ("질문하면 안 되나요?", "트리거 문장 자체가 S2 이면 후보로 남는다 (A10)"),
    ]

    def test_cases(self):
        for text, why in self.CASES:
            with self.subTest(text=text, why=why):
                self.assertTrue(is_question(text))


class TestIsQuestionFalse(unittest.TestCase):
    CASES = [
        ("그렇죠. 예?", "E1 (245행)"),
        ("그치? 정수 처리까지 갈 거 아니야?", "E1 · E5 (269행)"),
        ("또라이 교수가 돼야 되는 거 아니야?", "E5 (599행)"),
        ("화면이 안 보이죠?", "E2 (2363행)"),
        ("잘 들리세요?", "E2 변이형 (A5)"),
        ("질문 있나요?", "E2 변이형 (A5)"),
        ("질문 있나요.", "A8 개정: E2 는 물음표 없이도 적용"),
        ("그럴 거 아닙니까.", "A8 개정: E5 는 물음표 없이도 적용"),
        ("정말 그치", "E1 · 신호 없음"),
        ("어 어디 갔지?", "E6 (c) (2603행)"),
        ("이거예요?", "E4 (2612행)"),
        ("아니요?", "E4 (2108행)"),
        ("법원의 저작권이 없을까.", "물음표도 의문사도 없는 -을까 (128행)"),
        ("내려가지 않을까.", "혼잣말 (476행)"),
        ("내려가지 않을까?", "E6 (a): 의문사 없는 ? 문장 끝이 까"),
        ("앞에서 가명 처리 했습니까? 이렇게 질문하면 안되요.", "E7 (2072행)"),
        ("앞에서 가명 처리 했습니까라고 물어보면 안 됩니다.", "E7 문장 안의 -까라고"),
        ("비식별화했다구요?", "E3 (2099행)"),
        ("불법이라고?", "E3 (1139행)"),
        ("무엇이요?", "A6: E3"),
        ("어디에 남을까 개인 정보가 ai 에 들어가면.", "3-5 재현율 손실 (254행)"),
        ("뭐 이런 게 있었어.", "S5 꺼짐 (1898행)"),
        ("그 개념이 뭐냐하면 이런 거예요.", "E10 (335행)"),
        ("이건 중요한 질문이에요?", "E8"),
        ("", "빈 문자열"),
        ("   ", "공백"),
        ("???", "글자 없음"),
        ("😀😀", "이모지"),
        ("뭐?", "A7: 의문사 문장도 3자 미만 제외"),
        ("그건 이해했어요?", "E1: 문장 끝 어구는 길이 무관 (A4)"),
        ("오늘은 날씨가 좋습니다.", "평서문"),
    ]

    def test_cases(self):
        for text, why in self.CASES:
            with self.subTest(text=text, why=why):
                self.assertFalse(is_question(text))

    def test_non_str_does_not_raise(self):
        for bad in (None, 3, b"abc", ["?"]):
            with self.subTest(bad=bad):
                self.assertFalse(is_question(bad))


class TestSplitting(unittest.TestCase):
    def test_decimal_is_not_boundary(self):
        # 3.5 에서 문장이 나뉘지 않는다: 질문 신호가 없으므로 False
        self.assertFalse(is_question("버전 3.5 에서 바뀌었습니다."))

    def test_fullwidth_question_mark(self):
        self.assertTrue(is_question("이게 무엇입니까？"))

    def test_trailing_quote(self):
        self.assertTrue(is_question('그가 "그게 무엇입니까?"'))

    def test_question_in_middle_sentence(self):
        self.assertTrue(is_question("설명을 하겠습니다. 이게 뭘까요? 다음으로 갑니다."))


class TestRobustness(unittest.TestCase):
    def test_deterministic(self):
        for text in Q + ["그치?", "질문 있나요?"]:
            first = is_question(text)
            for _ in range(100):
                self.assertEqual(is_question(text), first)

    def test_long_inputs_fast(self):
        inputs = {
            "no_punct": "가" * 10000,
            "spaces": " " * 10000,
            "wh_repeat": "뭐 " * 5000,
            "questions": "이게 뭘까요? " * 1000,
            "dots": "." * 10000,
            "ji": "한지 " * 3300,
            "mixed": ("안 보이죠 " * 1000) + "?",
            "emoji": "😀" * 10000,
            "english": "What is this? " * 800,
        }
        for name, text in inputs.items():
            with self.subTest(name=name):
                t0 = time.perf_counter()
                is_question(text)
                self.assertLess(time.perf_counter() - t0, 0.1)


class TestGate(unittest.TestCase):
    """명세 7-1절 G1 ~ G8 과 경계."""

    def run_seq(self, seq, **kw):
        g = QuestionGate(**kw)
        return [g.should_reply(t, text) for t, text in seq]

    def test_g1(self):
        self.assertEqual(self.run_seq([(0, Q[0])]), [True])

    def test_g2_nonquestion_keeps_state(self):
        self.assertEqual(self.run_seq([(0, "오늘은 날씨가 좋습니다."), (1, Q[0])]), [False, True])

    def test_g3(self):
        self.assertEqual(self.run_seq([(0, Q[0]), (30, Q[1])]), [True, False])

    def test_g4_boundary(self):
        self.assertEqual(self.run_seq([(0, Q[0]), (59.9, Q[1]), (60, Q[1])]), [True, False, True])

    def test_g5_cooldown_not_extended(self):
        self.assertEqual(
            self.run_seq([(0, Q[0]), (20, Q[1]), (40, Q[2]), (60, Q[3])]),
            [True, False, False, True],
        )

    def test_g6_dedup(self):
        self.assertEqual(self.run_seq([(0, Q[0]), (100, Q[0])]), [True, False])

    def test_g7_window_cap(self):
        qs = [
            "첫째 질문은 무엇입니까?", "둘째 질문은 어디입니까?", "셋째 질문은 언제입니까?",
            "넷째 질문은 누구입니까?", "다섯째 질문은 왜입니까?", "여섯째 질문은 몇 개입니까?",
            "일곱째 질문은 어느 것입니까?", "여덟째 질문은 얼마입니까?",
        ]
        g = QuestionGate()
        out = [g.should_reply(60 * i, qs[i]) for i in range(6)]
        self.assertEqual(out, [True] * 6)
        self.assertFalse(g.should_reply(360, qs[6]))
        self.assertTrue(g.should_reply(601, qs[7]))

    def test_g8_clock_backward_resets(self):
        self.assertEqual(self.run_seq([(500, Q[0]), (10, Q[1])]), [True, True])

    def test_same_t_is_not_backward(self):
        # t 가 같으면 역행이 아니므로 쿨다운이 그대로 적용된다
        self.assertEqual(self.run_seq([(5, Q[0]), (5, Q[1])]), [True, False])

    def test_nonquestion_t_not_used_for_backward(self):
        g = QuestionGate()
        self.assertTrue(g.should_reply(100, Q[0]))
        self.assertFalse(g.should_reply(1, "오늘은 날씨가 좋습니다."))
        self.assertFalse(g.should_reply(110, Q[1]))  # 초기화되지 않았으므로 쿨다운 중

    def test_dedup_compares_all_answered_in_window(self):
        # (0,Q0) (61,Q1) (122,Q0): 직전 응답이 아니어도 창(200초) 안에 응답한 Q0 와 같으면 억제
        self.assertEqual(self.run_seq([(0, Q[0]), (61, Q[1]), (122, Q[0])], dedup=200.0), [True, True, False])

    def test_g9_filtered_candidate_not_recorded(self):
        self.assertEqual(self.run_seq([(0, Q[0]), (30, Q[1]), (100, Q[1])]), [True, False, True])

    def test_dedup_window_boundary(self):
        self.assertEqual(self.run_seq([(0, Q[0]), (120, Q[0])]), [True, False])   # <= dedup
        self.assertEqual(self.run_seq([(0, Q[0]), (120.1, Q[0])]), [True, True])  # 초과

    def test_dedup_not_extended_by_filtered(self):
        # 걸러진 후보는 기록하지 않으므로 억제가 연장되지 않는다 (B2): 200 은 응답 0 에서 120 초 초과
        self.assertEqual(self.run_seq([(0, Q[0]), (100, Q[0]), (200, Q[0])]), [True, False, True])

    def test_dedup_containment_and_normalization(self):
        a = "개인 정보는 정말 없어지는 걸까요?"
        b = "음 그러니까 개인정보는, 정말 없어지는 걸까요?!"
        self.assertEqual(self.run_seq([(0, a), (100, b)]), [True, False])

    def test_dedup_short_text_not_contained(self):
        # 정규화 8자 미만이면 포함 검사를 하지 않는다 (같을 때만 억제)
        short = "왜 그래요?"
        longer = "왜 그래요? 설명해 주세요?"
        self.assertEqual(self.run_seq([(0, short), (100, longer)]), [True, True])

    def test_custom_parameters(self):
        out = self.run_seq([(0, Q[0]), (10, Q[1])], cooldown=10.0)
        self.assertEqual(out, [True, True])
        out = self.run_seq([(0, Q[0]), (200, Q[0])], dedup=50.0)
        self.assertEqual(out, [True, True])
        out = self.run_seq([(0, Q[0]), (1, Q[1]), (2, Q[2])], cooldown=0.0, max_in_window=2)
        self.assertEqual(out, [True, True, False])

    def test_instances_independent(self):
        a, b = QuestionGate(), QuestionGate()
        self.assertTrue(a.should_reply(0, Q[0]))
        self.assertTrue(b.should_reply(1, Q[1]))

    def test_invalid_args(self):
        for kw in (dict(cooldown=-1), dict(window=0), dict(dedup=-1), dict(max_in_window=0),
                   dict(cooldown=float("nan"))):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    QuestionGate(**kw)
        with self.assertRaises(TypeError):
            QuestionGate(60.0)  # 키워드 전용

    def test_invalid_t(self):
        g = QuestionGate()
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(t=bad):
                with self.assertRaises(ValueError):
                    g.should_reply(bad, Q[0])

    def test_negative_t_allowed(self):
        self.assertEqual(self.run_seq([(-10, Q[0]), (-5, Q[1])]), [True, False])

    def test_memory_pruned(self):
        g = QuestionGate()
        for i in range(2000):
            g.should_reply(float(i * 1000), "질문 번호 %d 는 무엇입니까?" % i)
        self.assertLessEqual(len(g._cands), 1)
        self.assertLessEqual(len(g._trues), 6)


if __name__ == "__main__":
    unittest.main()
