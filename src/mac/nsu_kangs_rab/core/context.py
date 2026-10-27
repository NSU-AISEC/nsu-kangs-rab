"""사전 지식 (FR-2, docs/plan/technical-plan.md 2-4절 context.py, K-05).

- 글자 수는 NFC 정규화 뒤 코드 포인트 수이며 공백 · 줄바꿈을 포함한다(결정 0047).
- 글자 수 상한과 이미지 장 수 상한은 서로 독립이다. 상한을 넘으면 그 자료를 보류하고, 자료를 빼면 보류된 자료를
  보류된 순서대로 상한까지 자동 추가한다. 같은 종류의 보류 자료가 있으면 새 자료도 보류한다(앞에서부터 상한까지, ⑥).
- 파일 크기 보조 제한을 넘는 텍스트 파일은 추출하지 않고 보류 목록에도 두지 않는다(`removable=False`).
- 원문 파일은 읽기만 한다. Qt · 플랫폼 모듈을 가져오지 않는다.
"""
from __future__ import annotations
from .i18n import t as _t

import hashlib
import json
import os
import subprocess
import sys
import inspect
import io
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import imageinfo

CHAR_CAP = 50_000
IMAGE_CAP = 6
TEXT_FILE_CAP_BYTES = 2 * 1024 * 1024
PDF_FILE_CAP_BYTES = 25 * 1024 * 1024
PDF_EXTRACT_TIMEOUT_S = 10.0
TEXT_SUFFIXES = (".md", ".txt")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


@dataclass(frozen=True)
class Limits:
    char_cap: int = CHAR_CAP
    image_cap: int = IMAGE_CAP
    text_file_cap_bytes: int = TEXT_FILE_CAP_BYTES
    pdf_file_cap_bytes: int = PDF_FILE_CAP_BYTES
    image_bytes_cap: int = imageinfo.IMAGE_BYTES_CAP                          # 결정 0058: 이미지 한 장(변환 · 재부호화 뒤)
    registered_image_bytes_cap: int = imageinfo.REGISTERED_IMAGE_BYTES_CAP    # 결정 0060: 사전 지식 이미지의 바이트 합계

    @staticmethod
    def from_devopts(opts) -> "Limits":
        """`--dev-char-cap` · `--dev-image-cap` · `--dev-file-size-cap-bytes`(md · txt · pdf 모두에 적용) ·
        `--dev-image-bytes-cap` · `--dev-registered-image-bytes-cap`."""
        g = opts.get
        fc = g("file_size_cap_bytes")
        return Limits(char_cap=g("char_cap") or CHAR_CAP, image_cap=g("image_cap") or IMAGE_CAP,
                      text_file_cap_bytes=fc or TEXT_FILE_CAP_BYTES, pdf_file_cap_bytes=fc or PDF_FILE_CAP_BYTES,
                      image_bytes_cap=g("image_bytes_cap") or imageinfo.IMAGE_BYTES_CAP,
                      registered_image_bytes_cap=g("registered_image_bytes_cap") or imageinfo.REGISTERED_IMAGE_BYTES_CAP)


@dataclass
class Material:
    id: str
    name: str
    kind: str                    # "text" | "image"
    text: Optional[str] = None   # 텍스트 자료의 NFC 본문
    bytes: Optional[bytes] = None  # 이미지: 축소를 마친 보낼 바이트
    chars: int = 0
    size: int = 0                # 원본 크기(바이트)
    width: int = 0               # 이미지 원본 가로
    height: int = 0
    sha256: str = ""             # 원본 바이트의 해시(AC-FR2-6)
    sent_width: int = 0
    sent_height: int = 0
    media_type: str = ""         # image/png | image/jpeg | image/gif | image/webp
    path: Optional[str] = None


@dataclass
class Accepted:
    material: Material


@dataclass
class Held:
    name: str
    kind: str                    # "text" | "image"
    reason: str                  # "chars" | "images" | "file_size"
    removable: bool              # 다른 자료를 빼면 해소될 수 있는가(False 이면 취소만 제공)
    chars: int = 0
    size: int = 0
    limit: int = 0               # 글자 수 상한 · 장 수 상한 · 파일 크기 제한
    id: str = ""


@dataclass
class Unreadable:
    name: str
    reason: str                  # not_found | permission | format | encrypted | no_text | decode | timeout | io |
    #                              dependency(추출 부품 부재, D-033) | image_bytes(한 장 바이트 상한, 결정 0058) |
    #                              registered_bytes(사전 지식 이미지 합계, 결정 0060)
    detail: str = ""
    limit: int = 0               # image_bytes · registered_bytes 에 적용된 상한(바이트). 문구에 적용된 값을 쓴다


@dataclass
class RemoveResult:
    removed: bool
    resolved: list = field(default_factory=list)     # 자동 추가된 Material(보류된 순서)
    still_held: list = field(default_factory=list)   # 남은 보류(선택 창을 다시 표시한다)
    unreadable: list = field(default_factory=list)   # 자동 추가 중 축소에 실패해 버린 이미지(`Unreadable`, D-032)
    dropped: list = field(default_factory=list)      # 혼합 보류에서 보류 제외된 단독 초과 자료(`Held`, AC-FR2-15)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def ref_name(name: str) -> str:
    """프롬프트 · 근거 줄에 쓰는 이름: `;` · `,` 를 `_` 로, 줄바꿈을 공백으로(prompt-spec 4-1절)."""
    return name.replace(";", "_").replace(",", "_").replace("\r", " ").replace("\n", " ")


