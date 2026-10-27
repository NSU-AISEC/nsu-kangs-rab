#!/usr/bin/env python3
"""가짜 `stt_speech` 보조 프로세스 (기술 계획 2-8-4절 1항). 실제 macOS 엔진에는 접속하지 않는다.

`stt_speech` 와 같은 인자(`--locale <로캘> --start-n <n>` · `--list-locales`)와 같은 stdin 프레임 · stdout 줄 형식(2-8-2절)을 쓴다.
`--scenario <JSON 파일>` 이 있으면 그 시나리오를 수행한다(없으면 `ready` 만 내고 `Q` 에서 끝난다).

시나리오(JSON 객체):
- `"starts"`: 배열의 배열. k 번째 시작(세션용)은 `starts[k-1]` 을 수행하고, 시작 횟수가 배열 길이를 넘으면 마지막 것을 되풀이한다.
  `final` 줄의 `n` 은 `emit` 으로 내든 `on_cut` 으로 내든 가짜가 한 시작 안에서 `--start-n` 부터 하나의 계수로 매긴다(시나리오에 적은 `n` 은 무시한다, 권고 57).
  단계 하나는 시각 필드 하나 — `{"at_s": x}`(프로세스 시작 기점) · `{"after_first_a_s": x}`(첫 `A` 를 받은 때) ·
  `{"after_cut": {"n": i, "s": x}}`(i 번째 `C` 를 받은 때) — 와 `emit`(stdout 줄) 또는 `exit_code`(종료)를 가진다.
  `emit` 의 `start_mono` · `end_mono` 는 숫자이거나 `{"rel": "first_a"|"last_a", "s": x}`(그 시점에 받은 첫 또는 마지막 `A` 의 `t_mono` + x 초).
- `"on_cut"`: 배열. i 번째 `C` 에 i 번째 항목이 대응하고 개수를 넘으면 마지막 항목을 되풀이한다. 항목은
  `{"final_after_s": x, "text": …, "start_mono": …, "end_mono": …}`(지연 뒤 `final`, `n` 은 가짜가 `--start-n` 부터 매긴다) ·
  `null`(아무 일도 없음) · `{"exit_after_s": x, "exit_code": n}`(지연 뒤 종료). `"on_cut"` 이 없으면 모든 `C` 에 아무 일도 없다.
- `"list_locales"`: `{"list": [...], "line_after_s": a, "delay_s": b, "exit_code": n}` — `--list-locales` 실행의 응답. `a` 초 뒤에 `locales` 줄을
  내고(기본 0, 줄을 내기 전의 지연: 앱의 5초 시간 제한을 시험한다 — Q-49 ②) 그 뒤 `b` 초(기본 0)가 지나 종료한다. `exit_code` 가 0 이 아니면
  줄 없이 `a` 초 뒤 그 코드로 끝난다. 없으면 시나리오의 `starts[0]` 의 `locales` 줄과 무관하게 빈 목록이 아닌 기본 목록을 낸다.

기록(`<시나리오 파일>.rec.jsonl`, `.count`, `.list_count`) — **시험이 지워야 하는 파일이다**:
- 이 파일들은 가짜 프로세스가 여러 번 실행되는 동안 **이어진다**(덧붙인다). 시험은 시작 전에 지운다(`reset_files`). 그러지 않으면 이전 시험의 시작 횟수가
  남아 `starts[k-1]` 의 선택이 어긋난다(권고 55).
- `.count`: 세션용 시작 횟수. `--list-locales` 실행은 넣지 않고 `.list_count` 에 따로 센다 (Q-49 ①).
- `.rec.jsonl`: 줄마다 받은 즉시 쓰고 `os.write` 로 낸다(버퍼 없음). SIGTERM · SIGKILL 로 끝나도 그때까지의 줄이 남는다.
  `{"start": k, "args": [...]}`(시작), `{"start": k, "frame": "C"|"Q", "i": 번호, "at": 단조 시각}`, `{"start": k, "a": {"count": n, "first": t, "last": t}}`
  (`A` 의 누계 — 첫 `A` 를 받을 때, `C` · `Q` 를 받을 때, 종료 직전에 쓴다. 한 시작의 마지막 `a` 줄이 결과이다. `summarize_rec` 가 묶는다),
  `{"start": k, "event": "exit", "code": n}`.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import threading
import time

DEFAULT_LOCALES = ["de_DE", "en_US", "es_ES", "fr_FR", "it_IT", "ja_JP", "ko_KR", "pt_BR", "zh_CN"]
_OUT_LOCK = threading.Lock()


def reset_files(scenario_path: str) -> None:
    """시험이 시작 전에 부른다: 이어지는 기록 파일을 지운다."""
    for suffix in (".rec.jsonl", ".count", ".list_count"):
        try:
            os.remove(scenario_path + suffix)
        except OSError:
            pass


def summarize_rec(path: str) -> dict:
    """`.rec.jsonl` 을 시작별로 묶는다: {k: {"args": [...], "C": [시각...], "Q": [시각...], "a": {...}, "exit": code}}."""
    out: dict = {}
    try:
        f = open(path, encoding="utf-8")
    except OSError:
        return out
    with f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            e = out.setdefault(d["start"], {"args": None, "C": [], "Q": [], "a": None, "exit": None})
            if "args" in d:
                e["args"] = d["args"]
            elif d.get("frame") == "C":
                e["C"].append(d["at"])
            elif d.get("frame") == "Q":
                e["Q"].append(d["at"])
            elif "a" in d:
                e["a"] = d["a"]
            elif d.get("event") == "exit":
                e["exit"] = d["code"]
    return out


def _emit(d: dict) -> None:
    with _OUT_LOCK:
        os.write(1, (json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))


class Fake:
    def __init__(self, argv):
        self.argv = argv
        self.t0 = time.monotonic()
        self.scenario = {}
        self.sc_path = None
        self.locale = "ko_KR"
        self.start_n = 1
        self.list_mode = "--list-locales" in argv
        if "--scenario" in argv:
            self.sc_path = argv[argv.index("--scenario") + 1]
            with open(self.sc_path, encoding="utf-8") as f:
                self.scenario = json.load(f)
        if "--locale" in argv:
            self.locale = argv[argv.index("--locale") + 1]
        if "--start-n" in argv:
            self.start_n = int(argv[argv.index("--start-n") + 1])
        self.next_n = self.start_n
        self.k = 0
        self.first_a = self.last_a = None
        self.a_count = 0
        self.cuts = 0
        self._rec_fd = None
        self.lock = threading.Lock()

    # ---- 기록 ----
    def _rec(self, d: dict) -> None:
        if self._rec_fd is None:
            return
        d = dict(d)
        d["start"] = self.k
        os.write(self._rec_fd, (json.dumps(d, ensure_ascii=False) + "\n").encode("utf-8"))

    def _bump(self, suffix: str) -> int:
        path = self.sc_path + suffix
        try:
            n = int(open(path).read().strip() or 0)
        except (OSError, ValueError):
            n = 0
        n += 1
        with open(path, "w") as f:
            f.write(str(n))
        return n

    def _rec_a(self) -> None:
        if self.a_count:
            self._rec({"a": {"count": self.a_count, "first": self.first_a, "last": self.last_a}})

    def _exit(self, code: int) -> None:
        self._rec_a()
        self._rec({"event": "exit", "code": code})
        os._exit(code)

    # ---- 값 ----
    def _val(self, v):
        if isinstance(v, dict) and "rel" in v:
            base = self.first_a if v["rel"] == "first_a" else self.last_a
            return (base if base is not None else 0.0) + float(v["s"])
        return v

    def _emit_line(self, line: dict) -> None:
        d = dict(line)
        if d.get("type") == "final":                     # 권고 57: `n` 은 한 시작 안의 하나의 계수로 가짜가 매긴다(시나리오의 `n` 은 무시한다)
            with self.lock:
                d["n"] = self.next_n
                self.next_n += 1
        for key in ("start_mono", "end_mono"):
            if key in d:
                d[key] = self._val(d[key])
        _emit(d)

    def _later(self, delay: float, fn) -> None:
        if delay <= 0:
            fn()
            return
        t = threading.Timer(delay, fn)
        t.daemon = True
        t.start()

    # ---- 실행 ----
    def run(self) -> None:
        if self.list_mode:
            return self.run_list()
        if self.sc_path:
            self.k = self._bump(".count")
            self._rec_fd = os.open(self.sc_path + ".rec.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            self._rec({"args": self.argv[1:]})
        starts = self.scenario.get("starts")
        steps = []
        if starts:
            steps = starts[min(self.k, len(starts)) - 1] if self.k else starts[0]
        else:
            _emit({"type": "locales", "list": DEFAULT_LOCALES})
            _emit({"type": "asset", "state": "installed", "installed": True})
            _emit({"type": "ready"})
        self.steps_after_a = [s for s in steps if "after_first_a_s" in s]
        self.steps_after_cut = [s for s in steps if "after_cut" in s]
        for s in steps:
            if "at_s" in s:
                self._later(float(s["at_s"]) - (time.monotonic() - self.t0), lambda s=s: self._do(s))
        self.read_frames()
        self._exit(0)

    def _do(self, step: dict) -> None:
        if "emit" in step:
            self._emit_line(step["emit"])
        if "exit_code" in step:
            self._exit(int(step["exit_code"]))

    def run_list(self) -> None:
        if self.sc_path:
            self.k = self._bump(".list_count")
        ll = self.scenario.get("list_locales") or {"list": DEFAULT_LOCALES}
        code = int(ll.get("exit_code", 0))
        a = float(ll.get("line_after_s", 0))
        b = float(ll.get("delay_s", 0))
        time.sleep(a)
        if code != 0:
            os._exit(code)
        _emit({"type": "locales", "list": ll["list"]})
        time.sleep(b)
        os._exit(0)

    def read_frames(self) -> None:
        stdin = sys.stdin.buffer
        while True:
            h = stdin.read(5)
            if len(h) < 5:
                return
            kind, ln = struct.unpack("<BI", h)
            body = stdin.read(ln) if ln else b""
            if len(body) < ln:
                return
            if kind == 0x41 and ln >= 8:
                t = struct.unpack("<d", body[:8])[0]
                with self.lock:
                    first = self.first_a is None
                    if first:
                        self.first_a = t
                    self.last_a = t
                    self.a_count += 1
                if first:
                    self._rec_a()
                    for s in self.steps_after_a:
                        self._later(float(s["after_first_a_s"]), lambda s=s: self._do(s))
            elif kind == 0x43:
                self.cuts += 1
                i = self.cuts
                self._rec_a()
                self._rec({"frame": "C", "i": i, "at": time.monotonic()})
                self.on_cut(i)
            elif kind == 0x51:
                self._rec_a()
                self._rec({"frame": "Q", "i": 1, "at": time.monotonic()})
                return

    def on_cut(self, i: int) -> None:
        for s in self.steps_after_cut:
            ac = s["after_cut"]
            if int(ac["n"]) == i:
                self._later(float(ac["s"]), lambda s=s: self._do(s))
        oc = self.scenario.get("on_cut")
        if not oc:
            return
        item = oc[min(i, len(oc)) - 1]
        if item is None:
            return
        if "exit_after_s" in item:
            self._later(float(item["exit_after_s"]), lambda: self._exit(int(item["exit_code"])))
            return

        def fin():
            self._emit_line({"type": "final", "text": item["text"],
                             "start_mono": item["start_mono"], "end_mono": item["end_mono"]})
        self._later(float(item.get("final_after_s", 0)), fin)


if __name__ == "__main__":
    Fake(sys.argv).run()
