"""정리 문서가 가리키는 이미지의 JPEG 사본 (단계 18, 결정 0194 2 · 4 · 8 · 10항; 기술 계획 2-13절 S18-2). Qt 를 가져오지 않는다.

문서 텍스트의 Markdown 인라인 이미지 `![대체 글](경로 "제목")` 가운데 세션 폴더 안의 JPEG 이 아닌 래스터 이미지(png · gif · webp · bmp)에
`captures/jpeg/<저장된 파일 이름 전체>.jpg` 사본을 만들고 링크를 사본으로 바꾼다. 원본은 지우지 않는다. 변환기 `to_jpeg(원본, 사본)` 은
주입한다(실패하면 예외를 올린다). 변환하지 못한 이미지와 없는 파일은 링크를 그대로 두고 `doc_image` 사건 한 줄(사유와 상대 경로)을 남긴다.
"""
from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from typing import Callable, Iterable, Optional

COPY_DIR = "captures/jpeg"
CONVERT_EXT = {".png", ".gif", ".webp", ".bmp"}
KEEP_EXT = {".jpg", ".jpeg"}
# 경로 셋: ① `<…>` 로 감싼 것 ② 공백을 포함해도 이미지 확장자로 끝나는 부분까지(감싸지 않은 공백 경로, D-231)
# ③ 공백 없는 그 밖의 것. ②는 `)` · `"` · `<` · `>` · 줄바꿈을 포함하지 않는다.
_LINK = re.compile(r'(!\[[^\]]*\]\()\s*(<[^>\n]+>|[^)"<>\n]*?\.(?i:png|gif|webp|bmp|jpe?g)(?=(?:\s+"[^"\n]*")?\s*\))|[^)\s]+)((?:\s+"[^"\n]*")?)\s*(\))')
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def deleted_paths(view) -> set:
    """지운 카드에 딸린 캡처 · 첨부의 상대 경로(사본을 만들지 않는다, 결정 0194 10항)."""
    gone = view.deleted_ns
    return {c.get("path") for c in view.captures if c.get("n") in gone and c.get("path")}


def _rel(raw: str) -> Optional[str]:
    """세션 폴더 안의 상대 경로(정규화)이면 반환하고, URL · 절대 경로 · 폴더 밖 · 숨김 파일이면 None."""
    p = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
    if not p or _SCHEME.match(p) or p.startswith(("/", "#", "~")) or "\\" in p:
        return None
    n = posixpath.normpath(p)
    if n.startswith("..") or n == ".":
        return None
    if any(part.startswith(".") for part in n.split("/")):
        return None
    return n


def _link(rel: str) -> str:
    return "<%s>" % rel if re.search(r"[\s()]", rel) else rel


def convert_links(text: str, folder, to_jpeg: Callable[[str, str], None], emit: Optional[Callable] = None,
                  skip: Iterable[str] = ()) -> str:
    """`text` 의 이미지 링크를 JPEG 사본으로 바꾼 문서를 반환한다. 바꿀 것이 없으면 같은 텍스트이다."""
    base = Path(folder)
    skip = {posixpath.normpath(s) for s in skip}
    done: dict = {}

    def note(kind: str, rel: str, detail: str = "") -> None:
        if emit is not None:
            try:
                emit("doc_image", kind=kind, path=rel, detail=detail)
            except Exception:
                pass

    def resolve(rel: str) -> Optional[str]:
        if rel in done:
            return done[rel]
        done[rel] = None
        ext = posixpath.splitext(rel)[1].lower()
        if ext in KEEP_EXT or ext not in CONVERT_EXT or rel in skip:
            return None
        src = base / rel
        if not src.is_file():
            note("missing", rel)
            return None
        new = "%s/%s.jpg" % (COPY_DIR, posixpath.basename(rel))
        dest = base / new
        try:
            if not (dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime):
                dest.parent.mkdir(parents=True, exist_ok=True)
                to_jpeg(str(src), str(dest))
                if not dest.is_file() or dest.stat().st_size == 0:
                    raise OSError("empty")
        except Exception as e:  # noqa: BLE001 — 변환 실패는 문서 생성을 막지 않는다(결정 0194 8항)
            try:
                if dest.exists():
                    os.remove(dest)
            except OSError:
                pass
            note("convert_failed", rel, type(e).__name__)
            return None
        done[rel] = new
        return new

    def sub(m: re.Match) -> str:
        rel = _rel(m.group(2))
        if rel is None:
            return m.group(0)
        new = resolve(rel)
        if new is None:
            return m.group(0)
        return "%s%s%s)" % (m.group(1), _link(new), m.group(3))

    return _LINK.sub(sub, text)
