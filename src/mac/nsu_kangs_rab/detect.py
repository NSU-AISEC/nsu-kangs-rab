"""질문 감지와 자동 응답 억제 (규칙 기반, 표준 라이브러리만 사용).

명세: docs/plan/question-detection.md (3-8절 확정이 표와 어긋나면 우선한다).
플랫폼에 의존하지 않는 코드이다 (화면 · 음성 · 모델 모듈을 가져오지 않는다).

진입점:
    is_question(text: str) -> bool
    QuestionGate(*, cooldown=60.0, window=600.0, max_in_window=6, dedup=120.0).should_reply(t, text) -> bool
"""
import math
import re
import unicodedata
from collections import deque

__all__ = ["is_question", "QuestionGate"]

# ---------------------------------------------------------------- 문자 보조

_ALNUM = re.compile(r"[가-힣A-Za-z0-9]")
_SENT_END = re.compile(r"[.!?…？]+[\"'”’)\]」』]*(?=\s|$)")
_TRAIL = re.compile(r"[\s.!?…？\"'”’)\]」』]+$")
_LEAD = "\"'“‘([「『"


def _jong(ch):
    """한글 음절의 받침 번호(0 은 받침 없음). 한글 음절이 아니면 -1."""
    o = ord(ch) - 0xAC00
    if 0 <= o < 11172:
        return o % 28
    return -1


_JONG_N, _JONG_L, _JONG_B = 4, 8, 17  # ㄴ · ㄹ · ㅂ

# ---------------------------------------------------------------- 어휘 · 규칙

_WH = (
    "뭐", "뭘", "뭔", "무엇", "무슨", "어떤", "어떻게", "어떡", "어디", "어딜", "어디서",
    "언제", "누가", "누구", "왜", "얼마", "몇", "어느", "어째",
)

_E1_ENDS = ("그치", "그지", "그렇지", "그렇죠", "맞지", "맞죠", "맞아", "아니야",
            "이해했죠", "이해했어요", "알겠죠", "됐죠")
_E1_ALONE = frozenset(("응", "예", "어", "네", "그래서"))

_E2_END = re.compile(
    r"(?:안 ?보이죠|보이죠|들리죠|계시죠|질문 ?있(?:나요|습니까|으세요|어요|으신가요)"
    r"|궁금한 ?거 ?있어요|이해했어요|괜찮아|들리(?:세요|나요)|보이(?:세요|나요))$"
)
_E3_ENDS = ("다고", "라고", "구요", "이요", "냐고")
_E5_END = re.compile(r"(거|것|게) ?아(?:니야|니에요|닙니까|닌가|니냐|니니)$")
_E6_C = re.compile(r"(?:어디 ?갔지|어딨지|뭐였지)$")
_E7_TRIGGER = re.compile(
    r"라고 ?(?:질문|물어|이야기|얘기)|이렇게 ?질문|질문하면 ?안|질문하지 ?말고|라는 ?질문"
)
_E8_END = re.compile(
    r"질문 ?(?:이에요|이야|이죠|입니다|이다|이네요|이었어요)$"
    r"|질문 ?(?:할|하고 ?싶은) ?(?:게|거|것) ?(?:많|있)[가-힣]*$"
)
_E10_MID = re.compile(r"냐 ?하면|냐면|는가에|는지 ?모른")
_S4_END = re.compile(r"게 ?좋(?:겠어요|을까요|습니까)$")


def _has_wh(sentence):
    for tok in sentence.split(" "):
        tok = tok.lstrip(_LEAD)
        if tok and tok.startswith(_WH):
            return True
    return False


def _jong_before(core, idx, want):
    """core[idx] 바로 앞 글자의 받침이 want 중 하나인가."""
    return idx >= 1 and _jong(core[idx - 1]) in want


def _ends_s2(core):
    if core.endswith("습니까"):
        return True
    if core.endswith("니까") and _jong_before(core, len(core) - 2, (_JONG_B,)):
        return True
    if core.endswith("까요") and _jong_before(core, len(core) - 2, (_JONG_L,)):
        return True
    if core.endswith("나요"):
        return True
    if core.endswith("가요") and _jong_before(core, len(core) - 2, (_JONG_N,)):
        return True
    return False


def _ends_s3(core):
    if core.endswith("냐"):
        return True
    return core.endswith("까") and _jong_before(core, len(core) - 1, (_JONG_L,))


def _has_e10_clause(sentence):
    if _E10_MID.search(sentence):
        return True
    start = 0
    while True:  # -ㄴ지 : 받침 ㄴ 으로 끝나는 음절 + 지
        i = sentence.find("지", start)
        if i < 0:
            return False
        if i >= 1 and _jong(sentence[i - 1]) == _JONG_N:
            return True
        start = i + 1


def _e5(core):
    m = _E5_END.search(core)
    if not m:
        return False
    i = m.start()
    # 거/것/게 앞의 관형 어미: 앞 글자(공백 제외)의 받침이 ㄴ 또는 ㄹ
    j = i - 1
    while j >= 0 and core[j] == " ":
        j -= 1
    return j >= 0 and _jong(core[j]) in (_JONG_N, _JONG_L)


