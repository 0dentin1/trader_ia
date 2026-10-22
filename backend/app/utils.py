"""Utilitários: serialização segura para JSON, logs e normalização numérica."""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

import numpy as np


def clean(v: Any) -> Any:
    """Converte tipos numpy/pandas em tipos JSON e NaN/inf em None (recursivo)."""
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, deque)):
        return [clean(x) for x in v]
    if isinstance(v, np.ndarray):
        return [clean(x) for x in v.tolist()]
    return str(v)


def fnum(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def step_decimals(step: float) -> int:
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def round_to_step(value: float, step: float, digits: int) -> float:
    if step <= 0:
        return round(value, digits)
    return round(round(value / step) * step, digits)


def floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    n = math.floor(value / step + 1e-9)
    return round(n * step, step_decimals(step))


class LogBook:
    """Log de pensamento/ação da IA, thread-safe, com sequência incremental."""

    def __init__(self, maxlen: int = 400) -> None:
        self._lock = threading.Lock()
        self._items: deque[dict] = deque(maxlen=maxlen)
        self._seq = 0
        self._throttle: dict[str, float] = {}

    def add(self, msg: str, level: str = "info", mode: str | None = None) -> dict:
        with self._lock:
            self._seq += 1
            entry = {
                "id": self._seq,
                "ts": datetime.now().strftime("%H:%M:%S"),
                "epoch": time.time(),
                "level": level,
                "mode": mode,
                "msg": msg,
            }
            self._items.append(entry)
            return entry

    def throttled(self, key: str, interval_s: float, msg: str, level: str = "info", mode: str | None = None) -> None:
        now = time.monotonic()
        if now - self._throttle.get(key, 0.0) >= interval_s:
            self._throttle[key] = now
            self.add(msg, level, mode)

    def since(self, seq: int) -> list[dict]:
        with self._lock:
            return [e for e in self._items if e["id"] > seq]

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._items)

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq
