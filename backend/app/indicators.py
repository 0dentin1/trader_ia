"""Indicadores técnicos vetorizados (pandas/numpy), sem dependências externas.

Fórmulas clássicas: EMA, RSI/ATR/ADX com suavização de Wilder (RMA), Estocástico Lento (14,3,3),
VWAP diária (reinicia a cada dia do servidor da corretora) com bandas de desvio padrão ponderado
por volume, RVOL (volume / média das 20 velas anteriores) e microestrutura (máx/mín das N velas anteriores).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MICRO_N = 10


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = rma(d.clip(lower=0.0), n)
    dn = rma((-d).clip(lower=0.0), n)
    rs = up / dn.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(dn != 0.0, 100.0)
    out = out.where(~((up == 0.0) & (dn == 0.0)), 50.0)
    return out.where(up.notna())


def stoch_slow(df: pd.DataFrame, k: int = 14, smooth: int = 3, d: int = 3) -> tuple[pd.Series, pd.Series]:
    ll = df["low"].rolling(k).min()
    hh = df["high"].rolling(k).max()
    rng = (hh - ll).replace(0.0, np.nan)
    raw = 100.0 * (df["close"] - ll) / rng
    slow_k = raw.rolling(smooth).mean()
    slow_d = slow_k.rolling(d).mean()
    return slow_k, slow_d


def adx(df: pd.DataFrame, n: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    atr_ = rma(true_range(df), n).replace(0.0, np.nan)
    plus_di = 100.0 * rma(plus_dm, n) / atr_
    minus_di = 100.0 * rma(minus_dm, n) / atr_
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return rma(dx.fillna(0.0), n), plus_di, minus_di


def volume_series(df: pd.DataFrame) -> pd.Series:
    """Volume real (bolsa) quando disponível; caso contrário volume de ticks (forex/CFD)."""
    if "real_volume" in df and float(df["real_volume"].tail(50).sum()) > 0:
        return df["real_volume"].astype(float)
    return df["tick_volume"].astype(float)


def daily_vwap(df: pd.DataFrame, vol: pd.Series) -> pd.DataFrame:
    day = df["time"] // 86400
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    v = vol.where(vol > 0, 0.0)
    cv = v.groupby(day).cumsum()
    cpv = (tp * v).groupby(day).cumsum()
    cpv2 = (tp * tp * v).groupby(day).cumsum()
    cvn = cv.replace(0.0, np.nan)
    vwap = cpv / cvn
    sd = np.sqrt((cpv2 / cvn - vwap * vwap).clip(lower=0.0))
    out = pd.DataFrame({"vwap": vwap, "vwap_sd": sd}, index=df.index)
    # O primeiro dia da janela pode estar incompleto -> VWAP inválida; descarta-o se houver outro dia.
    first_day = day.iloc[0]
    if day.iloc[-1] != first_day:
        first_day_partial = int(df["time"].iloc[0]) % 86400 != 0
        if first_day_partial:
            out.loc[day == first_day, ["vwap", "vwap_sd"]] = np.nan
    out["vwap_up1"] = out["vwap"] + out["vwap_sd"]
    out["vwap_dn1"] = out["vwap"] - out["vwap_sd"]
    out["vwap_up2"] = out["vwap"] + 2.0 * out["vwap_sd"]
    out["vwap_dn2"] = out["vwap"] - 2.0 * out["vwap_sd"]
    return out


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Recebe OHLCV do MT5 (colunas time, open, high, low, close, tick_volume, spread, real_volume)."""
    out = df.copy()
    c = out["close"]
    out["vol"] = volume_series(out)
    out["ema9"] = ema(c, 9)
    out["ema21"] = ema(c, 21)
    out["ema200"] = ema(c, 200)
    out["atr"] = rma(true_range(out), 14)
    out["atr_ma50"] = out["atr"].rolling(50).mean()
    out["rsi"] = rsi(c, 14)
    out["stoch_k"], out["stoch_d"] = stoch_slow(out, 14, 3, 3)
    out["adx"], out["plus_di"], out["minus_di"] = adx(out, 14)
    out["vol_ma20"] = out["vol"].shift(1).rolling(20).mean()
    out["rvol"] = out["vol"] / out["vol_ma20"].replace(0.0, np.nan)
    out["micro_high"] = out["high"].shift(1).rolling(MICRO_N).max()
    out["micro_low"] = out["low"].shift(1).rolling(MICRO_N).min()
    vw = daily_vwap(out, out["vol"])
    for col in vw.columns:
        out[col] = vw[col]
    return out


CHART_COLS = ("time", "open", "high", "low", "close", "vol", "vwap", "vwap_up1", "vwap_dn1",
              "vwap_up2", "vwap_dn2", "ema9", "ema21", "ema200")


def chart_rows(df: pd.DataFrame, tail: int | None = None) -> list[dict]:
    """Converte as velas + indicadores para o formato consumido pelo gráfico (NaN -> None)."""
    sub = df if tail is None else df.tail(tail)
    cols = [c for c in CHART_COLS if c in sub.columns]
    arr = sub[cols].to_numpy(dtype=float)
    rows: list[dict] = []
    for r in arr:
        row = {}
        for i, col in enumerate(cols):
            v = r[i]
            if col == "time":
                row[col] = int(v)
            else:
                row[col] = float(v) if np.isfinite(v) else None
        rows.append(row)
    return rows
