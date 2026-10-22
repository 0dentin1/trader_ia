"""Leitura quantitativa do fluxo de ticks (tape reading): saldo de agressão e velocidade.

- Ativos de bolsa (B3, CME...): usa as flags TICK_FLAG_BUY / TICK_FLAG_SELL do próprio MT5 e o volume real.
- Forex/CFD (sem flags de agressão): aplica a regra do tick (uptick = pressão compradora, downtick = vendedora)
  sobre o preço `last` (se existir) ou sobre o preço médio bid/ask.

Os ticks são agregados em baldes de 1 segundo, mantendo o custo do cálculo constante mesmo em
ativos com centenas de negócios por segundo.
"""
from __future__ import annotations

from collections import deque

import numpy as np

TICK_FLAG_BUY = 32
TICK_FLAG_SELL = 64
TICK_FLAG_LAST = 8


class TickFlow:
    def __init__(self, keep_seconds: int = 180) -> None:
        self._keep = keep_seconds
        self._buckets: deque[list] = deque()  # [second, buy, sell, count]
        self.last_msc = 0
        self._last_px: float | None = None
        self._last_side = 0

    def reset(self) -> None:
        self._buckets.clear()
        self.last_msc = 0
        self._last_px = None
        self._last_side = 0

    def _bucket(self, sec: int) -> list:
        if self._buckets and self._buckets[-1][0] == sec:
            return self._buckets[-1]
        b = [sec, 0.0, 0.0, 0]
        self._buckets.append(b)
        while self._buckets and self._buckets[0][0] < sec - self._keep:
            self._buckets.popleft()
        return b

    def ingest(self, arr: np.ndarray | None) -> int:
        if arr is None or len(arr) == 0:
            return 0
        names = arr.dtype.names or ()
        tm = arr["time_msc"].astype(np.int64)
        mask = tm > self.last_msc
        if not mask.any():
            return 0
        sub = arr[mask]
        n = len(sub)
        flags = sub["flags"].astype(np.int64) if "flags" in names else np.zeros(n, dtype=np.int64)
        last = sub["last"].astype(float) if "last" in names else np.zeros(n)
        bid = sub["bid"].astype(float)
        ask = sub["ask"].astype(float)
        vreal = sub["volume_real"].astype(float) if "volume_real" in names else np.zeros(n)
        vint = sub["volume"].astype(float) if "volume" in names else np.zeros(n)
        tms = sub["time_msc"].astype(np.int64)
        for i in range(n):
            f = int(flags[i])
            has_trade = bool(f & TICK_FLAG_LAST) and last[i] > 0
            vol = vreal[i] if vreal[i] > 0 else vint[i]
            weight = vol if (has_trade and vol > 0) else 1.0
            side = 0
            if f & TICK_FLAG_BUY and not f & TICK_FLAG_SELL:
                side = 1
            elif f & TICK_FLAG_SELL and not f & TICK_FLAG_BUY:
                side = -1
            else:
                if has_trade:
                    px: float | None = float(last[i])
                elif bid[i] > 0 and ask[i] > 0:
                    px = (bid[i] + ask[i]) / 2.0
                else:
                    px = None
                if px is not None and self._last_px is not None:
                    if px > self._last_px:
                        side = 1
                    elif px < self._last_px:
                        side = -1
                    elif has_trade:
                        side = self._last_side  # regra do tick: preço igual herda o último lado
                if px is not None:
                    self._last_px = px
            if side != 0:
                self._last_side = side
            b = self._bucket(int(tms[i]) // 1000)
            if side > 0:
                b[1] += weight
            elif side < 0:
                b[2] += weight
            b[3] += 1
        self.last_msc = int(tms[-1])
        return n

    def metrics(self, now_msc: int, window_s: int = 60, fast_s: int = 5) -> dict:
        now_sec = now_msc // 1000
        start = now_sec - window_s
        fast_start = now_sec - fast_s
        buy = sell = 0.0
        count = fast_count = 0
        for sec, b, s, c in reversed(self._buckets):
            if sec <= start:
                break
            count += c
            buy += b
            sell += s
            if sec > fast_start:
                fast_count += c
        total = buy + sell
        delta = (buy - sell) / total if total > 0 else 0.0
        vel_fast = fast_count / fast_s
        vel_avg = count / window_s
        return {
            "buy": buy, "sell": sell, "delta": delta, "ticks": count,
            "velocity": vel_fast, "velocity_avg": vel_avg,
            "acceleration": (vel_fast / vel_avg) if vel_avg > 0 else 0.0,
            "enough": count >= 20,
        }