def _e2(core):
    m = _E2_END.search(core)
    if not m:
        return False
    return len(_ALNUM.findall(core[: m.start()])) < 8


def _sentence_is_question(s, e7_quoted):
    """문장 하나가 질문 문장인가. e7_quoted 는 E7 로 인용 처리된 문장 여부."""
    if e7_quoted:
        return False
    core = _TRAIL.sub("", s)
    if not core:
        return False
    n_alnum = len(_ALNUM.findall(core))
    if n_alnum == 0:
        return False
    has_q = s.rstrip(" \"'”’)]」』").endswith(("?", "？"))
    wh = _has_wh(core)

    # 질문 신호
    s2 = _ends_s2(core)
    s3 = (not has_q) and wh and _ends_s3(core)
    s4 = (not has_q) and wh and bool(_S4_END.search(core))
    if not (has_q or s2 or s3 or s4):
        return False

    # 제외 규칙
    if n_alnum < (3 if wh else 5):  # E4
        return False
    # E1 · E2 · E3 · E5 는 물음표 유무와 관계없이 적용하고 S1 ~ S4 보다 우선한다 (명세 A8)
    if not wh and (core in _E1_ALONE or core.endswith(_E1_ENDS)):  # E1
        return False
    if _e2(core):  # E2
        return False
    if core.endswith(_E3_ENDS):  # E3
        return False
    if _e5(core):  # E5
        return False
    if has_q and not wh and core.endswith("까"):  # E6 (a): ? 가 있는 문장만
        return False
    if _E6_C.search(core):  # E6 (c)
        return False
    if _E8_END.search(core):  # E8
        return False
    if not (has_q or s2) and _has_e10_clause(core):  # E10 (문장 끝이 S1 · S2 이면 적용하지 않는다)
        return False
    return True


def _split_sentences(text):
    out, pos = [], 0
    for m in _SENT_END.finditer(text):
        piece = text[pos:m.end()].strip()
        if piece:
            out.append(piece)
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        out.append(tail)
    return out


def is_question(text):
    """전사 세그먼트 한 줄의 본문이 질문이면 True. 예외를 던지지 않는다."""
    try:
        if not isinstance(text, str):
            return False
        text = " ".join(text.split())
        if not text or not _ALNUM.search(text):
            return False
        sents = _split_sentences(text)
        quoted = [False] * len(sents)
        for j, s in enumerate(sents):
            if "까라고" in s:  # E7: 문장 안의 인용
                quoted[j] = True
            if j > 0 and _E7_TRIGGER.search(s):  # E7: 트리거 바로 앞 문장
                quoted[j - 1] = True
        return any(_sentence_is_question(s, quoted[j]) for j, s in enumerate(sents))
    except Exception:  # 명세: is_question 은 예외를 던지지 않는다
        return False


# ---------------------------------------------------------------- 억제

def _normalize(text):
    return "".join(
        ch for ch in text.lower() if unicodedata.category(ch)[0] not in ("P", "S", "Z")
    )


class QuestionGate:
    """자동 응답 억제: 중복 → 쿨다운 → 창 상한 (명세 4절)."""

    def __init__(self, *, cooldown=60.0, window=600.0, max_in_window=6, dedup=120.0):
        if not cooldown >= 0:
            raise ValueError("cooldown 은 0 이상이어야 한다")
        if not window > 0:
            raise ValueError("window 는 0 보다 커야 한다")
        if not dedup >= 0:
            raise ValueError("dedup 은 0 이상이어야 한다")
        if not max_in_window >= 1:
            raise ValueError("max_in_window 는 1 이상이어야 한다")
        self.cooldown = cooldown
        self.window = window
        self.max_in_window = max_in_window
        self.dedup = dedup
        self._reset()

    def _reset(self):
        self._last_t = None      # 직전 질문 후보의 시각 (시계 역행 판정용)
        self._last_true = None   # 마지막으로 True 를 반환한 시각
        self._cands = deque()    # (시각, 정규화 본문) — 응답한(True 반환) 질문만 기록한다
        self._trues = deque()    # True 를 반환한 시각

    def should_reply(self, t, text):
        if not math.isfinite(t):  # NaN · 무한대. 숫자가 아니면 TypeError
            raise ValueError("t 는 유한한 수여야 한다")
        if not is_question(text):
            return False
        if self._last_t is not None and t < self._last_t:  # 시계 역행: 새로 시작
            self._reset()
        self._last_t = t

        while self._cands and t - self._cands[0][0] > self.dedup:
            self._cands.popleft()
        while self._trues and self._trues[0] <= t - self.window:
            self._trues.popleft()

        norm = _normalize(text)
        dup = False
        for _, c in self._cands:
            short, long_ = (norm, c) if len(norm) <= len(c) else (c, norm)
            if norm == c or (len(short) >= 8 and short in long_):
                dup = True
                break
        if dup:
            return False
        if self._last_true is not None and t - self._last_true < self.cooldown:
            return False
        if len(self._trues) >= self.max_in_window:
            return False
        self._last_true = t
        self._trues.append(t)
        self._cands.append((t, norm))  # 걸러진 후보는 기록하지 않는다 (명세 B1 · B2)
        return True
