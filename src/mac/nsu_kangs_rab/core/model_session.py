"""`claude -p` 상주 프로세스 한 개의 실행 · 입출력 · 종료 · 인증 출처 검사 (K-03, 2-4절 `llm.py`).

- 명령줄과 환경은 `llm.build_command` · `llm.clean_env`(K-01)가 만든다.
- 사건은 읽기 스레드에서 `on_event` 로 낸다. 오류는 예외 대신 `Error` 사건이다(2-2절 3항).
- 키 문자열은 `secrets` 로 등록해 오류 문구 · 이벤트 로그에서 가린다(AC-FR1-17).
"""
from __future__ import annotations
from .i18n import t as _t

import json
import os
import threading
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import llm, stream
from .procs import ProcHandle, Procs
from .types import (Compacted, Compacting, ControlResponse, Error, Init, OutgoingMessage, ProcessExited, Result)

EXPECTED_SOURCE = {llm.Auth.SUBSCRIPTION: "none", llm.Auth.API: "ANTHROPIC_API_KEY"}  # A-04: 닫는 쪽
STDERR_TAIL = 400


def write_prompt_file(run_dir, text: str) -> str:
    """A-28: `run/`(0700) 아래 0600 파일. 이름은 무작위이다. 호출한 쪽이 프로세스가 끝나면 지운다."""
    d = Path(run_dir).resolve()  # 하위 프로세스의 작업 폴더가 달라도 같은 파일을 가리킨다
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    p = d / ("system-prompt-%s.txt" % uuid.uuid4().hex)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return str(p)


