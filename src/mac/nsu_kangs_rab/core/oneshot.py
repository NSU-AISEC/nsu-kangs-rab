"""일회성 `claude -p` 프로세스 하나 (K-16 정리 문서 · K-15 다이어그램; 계획 2-4절 `OneShot.run`).

상주 프로세스와 같은 `ModelSession` 을 일회성 설정(`llm.Kind.ONESHOT`)으로 쓴다. 한 번 보내고 `Result` 를 받으면 끝낸다.

- 명령줄 · 환경은 `llm.build_command` · `llm.clean_env` 가 만든다(결정 0033 · 0055, 인증 원칙).
- 첫 메시지는 단독 `/effort <수준>` 이며 `init` 의 인증 출처 검사를 통과한 뒤에 요청을 보낸다(결정 0056).
- 끝나면 `on_done(Outcome)` 을 한 번만 호출한다. 시간 초과 · 취소 · 오류 · 정상 종료 모두 같다.
- 종료는 기록한 PID 로만 한다(`Procs.terminate`).
"""
from __future__ import annotations
from .i18n import t as _t

import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from . import llm
from .model_session import ModelSession
from .types import Error, OutgoingMessage, ProcessExited, Result, TextDelta

DEFAULT_TIMEOUT_S = 900.0   # B-15: 정리 문서(이력이 없는 경로). 다이어그램은 180초를 준다


@dataclass(frozen=True)
class Outcome:
    ok: bool
    text: str = ""
    error_kind: Optional[str] = None
    detail: str = ""
    cancelled: bool = False
    timed_out: bool = False


class OneShot:
    def __init__(self, *, claude_path: str, model: str, auth: llm.Auth, parent_env: Mapping[str, str], procs,
                 cwd: str, run_dir: str, effort: Optional[str] = "high", api_key: Optional[str] = None,
                 eventlog=None, system_prompt: Optional[str] = None, tools: Sequence[str] = (),
                 plugin_dir: Optional[str] = None, permission_mode: Optional[str] = None,
                 settings_extra: Optional[Mapping[str, object]] = None, timeout_s: float = DEFAULT_TIMEOUT_S,
                 purpose: str = "cleanup_doc", model_factory: Optional[Callable] = None):
        self._cfg = llm.SessionConfig(claude_path=claude_path, model=model, effort=effort, kind=llm.Kind.ONESHOT,
                                      tools=tuple(tools), plugin_dir=plugin_dir, permission_mode=permission_mode,
                                      settings_extra=settings_extra, include_partial_messages=True)   # 결정 0154: 절 단위 진행 표시에 조각이 필요하다
        self._auth, self._env, self._procs, self._cwd = auth, parent_env, procs, cwd
        self._run_dir, self._api_key, self._log = run_dir, api_key, eventlog
        self._prompt = system_prompt
        self._timeout = timeout_s
        self._purpose = purpose
        self._factory = model_factory or ModelSession
        self._mu = threading.Lock()
        self._done = False
        self._on_done: Optional[Callable[[Outcome], None]] = None
        self._session = None
        self._timer: Optional[threading.Timer] = None
        self._text = ""
        self.on_text: Optional[Callable[[str], None]] = None     # 받은 글 조각(진행 표시용)
        self.pid: Optional[int] = None

    def run(self, prompt: str, on_done: Callable[[Outcome], None]) -> bool:
        """프로세스를 시작하고 요청을 보낸다. 시작하지 못하면 `on_done` 을 호출하고 False 를 반환한다."""
        self._on_done = on_done
        s = self._factory(self._cfg, self._auth, self._on_event, procs=self._procs, parent_env=self._env,
                          cwd=self._cwd, api_key=self._api_key if self._auth is llm.Auth.API else None,
                          eventlog=self._log, prompt_text=self._prompt, run_dir=self._run_dir)
        s.role = "oneshot"
        self._session = s
        if not s.start():
            # 시작 실패의 `Error` 사건이 `_on_event` 로 이미 가서 끝났을 수 있다. 끝나지 않았으면 여기서 끝낸다.
            self._finish(Outcome(False, error_kind="no_claude", detail=_t("oneshot.run_423")))
            return False
        self.pid = s.pid
        self._timer = threading.Timer(self._timeout, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()
        ok = s.send(OutgoingMessage(0, ({"type": "text", "text": prompt},)))
        if not ok:
            self._finish(Outcome(False, error_kind="process_exit", detail=_t("msession.send_419")))
            return False
        return True

    def cancel(self) -> None:
        """진행 중이면 PID 로 종료하고 `Outcome(cancelled=True)` 로 끝낸다."""
        self._finish(Outcome(False, cancelled=True))

    # ---- 내부 ----
    def _on_event(self, ev) -> None:
        if isinstance(ev, TextDelta):
            self._text += ev.text
            cb = self.on_text
            if cb is not None:
                try:
                    cb(ev.text)
                except Exception:
                    pass
        elif isinstance(ev, Result):
            if ev.ok:
                self._finish(Outcome(True, text=ev.text or self._text))
            else:
                self._finish(Outcome(False, text=ev.text or "", error_kind=ev.error_kind or "unknown",
                                     detail=(ev.text or "")[:400]))
        elif isinstance(ev, Error):
            # 오류 뒤에 `Result` 가 따를 수 있으므로 종료 · 시작 실패 계열만 여기서 끝낸다
            if ev.kind in ("auth", "no_claude", "process_exit", "io"):
                self._finish(Outcome(False, error_kind=ev.kind, detail=ev.detail))
        elif isinstance(ev, ProcessExited):
            if not ev.expected:
                self._finish(Outcome(False, error_kind="process_exit", detail=_t("endflow.on_event_291")))

    def _on_timeout(self) -> None:
        self._finish(Outcome(False, timed_out=True, error_kind="timeout", detail=_t("oneshot.on_timeout_424") % self._timeout))

    def _finish(self, outcome: Outcome) -> None:
        with self._mu:
            if self._done:
                return
            self._done = True
        t, self._timer = self._timer, None
        if t is not None:
            t.cancel()
        s = self._session
        cb = self._on_done

        def work():
            if s is not None:
                try:
                    s.close()      # 기록한 PID 로 종료한다(읽기 스레드가 아닌 곳에서 호출한다)
                except Exception:
                    pass
            if cb is not None:
                try:
                    cb(outcome)
                except Exception:
                    pass
        threading.Thread(target=work, daemon=True).start()
