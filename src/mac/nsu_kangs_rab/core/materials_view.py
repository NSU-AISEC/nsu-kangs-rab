"""사전 지식 화면의 모델 (K-19; FR-2 "보류의 처리" ① ~ ⑨, AC-FR2-1 · 2 · 7 · 9 · 10 · 13).

Qt 를 가져오지 않는다. 화면(`app/materials.py`)은 이 모델이 반환한 값을 그대로 표시한다.
판정 논리(상한 · 보류 · 자동 추가)는 `ContextStore` 가 맡고, 이 모델은 호출 결과를 화면에 쓸 값으로 바꾼다.

- `rows()`: 사전 지식 목록의 항목. 텍스트는 이름 · 크기 · 글자 수, 이미지는 이름 · 크기 · 가로 × 세로(글자 수 없음, AC-FR2-1).
- `add_paths(paths)`: 받은 파일 목록의 순서로 추가한다(⑥). 파일 크기 초과는 사실만 알리고(취소만 제공) 선택 창을 거치지 않는다(AC-FR2-10).
- `selection()`: 선택 창의 내용. 보류가 없으면 None. 자료 하나만으로 상한을 넘으면(`removable` 이 거짓) 취소만 제공한다(③).
- `remove(id)`: 사전 지식나 보류 자료를 뺀다. 뺀 뒤 자동 추가된 자료 · 남은 보류 · 버려진 이미지의 사유를 반환한다(⑦ ⑧).
- `cancel()`: 보류를 모두 버린다(④). 목록은 바뀌지 않는다.
"""
from __future__ import annotations
from .i18n import t as _t, tn

import os
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .context import Accepted, ContextStore, Held, Material, Unreadable

# 사전 지식 화면의 문구(기능 정의 FR-2 "사전 지식 화면의 문구", AC-FR2-14): 사유 문구와 조치 문구. 상한 사유의 `{limit}` 는
# 적용된 값으로 바꾼다. 자료의 이름은 `unreadable_text` · `held_text` 가 앞에 붙인다. 어느 문구에도 파일의 내용을 넣지 않는다.
UNREADABLE_TEXT = {
    "not_found": (_t("matview.unreadable_text"), _t("matview.unreadable_text_2")),
    "permission": (_t("matview.unreadable_text_3"), _t("matview.unreadable_text_4")),
    "format": (_t("matview.unreadable_text_5"), _t("matview.unreadable_text_6")),
    "encrypted": (_t("matview.unreadable_text_7"), _t("matview.unreadable_text_8")),
    "no_text": (_t("matview.unreadable_text_9"), _t("matview.unreadable_text_10")),
    "decode": (_t("matview.unreadable_text_11"), _t("matview.unreadable_text_12")),
    "timeout": (_t("matview.unreadable_text_13"), _t("matview.unreadable_text_14")),
    "io": (_t("matview.unreadable_text_15"), _t("matview.unreadable_text_16")),
    "dependency": (_t("matview.unreadable_text_17"), _t("matview.unreadable_text_18")),
    "image_bytes": (_t("matview.unreadable_text_19"), _t("matview.unreadable_text_20")),
    "registered_bytes": (_t("matview.unreadable_text_21"), _t("matview.unreadable_text_22")),
}
HELD_REASON_TEXT = {
    "chars": (_t("matview.held_reason_text"), _t("matview.held_reason_text_2")),
    "images": (_t("matview.held_reason_text_3"), _t("matview.held_reason_text_4")),
    "file_size": (_t("matview.held_reason_text_5"), _t("matview.held_reason_text_6")),
}


def cap_bytes_text(n: int) -> str:
    """상한의 바이트 수를 MB(10^6)로 적는다(3,750,000 → 3.75 MB, 15,000,000 → 15 MB)."""
    return ("%.2f" % (n / 1_000_000)).rstrip("0").rstrip(".") + " MB"


def cap_chars_text(n: int) -> str:
    return _t("matview.cap_chars_text_343") % (n // 10000) if n >= 10000 and n % 10000 == 0 else tn("matview.cap_chars_text_344", n) % n


def format_size(n: int) -> str:
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024)
    return "%.1f MB" % (n / (1024 * 1024))


@dataclass(frozen=True)
class Row:
    id: str
    name: str
    kind: str                    # "text" | "image"
    size_text: str
    chars: Optional[int]         # 이미지는 None(글자 수 없음)
    dimensions: Optional[str]    # 텍스트는 None. "가로 × 세로"
    label: str                   # 목록에 표시하는 한 줄


def row_of(m: Material) -> Row:
    if m.kind == "image":
        dim = "%d × %d" % (m.width, m.height)
        return Row(m.id, m.name, "image", format_size(m.size), None, dim, "%s · %s · %s" % (m.name, format_size(m.size), dim))
    return Row(m.id, m.name, "text", format_size(m.size), m.chars, None,
               tn("matview.row_of_345", m.chars) % (m.name, format_size(m.size), m.chars))


@dataclass(frozen=True)
class HeldRow:
    id: str
    name: str
    kind: str
    reason: str                  # chars | images | file_size
    removable: bool
    text: str                    # 표시 문구(자료 이름 · 글자 수 또는 장 수 · 상한 / 파일 크기 · 제한)