@dataclass
class _Run:
    """프로세스 하나의 상태. 재시작해도 이전 프로세스의 정리가 새 프로세스의 자원을 건드리지 않게 프로세스마다 둔다(D-029)."""
    h: ProcHandle
    prompt_file: Optional[str] = None
    timer: Optional[threading.Timer] = None
    stderr: list = field(default_factory=list)
    threads: list = field(default_factory=list)   # [읽기, 표준 오류, 대기]
    rejected: bool = False
    finalized: bool = False
    saw_event: bool = False                        # 사건을 하나라도 받았는가(즉시 종료의 판별)
    gate: bool = False                             # Q11: init 의 인증 출처 검사가 끝나기 전에는 질의를 보내지 않는다
    queued: list = field(default_factory=list)     # gate 동안 받은 질의(검사 통과 뒤 순서대로 보낸다)
    hide_result: bool = False                      # 첫 `/effort` 의 국소 명령 Result 를 사용자에게 내지 않는다
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class ModelSession:
    def __init__(self, config: llm.SessionConfig, auth: llm.Auth, on_event: Callable[[object], None], *,
                 procs: Procs, parent_env: Mapping[str, str], cwd: str, api_key: Optional[str] = None,
                 eventlog=None, request_timeout_s: Optional[float] = None, stdin_wait_s: float = 3.0,
                 term_wait_s: float = 3.0, prompt_text: Optional[str] = None, run_dir: Optional[str] = None,
                 drain_grace_s: float = 0.5):
        self.config, self.auth, self._cb = config, auth, on_event
        self._procs, self._parent_env, self._cwd = procs, parent_env, cwd
        self._api_key, self._log = api_key, eventlog
        self._timeout_s, self._stdin_wait, self._term_wait = request_timeout_s, stdin_wait_s, term_wait_s
        self._prompt_text, self._run_dir = prompt_text, run_dir
        self._grace = drain_grace_s
        self._run: Optional[_Run] = None
        self._wlock = threading.Lock()
        self.init: Optional[Init] = None
        self.rejected = False  # 인증 출처 불일치로 시작하지 않은 상태
        self.pid: Optional[int] = None
        self.command: list = []
        self.role = "resident"   # 일회성 프로세스(`core/oneshot.py`)는 "oneshot" 으로 바꾼다
        if eventlog is not None and api_key:
            eventlog.register_secret(api_key)

    # ---- 시작 ----
    def start(self) -> bool:
        """프로세스를 시작한다. 실패하면 `Error` 사건을 내고 False. 예외를 던지지 않는다."""
        self.init, self.rejected = None, False
        try:
            env = llm.clean_env(self._parent_env, self.auth, self._api_key)
        except llm.AuthConfigError as e:
            self._error("auth", str(e))
            return False
        cfg = self.config
        prompt_file = None
        try:
            if self._prompt_text is not None and self._run_dir is not None and not cfg.system_prompt_file:
                prompt_file = write_prompt_file(self._run_dir, self._prompt_text)
                cfg = replace(cfg, system_prompt_file=prompt_file, system_prompt=None)
            self.command = llm.build_command(cfg)
        except llm.CommandConfigError as e:
            self._unlink(prompt_file)
            self._error("io", str(e))
            return False
        except OSError as e:
            self._error("io", _t("msession.start_416") % type(e).__name__)
            return False
        try:
            h = self._procs.spawn(self.command, env, self._cwd, self.role)
        except FileNotFoundError:
            self._unlink(prompt_file)
            self._error("no_claude", _t("msession.start_417"))
            return False
        except OSError as e:
            self._unlink(prompt_file)
            self._error("no_claude", _t("msession.start_418") % type(e).__name__)
            return False
        run = _Run(h, prompt_file)
        self._run = run
        self.pid = h.pid
        self._emit("process_start", role=self.role, pid=h.pid)
        reader = threading.Thread(target=self._read_out, args=(run,), daemon=True)
        err = threading.Thread(target=self._read_err, args=(run,), daemon=True)
        waiter = threading.Thread(target=self._wait, args=(run,), daemon=True)
        run.threads = [reader, err, waiter]
        for th in run.threads:
            th.start()
        if cfg.effort:  # Q11: 첫 메시지는 단독 `/effort`(모델 호출 없이 init 을 얻는다). 질의는 init 검사 뒤에 보낸다
            run.gate = run.hide_result = True
            self._write({"type": "user", "message": {"role": "user",
                                                    "content": [{"type": "text", "text": "/effort %s" % cfg.effort}]}})
        return True

    # ---- 입력 ----
    def _write(self, obj: dict) -> bool:
        run = self._run
        h = run.h if run is not None else None
        if h is None or not h.alive():
            return False
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self._wlock:
            try:
                h.popen.stdin.write(line)
                h.popen.stdin.flush()
                return True
            except (OSError, ValueError):
                return False

    def send(self, msg: OutgoingMessage) -> bool:
        run = self._run
        if run is not None:
            with run.lock:
                if run.gate and not run.finalized:  # init 검사 전: 보류한다. 통과하면 `_on_init` 이 보낸다
                    run.queued.append(msg)
                    return True
        ok = self._send_now(msg)
        if not ok:
            self._error("process_exit", _t("msession.send_419"))
            return False
        self._arm_timer()
        return True

    def _send_now(self, msg: OutgoingMessage) -> bool:
        return self._write({"type": "user", "message": {"role": "user", "content": list(msg.blocks)}})

    def interrupt(self) -> Optional[str]:
        """`control_request`(interrupt, `cancel_queued: true`). 반환: request_id."""
        rid = "int-%s" % uuid.uuid4().hex[:8]
        ok = self._write({"type": "control_request", "request_id": rid,
                          "request": {"subtype": "interrupt", "cancel_queued": True}})
        return rid if ok else None

    def set_effort(self, level: str) -> bool:
        """A-22: 사용자 글이 없는 단독 `/effort <level>` 메시지."""
        return self._write({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "/effort %s" % level}]}})

    # ---- 읽기 ----
    def _read_out(self, run: _Run) -> None:
        h = run.h
        try:
            for line in h.popen.stdout:
                for ev in stream.parse_line(line):
                    if run.finalized:  # 정리가 끝난 프로세스의 늦은 사건은 버린다(D-029)
                        return
                    run.saw_event = True
                    if isinstance(ev, Init):
                        self._on_init(run, ev)
                        if run.rejected:
                            return
                    if isinstance(ev, Result):
                        if run.hide_result:  # 첫 `/effort` 의 국소 명령 Result 는 num_turns 가 0 이다(모델 호출 없음)
                            run.hide_result = False
                            if ev.ok and ev.num_turns == 0:   # `/effort` 가 Result 를 내지 않는 판의 질의 Result 는 숨기지 않는다
                                continue
                        self._cancel_timer(run)
                        if not ev.ok and ev.error_kind:
                            self._error(ev.error_kind, self._redact(ev.text)[:STDERR_TAIL])
                    self._deliver(ev)
        except (OSError, ValueError):
            return

    def _read_err(self, run: _Run) -> None:
        try:
            for line in run.h.popen.stderr:
                run.stderr.append(line.strip())
                del run.stderr[:-20]
        except (OSError, ValueError):
            return

    def _wait(self, run: _Run) -> None:
        """프로세스의 종료는 표준 출력의 EOF 가 아니라 프로세스 종료로 판단한다(손자가 파이프를 쥘 수 있다)."""
        code = run.h.popen.wait()
        reader, err, _ = run.threads
        reader.join(timeout=self._grace)
        err.join(timeout=self._grace)
        self._finalize(run, code)

    def _finalize(self, run: _Run, code: Optional[int]) -> None:
        with run.lock:
            if run.finalized:
                return
            run.finalized = True
            run.gate, run.queued = False, []  # 끝난 프로세스에 보류한 질의는 보내지 않는다
        h = run.h
        reader, err, _ = run.threads if run.threads else (None, None, None)
        for f, th in ((h.popen.stdin, None), (h.popen.stdout, reader), (h.popen.stderr, err)):
            try:
                if f is not None and (th is None or not th.is_alive()):  # 읽는 중인 파이프는 닫지 않는다
                    f.close()
            except (OSError, ValueError):
                pass
        self._cancel_timer(run)
        self._procs.reap(h)
        self._unlink(run.prompt_file)
        run.prompt_file = None
        expected = bool(h.closing or run.rejected)
        self._emit("process_exit", role=self.role, pid=h.pid, code=code, expected=expected)
        if not expected:
            tail = self._redact(" ".join(run.stderr)[-STDERR_TAIL:])
            # 표준 오류로의 분류는 즉시 종료(사건을 하나도 받기 전의 종료)일 때만 한다
            kind = (stream.classify_text(tail) if not run.saw_event else None) or "process_exit"
            self._error(kind, tail or _t("msession.finalize_420") % code)
        self._deliver(ProcessExited(code, expected))

    def _on_init(self, run: _Run, ev: Init) -> None:
        if run is self._run:
            self.init = ev
        want = EXPECTED_SOURCE[self.auth]
        if ev.api_key_source != want:  # 값이 없는 경우(None)도 닫는다(A-04)
            run.rejected = True
            if run is self._run:
                self.rejected = True
            self._emit("auth_mismatch", auth=self.auth.value, api_key_source=ev.api_key_source, expected_source=want)
            self._error("auth", _t("msession.on_init_421") % (want, ev.api_key_source))
            with run.lock:
                gated = run.gate
                run.gate, run.queued = False, []  # 보류한 질의는 보내지 않는다
            if gated:  # 질의를 보내지 않았다: 표준 입력을 닫고 SIGTERM
                target, args = self._procs.terminate, (run.h, 0.0, self._term_wait)
            else:      # `/effort` 경로가 아니다: 이미 질의가 나갔을 수 있으므로 PID 로 SIGKILL
                target, args = self._procs.kill, (run.h,)
            threading.Thread(target=target, args=args, daemon=True).start()
            return
        with run.lock:
            pending, run.gate, run.queued = run.queued, False, []
        for msg in pending:
            if self._send_now(msg):
                self._arm_timer()
            else:
                self._error("process_exit", _t("msession.send_419"))
                break

    # ---- 종료 · 재시작 ----
    def close(self) -> Optional[int]:
        run = self._run
        if run is None:
            return None
        self._cancel_timer(run)
        code = self._procs.terminate(run.h, self._stdin_wait, self._term_wait)
        if len(run.threads) == 3:
            run.threads[2].join(timeout=self._grace * 2 + 1.0)
        self._finalize(run, code)  # 대기 스레드가 끝내지 못했으면 여기서 끝낸다(멱등)
        return code

    def restart(self) -> bool:
        """B-06: 종료 뒤 같은 설정으로 새 프로세스를 시작한다. 재전송(전사 전체 · 사전 지식 이미지)은 호출한 쪽이 한다."""
        old = self.pid
        self.close()
        ok = self.start()
        self._emit("process_restart", role=self.role, old_pid=old, new_pid=self.pid if ok else None)
        return ok

    # ---- 내부 ----
    def _arm_timer(self) -> None:
        run = self._run
        if not self._timeout_s or run is None:
            return
        self._cancel_timer(run)
        secs = self._timeout_s

        def fire():
            if not run.finalized:
                self._error("network", _t("msession.fire_422") % secs)
        t = threading.Timer(secs, fire)
        t.daemon = True
        run.timer = t
        t.start()

    @staticmethod
    def _cancel_timer(run: _Run) -> None:
        t, run.timer = run.timer, None
        if t is not None:
            t.cancel()

    def _redact(self, s: str) -> str:
        return s.replace(self._api_key, "[redacted]") if self._api_key else s

    @staticmethod
    def _unlink(path: Optional[str]) -> None:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _deliver(self, ev) -> None:
        try:
            self._cb(ev)
        except Exception:  # 콜백의 오류가 읽기 스레드를 멈추지 않는다
            pass

    def _error(self, kind: str, detail: str) -> None:
        self._emit("error", module="llm", kind=kind, detail=self._redact(detail))
        self._deliver(Error(kind, self._redact(detail)))

    def _emit(self, type_: str, **fields) -> None:
        if self._log is not None:
            self._log.emit(type_, **fields)
