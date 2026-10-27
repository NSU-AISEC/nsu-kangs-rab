#!/usr/bin/env python3
"""K-03 단위 시험용 가짜 `claude`. 실제 모델 · 네트워크를 쓰지 않는다.
동작 지정은 감싼 스크립트가 앞에 붙인 `--fake-*` 인자로 한다(앱이 만든 환경은 허용 목록이라 환경 변수가 전달되지 않는다).
  --fake-log FILE       시작 때와 메시지마다 JSON 한 줄을 덧붙인다 (argv · 환경 이름 · 프롬프트 파일 · 받은 메시지)
  --fake-mode MODE      normal | exit_now | hang | ignore_stdin | rate_limit | fail_first
  --fake-source S       init.apiKeySource (기본: 환경에 ANTHROPIC_API_KEY 가 있으면 그 이름, 없으면 none)
  --fake-stderr TEXT    exit_now 에서 표준 오류에 쓸 문구 (`@KEY@` 는 환경의 ANTHROPIC_API_KEY 값)
  --fake-error-text T   rate_limit · fail_first 의 오류 결과 문구
  --fake-fail-n N       fail_first 에서 처음 N 개 요청을 실패시킨다
  --fake-no-local-result 1  `/` 로 시작하는 지역 명령에 Result 를 내지 않는다 (X8)
  --fake-no-ack 1       control_request(interrupt)에 control_response 도 결과도 내지 않는다 (K-07 통합 시험)
  --fake-grandchild 1   표준 출력 · 오류를 쥔 채 오래 사는 손자 프로세스를 시작하고 PID 를 기록한다 (D-029)
"""
import hashlib, json, os, sys, time

raw = sys.argv[1:]
fake, args = {}, []
i = 0
while i < len(raw):
    if raw[i].startswith("--fake-"):
        fake[raw[i][7:]] = raw[i + 1]
        i += 2
    else:
        args.append(raw[i])
        i += 1
LOG = fake.get("log")
mode = fake.get("mode", "normal")

def log(obj):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

def opt(name):
    return args[args.index(name) + 1] if name in args else None

def out(o):
    sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n")
    sys.stdout.flush()

pf = opt("--system-prompt-file")
pinfo = None
if pf:
    try:
        data = open(pf, "rb").read()
        pinfo = {"path": pf, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mode": oct(os.stat(pf).st_mode & 0o777)}
    except OSError as e:
        pinfo = {"path": pf, "error": type(e).__name__}
sp = opt("--system-prompt")
log({"kind": "start", "argv": args, "env_names": sorted(os.environ), "prompt_file": pinfo,
     "prompt_arg_len": len(sp) if sp is not None else None, "prompt_arg_sha256": hashlib.sha256(sp.encode()).hexdigest() if sp is not None else None})

if fake.get("grandchild") == "1":
    import subprocess
    gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(25)"], stdin=subprocess.DEVNULL,
                          start_new_session=True)
    log({"kind": "grandchild", "pid": gc.pid})

if mode == "exit_now":
    sys.stderr.write(fake.get("stderr", "Error: failed").replace("@KEY@", os.environ.get("ANTHROPIC_API_KEY", "")) + "\n")
    sys.exit(1)
if mode == "ignore_stdin":
    import signal
    signal.signal(signal.SIGTERM, signal.SIG_IGN) if fake.get("ignore_term") == "1" else None
    time.sleep(60)
    sys.exit(0)

source = fake.get("source") or ("ANTHROPIC_API_KEY" if os.environ.get("ANTHROPIC_API_KEY") else "none")
state = {"inited": False, "n": 0}
fail_n = int(fake.get("fail-n", "1"))

def result_ok(text, turns=1):
    out({"type": "result", "subtype": "success", "is_error": False, "result": text, "terminal_reason": "completed",
         "num_turns": turns,
         "usage": {"input_tokens": 2, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 5}})

def result_err(text):
    out({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": text, "terminal_reason": "error",
         "usage": {"input_tokens": 0, "output_tokens": 0}})

for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if msg.get("type") == "control_request":
        log({"kind": "control", "msg": msg})
        if fake.get("no-ack") == "1":
            continue
        out({"type": "control_response", "response": {"subtype": "success", "request_id": msg.get("request_id"), "response": {"still_queued": []}}})
        out({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "", "terminal_reason": "aborted_streaming", "usage": {}})
        continue
    if msg.get("type") != "user":
        continue
    c = msg["message"]["content"]
    text = c if isinstance(c, str) else "\n".join(b.get("text", "") for b in c if b.get("type") == "text")
    log({"kind": "msg", "text": text, "blocks": [b.get("type") for b in (c if isinstance(c, list) else [])]})
    if not state["inited"]:
        out({"type": "system", "subtype": "init", "model": "claude-sonnet-5-5", "apiKeySource": source, "claude_code_version": "fake", "tools": []})
        state["inited"] = True
    if text.startswith("/"):
        if fake.get("no-local-result") != "1":
            result_ok("(command)", 0)
        continue
    state["n"] += 1
    if mode == "hang":
        continue
    if mode == "rate_limit" or (mode == "fail_first" and state["n"] <= fail_n):
        result_err(fake.get("error-text", "Claude usage limit reached"))
        continue
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}}})
    result_ok("ok")
