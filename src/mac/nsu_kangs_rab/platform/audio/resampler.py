"""`Resampler`: 장치 속도 · 다채널 → 16 kHz 단일 채널 float32 (기술 계획 B-12).

`scipy.signal.resample_poly` 를 쓰고 블록 경계에서 끊김이 없게 이어 붙인다: 이전 입력의 꼬리를 문맥으로 남기고, 필터의
양쪽 지지 구간이 모두 있는 출력만 낸다(마지막 부분은 `flush()` 가 0 으로 채워 낸다). 어떤 크기로 쪼개 넣어도 한 번에
변환한 결과와 같다(오차 1e-5 미만). 채널은 평균으로 다운믹스한다. 16 kHz 모노는 그대로 통과한다.
"""
from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly

TARGET = 16000


class Resampler:
    def __init__(self, src_rate: int, dst_rate: int = TARGET):
        if src_rate <= 0 or dst_rate <= 0:
            raise ValueError("속도는 양수여야 한다")
        g = gcd(int(src_rate), int(dst_rate))
        self.src_rate, self.dst_rate = int(src_rate), int(dst_rate)
        self.up, self.down = self.dst_rate // g, self.src_rate // g
        self._passthrough = self.up == self.down
        half_len = 10 * max(self.up, self.down)               # resample_poly 의 기본 FIR 반길이(상승 속도 기준)
        self._margin = -(-half_len // self.up) + 2            # 입력 표본 수
        self._buf = np.zeros(0, dtype=np.float64)
        self._buf_start = 0       # buf[0] 의 절대 입력 위치(down 의 배수)
        self._emitted = 0         # 낸 출력 표본 수
        self._total_in = 0

    @staticmethod
    def _mono(x: np.ndarray) -> np.ndarray:
        x = np.asarray(x)
        if x.ndim == 2:
            x = x.mean(axis=1)
        return x.astype(np.float64, copy=False)

    def process(self, x: np.ndarray) -> np.ndarray:
        x = self._mono(x)
        if self._passthrough:
            return x.astype(np.float32)
        self._total_in += x.size
        self._buf = np.concatenate([self._buf, x])
        return self._emit(final=False)

    def flush(self) -> np.ndarray:
        if self._passthrough:
            return np.zeros(0, dtype=np.float32)
        return self._emit(final=True)

    def _emit(self, final: bool) -> np.ndarray:
        if self._buf.size == 0 and not final:
            return np.zeros(0, dtype=np.float32)
        y = resample_poly(self._buf, self.up, self.down) if self._buf.size else np.zeros(0)
        base = self._buf_start * self.up // self.down            # y[0] 의 절대 출력 위치
        n_total_out = -(-self._total_in * self.up // self.down)  # 지금까지 입력으로 낼 수 있는 전체 출력 수
        if final:
            last = n_total_out
        else:
            # 입력 위치 j*down/up 이 buf 끝에서 margin 이상 떨어진 출력만 낸다
            end_in = self._buf_start + self._buf.size - self._margin
            last = max(0, (end_in * self.up) // self.down)
        lo = self._emitted
        out = y[lo - base:last - base] if last > lo else np.zeros(0)
        if last > lo:
            self._emitted = last
        if not final:  # 문맥만 남기고 앞을 버린다 (버리는 위치는 down 의 배수)
            keep_from_in = (self._emitted * self.down) // self.up - self._margin
            keep_from_in = max(self._buf_start, (keep_from_in // self.down) * self.down)
            cut = keep_from_in - self._buf_start
            if cut > 0:
                self._buf = self._buf[cut:]
                self._buf_start = keep_from_in
        return out.astype(np.float32)
