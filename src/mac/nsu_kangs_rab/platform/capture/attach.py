"""첨부 판정 (AC-FR7-15): png · jpg · gif · webp 만 받고 한 번에 최대 5장이다.

`judge_attachments(files, already=0)` 는 입력 순서대로 판정한다. 형식은 이름이 아니라 내용(머리)으로 가린다.
`already` 는 이미 입력창에 붙어 있는 장수이며 합계가 `MAX_ATTACH` 를 넘는 6장째부터 거부한다(전제, 보고 참조).
거부 항목은 사유 코드(`format` · `count`)와 화면에 쓸 문구를 가진다. 판정은 파일을 바꾸지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from ...core.i18n import t as _t
from .imagetypes import image_size

MAX_ATTACH = 5


@dataclass(frozen=True)
class Accepted:
    name: str
    data: bytes
    fmt: str
    width: int
    height: int


@dataclass(frozen=True)
class Rejected:
    name: str
    reason: str   # "format" | "count"
    message: str


def judge_attachments(files: Sequence[Tuple[str, bytes]], already: int = 0) -> Tuple[List[Accepted], List[Rejected]]:
    ok: List[Accepted] = []
    bad: List[Rejected] = []
    for name, data in files:
        info = image_size(data)
        if info is None:
            bad.append(Rejected(name, "format", _t("attach.judge_attachments_439")))
            continue
        if already + len(ok) >= MAX_ATTACH:
            bad.append(Rejected(name, "count", _t("attach.judge_attachments_440") % MAX_ATTACH))
            continue
        fmt, w, h = info
        ok.append(Accepted(name, data, fmt, w, h))
    return ok, bad