def held_text(h: Held) -> str:
    reason, action = HELD_REASON_TEXT.get(h.reason, (_t("matview.held_text_346"), ""))
    if h.reason == "file_size":
        detail = _t("matview.detail") % (reason, format_size(h.size), format_size(h.limit))
    elif h.reason == "chars":
        detail = tn("matview.detail_2", h.chars) % (reason.format(limit=cap_chars_text(h.limit)), h.chars)
    else:
        detail = reason.format(limit=tn("matview.detail_3", h.limit) % h.limit)
    return "%s: %s. %s" % (h.name, detail, action) if action else "%s: %s" % (h.name, detail)


def held_row(h: Held) -> HeldRow:
    return HeldRow(h.id, h.name, h.kind, h.reason, h.removable, held_text(h))


def unreadable_text(u: Unreadable) -> str:
    reason, action = UNREADABLE_TEXT.get(u.reason, (_t("matview.unreadable_text_350"), ""))
    if "{limit}" in reason:
        reason = reason.format(limit=cap_bytes_text(u.limit) if u.limit else _t("matview.reason"))
    return "%s: %s. %s" % (u.name, reason, action) if action else "%s: %s" % (u.name, reason)


@dataclass
class Selection:
    """선택 창의 내용. `cancel_only` 이면 빼기를 제공하지 않고 사실만 표시한다(③)."""
    registered: list             # Row (추가된 자료, 빼기 후보)
    held: list                   # HeldRow (보류된 자료, 보류된 순서)
    cancel_only: bool
    message: str
    sole_ids: tuple = ()         # 혼합 보류: 단독 초과 자료의 id(빼기 대상에서 제외하고 구별해 표시한다)


@dataclass
class AddReport:
    accepted: list = field(default_factory=list)       # Material (추가됨)
    unreadable: list = field(default_factory=list)     # 사유 문구 (읽을 수 없음 · 바이트 상한 · 합계 상한)
    facts: list = field(default_factory=list)          # HeldRow (파일 크기 초과: 사실 표시, 취소만 제공)
    pending: list = field(default_factory=list)        # HeldRow (선택 창 대상)
    show_selection: bool = False


@dataclass
class RemoveReport:
    removed: bool
    resolved: list = field(default_factory=list)       # Material (자동 추가됨)
    unreadable: list = field(default_factory=list)     # 사유 문구 (보류에서 빠진 이미지, ⑧)
    still_held: list = field(default_factory=list)     # HeldRow
    dropped: list = field(default_factory=list)        # 보류에서 빠진 단독 초과 자료의 이름(혼합 보류, AC-FR2-15)
    show_selection: bool = False                       # 남은 보류가 있으면 선택 창을 다시 표시한다(③ ⑦)


class MaterialsModel:
    def __init__(self, store: ContextStore):
        self.store = store

    # ---- 조회 ----
    def rows(self) -> list:
        return [row_of(m) for m in self.store.materials()]

    def count(self) -> int:
        return self.store.count()

    def held_rows(self) -> list:
        return [held_row(h) for h in self.store.held()]

    def selection(self) -> Optional[Selection]:
        held = self.held_rows()
        if not held:
            return None
        sole = [h for h in held if not h.removable]
        if sole and len(sole) == len(held):   # 모두 단독 초과: 사실만 표시하고 취소만 제공한다(③)
            return Selection(self.rows(), held, True, "; ".join(h.text for h in sole), tuple(h.id for h in sole))
        if sole:     # 혼합(AC-FR2-15): 선택 창 하나에 둘을 구별해 보인다. 단독 초과 자료는 빼기 대상이 아니다
            marked = [HeldRow(h.id, h.name, h.kind, h.reason, h.removable,
                              h.text + _t("matview.marked")) if not h.removable else h for h in held]
            return Selection(self.rows(), marked, False,
                             _t("matview.selection_353")
                             % ", ".join(h.name for h in sole), tuple(h.id for h in sole))
        return Selection(self.rows(), held, False, _t("matview.selection_354"))

    # ---- 추가 ----
    def add_paths(self, paths: Sequence) -> AddReport:
        rep = AddReport()
        for p in paths:
            self._take(self.store.add_file(p), rep)
        rep.show_selection = bool(rep.pending)
        return rep

    def add_text(self, name: str, text: str) -> AddReport:
        rep = AddReport()
        taken = {r.name for r in self.rows()} | {h.name for h in self.held_rows()}
        base = name or _t("materials.paste_name")
        unique, n = base, 2
        while unique in taken:     # FR-2: 같은 이름이 있으면 '붙여넣은 글 2' 처럼 번호를 붙인다(AC-FR2-14)
            unique, n = "%s %d" % (base, n), n + 1
        self._take(self.store.add_text(unique, text), rep)
        rep.show_selection = bool(rep.pending)
        return rep

    def _take(self, r, rep: AddReport) -> None:
        if isinstance(r, Accepted):
            rep.accepted.append(r.material)
        elif isinstance(r, Unreadable):
            rep.unreadable.append(unreadable_text(r))
        elif isinstance(r, Held):
            if r.reason == "file_size":        # 목록 · 보류에 들어가지 않는 사실(AC-FR2-10)
                rep.facts.append(held_row(r))
            else:
                rep.pending.append(held_row(r))

    # ---- 빼기 · 취소 ----
    def remove(self, material_id: str) -> RemoveReport:
        r = self.store.remove(material_id)
        still = [held_row(h) for h in r.still_held]
        return RemoveReport(r.removed, list(r.resolved), [unreadable_text(u) for u in r.unreadable], still,
                            show_selection=bool(still), dropped=[h.name for h in r.dropped])

    def cancel(self) -> int:
        return self.store.cancel_held()


def display_name(path) -> str:
    return os.path.basename(str(path))
