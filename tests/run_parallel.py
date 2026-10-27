"""전체 단위 시험을 TestCase 클래스 단위로 나누어 여러 프로세스로 동시에 실행한다.

사용: `.venv/bin/python tests/run_parallel.py [--jobs 6] [--logdir DIR] [--times FILE] [--serial-module MODULE ...]`
- 시험 목록은 `tests/unit` 의 `unittest discover` 로 얻고(`media/` 포함), `모듈.클래스` 단위로 한 프로세스에서 실행한다.
  각 프로세스는 `QT_QPA_PLATFORM=offscreen` 으로 자기 Qt 를 띄운다.
- 단위마다 걸린 시간을 `--times` 파일(기본 `sessions/test-times.json`, 커밋하지 않는다)에 기록하고, 다음 실행부터 긴 단위부터 배분한다.
  기록이 없으면 시험 수를 길이로 어림한다.
- `--serial-module` 로 지정한 모듈(기본 `test_stt_flow`: 병렬 부하에서 보조 프로세스 준비 대기 8초를 넘겨 간헐적으로 실패했다)은 병렬 실행이 끝난 뒤 한 프로세스로 차례로 실행한다(자원을 함께 쓰는 모듈).
- 출력: 단위별 로그(`<logdir>/<모듈.클래스>.log`)와 합계(`Ran N tests` · `OK`/`FAILED`). 실패한 단위가 있으면 종료 코드는 1 이다.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIT = ROOT / "tests" / "unit"
PY = str(ROOT / ".venv" / "bin" / "python")
ENV = dict(os.environ, QT_QPA_PLATFORM="offscreen")

LIST_SRC = r'''
import json, sys, unittest
from collections import Counter
def walk(s):
    for t in s:
        if isinstance(t, unittest.TestSuite):
            yield from walk(t)
        else:
            yield t
suite = unittest.defaultTestLoader.discover(".", pattern="test_*.py", top_level_dir=".")
c = Counter()
bad = []
for t in walk(suite):
    if t.__class__.__name__ == "_FailedTest":
        bad.append(t.id())
        continue
    c[t.__class__.__module__ + "." + t.__class__.__name__] += 1
print(json.dumps({"units": c, "bad": bad}))
'''


def list_units():
    r = subprocess.run([PY, "-c", LIST_SRC], cwd=UNIT, env=ENV, capture_output=True, text=True)
    line = [x for x in r.stdout.splitlines() if x.startswith("{")]
    if r.returncode != 0 or not line:
        sys.stderr.write(r.stderr[-2000:])
        raise SystemExit("시험 목록을 얻지 못했다")
    d = json.loads(line[-1])
    return d["units"], d["bad"]


def run_unit(name, logdir):
    t0 = time.monotonic()
    log = logdir / (name + ".log")
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.run([PY, "-m", "unittest", "-v", name], cwd=UNIT, env=dict(ENV, PYTHONPATH=os.pathsep.join([str(UNIT), str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))), stdout=f, stderr=subprocess.STDOUT)
    dt = time.monotonic() - t0
    text = log.read_text(encoding="utf-8", errors="replace")
    ran = re.findall(r"^Ran (\d+) tests?", text, re.M)
    skipped = re.findall(r"skipped=(\d+)", text.split("Ran ")[-1]) if ran else []
    return {"name": name, "rc": p.returncode, "ran": int(ran[-1]) if ran else 0, "skipped": int(skipped[-1]) if skipped else 0, "sec": dt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--logdir", default=str(ROOT / "sessions" / "parallel-logs"))
    ap.add_argument("--times", default=str(ROOT / "sessions" / "test-times.json"))
    ap.add_argument("--serial-module", action="append", default=None, help="병렬 실행 뒤 직렬로 실행할 모듈(기본: test_stt_flow, 보조 프로세스 준비 시간 제한 8초가 부하에 민감하다)")
    a = ap.parse_args()
    if a.serial_module is None:
        a.serial_module = ["test_stt_flow"]
    logdir = Path(a.logdir)
    logdir.mkdir(parents=True, exist_ok=True)
    tfile = Path(a.times)
    times = json.loads(tfile.read_text()) if tfile.exists() else {}
    units, bad = list_units()
    expected = sum(units.values())
    print("단위 %d개, 시험 %d건, 가져오기 실패 %d건" % (len(units), expected, len(bad)), flush=True)
    serial = [u for u in units if u.rsplit(".", 1)[0] in a.serial_module]
    par = [u for u in units if u not in serial]
    par.sort(key=lambda u: -times.get(u, units[u] * 1.0))      # 긴 단위부터
    t0 = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        for r in ex.map(lambda u: run_unit(u, logdir), par):
            results.append(r)
            print("%-6s %6.1fs %4d건  %s" % ("OK" if r["rc"] == 0 else "FAIL rc=%d" % r["rc"], r["sec"], r["ran"], r["name"]), flush=True)
    for m in sorted({u.rsplit(".", 1)[0] for u in serial}):      # 직렬 모듈은 모듈 전체를 한 프로세스로 돌린다(클래스 하나만 돌리면 순서에 민감한 시험이 실패한다)
        r = run_unit(m, logdir)
        r["ran_expected"] = sum(n for u, n in units.items() if u.rsplit(".", 1)[0] == m)
        results.append(r)
        print("%-6s %6.1fs %4d건  %s (모듈 직렬)" % ("OK" if r["rc"] == 0 else "FAIL", r["sec"], r["ran"], r["name"]), flush=True)
    wall = time.monotonic() - t0
    times.update({r["name"]: round(r["sec"], 1) for r in results})
    tfile.parent.mkdir(parents=True, exist_ok=True)
    tfile.write_text(json.dumps(times, ensure_ascii=False, indent=0))
    ran = sum(r["ran"] for r in results)
    skipped = sum(r["skipped"] for r in results)
    failed = [r["name"] for r in results if r["rc"] != 0]
    print("Ran %d tests in %.1fs (단위 합 %.1fs)" % (ran, wall, sum(r["sec"] for r in results)))
    ok = not failed and not bad and ran == expected
    print("OK (skipped=%d)" % skipped if ok else "FAILED (실패 단위 %s, 가져오기 실패 %s, 시험 수 %d/%d)" % (failed, bad, ran, expected))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
