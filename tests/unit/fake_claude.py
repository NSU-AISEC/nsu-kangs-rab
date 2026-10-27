#!/usr/bin/env python3
"""가짜 `claude` (시험용). `claude -p --input-format stream-json --output-format stream-json …` 의 이벤트 형식을 흉내 낸다.
실제 모델도 네트워크도 쓰지 않는다. experiments/spike_*.py 의 --run 경로가 호출 수 · 입출력 형식에 맞게 동작하는지 확인하는 데만 쓴다.

환경 변수 FAKE_CLAUDE_LOG: 이 파일에 처리한 사용자 메시지마다 JSON 한 줄을 덧붙인다 ({"kind": "model"|"local", "head": 앞 40자, "nsp": --no-session-persistence 인자 유무}). `--help` 는 도움말 문구를 출력하고 끝낸다.
동작: 사용자 메시지마다 message_start(usage: 앞 요청의 총량을 캐시 읽기로, 이번 글자 수를 캐시 생성으로) → 텍스트 델타 → assistant → result.
      "1부터 400까지" 요청은 숫자를 천천히 흘려 interrupt(control_request)로 멈출 수 있다. "/" 로 시작하는 단독 명령과 [사용자] 뒤의 명령은 모델 호출 없이 result 만 낸다
      (/clear 는 이력 초기화). 판단 표본("[요청] 종류=트리거")에는 "판단: 질문 | …" 첫 줄. 환경 변수 FAKE_CLAUDE_FAIL_OVER 보다 긴 --append-system-prompt 는 오류로 끝난다.
"""
import json, os, select, sys, time

args = sys.argv[1:]
LOG = os.environ.get("FAKE_CLAUDE_LOG")
if "--help" in args:
    print("Usage: claude [options]\n  --system-prompt <prompt>\n  --append-system-prompt <prompt>\n  --effort <level>\n  --tools <tools...>")
    sys.exit(0)

def opt(name):
    return args[args.index(name) + 1] if name in args else None

fail_over = int(os.environ.get("FAKE_CLAUDE_FAIL_OVER", "0") or 0)
for flag in ("--append-system-prompt", "--system-prompt"):
    v = opt(flag)
    if v and fail_over and len(v) > fail_over:
        print("Error: prompt too long", file=sys.stderr)
        sys.exit(1)
model = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}.get(opt("--model"), opt("--model") or "claude-sonnet-5-5")
sysprompt = (opt("--system-prompt") or "") + (opt("--append-system-prompt") or "")
base = 2900 + len(sysprompt) // 3
state = {"total": base, "inited": False, "n": 0}

def out(o):
    sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def log(kind, head):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, "head": head[:40], "nsp": "--no-session-persistence" in args}, ensure_ascii=False) + "\n")

def text_of(msg):
    c = msg.get("message", {}).get("content")
    return c if isinstance(c, str) else "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")

def has_image(msg):
    c = msg.get("message", {}).get("content")
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "image" for b in c)

def stream(text, interruptible):
    """텍스트를 델타로 흘린다. interruptible 이면 stdin 의 control_request interrupt 를 보고 멈춘다. 멈췄으면 True."""
    for i in range(0, len(text), 6):
        if interruptible:
            r, _, _ = select.select([sys.stdin], [], [], 0.0)
            if r:
                line = sys.stdin.readline()
                try:
                    o = json.loads(line)
                except ValueError:
                    o = {}
                if o.get("type") == "control_request":
                    out({"type": "control_response", "response": {"subtype": "success", "request_id": o.get("request_id"), "response": {"still_queued": []}}})
                    return True
        out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text[i:i + 6]}}})
        if interruptible:
            time.sleep(0.002)
    return False

for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if msg.get("type") != "user":
        continue
    text = text_of(msg)
    if not state["inited"]:
        out({"type": "system", "subtype": "init", "model": model, "apiKeySource": "none", "permissionMode": "default", "claude_code_version": "fake",
             "tools": [], "capabilities": ["interrupt_receipt_v1"], "session_id": "fake"})
        state["inited"] = True
    body = text.split("[사용자]")[-1].strip() if "[사용자]" in text else text.strip()
    if body.startswith("/") and len(body) < 40:
        log("local", text)
        if body.startswith("/clear"):
            state["total"] = base
        out({"type": "result", "subtype": "success", "is_error": False, "result": "(command)", "terminal_reason": "completed",
             "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})
        continue
    log("model", text)
    new = len(text) + (1500 if has_image(msg) else 0)
    usage = {"input_tokens": 2, "cache_creation_input_tokens": new, "cache_read_input_tokens": state["total"], "output_tokens": 0}
    out({"type": "stream_event", "event": {"type": "message_start", "message": {"model": model, "usage": usage}}})
    if "1부터 400까지" in text:
        reply = "".join("%d\n" % k for k in range(1, 401))
        stopped = stream(reply, True)
    else:
        if text.startswith("[요청] 종류=트리거"):
            reply = "판단: 질문 | \"질문 문장\"\n답변이다.\n근거: 없음"
        elif "마지막으로 쓴 숫자" in text:
            reply = "193"
        else:
            reply = "ok"
        stopped = stream(reply, False)
    outtok = len(reply) // 3 if not stopped else 0
    out({"type": "assistant", "message": {"model": model, "content": [{"type": "text", "text": reply}], "usage": usage}})
    state["total"] = state["total"] + new + (outtok if not stopped else 0)
    if stopped:
        out({"type": "result", "subtype": "error_during_execution", "is_error": True, "terminal_reason": "aborted_streaming", "result": "",
             "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})
    else:
        out({"type": "result", "subtype": "success", "is_error": False, "result": reply, "terminal_reason": "completed",
             "usage": {"input_tokens": 2, "output_tokens": outtok, "cache_read_input_tokens": usage["cache_read_input_tokens"], "cache_creation_input_tokens": new}})
