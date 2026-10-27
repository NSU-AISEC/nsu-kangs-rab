"""`audio` → `stt` 로 주고받는 자료형 (기술 계획 2-3절 `PcmBlock`)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class PcmBlock:
    """float32, 16 kHz, 단일 채널. `t_mono` 는 블록 첫 표본의 단조 시각(초)."""
    samples: np.ndarray
    t_mono: float
