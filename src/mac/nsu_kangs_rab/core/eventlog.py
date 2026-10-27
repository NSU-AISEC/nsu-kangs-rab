"""이벤트 로그의 기록기 (K-02, B-08, 기능 정의 5-1절).

- JSON Lines, `<설정 폴더>/logs/events-<실행 시각>-<PID>.jsonl`. 실행마다 새 파일, 최근 20개를 남긴다.
- 모든 줄에 `type` · `t_mono` · `t_wall`. 본문(전사 · 응답)과 키는 넣지 않는다: 금지 필드 이름은 떨어뜨리고,
  등록한 비밀 문자열이 값에 있으면 가린다. 예외를 던지지 않는다(쓰기 실패는 `failed` 로 본다).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

KEEP = 20
# 본문 · 키를 담기 쉬운 필드 이름. 해시와 글자 수는 `*_sha256` · `*_chars` 처럼 다른 이름으로 낸다.
FORBIDDEN_FIELDS = frozenset({"text", "body", "content", "prompt", "transcript", "response", "input",
                              "api_key", "apikey", "key", "secret", "token", "password"})
REDACTED = "[redacted]"
_RESERVED = ("type", "t_mono", "t_wall")


def _wall_now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


class EventLog:
    def __init__(self, config_dir, pid: Optional[int] = None, mono: Callable[[], float] = time.monotonic,
                 wall: Callable[[], str] = _wall_now, now: Optional[Callable[[], _dt.datetime]] = None,
                 keep: int = KEEP):
        self._mono, self._wall = mono, wall
        self._lock = threading.Lock()
        self._secrets: list = []
        self.failed = False
        self.dir = Path(config_dir) / "logs"
        self.pid = os.getpid() if pid is None else pid
        stamp = (now() if now else _dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
        self.path = self.dir / ("events-%s-%d.jsonl" % (stamp, self.pid))
        self._fh = None
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            n = 2
            p = self.path
            while p.exists():  # 같은 초 · 같은 PID 의 실행이 겹치면 덮어쓰지 않는다
                p = self.dir / ("events-%s-%d-%d.jsonl" % (stamp, self.pid, n))
                n += 1
            self.path = p
            self._fh = open(self.path, "a", encoding="utf-8")
            self._prune(keep)
        except OSError:
            self.failed = True

    def _prune(self, keep: int) -> None:
        files = sorted(p for p in self.dir.glob("events-*.jsonl") if p != self.path)
        extra = len(files) - max(keep - 1, 0)  # 현재 파일 몫을 빼고 남긴다
        for p in files[:max(extra, 0)]:
            try:
                p.unlink()
            except OSError:
                pass

    def register_secret(self, value: Optional[str]) -> None:
        """이 문자열이 값에 들어 있는 필드는 가려서 기록한다(AC-FR1-17). 빈 값은 무시한다."""
        if value:
            self._secrets.append(value)

    def _clean(self, v, path: str = "", dropped: Optional[list] = None):
        """값을 정리한다. 중첩에서 떨어뜨린 금지 이름은 점 경로(`a.b`, 목록은 `a[0].b`)로 `dropped` 에 더한다(D-028)."""
        if isinstance(v, str):
            for s in self._secrets:
                if s in v:
                    return REDACTED
            return v
        if isinstance(v, (list, tuple)):
            return [self._clean(x, "%s[%d]" % (path, i), dropped) for i, x in enumerate(v)]
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                name = str(k)
                sub = "%s.%s" % (path, name) if path else name
                if name.lower() in FORBIDDEN_FIELDS:
                    if dropped is not None:
                        dropped.append(sub)
                    continue
                out[name] = self._clean(x, sub, dropped)
            return out
        return v

    def emit(self, type: str, /, **fields) -> bool:
        """사건 한 줄을 기록한다. 반환: 기록했는지."""
        dropped = [k for k in fields if k.lower() in FORBIDDEN_FIELDS or k in _RESERVED]
        rec: dict = {"type": type, "t_mono": self._mono(), "t_wall": self._wall()}
        for k, v in fields.items():
            if k not in dropped:
                rec[k] = self._clean(v, k, dropped)
        if dropped:
            rec["dropped_fields"] = sorted(dropped)
        try:
            line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            line = json.dumps({"type": type, "t_mono": rec["t_mono"], "t_wall": rec["t_wall"], "error": "unserializable"})
        with self._lock:
            if self._fh is None:
                self.failed = True
                return False
            try:
                self._fh.write(line + "\n")
                self._fh.flush()
                return True
            except (OSError, ValueError):
                self.failed = True
                return False

    def session_start(self, *, kind: str, save_dir: str, claude_path: Optional[str], claude_is_script: Optional[bool],
                      provider: str, auth: str, model: str, effort: Optional[str], audio_source: Optional[str],
                      prompt_source: str, prompt_sha256: str, materials: Iterable = (),
                      dev_options: Iterable = (), stt_language: str = "ko", app_language: str = "ko") -> bool:
        """5-1절 "세션 시작" 행의 필드. `dev_options` 는 이름만이고 사용하지 않았으면 빈 목록이다."""
        return self.emit("session_start", kind=kind, save_dir=save_dir, claude_path=claude_path,
                         claude_is_script=claude_is_script, provider=provider, auth=auth, model=model,
                         effort=effort, audio_source=audio_source, prompt_source=prompt_source,
                         prompt_sha256=prompt_sha256, materials=list(materials), dev_options=list(dev_options),
                         stt_language=stt_language, app_language=app_language)

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None