def escape_lines(text: str) -> str:
    """줄 머리의 `[` 를 `\\[` 로 바꾼다(prompt-spec 4절)."""
    return "\n".join(("\\" + ln) if ln.startswith("[") else ln for ln in text.split("\n"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def default_pdf_worker_cmd() -> list:
    """PDF 추출 프로세스의 명령. 묶은 앱에서는 `sys.executable` 이 앱 자신이므로 `--pdf-worker` 로 다시 시작한다(K-17).
    개발 환경은 `-I` 로 단독 실행한다(core/types.py 가 표준 types 를 가리지 않게 한다)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pdf-worker"]
    return [sys.executable, "-I", str(Path(__file__).with_name("pdfworker.py"))]


class ContextStore:
    def __init__(self, limits: Optional[Limits] = None, shrink: Optional[Callable] = None,
                 emit: Optional[Callable[..., object]] = None,
                 pdf_timeout_s: float = PDF_EXTRACT_TIMEOUT_S, clock: Callable[[], float] = time.monotonic,
                 procs=None, pdf_worker_cmd=None):
        self.limits = limits or Limits()
        self._procs = procs               # `core.procs.Procs`. 없으면 첫 PDF 때 만든다
        self._pdf_worker = list(pdf_worker_cmd) if pdf_worker_cmd else default_pdf_worker_cmd()
        self._pdf_timeout_s = pdf_timeout_s
        self._clock = clock
        self._shrink = shrink or imageinfo.ImageShrinker()
        try:   # 4인자만 받는 주입 함수(시험용)도 받는다
            ps = inspect.signature(self._shrink).parameters
            self._shrink_cap = "max_bytes" in ps or any(x.kind is x.VAR_KEYWORD for x in ps.values())
        except (TypeError, ValueError):
            self._shrink_cap = False
        self._emit = emit
        self._items: list = []        # 추가된 Material(추가 순서)
        self._held: list = []         # (Held, 지연 추가 정보) 보류 순서
        self._seq = 0
        self._last_unreadable: list = []

    # ---- 조회 ----
    def materials(self) -> list:
        return list(self._items)

    def held(self) -> list:
        return [h for h, _ in self._held]

    def count(self) -> int:
        return len(self._items)

    def total_chars(self) -> int:
        return sum(m.chars for m in self._items if m.kind == "text")

    def image_count(self) -> int:
        return sum(1 for m in self._items if m.kind == "image")

    # ---- 추가 ----
    def add_text(self, name: str, text: str):
        norm = nfc(text)
        raw = norm.encode("utf-8")
        return self._offer("text", name, {"text": norm, "size": len(raw), "sha256": _sha(raw), "path": None})

    def add_file(self, path):
        p = Path(path)
        name = p.name
        suffix = p.suffix.lower()
        if suffix not in TEXT_SUFFIXES + (".pdf",) + IMAGE_SUFFIXES:
            return Unreadable(name, "format", _t("ctx.add_file_393"))
        if suffix in IMAGE_SUFFIXES:
            return self.add_image(p)
        try:
            size = p.stat().st_size
        except FileNotFoundError:
            return Unreadable(name, "not_found")
        except PermissionError:
            return Unreadable(name, "permission")
        except OSError as e:
            return Unreadable(name, "io", type(e).__name__)
        cap = self.limits.pdf_file_cap_bytes if suffix == ".pdf" else self.limits.text_file_cap_bytes
        if size > cap:  # 추출하지 않는다(AC-FR2-10)
            h = Held(name, "text", "file_size", False, size=size, limit=cap)
            self._event("material_held", kind="text", reason="file_size", name=name, removable=False, size=size, limit=cap)
            return h
        try:
            raw = p.read_bytes()
        except PermissionError:
            return Unreadable(name, "permission")
        except OSError as e:
            return Unreadable(name, "io", type(e).__name__)
        if suffix == ".pdf":
            r = self._extract_pdf_process(p, name)
            if isinstance(r, Unreadable):
                return r
            text = r
        else:
            text = _decode(raw)
            if text is None:
                return Unreadable(name, "decode", _t("ctx.add_file_394"))
        return self._offer("text", name, {"text": nfc(text), "size": size, "sha256": _sha(raw), "path": str(p)})

    def _extract_pdf_process(self, path, name: str):
        """추출을 앱이 시작한 별도 프로세스에서 하고 시간 초과에 그 PID 로만 끝낸다(A-06, X3). 사유는 `timeout`."""
        if self._procs is None:
            from .procs import Procs
            self._procs = Procs()
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "en_US.UTF-8"}
        try:
            abs_path = Path(path).resolve()   # 작업 폴더를 바꾸므로 절대 경로로 넘긴다(D-034)
            h = self._procs.spawn(self._pdf_worker + [str(abs_path)], env, str(abs_path.parent), "pdf")
        except OSError as e:
            return Unreadable(name, "io", type(e).__name__)
        try:
            out, _err = h.popen.communicate(timeout=self._pdf_timeout_s)
        except subprocess.TimeoutExpired:
            self._procs.kill(h)       # 기록한 PID 에 SIGKILL, 종료를 기다려 회수한다
            try:
                h.popen.communicate(timeout=1.0)
            except Exception:
                pass
            return Unreadable(name, "timeout", _t("ctx.extract_pdf_process_395") % self._pdf_timeout_s)
        finally:
            self._procs.reap(h)
        try:
            res = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return Unreadable(name, "format", _t("ctx.extract_pdf_process_396"))
        st = res.get("status")
        if st == "ok":
            return res.get("text", "")
        if st == "encrypted":
            return Unreadable(name, "encrypted", _t("ctx.extract_pdf_process_397"))
        if st == "no_text":
            return Unreadable(name, "no_text", _t("ctx.extract_pdf_process_398"))
        if st == "dependency":
            return Unreadable(name, "dependency", str(res.get("detail", "")))
        return Unreadable(name, "format", str(res.get("detail", "")))

    def add_image(self, path):
        p = Path(path)
        name = p.name
        try:
            raw = p.read_bytes()
        except FileNotFoundError:
            return Unreadable(name, "not_found")
        except PermissionError:
            return Unreadable(name, "permission")
        except OSError as e:
            return Unreadable(name, "io", type(e).__name__)
        try:
            fmt, w, h = imageinfo.read_size(raw)
        except imageinfo.ImageFormatError as e:
            return Unreadable(name, "format", str(e))
        return self._offer("image", name, {"raw": raw, "fmt": fmt, "width": w, "height": h, "size": len(raw),
                                           "sha256": _sha(raw), "path": str(p)})

    def _offer(self, kind: str, name: str, info: dict):
        if kind == "text":
            chars = len(info["text"])
            if chars == 0:
                return Unreadable(name, "no_text", _t("ctx.extract_pdf_process_398"))
            info["chars"] = chars
        limit = self.limits.char_cap if kind == "text" else self.limits.image_cap
        queued = any(h.kind == kind for h, _ in self._held)
        if queued or not self._fits(kind, info):
            alone = (info["chars"] <= self.limits.char_cap) if kind == "text" else (self.limits.image_cap >= 1)
            held = Held(name, kind, "chars" if kind == "text" else "images", alone,
                        chars=info.get("chars", 0), size=info["size"], limit=limit, id=self._next_id())
            self._held.append((held, (name, info)))
            self._event("material_held", kind=kind, reason=held.reason, name=name, removable=alone,
                        chars=held.chars, limit=limit)
            return held
        m = self._register(name, kind, info)
        if isinstance(m, Unreadable):   # 축소에 실패했거나(D-032) 바이트 상한을 넘는 이미지
            return m
        return Accepted(m)

    def _fits(self, kind: str, info: dict) -> bool:
        if kind == "text":
            return self.total_chars() + info["chars"] <= self.limits.char_cap
        return self.image_count() + 1 <= self.limits.image_cap

    def _next_id(self) -> str:
        self._seq += 1
        return "m%d" % self._seq

    def image_bytes_total(self) -> int:
        return sum(len(m.bytes or b"") for m in self._items if m.kind == "image")

    def _register(self, name: str, kind: str, info: dict, mid: Optional[str] = None):
        """추가한다. 이미지는 변환 · 축소 뒤의 바이트로 한 장 상한(결정 0058)과 사전 지식 합계 상한(결정 0060)을 검사한다.
        실패하면 목록을 바꾸지 않고 `Unreadable` 을 반환한다(D-032: 예외를 밖으로 내지 않는다)."""
        mid = mid or self._next_id()
        if kind == "text":
            m = Material(mid, name, "text", text=info["text"], chars=info["chars"], size=info["size"],
                         sha256=info["sha256"], path=info.get("path"))
        else:
            try:
                if self._shrink_cap:
                    s = self._shrink(info["raw"], info["fmt"], info["width"], info["height"],
                                     max_bytes=self.limits.image_bytes_cap)
                else:
                    s = self._shrink(info["raw"], info["fmt"], info["width"], info["height"])
            except imageinfo.ImageTooLarge as e:   # 결정 0058 2항: 재부호화 뒤에도 상한 초과
                self._event("material_unreadable", name=name, kind=kind, reason="image_bytes", size=e.size, limit=e.cap)
                return Unreadable(name, "image_bytes", _t("ctx.register_399") % e.cap, limit=e.cap)
            except Exception as e:  # 축소 구현(Qt)의 오류. 그 자료만 버린다
                self._event("material_unreadable", name=name, kind=kind, reason="shrink_failed", error_class=type(e).__name__)
                return Unreadable(name, "format", _t("ctx.register_400"))
            total = self.image_bytes_total() + len(s.data)
            if total > self.limits.registered_image_bytes_cap:   # 결정 0060: 같은 값은 받는다
                self._event("material_unreadable", name=name, kind=kind, reason="registered_bytes", size=total,
                            limit=self.limits.registered_image_bytes_cap)
                return Unreadable(name, "registered_bytes", _t("ctx.register_401") % self.limits.registered_image_bytes_cap,
                                  limit=self.limits.registered_image_bytes_cap)
            m = Material(mid, name, "image", bytes=s.data, size=info["size"], width=info["width"],
                         height=info["height"], sha256=info["sha256"], sent_width=s.width, sent_height=s.height,
                         media_type=MEDIA_TYPES.get(s.fmt, "image/png"), path=info.get("path"))
        self._items.append(m)
        return m

    # ---- 빼기 · 보류 처리 ----
    def remove(self, material_id: str) -> RemoveResult:
        for i, m in enumerate(self._items):
            if m.id == material_id:
                del self._items[i]
                dropped = self._drop_sole()
                resolved, still = self._retry()
                return RemoveResult(True, resolved, still, self._last_unreadable, dropped)
        for i, (h, _) in enumerate(self._held):
            if h.id == material_id:  # 보류된 자료를 직접 뺀다 = 그 자료의 취소
                del self._held[i]
                self._event("material_hold_cancelled", name=h.name, kind=h.kind)
                dropped = self._drop_sole()
                return RemoveResult(True, [], self.held(), dropped=dropped)
        return RemoveResult(False, [], self.held())

    def _drop_sole(self) -> list:
        """혼합 보류(AC-FR2-15): 단독으로 상한을 넘는 자료와 빼면 풀리는 자료가 함께 있을 때, 선택 창의 확인(빼기)으로
        단독 초과 자료를 추가하지 않은 채 보류에서 뺀다. 빼면 풀리는 보류가 없으면(모두 단독 초과) 취소만 제공하므로 두지 않는다."""
        sole = [h for h, _ in self._held if not h.removable]
        if not sole or all(not h.removable for h, _ in self._held):
            return []
        self._held = [(h, v) for h, v in self._held if h.removable]
        for h in sole:
            self._event("material_hold_dropped", name=h.name, kind=h.kind, reason="sole_over",
                        chars=h.chars, limit=h.limit)
        return sole

    def retry_held(self) -> RemoveResult:
        resolved, still = self._retry()
        return RemoveResult(False, resolved, still, self._last_unreadable)

    def _retry(self) -> tuple:
        """보류를 앞에서부터 자동 추가한다. 축소가 실패한 이미지는 보류에서 빼고 `_last_unreadable` 에 모은다(D-032)."""
        resolved = []
        blocked: set = set()
        keep = []
        self._last_unreadable = []
        for h, (name, info) in self._held:
            if h.kind in blocked or not self._fits(h.kind, info):
                blocked.add(h.kind)
                keep.append((h, (name, info)))
                continue
            m = self._register(name, h.kind, info, mid=h.id)
            if isinstance(m, Unreadable):   # 축소 실패(D-032) · 바이트 상한: 보류에서 빼고 나머지를 계속한다(AC-FR2-13)
                self._last_unreadable.append(m)
                continue
            resolved.append(m)
            self._event("material_hold_resolved", name=name, kind=h.kind)
        self._held = keep   # `_register` 는 예외를 내지 않으므로 추가한 자료는 보류에 남지 않는다
        still = self.held()
        if still:
            # 보류가 남아 있으면 "유지" 를 남긴다(뺀 뒤에도 상한을 넘음)
            self._event("material_hold_kept", count=len(still))
        return resolved, still

    def cancel_held(self) -> int:
        """선택 창의 취소: 보류된 자료를 모두 버린다. 목록은 바뀌지 않는다. 반환: 버린 수."""
        n = len(self._held)
        for h, _ in self._held:
            self._event("material_hold_cancelled", name=h.name, kind=h.kind)
        self._held = []
        return n

    # ---- 모델에 전달 ----
    def system_prompt(self, app_rules: str, session_prompt: str) -> str:
        """prompt-spec 1절의 순서: 앱 규칙 → `[사용자 문구]` 와 세션 프롬프트 → `[사전 지식]` 과 자료(4-1절).
        세션 프롬프트는 자르거나 바꾸지 않는다(AC-FR2-11)."""
        parts = [app_rules, "[사용자 문구]\n" + session_prompt]
        texts = [m for m in self._items if m.kind == "text"]
        if texts:
            lines = ["[사전 지식] 개수=%d" % len(texts)]
            for m in texts:
                lines.append("[자료] 이름=%s 문자=%d" % (ref_name(m.name), m.chars))
                lines.append(escape_lines(m.text))
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def first_request_images(self) -> list:
        """추가 순서의 이미지 자료(축소 완료)."""
        return [m for m in self._items if m.kind == "image"]

    def _event(self, type: str, **fields) -> None:
        if self._emit:
            try:
                self._emit(type, **fields)
            except Exception:
                pass


def _decode(raw: bytes) -> Optional[str]:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None
