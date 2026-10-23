"""Motor de Análise Quantitativa V5 (MEGA BRAIN) — 5 Famílias de Estratégias Institucionais,
Detector Determinístico de Regimes, Validação Estrita de Timeframes e Dados (Zero Viés de Falta de Dados),
Cálculo Objetivo de Espaço Estrutural e Separação entre Score Heurístico e Probabilidade Calibrada."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ALGO_VERSION, MAX_TICK_AGE_S, PILLAR_NAMES, ModeConfig

REGIME_PT = {
    "TREND_UP": "Tendência Forte de Alta",
    "TREND_DOWN": "Tendência Forte de Baixa",
    "PULLBACK_UP": "Tendência Moderada / Pullback de Alta",
    "PULLBACK_DOWN": "Tendência Moderada / Pullback de Baixa",
    "WEAK_TREND_UP": "Tendência Fraca de Alta",
    "WEAK_TREND_DOWN": "Tendência Fraca de Baixa",
    "RANGE": "Mercado Lateral / Consolidação",
    "HIGH_VOL": "Alta Volatilidade",
    "LOW_VOL": "Baixa Volatilidade (Sem Amplitude)",
    "REGIME_TRANSITION": "Transição de Regime (Divergência M1/M5)",
    "DISPROPORTIONATE_SPREAD": "Spread Desproporcional ao Alvo/ATR",
    "UNFAVORABLE_EXECUTION": "Execução Desfavorável",
    "INCOMPLETE_DATA": "Dados Incompletos ou Desatualizados",
    "UNKNOWN": "Indefinido",
}

STRATEGY_FAMILIES = {
    "EMA_PULLBACK": "Pullback Institucional EMA 9/21",
    "SMC_LIQUIDITY_SWEEP": "SMC Varredura de Liquidez",
    "VOLATILITY_SQUEEZE": "Explosão de Compressão (Breakout)",
    "VWAP_INSTITUTIONAL": "Defesa/Rejeição Institucional na VWAP",
    "MTF_MOMENTUM": "Fluxo Sincronizado M1+M5+M15",
}


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def _pillar(
    idx: int,
    weight: float,
    value_str: str,
    checks: list[tuple[str, bool, float]],
    continuous_score: float | None = None,
) -> dict:
    if continuous_score is None:
        score = sum(w for _, ok, w in checks if ok)
    else:
        score = continuous_score
    score = round(_clamp(score, 0.0, 1.0), 3)
    return {
        "id": idx,
        "name": PILLAR_NAMES[idx - 1],
        "tag": f"P{idx}",
        "weight": weight,
        "score": score,
        "ok": score >= 0.65,
        "value": value_str,
        "checks": [{"label": lbl, "ok": bool(ok)} for lbl, ok, _ in checks],
    }


def _htf_summary(htf_df: pd.DataFrame | None, server_now: int = 0, max_stale_s: int = 1200) -> dict:
    """
    Resumo completo do Timeframe Superior (M5 ou M15).
    IMPORTANTE (Parte 2.9): A ausência ou desatualização de M5/M15 retorna `available=False`
    e NUNCA é tratada como confirmação positiva de tendência.
    """
    if htf_df is None or len(htf_df) < 35:
        return {
            "available": False,
            "stale": False,
            "reason": "Histórico insuficiente no timeframe superior (< 35 barras).",
            "trend": 0,
            "bias21": 0,
            "bias9": 0,
            "bar_dir": 0,
            "bar_body_atr": 0.0,
            "atr": 0.0,
            "rsi": 50.0,
            "bar_time": 0,
        }

    last = htf_df.iloc[-1]
    prev = htf_df.iloc[-2]
    c = _f(last.get("close"))
    o = _f(last.get("open"))
    h = _f(last.get("high"))
    l = _f(last.get("low"))
    e9 = _f(last.get("ema9"))
    e21 = _f(last.get("ema21"))
    e200 = _f(last.get("ema200"))
    atr_h = _f(last.get("atr"))
    rsi_h = _f(last.get("rsi"))
    bar_t = int(last.get("time") or 0)

    if None in (c, o, h, l, e9, e21, atr_h, rsi_h) or atr_h <= 0:
        return {
            "available": False,
            "stale": False,
            "reason": "Indicadores inválidos (NaN/inf) no timeframe superior.",
            "trend": 0,
            "bias21": 0,
            "bias9": 0,
            "bar_dir": 0,
            "bar_body_atr": 0.0,
            "atr": 0.0,
            "rsi": 50.0,
            "bar_time": bar_t,
        }

    if server_now > 0 and bar_t > 0 and (server_now - bar_t) > max_stale_s:
        return {
            "available": False,
            "stale": True,
            "reason": f"Timeframe superior desatualizado ({server_now - bar_t}s > {max_stale_s}s).",
            "trend": 0,
            "bias21": 0,
            "bias9": 0,
            "bar_dir": 0,
            "bar_body_atr": 0.0,
            "atr": atr_h,
            "rsi": round(rsi_h, 1),
            "bar_time": bar_t,
        }

    e200_val = e200 if e200 is not None else e21
    body = c - o
    prev_c = _f(prev.get("close")) or c
    prev_o = _f(prev.get("open")) or o
    prev_body = prev_c - prev_o

    if c > e21 and e9 >= e21:
        bias21 = 1
    elif c < e21 and e9 <= e21:
        bias21 = -1
    else:
        bias21 = 1 if c >= e21 else -1

    if c > e200_val and e21 >= e200_val:
        trend = 1
    elif c < e200_val and e21 <= e200_val:
        trend = -1
    else:
        trend = bias21

    bias9 = 1 if c >= e9 else -1
    bar_dir = 1 if body > 0.04 * atr_h else (-1 if body < -0.04 * atr_h else (1 if prev_body >= 0 else -1))

    return {
        "available": True,
        "stale": False,
        "reason": "",
        "trend": trend,
        "bias21": bias21,
        "bias9": bias9,
        "bar_dir": bar_dir,
        "bar_body_atr": round(body / atr_h, 3),
        "atr": atr_h,
        "rsi": round(rsi_h, 1),
        "bar_time": bar_t,
    }


def classify_structural_room(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr: float,
    d: int,
    htf_m5: dict,
) -> dict:
    """
    Avalia objetivamente o espaço estrutural até suporte/resistência (Parte 2.10).
    NUNCA atribui 2.20 ATR automaticamente apenas porque o preço tocou ou ultrapassou o nível.
    Distingue:
    - BELOW_RESISTANCE / ABOVE_SUPPORT (preço ainda aquém do nível)
    - POTENTIAL_BREAKOUT (rompimento intrabar sem fechamento confirmado -> BLOQUEADO)
    - CONFIRMED_BREAKOUT (vela anterior fechou além do nível com corpo forte e sem rejeição)
    - RETEST_CONFIRMED (rompeu nível anterior, recuou para testar e defendeu a favor)
    - UNKNOWN_STRUCTURE (histórico insuficiente ou range degenerado -> BLOQUEADO)
    """
    if len(highs) < 30 or atr <= 0:
        return {
            "status": "UNKNOWN_STRUCTURE",
            "room_atr": 0.0,
            "confirmed": False,
            "barrier_price": 0.0,
            "reason": "Estrutura de suporte/resistência insuficiente (< 30 barras).",
        }

    price = float(closes[-1])
    o0, h0, l0, c0 = float(opens[-1]), float(highs[-1]), float(lows[-1]), float(closes[-1])
    o1, h1, l1, c1 = float(opens[-2]), float(highs[-2]), float(lows[-2]), float(closes[-2])
    rng0 = max(h0 - l0, 1e-9)
    rng1 = max(h1 - l1, 1e-9)
    body1 = c1 - o1
    uw0_pct = (h0 - max(o0, c0)) / rng0
    lw0_pct = (min(o0, c0) - l0) / rng0
    uw1_pct = (h1 - max(o1, c1)) / rng1
    lw1_pct = (min(o1, c1) - l1) / rng1

    # Estrutura local das 24 velas anteriores fechadas (excluindo B0)
    swing_high_24 = float(np.max(highs[-25:-1]))
    swing_low_24 = float(np.min(lows[-25:-1]))
    # Estrutura anterior a B1 (para verificar se B1 fechou rompendo o topo/fundo prévio)
    prior_high_23 = float(np.max(highs[-26:-2]))
    prior_low_23 = float(np.min(lows[-26:-2]))
    # Estrutura mais ampla (até 90 barras fechadas)
    look_macro = min(len(highs) - 1, 90)
    macro_high = float(np.max(highs[-look_macro:-1]))
    macro_low = float(np.min(lows[-look_macro:-1]))

    if swing_high_24 - swing_low_24 < 0.40 * atr:
        return {
            "status": "UNKNOWN_STRUCTURE",
            "room_atr": 0.20,
            "confirmed": False,
            "barrier_price": swing_high_24 if d > 0 else swing_low_24,
            "reason": "Estrutura comprimida/indefinida (< 0,40 ATR de amplitude em 24 barras).",
        }

    m5_aligned = bool(htf_m5.get("available") and htf_m5.get("bias21", 0) * d > 0)

    if d > 0:
        # COMPRA: avaliando espaço até resistência (swing_high_24)
        raw_dist_atr = (swing_high_24 - price) / atr
        if raw_dist_atr >= 0.15:
            # Preço ainda abaixo da resistência de 24 velas
            enough = raw_dist_atr >= 1.15
            return {
                "status": "BELOW_RESISTANCE",
                "room_atr": round(float(np.clip(raw_dist_atr, 0.05, 2.80)), 2),
                "confirmed": enough,
                "barrier_price": swing_high_24,
                "reason": (
                    f"Espaço livre até resistência: {raw_dist_atr:.2f} ATR"
                    if enough
                    else f"Resistência próxima em {swing_high_24} ({raw_dist_atr:.2f} ATR < 1,15 ATR)"
                ),
            }

        # Preço está encostado ou acima de prior_high_23 / swing_high_24: verificar se é rompimento confirmado ou falso
        b1_broke_clean = (
            c1 >= prior_high_23 + 0.08 * atr
            and body1 >= 0.45 * rng1
            and uw1_pct <= 0.25
            and c0 >= c1 - 0.10 * atr
            and uw0_pct <= 0.28
            and m5_aligned
        )
        # Reteste confirmado de topo anterior rompido nas últimas 10 barras
        mid_high_10 = float(np.max(highs[-15:-5]))
        retest_ok = (
            c1 > mid_high_10
            and l1 <= mid_high_10 + 0.18 * atr
            and lw1_pct >= 0.35
            and c0 > o0
            and m5_aligned
        )

        if b1_broke_clean or retest_ok:
            # Calcula espaço real até o topo macro (90 barras) ou projeção conservadora do ATR do M5
            macro_room = (macro_high - price) / atr if macro_high > price + 0.30 * atr else 0.0
            htf_proj = (float(htf_m5.get("atr") or atr) * 0.70) / atr if htf_m5.get("available") else 1.35
            confirmed_room = max(macro_room, min(1.65, max(1.25, htf_proj)))
            status_code = "CONFIRMED_BREAKOUT" if b1_broke_clean else "RETEST_CONFIRMED"
            return {
                "status": status_code,
                "room_atr": round(float(np.clip(confirmed_room, 1.20, 2.20)), 2),
                "confirmed": True,
                "barrier_price": macro_high,
                "reason": f"Rompimento/reteste confirmado acima de {prior_high_23} com M5 alinhado.",
            }

        # Caso contrário: rompimento potencial NÃO confirmado (possível topo duplo / armadilha)
        return {
            "status": "POTENTIAL_BREAKOUT",
            "room_atr": round(max(0.05, raw_dist_atr), 2),
            "confirmed": False,
            "barrier_price": swing_high_24,
            "reason": "Preço testando topo/resistência sem fechamento de rompimento confirmado (risco de falso rompimento).",
        }

    else:
        # VENDA: avaliando espaço até suporte (swing_low_24)
        raw_dist_atr = (price - swing_low_24) / atr
        if raw_dist_atr >= 0.15:
            enough = raw_dist_atr >= 1.15
            return {
                "status": "ABOVE_SUPPORT",
                "room_atr": round(float(np.clip(raw_dist_atr, 0.05, 2.80)), 2),
                "confirmed": enough,
                "barrier_price": swing_low_24,
                "reason": (
                    f"Espaço livre até suporte: {raw_dist_atr:.2f} ATR"
                    if enough
                    else f"Suporte próximo em {swing_low_24} ({raw_dist_atr:.2f} ATR < 1,15 ATR)"
                ),
            }

        b1_broke_clean = (
            c1 <= prior_low_23 - 0.08 * atr
            and (-body1) >= 0.45 * rng1
            and lw1_pct <= 0.25
            and c0 <= c1 + 0.10 * atr
            and lw0_pct <= 0.28
            and m5_aligned
        )
        mid_low_10 = float(np.min(lows[-15:-5]))
        retest_ok = (
            c1 < mid_low_10
            and h1 >= mid_low_10 - 0.18 * atr
            and uw1_pct >= 0.35
            and c0 < o0
            and m5_aligned
        )

        if b1_broke_clean or retest_ok:
            macro_room = (price - macro_low) / atr if macro_low < price - 0.30 * atr else 0.0
            htf_proj = (float(htf_m5.get("atr") or atr) * 0.70) / atr if htf_m5.get("available") else 1.35
            confirmed_room = max(macro_room, min(1.65, max(1.25, htf_proj)))
            status_code = "CONFIRMED_BREAKOUT" if b1_broke_clean else "RETEST_CONFIRMED"
            return {
                "status": status_code,
                "room_atr": round(float(np.clip(confirmed_room, 1.20, 2.20)), 2),
                "confirmed": True,
                "barrier_price": macro_low,
                "reason": f"Rompimento/reteste confirmado abaixo de {prior_low_23} com M5 alinhado.",
            }

        return {
            "status": "POTENTIAL_BREAKOUT",
            "room_atr": round(max(0.05, raw_dist_atr), 2),
            "confirmed": False,
            "barrier_price": swing_low_24,
            "reason": "Preço testando fundo/suporte sem fechamento de rompimento confirmado (risco de falso rompimento).",
        }


def classify_market_regime(
    *,
    price: float,
    e9: float,
    e21: float,
    e200: float,
    adx_v: float,
    pdi: float,
    mdi: float,
    atr: float,
    atr_ratio: float,
    atr_points: float,
    spread_price: float,
    spread_points: int,
    max_spread: int,
    htf_m5: dict,
    htf_m15: dict,
    flow_ok: bool,
    tick_stale: bool,
    buy_strats: list[str],
    sell_strats: list[str],
) -> tuple[str, str]:
    """
    Detector determinístico e testável de regimes de mercado (Parte 4.4).
    Retorna `(ui_regime_code, detailed_regime_code)`.
    """
    if not htf_m5.get("available") or not htf_m15.get("available") or tick_stale:
        return "UNKNOWN", "INCOMPLETE_DATA"
    if spread_points > max_spread or spread_price > 0.25 * atr:
        return "HIGH_VOL", "DISPROPORTIONATE_SPREAD"
    if not flow_ok and atr_points < 7.0:
        return "RANGE", "UNFAVORABLE_EXECUTION"
    if atr_points < 6.0 or atr_ratio < 0.55:
        return "RANGE", "LOW_VOL"
    if atr_ratio > 2.20:
        return "HIGH_VOL", "HIGH_VOL"

    m1_dir = 1 if (price > e21 and e9 >= e21) else (-1 if (price < e21 and e9 <= e21) else 0)
    m5_dir = int(htf_m5.get("bias21") or 0)
    if m1_dir != 0 and m5_dir != 0 and m1_dir * m5_dir < 0:
        return "RANGE", "REGIME_TRANSITION"

    if adx_v >= 22.0 and pdi > mdi and m1_dir > 0 and m5_dir > 0 and price >= e200:
        return "TREND_UP", "TREND_UP"
    if adx_v >= 22.0 and mdi > pdi and m1_dir < 0 and m5_dir < 0 and price <= e200:
        return "TREND_DOWN", "TREND_DOWN"

    if m1_dir > 0 and m5_dir > 0:
        if buy_strats and ("Pullback" in buy_strats[0] or "SMC" in buy_strats[0]):
            return "PULLBACK_UP", "PULLBACK_UP"
        return "TREND_UP", "WEAK_TREND_UP"
    if m1_dir < 0 and m5_dir < 0:
        if sell_strats and ("Pullback" in sell_strats[0] or "SMC" in sell_strats[0]):
            return "PULLBACK_DOWN", "PULLBACK_DOWN"
        return "TREND_DOWN", "WEAK_TREND_DOWN"

    return "RANGE", "RANGE"


def _analyze_candles_and_strategies(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    ema9s: np.ndarray,
    ema21s: np.ndarray,
    ema200s: np.ndarray,
    vwaps: np.ndarray,
    atr: float,
    rsi_v: float,
    rvol: float,
    vwap_dist_atr: float,
    htf_m5: dict,
    htf_m15: dict,
    delta: float,
    flow_ok: bool,
    digits: int,
) -> dict:
    """
    Analisa a anatomia das velas (B3, B2, B1, B0) e identifica as 5 famílias de estratégias.
    IMPORTANTE (Parte 2.9): Exige `htf_m5["available"] == True` e `htf_m15["available"] == True`.
    A falta de dados de M5 ou M15 NUNCA é tratada como tendência favorável.
    """
    eps = max(atr * 0.05, 1e-9)

    o0, h0, l0, c0 = float(opens[-1]), float(highs[-1]), float(lows[-1]), float(closes[-1])
    rng0 = max(h0 - l0, eps)
    body0 = c0 - o0
    abs_body0 = abs(body0)
    uw0_pct = (h0 - max(o0, c0)) / rng0
    lw0_pct = (min(o0, c0) - l0) / rng0
    pos0 = (c0 - l0) / rng0
    stretch0_atr = abs_body0 / max(atr, 1e-9)

    o1, h1, l1, c1 = float(opens[-2]), float(highs[-2]), float(lows[-2]), float(closes[-2])
    rng1 = max(h1 - l1, eps)
    body1 = c1 - o1
    abs_body1 = abs(body1)
    uw1_pct = (h1 - max(o1, c1)) / rng1
    lw1_pct = (min(o1, c1) - l1) / rng1
    body1_pct = abs_body1 / rng1
    pos1 = (c1 - l1) / rng1

    o2, h2, l2, c2 = float(opens[-3]), float(highs[-3]), float(lows[-3]), float(closes[-3])
    rng2 = max(h2 - l2, eps)
    body2 = c2 - o2
    uw2_pct = (h2 - max(o2, c2)) / rng2
    lw2_pct = (min(o2, c2) - l2) / rng2

    o3, c3 = float(opens[-4]), float(closes[-4])
    body3 = c3 - o3

    e9, e21, _ = float(ema9s[-1]), float(ema21s[-1]), float(ema200s[-1])
    vwap_now = float(vwaps[-1]) if np.isfinite(vwaps[-1]) else e21

    b1_bull_hammer = lw1_pct >= 0.42 and uw1_pct <= 0.28 and pos1 >= 0.56 and rng1 >= 0.30 * atr
    b1_bear_star = uw1_pct >= 0.42 and lw1_pct <= 0.28 and pos1 <= 0.44 and rng1 >= 0.30 * atr
    b1_bull_engulf = body1 > 0 and body2 < 0 and c1 >= o2 and abs_body1 >= abs(body2) * 0.85 and pos1 >= 0.62
    b1_bear_engulf = body1 < 0 and body2 > 0 and c1 <= o2 and abs_body1 >= abs(body2) * 0.85 and pos1 <= 0.38
    b1_bull_marubozu = body1 > 0 and body1_pct >= 0.62 and pos1 >= 0.72 and rng1 >= 0.38 * atr
    b1_bear_marubozu = body1 < 0 and body1_pct >= 0.62 and pos1 <= 0.28 and rng1 >= 0.38 * atr

    b0_bull_pin = lw0_pct >= 0.44 and uw0_pct <= 0.25 and pos0 >= 0.60 and rng0 >= 0.30 * atr
    b0_bear_pin = uw0_pct >= 0.44 and lw0_pct <= 0.25 and pos0 <= 0.40 and rng0 >= 0.30 * atr

    broke_prev_high = c0 > h1
    broke_prev_low = c0 < l1
    above_prev_mid = c0 >= (h1 + l1) * 0.5
    below_prev_mid = c0 <= (h1 + l1) * 0.5

    three_down = body1 < 0 and body2 < 0 and body3 < 0
    three_up = body1 > 0 and body2 > 0 and body3 > 0

    lower_wick_pressure = lw1_pct * 0.45 + lw0_pct * 0.35 + lw2_pct * 0.20
    upper_wick_pressure = uw1_pct * 0.45 + uw0_pct * 0.35 + uw2_pct * 0.20
    wick_net = lower_wick_pressure - upper_wick_pressure

    # --- VALIDAÇÃO ESTRITA DE TENDÊNCIA MULTI-TIMEFRAME (Parte 2.9: sem dados = False!) ---
    m1_up_trend = c0 >= e21 and e9 >= e21 - 0.05 * atr
    m1_dn_trend = c0 <= e21 and e9 <= e21 + 0.05 * atr
    m5_avail = bool(htf_m5.get("available"))
    m15_avail = bool(htf_m15.get("available"))

    m5_up = bool(m5_avail and htf_m5["bias21"] > 0 and htf_m5["bar_body_atr"] >= -0.12)
    m5_dn = bool(m5_avail and htf_m5["bias21"] < 0 and htf_m5["bar_body_atr"] <= 0.12)
    m15_up = bool(m15_avail and htf_m15["trend"] >= 0)
    m15_dn = bool(m15_avail and htf_m15["trend"] <= 0)

    # 1. PULLBACK INSTITUCIONAL NA EMA 9/21 + IGNIÇÃO
    touched_ema_up = (min(l1, l0) <= max(e9, e21) + 0.18 * atr) and (c0 > e9) and (body0 > 0 or c1 > o1)
    touched_ema_dn = (max(h1, h0) >= min(e9, e21) - 0.18 * atr) and (c0 < e9) and (body0 < 0 or c1 < o1)
    strat_pullback_buy = bool(m1_up_trend and m5_up and touched_ema_up and (b1_bull_hammer or b1_bull_engulf or broke_prev_high or b0_bull_pin))
    strat_pullback_sell = bool(m1_dn_trend and m5_dn and touched_ema_dn and (b1_bear_star or b1_bear_engulf or broke_prev_low or b0_bear_pin))

    # 2. SMC LIQUIDITY SWEEP
    min_prev5 = float(np.min(lows[-7:-2]))
    max_prev5 = float(np.max(highs[-7:-2]))
    swept_low = (min(l1, l0) <= min_prev5 + 0.05 * atr) and (c0 > min_prev5) and (lw1_pct >= 0.36 or lw0_pct >= 0.36 or b1_bull_engulf)
    swept_high = (max(h1, h0) >= max_prev5 - 0.05 * atr) and (c0 < max_prev5) and (uw1_pct >= 0.36 or uw0_pct >= 0.36 or b1_bear_engulf)
    strat_smc_buy = bool(m5_up and swept_low and c0 >= o0)
    strat_smc_sell = bool(m5_dn and swept_high and c0 <= o0)

    # 3. VOLATILITY SQUEEZE BREAKOUT
    recent_ranges = highs[-7:-2] - lows[-7:-2]
    is_squeezed = float(np.mean(recent_ranges)) <= 0.92 * atr
    box_high = float(np.max(highs[-6:-1]))
    box_low = float(np.min(lows[-6:-1]))
    strat_squeeze_buy = bool(m5_up and is_squeezed and (c0 > box_high or (broke_prev_high and b1_bull_marubozu)) and body0 > 0 and uw0_pct < 0.28)
    strat_squeeze_sell = bool(m5_dn and is_squeezed and (c0 < box_low or (broke_prev_low and b1_bear_marubozu)) and body0 < 0 and lw0_pct < 0.28)

    # 4. VWAP INSTITUTIONAL BOUNCE & CONTINUATION
    near_vwap_up = (c0 > vwap_now) and (min(l1, l0) <= vwap_now + 0.35 * atr) and body0 > 0
    near_vwap_dn = (c0 < vwap_now) and (max(h1, h0) >= vwap_now - 0.35 * atr) and body0 < 0
    strat_vwap_buy = bool(m1_up_trend and m5_up and near_vwap_up and (above_prev_mid or broke_prev_high))
    strat_vwap_sell = bool(m1_dn_trend and m5_dn and near_vwap_dn and (below_prev_mid or broke_prev_low))

    # 5. MULTI-TIMEFRAME FULL MOMENTUM
    strat_mtf_buy = bool(
        m1_up_trend and m5_up and m15_up and htf_m5.get("bar_dir", 0) > 0
        and body1 > 0 and body0 > 0.04 * atr and uw0_pct < 0.28 and stretch0_atr < 0.72
    )
    strat_mtf_sell = bool(
        m1_dn_trend and m5_dn and m15_dn and htf_m5.get("bar_dir", 0) < 0
        and body1 < 0 and body0 < -0.04 * atr and lw0_pct < 0.28 and stretch0_atr < 0.72
    )

    buy_strats: list[str] = []
    buy_strat_ids: list[str] = []
    if strat_pullback_buy:
        buy_strats.append("Pullback Institucional EMA 9/21")
        buy_strat_ids.append("EMA_PULLBACK")
    if strat_smc_buy:
        buy_strats.append("SMC Varredura de Liquidez (Fundo)")
        buy_strat_ids.append("SMC_LIQUIDITY_SWEEP")
    if strat_squeeze_buy:
        buy_strats.append("Explosão de Compressão (Breakout)")
        buy_strat_ids.append("VOLATILITY_SQUEEZE")
    if strat_vwap_buy:
        buy_strats.append("Defesa Institucional na VWAP")
        buy_strat_ids.append("VWAP_INSTITUTIONAL")
    if strat_mtf_buy:
        buy_strats.append("Fluxo Sincronizado M1+M5+M15")
        buy_strat_ids.append("MTF_MOMENTUM")

    sell_strats: list[str] = []
    sell_strat_ids: list[str] = []
    if strat_pullback_sell:
        sell_strats.append("Pullback Institucional EMA 9/21")
        sell_strat_ids.append("EMA_PULLBACK")
    if strat_smc_sell:
        sell_strats.append("SMC Varredura de Liquidez (Topo)")
        sell_strat_ids.append("SMC_LIQUIDITY_SWEEP")
    if strat_squeeze_sell:
        sell_strats.append("Explosão de Compressão (Breakout)")
        sell_strat_ids.append("VOLATILITY_SQUEEZE")
    if strat_vwap_sell:
        sell_strats.append("Rejeição Institucional na VWAP")
        sell_strat_ids.append("VWAP_INSTITUTIONAL")
    if strat_mtf_sell:
        sell_strats.append("Fluxo Sincronizado M1+M5+M15")
        sell_strat_ids.append("MTF_MOMENTUM")

    # Índice Heurístico Direcional (Parte 4.1: não é probabilidade estatística calibrada!)
    edge = 0.0
    if m5_up and m1_up_trend:
        edge += 16.0
    elif m5_dn and m1_dn_trend:
        edge -= 16.0

    if b1_bull_marubozu or b1_bull_engulf or b1_bull_hammer:
        edge += 14.0
    if b1_bear_marubozu or b1_bear_engulf or b1_bear_star:
        edge -= 14.0

    edge += wick_net * 22.0
    edge += float(np.clip(body0 / max(atr, 1e-9), -1.2, 1.2)) * 16.0
    if broke_prev_high and body0 > 0:
        edge += 12.0
    elif broke_prev_low and body0 < 0:
        edge -= 12.0

    if len(buy_strats) > len(sell_strats):
        edge += 10.0 * len(buy_strats)
    elif len(sell_strats) > len(buy_strats):
        edge -= 10.0 * len(sell_strats)

    if flow_ok:
        edge += float(np.clip(delta, -1.0, 1.0)) * 12.0

    prob_up = float(np.clip(50.0 + edge * 0.55, 10.0, 96.0))
    prob_down = round(100.0 - prob_up, 1)
    prob_up = round(prob_up, 1)
    next_dir = "BUY" if prob_up >= prob_down else "SELL"

    bull_impulse = bool((b1_bull_marubozu or broke_prev_high) and body0 > 0.04 * atr and uw0_pct < 0.28)
    bear_impulse = bool((b1_bear_marubozu or broke_prev_low) and body0 < -0.04 * atr and lw0_pct < 0.28)
    bull_reversal = bool(strat_pullback_buy or strat_smc_buy)
    bear_reversal = bool(strat_pullback_sell or strat_smc_sell)

    # --- VETOS INEGOCIÁVEIS ---
    veto_buy: list[str] = []
    veto_sell: list[str] = []

    if not m5_avail or not m15_avail:
        missing_msg = htf_m5.get("reason") or htf_m15.get("reason") or "Dados obrigatórios de M5/M15 indisponíveis (NO_TRADE)"
        veto_buy.append(missing_msg)
        veto_sell.append(missing_msg)

    if m5_avail and not m5_up:
        veto_buy.append("Proibido Comprar contra a tendência de Baixa do M5")
    if m15_avail and not m15_up:
        veto_buy.append("Proibido Comprar contra a tendência Macro do M15")
    if not m1_up_trend and not strat_smc_buy:
        veto_buy.append("Preço abaixo da EMA 21 (tendência curta vendedora)")
    if body0 < -0.02 * atr:
        veto_buy.append("Vela atual está vermelha caindo abaixo da abertura")
    if uw0_pct >= 0.38 and rng0 >= 0.25 * atr:
        veto_buy.append(f"Vela atual deixando rabo superior ({uw0_pct * 100:.0f}% rejeição no topo)")
    if (b1_bear_star or b1_bear_engulf) and not broke_prev_high:
        veto_buy.append("Vela anterior deixou rejeição vendedora no topo")
    if three_up and stretch0_atr >= 0.45:
        veto_buy.append("3 velas seguidas de alta sem respiro (aguardando pullback na média)")
    if stretch0_atr >= 0.72 and body0 > 0:
        veto_buy.append(f"Vela atual já esticou +{stretch0_atr:.2f} ATR (proibido comprar no topo da vela)")

    if m5_avail and not m5_dn:
        veto_sell.append("Proibido Vender contra a tendência de Alta do M5")
    if m15_avail and not m15_dn:
        veto_sell.append("Proibido Vender contra a tendência Macro do M15")
    if not m1_dn_trend and not strat_smc_sell:
        veto_sell.append("Preço acima da EMA 21 (tendência curta compradora)")
    if body0 > 0.02 * atr:
        veto_sell.append("Vela atual está verde subindo acima da abertura")
    if lw0_pct >= 0.38 and rng0 >= 0.25 * atr:
        veto_sell.append(f"Vela atual deixando rabo inferior ({lw0_pct * 100:.0f}% rejeição no fundo)")
    if (b1_bull_hammer or b1_bull_engulf) and not broke_prev_low:
        veto_sell.append("Vela anterior deixou rejeição compradora no fundo")
    if three_down and stretch0_atr >= 0.45:
        veto_sell.append("3 velas seguidas de queda sem respiro (aguardando pullback na média)")
    if stretch0_atr >= 0.72 and body0 < 0:
        veto_sell.append(f"Vela atual já caiu -{stretch0_atr:.2f} ATR (proibido vender no fundo da vela)")

    if buy_strats and prob_up >= prob_down:
        prev_desc = f"Estratégia: {buy_strats[0]} · fechou {c1:.{digits}f}"
    elif sell_strats and prob_down > prob_up:
        prev_desc = f"Estratégia: {sell_strats[0]} · fechou {c1:.{digits}f}"
    elif b1_bull_hammer:
        prev_desc = f"Martelo Comprador (rabo inferior {lw1_pct * 100:.0f}%)"
    elif b1_bear_star:
        prev_desc = f"Rejeição de Topo (rabo superior {uw1_pct * 100:.0f}%)"
    else:
        dir_str = "Alta" if body1 >= 0 else "Baixa"
        prev_desc = (
            f"Fechou em {dir_str} ({c1:.{digits}f}) · corpo {body1_pct * 100:.0f}% · "
            f"rabo sup {uw1_pct * 100:.0f}% / inf {lw1_pct * 100:.0f}%"
        )

    if body0 >= 0:
        brk = " · rompeu máxima anterior" if broke_prev_high else ""
        curr_desc = f"Abriu em {o0:.{digits}f} e está SUBINDO ({c0:.{digits}f}){brk}"
    else:
        brk = " · perdeu mínima anterior" if broke_prev_low else ""
        curr_desc = f"Abriu em {o0:.{digits}f} e está CAINDO ({c0:.{digits}f}){brk}"

    if wick_net >= 0.14:
        wick_desc = "Pavios inferiores dominantes (compradores defendendo suporte/média)"
    elif wick_net <= -0.14:
        wick_desc = "Pavios superiores dominantes (vendedores defendendo resistência/média)"
    else:
        wick_desc = "Pavios equilibrados sem rejeição contrária"

    return {
        "prob_up": prob_up,
        "prob_down": prob_down,
        "is_calibrated": False,
        "probability_type": "HEURISTIC_DIRECTIONAL_INDEX",
        "next_dir": next_dir,
        "prev_desc": prev_desc,
        "curr_desc": curr_desc,
        "wick_desc": wick_desc,
        "wick_pressure": round(float(wick_net), 3),
        "buy_strategies": buy_strats,
        "sell_strategies": sell_strats,
        "buy_strategy_ids": buy_strat_ids,
        "sell_strategy_ids": sell_strat_ids,
        "bull_reversal": bull_reversal,
        "bear_reversal": bear_reversal,
        "bull_impulse": bull_impulse,
        "bear_impulse": bear_impulse,
        "bull_hammer": bool(b1_bull_hammer),
        "bear_star": bool(b1_bear_star),
        "bull_engulf": bool(b1_bull_engulf),
        "bear_engulf": bool(b1_bear_engulf),
        "b0_bull_pin": bool(b0_bull_pin),
        "b0_bear_pin": bool(b0_bear_pin),
        "broke_prev_high": bool(broke_prev_high),
        "broke_prev_low": bool(broke_prev_low),
        "above_prev_mid": bool(above_prev_mid),
        "below_prev_mid": bool(below_prev_mid),
        "b0_body": float(body0),
        "b1_body": float(body1),
        "b0_stretch_atr": round(float(stretch0_atr), 3),
        "b0_uw_pct": round(float(uw0_pct), 3),
        "b0_lw_pct": round(float(lw0_pct), 3),
        "b1_uw_pct": round(float(uw1_pct), 3),
        "b1_lw_pct": round(float(lw1_pct), 3),
        "veto_buy": veto_buy,
        "veto_sell": veto_sell,
    }


def _select_horizon(
    d: int,
    cdl: dict,
    htf_m5: dict,
    htf_m15: dict,
    adx_v: float,
    room_atr: float,
    bar_remaining_s: int,
    tf_seconds: int,
    timeframe: str,
) -> dict:
    """
    Define o Horizonte Temporal e assegura que o alvo não exceda o espaço estrutural real disponível.
    Registra a estratégia principal e as estratégias em confluência (Parte 4.3).
    """
    side_up = d > 0
    strats = cdl["buy_strategies"] if side_up else cdl["sell_strategies"]
    strat_ids = cdl["buy_strategy_ids"] if side_up else cdl["sell_strategy_ids"]
    strat_name = strats[0] if strats else "Aguardando Setup Institucional"
    strat_id = strat_ids[0] if strat_ids else "NONE"
    m15_aligned = bool(htf_m15.get("available") and htf_m15.get("trend", 0) * d > 0)

    if m15_aligned and adx_v >= 20.0 and room_atr >= 2.0:
        dur_s = min(300, max(180, bar_remaining_s + 180))
        sl_atr = 1.25
        tp_atr = round(float(np.clip(room_atr * 0.80, 1.75, 2.20)), 2)
        return {
            "type": "ONDA_TENDENCIA",
            "label": f"🚀 Onda Institucional ({dur_s // 60}m{dur_s % 60:02d}s)",
            "short_label": f"🚀 Onda {dur_s // 60}m",
            "timeframe": timeframe,
            "duration_s": int(dur_s),
            "tp_atr": tp_atr,
            "sl_atr": sl_atr,
            "strategy": strat_name,
            "strategy_id": strat_id,
            "confluence_strategies": list(strats),
            "confluence_strategy_ids": list(strat_ids),
            "reason": f"{strat_name} · M1+M5+M15 alinhados (Alvo {tp_atr}x vs Stop {sl_atr}x)",
        }

    if room_atr >= 1.50:
        dur_s = min(180, max(120, bar_remaining_s + tf_seconds * 2))
        sl_atr = 1.20
        tp_atr = round(float(np.clip(room_atr * 0.78, 1.55, 1.85)), 2)
        return {
            "type": "IMPULSO_CURTO",
            "label": f"🎯 Impulso 2-3 Velas ({dur_s}s)",
            "short_label": f"🎯 Impulso ({dur_s}s)",
            "timeframe": timeframe,
            "duration_s": int(dur_s),
            "tp_atr": tp_atr,
            "sl_atr": sl_atr,
            "strategy": strat_name,
            "strategy_id": strat_id,
            "confluence_strategies": list(strats),
            "confluence_strategy_ids": list(strat_ids),
            "reason": f"{strat_name} · válido por {dur_s}s (Alvo {tp_atr}x > Stop {sl_atr}x)",
        }

    dur_s = min(110, max(75, bar_remaining_s + 60))
    sl_atr = 1.15
    # Não projeta um alvo maior do que 90% do espaço real disponível quando o espaço é conhecido
    max_feasible_tp = max(1.45, min(1.65, room_atr * 0.88)) if room_atr >= 1.15 else 1.45
    tp_atr = round(float(max_feasible_tp), 2)
    return {
        "type": "SCALP_1VELA",
        "label": f"⚡ Tiro Sniper de Vela ({dur_s}s)",
        "short_label": f"⚡ Vela ({dur_s}s)",
        "timeframe": timeframe,
        "duration_s": int(dur_s),
        "tp_atr": tp_atr,
        "sl_atr": sl_atr,
        "strategy": strat_name,
        "strategy_id": strat_id,
        "confluence_strategies": list(strats),
        "confluence_strategy_ids": list(strat_ids),
        "reason": f"{strat_name} · previsão de {dur_s}s (Alvo {tp_atr}x > Stop {sl_atr}x)",
    }


def analyze(
    df: pd.DataFrame | None,
    htf_df: pd.DataFrame | None,
    tick: dict | None,
    sym: dict | None,
    flow: dict,
    mode: ModeConfig,
    settings: dict,
    tf_seconds: int = 60,
    htf_m15_df: pd.DataFrame | None = None,
    server_now: int = 0,
    calibration_lookup: dict | None = None,
) -> dict:
    if df is None or len(df) < 120 or tick is None or sym is None:
        return {"ready": False, "study_block": "Carregando histórico de velas do MT5 (mínimo 120 barras)."}

    last = df.iloc[-1]
    atr = _f(last.get("atr"))
    e9, e21, e200 = _f(last.get("ema9")), _f(last.get("ema21")), _f(last.get("ema200"))
    vwap_v = _f(last.get("vwap")) or e21
    vwap_std = _f(last.get("vwap_sd")) or atr
    rsi_v, k_v, d_v = _f(last.get("rsi")), _f(last.get("stoch_k")), _f(last.get("stoch_d"))
    adx_v, pdi, mdi = _f(last.get("adx")), _f(last.get("plus_di")), _f(last.get("minus_di"))
    rvol = _f(last.get("rvol"))

    if (
        not atr
        or atr <= 0
        or None in (e9, e21, e200, vwap_v, rsi_v, k_v, d_v, adx_v, pdi, mdi, rvol)
    ):
        return {"ready": False, "study_block": "Indicadores em aquecimento ou com valores inválidos (NO_TRADE)."}

    bid = _f(tick.get("bid"))
    ask = _f(tick.get("ask"))
    point = _f(sym.get("point"))
    if not bid or not ask or bid <= 0 or ask < bid or not point or point <= 0:
        return {"ready": False, "study_block": "Cotação bid/ask ou especificação point inválida (NO_TRADE)."}

    tick_time = int(tick.get("time") or 0)
    tick_stale = bool(server_now > 0 and tick_time > 0 and abs(server_now - tick_time) > MAX_TICK_AGE_S)

    closes = df["close"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    ema9s = df["ema9"].to_numpy(dtype=float)
    ema21s = df["ema21"].to_numpy(dtype=float)
    ema200s = df["ema200"].to_numpy(dtype=float)
    vwaps = df["vwap"].to_numpy(dtype=float)
    atrs = df["atr"].to_numpy(dtype=float)

    digits = int(sym.get("digits") or 5)
    spread_price = max(0.0, ask - bid)
    spread_points = int(round(spread_price / point))
    price = float(closes[-1])

    bar_time = int(last["time"])
    now_ref = server_now if server_now > 0 else (tick_time or bar_time)
    bar_elapsed_s = max(0, min(tf_seconds, now_ref - bar_time))
    bar_remaining_s = max(0, tf_seconds - bar_elapsed_s)

    atr_med = float(np.nanmedian(atrs[-60:])) or atr
    atr_ratio = atr / atr_med if atr_med > 0 else 1.0
    slope = (ema200s[-1] - ema200s[-10]) / atr if np.isfinite(ema200s[-10]) else 0.0
    vwap_dist_atr = (price - vwap_v) / atr

    delta = float(flow.get("delta") or 0.0)
    accel = float(flow.get("acceleration") or 0.0)
    flow_ok = bool(flow.get("enough"))

    htf_s = _htf_summary(htf_df, server_now=now_ref, max_stale_s=1200)
    htf_m15_s = _htf_summary(htf_m15_df, server_now=now_ref, max_stale_s=2700)

    cdl = _analyze_candles_and_strategies(
        opens,
        highs,
        lows,
        closes,
        ema9s,
        ema21s,
        ema200s,
        vwaps,
        atr,
        rsi_v,
        rvol,
        vwap_dist_atr,
        htf_s,
        htf_m15_s,
        delta,
        flow_ok,
        digits,
    )

    # Cálculo objetivo do espaço estrutural para compra e venda (Parte 2.10)
    struct_up = classify_structural_room(opens, highs, lows, closes, atr, 1, htf_s)
    struct_dn = classify_structural_room(opens, highs, lows, closes, atr, -1, htf_s)

    w = mode.weights
    max_spread = int(settings.get("max_spread_points", 25))
    atr_points = atr / max(point, 1e-9)

    ui_regime, detailed_regime = classify_market_regime(
        price=price,
        e9=e9,
        e21=e21,
        e200=e200,
        adx_v=adx_v,
        pdi=pdi,
        mdi=mdi,
        atr=atr,
        atr_ratio=atr_ratio,
        atr_points=atr_points,
        spread_price=spread_price,
        spread_points=spread_points,
        max_spread=max_spread,
        htf_m5=htf_s,
        htf_m15=htf_m15_s,
        flow_ok=flow_ok,
        tick_stale=tick_stale,
        buy_strats=cdl["buy_strategies"],
        sell_strats=cdl["sell_strategies"],
    )

    def build_side(d: int) -> tuple[list[dict], float, list[dict], dict, list[str], dict]:
        side_up = d > 0
        prob_next = cdl["prob_up"] if side_up else cdl["prob_down"]
        vetoes = list(cdl["veto_buy"] if side_up else cdl["veto_sell"])
        strats = cdl["buy_strategies"] if side_up else cdl["sell_strategies"]
        has_strat = len(strats) > 0
        strat_label = strats[0] if has_strat else "Aguardando setup institucional"
        struct_info = struct_up if side_up else struct_dn
        room_atr = float(struct_info["room_atr"])

        if tick_stale:
            vetoes.append(f"Cotação do ativo desatualizada ({abs(now_ref - tick_time)}s > {MAX_TICK_AGE_S}s)")
        if atr_points < 6.0:
            vetoes.append(f"Volatilidade muito baixa neste timeframe (ATR {atr_points:.1f} pts < 6 pts)")
        if spread_points > max_spread:
            vetoes.append(f"Spread atual ({spread_points} pts) acima do limite configurado ({max_spread} pts)")

        horizon = _select_horizon(
            d, cdl, htf_s, htf_m15_s, adx_v, room_atr, bar_remaining_s, tf_seconds, mode.timeframe
        )

        # --- PILAR 1: Estratégia Institucional & Anatomia da Vela (Peso 2.5) ---
        b0_favor = (cdl["b0_body"] * d >= 0.03 * atr) or (cdl["b0_bull_pin"] if side_up else cdl["b0_bear_pin"])
        wicks_ok = (
            (cdl["b0_uw_pct"] < 0.34 and cdl["b1_uw_pct"] < 0.40)
            if side_up
            else (cdl["b0_lw_pct"] < 0.34 and cdl["b1_lw_pct"] < 0.40)
        )
        s_prob = _clamp((prob_next - 52.0) / 34.0, 0.0, 1.0)
        s_strat = 1.0 if len(strats) >= 2 else (0.85 if has_strat else 0.20)
        p1_score = _clamp(s_strat * 0.45 + s_prob * 0.35 + (0.20 if (b0_favor and wicks_ok) else 0.0))
        if vetoes:
            p1_score *= 0.25

        p1 = _pillar(
            1,
            w[0],
            f"{strat_label} · Índice Dir. Heurístico: {prob_next:.0f}% {'ALTA' if side_up else 'BAIXA'}",
            [
                (f"Estratégia ativa: {strat_label}", has_strat, 0.40),
                (f"Índice direcional da vela ≥ 66 ({prob_next:.0f})", prob_next >= 66.0, 0.35),
                (f"Vela atual e pavios confirmando direção ({cdl['wick_desc']})", bool(b0_favor and wicks_ok), 0.25),
            ],
            continuous_score=p1_score,
        )

        # --- PILAR 2: Alinhamento Obrigatório de Tendência M1 + M5 + M15 (Peso 2.5) ---
        # Parte 2.9: sem dados disponíveis de M5 ou M15 -> False!
        m1_trend_ok = (price >= e21 and e9 >= e21 - 0.05 * atr) if side_up else (price <= e21 and e9 <= e21 + 0.05 * atr)
        m5_trend_ok = bool(htf_s["available"] and htf_s["bias21"] * d > 0 and htf_s["bar_body_atr"] * d >= -0.10)
        m15_trend_ok = bool(htf_m15_s["available"] and htf_m15_s["trend"] * d >= 0)

        p2_score = (
            (0.40 if m1_trend_ok else 0.0)
            + (0.40 if m5_trend_ok else 0.0)
            + (0.20 if m15_trend_ok else 0.0)
        )
        p2 = _pillar(
            2,
            w[1],
            (
                f"M1 {'A Favor' if m1_trend_ok else 'Contra'} · "
                f"M5 {'A Favor' if m5_trend_ok else ('Indisponível' if not htf_s['available'] else 'Contra')} · "
                f"M15 {'A Favor' if m15_trend_ok else ('Indisponível' if not htf_m15_s['available'] else 'Contra')}"
            ),
            [
                ("Tendência M1 a favor (Preço e EMA 9/21 alinhados)", bool(m1_trend_ok), 0.40),
                ("Tendência M5 validada e a favor (Dados obrigatórios presentes)", bool(m5_trend_ok), 0.40),
                ("Tendência Macro M15 validada e alinhada", bool(m15_trend_ok), 0.20),
            ],
            continuous_score=p2_score,
        )

        # --- PILAR 3: Espaço Estrutural até Suporte/Resistência (Peso 1.8) ---
        enough_room = bool(struct_info["confirmed"] and room_atr >= 1.15 and room_atr >= horizon["tp_atr"] * 0.75)
        if not enough_room:
            vetoes.append(struct_info["reason"])
        p3_score = _clamp((room_atr - 0.50) / 1.30, 0.0, 1.0) if struct_info["confirmed"] else 0.15
        p3 = _pillar(
            3,
            w[2],
            f"{struct_info['status']} · Espaço: {room_atr:.2f} ATR · Alvo {horizon['tp_atr']}x > Stop {horizon['sl_atr']}x",
            [
                (f"Estrutura confirmada e espaço ≥ 1,15 ATR ({room_atr:.2f} ATR)", enough_room, 0.55),
                (f"Retorno compatível com o espaço e maior que o Stop ({horizon['tp_atr']}x vs {horizon['sl_atr']}x)", horizon["tp_atr"] > horizon["sl_atr"] * 1.2, 0.45),
            ],
            continuous_score=p3_score,
        )

        # --- PILAR 4: Fluxo Real de Ticks & Ignição de Volume (Peso 1.4) ---
        flow_aligned = bool(flow_ok and d * delta >= 0.14)
        if not flow_ok:
            vetoes.append("Amostra de fluxo de ticks insuficiente para confirmar agressão")
        elif d * delta < -0.10:
            vetoes.append(f"Fluxo de ticks em tempo real está contra ({delta * 100:+.0f}%)")

        if flow_ok:
            s_delta = _clamp((d * delta + 0.05) / 0.50, 0.0, 1.0)
            s_rvol = _clamp(rvol / 1.20, 0.25, 1.0)
            p4_score = _clamp(s_delta * 0.65 + s_rvol * 0.35)
        else:
            p4_score = 0.20
        p4 = _pillar(
            4,
            w[3],
            f"Fluxo {delta * 100:+.0f}% ({'OK' if flow_ok else 'Amostra curta'}) · RVOL {rvol:.2f}x · Acel {accel:.2f}x",
            [
                (f"Fluxo de ticks validado e empurrando a favor ({delta * 100:+.0f}%)", flow_aligned, 0.50),
                (f"Volume ativo na vela (RVOL {rvol:.2f}x ≥ {mode.rvol_min:.2f}x)", bool(rvol >= mode.rvol_min), 0.50),
            ],
            continuous_score=p4_score,
        )

        # --- PILAR 5: Eficiência Matemática (Custos & Spread vs Alvo) (Peso 1.0) ---
        target_price = horizon["tp_atr"] * atr
        spread_to_tp = spread_price / max(target_price, 1e-9)
        spread_ok = spread_points <= max_spread and spread_to_tp <= 0.15 and atr_points >= 6.0
        if spread_to_tp > 0.16:
            vetoes.append(f"Spread consome {spread_to_tp * 100:.0f}% do alvo (máximo exigido ≤ 15%)")
        p5_score = _clamp(1.0 - (spread_to_tp / 0.20), 0.0, 1.0) if (spread_points <= max_spread and atr_points >= 6.0) else 0.0
        p5 = _pillar(
            5,
            w[4],
            f"Spread {spread_points} pts ({spread_to_tp * 100:.0f}% do alvo) · ATR {atr_points:.1f} pts",
            [
                (f"Custo do spread ≤ 15% do alvo ({spread_to_tp * 100:.0f}%)", spread_to_tp <= 0.15, 0.60),
                (f"Volatilidade saudável (ATR {atr_points:.1f} pts ≥ 6 pts)", atr_points >= 6.0, 0.40),
            ],
            continuous_score=p5_score,
        )

        # --- PILAR 6: Timing de Entrada (Pullback / Sem Esticamento / RSI Limpo) (Peso 1.3) ---
        dist_ema9_atr = abs(price - e9) / atr
        not_overextended = cdl["b0_stretch_atr"] < 0.68 and dist_ema9_atr < 1.15
        rsi_ok = (44.0 <= rsi_v <= 65.0) if side_up else (35.0 <= rsi_v <= 56.0)
        stoch_ok = (k_v >= d_v and k_v < 82.0) if side_up else (k_v <= d_v and k_v > 18.0)
        p6_score = (0.45 if not_overextended else 0.0) + (0.35 if rsi_ok else 0.10) + (0.20 if stoch_ok else 0.05)
        p6 = _pillar(
            6,
            w[5],
            f"Avanço vela {cdl['b0_stretch_atr']:.2f} ATR · Dist EMA9 {dist_ema9_atr:.2f} ATR · RSI {rsi_v:.1f}",
            [
                (f"Vela no início do movimento sem esticamento ({cdl['b0_stretch_atr']:.2f} ATR < 0,68)", bool(not_overextended), 0.45),
                (f"RSI ({rsi_v:.1f}) na zona de força limpa (sem sobrecompra/sobrevenda)", bool(rsi_ok), 0.35),
                (f"Estocástico ({k_v:.0f}/{d_v:.0f}) alinhado", bool(stoch_ok), 0.20),
            ],
            continuous_score=p6_score,
        )

        ps = [p1, p2, p3, p4, p5, p6]
        tw = sum(p["weight"] for p in ps) or 1.0
        raw_score = 100.0 * sum(p["weight"] * p["score"] for p in ps) / tw

        greens = sum(1 for p in ps if p["ok"])
        if greens == 6 and has_strat and not vetoes and prob_next >= 68.0:
            raw_score = min(98.0, raw_score + 6.0)
        elif greens >= 5 and has_strat and not vetoes and prob_next >= 66.0:
            raw_score = min(95.0, raw_score + 3.0)

        if not has_strat:
            raw_score = min(raw_score, 78.0)
        if vetoes:
            raw_score -= 18.0 * len(vetoes)

        final_score = round(_clamp(raw_score, 0.0, 99.0), 1)

        # Avaliação de famílias de indicadores sem redundância (Parte 4.2)
        grouped_families_score = round(
            100.0 * (p2_score * 0.30 + p3_score * 0.25 + p1_score * 0.20 + p4_score * 0.15 + p5_score * 0.10),
            1,
        )
        # Versão desduplicada (remove Stoch/RSI duplicados de P6 e o peso duplo de edge em P1)
        dedup_p1 = 1.0 if has_strat and b0_favor and wicks_ok else (0.5 if has_strat else 0.0)
        dedup_p6 = 1.0 if not_overextended else 0.0
        de_duplicated_score = round(
            100.0 * (p2_score * 0.30 + p3_score * 0.25 + dedup_p1 * 0.20 + p4_score * 0.15 + dedup_p6 * 0.10),
            1,
        )
        minimal_core_score = round(100.0 * (p2_score * 0.40 + p3_score * 0.35 + p5_score * 0.25), 1)

        model_variants = {
            "current_v5": final_score,
            "grouped_families": grouped_families_score,
            "de_duplicated": de_duplicated_score,
            "minimal_core": minimal_core_score,
            "structural_room_status": struct_info["status"],
        }

        gates = [
            {"label": f"Estratégia Institucional confirmada ({strat_label})", "ok": has_strat and len(vetoes) == 0},
            {"label": "Favor da Tendência M1 + M5 + M15 (Com dados válidos)", "ok": m1_trend_ok and m5_trend_ok and m15_trend_ok},
            {"label": f"Espaço estrutural confirmado ≥ 1,15 ATR ({room_atr:.2f} ATR)", "ok": enough_room},
            {"label": f"Spread baixo ({spread_to_tp * 100:.0f}% do alvo ≤ 15%), Fluxo e ATR ativos", "ok": spread_ok and flow_aligned},
            {"label": f"Pilares institucionais aprovados ({greens}/6 ≥ {mode.min_green_pillars})", "ok": greens >= mode.min_green_pillars},
        ]
        return ps, final_score, gates, horizon, vetoes, model_variants

    p_buy, s_buy, g_buy, h_buy, v_buy, mv_buy = build_side(1)
    p_sell, s_sell, g_sell, h_sell, v_sell, mv_sell = build_side(-1)

    if s_buy >= s_sell:
        d_best = 1
        ps, score, gates, horizon, vetoes_active, mv_best = p_buy, s_buy, g_buy, h_buy, v_buy, mv_buy
    else:
        d_best = -1
        ps, score, gates, horizon, vetoes_active, mv_best = p_sell, s_sell, g_sell, h_sell, v_sell, mv_sell

    all_gates = all(x["ok"] for x in gates)
    signal = ("BUY" if d_best > 0 else "SELL") if (score >= mode.min_score and all_gates and not vetoes_active) else None

    study_block = None
    if vetoes_active:
        study_block = vetoes_active[0]
    elif not all_gates:
        failed = [x["label"] for x in gates if not x["ok"]]
        if failed:
            study_block = "Aguardando: " + failed[0]

    # Calibração de probabilidade (Parte 4.1: só informa probabilidade calibrada se houver amostra OOS validada)
    cal_info = {
        "score_type": "HEURISTIC_CONFLUENCE",
        "probability_status": "UNCALIBRATED",
        "calibrated_win_prob": None,
        "sample_size": 0,
        "brier_score": None,
        "note": "Pontuação heurística de confluência (não representa probabilidade real de acerto sem calibração fora da amostra).",
    }
    if calibration_lookup and isinstance(calibration_lookup, dict):
        n_oos = int(calibration_lookup.get("sample_size") or 0)
        if n_oos >= 30 and calibration_lookup.get("calibrated_win_prob") is not None:
            cal_info.update({
                "probability_status": "CALIBRATED_OOS",
                "calibrated_win_prob": round(float(calibration_lookup["calibrated_win_prob"]), 1),
                "sample_size": n_oos,
                "brier_score": calibration_lookup.get("brier_score"),
                "note": f"Calibrada em {n_oos} operações fora da amostra.",
            })
        elif n_oos > 0:
            cal_info["probability_status"] = "INSUFFICIENT_SAMPLE"
            cal_info["sample_size"] = n_oos

    return {
        "ready": True,
        "algo_version": ALGO_VERSION,
        "mode": mode.key,
        "timeframe": mode.timeframe,
        "htf_tf": mode.htf,
        "spread_points": spread_points,
        "regime": {
            "code": ui_regime,
            "detailed_code": detailed_regime,
            "label": REGIME_PT.get(detailed_regime, REGIME_PT.get(ui_regime, ui_regime)),
            "adx": round(adx_v, 2),
            "plus_di": round(pdi, 2),
            "minus_di": round(mdi, 2),
            "atr": atr,
            "atr_ratio": round(atr_ratio, 2),
            "ema200_slope": round(slope, 3),
            "spread_points": spread_points,
            "spread_atr": round(spread_price / atr, 3),
        },
        "candle": cdl,
        "horizon": horizon,
        "score": score,
        "confluence_score": score,
        "score_buy": s_buy,
        "score_sell": s_sell,
        "calibration": cal_info,
        "model_variants": mv_best,
        "structure": struct_up if d_best > 0 else struct_dn,
        "direction": "BUY" if d_best > 0 else "SELL",
        "signal": signal,
        "pillars": ps,
        "gates": gates,
        "study_block": study_block,
        "flow": flow,
        "atr": atr,
        "bar_time": bar_time,
        "bar_remaining_s": bar_remaining_s,
        "indicators": {
            "price": price,
            "vwap": vwap_v,
            "vwap_std": vwap_std,
            "ema9": e9,
            "ema21": e21,
            "ema200": e200,
            "rsi": round(rsi_v, 2),
            "stoch_k": round(k_v, 2),
            "stoch_d": round(d_v, 2),
            "adx": round(adx_v, 2),
            "plus_di": round(pdi, 2),
            "minus_di": round(mdi, 2),
            "atr": atr,
            "rvol": round(rvol, 2),
        },
        "htf": htf_s,
        "htf_m15": htf_m15_s,
    }


def analyze_multi_horizon(
    dfs: dict[str, pd.DataFrame | None],
    tick: dict | None,
    sym: dict | None,
    flow: dict,
    base_mode: ModeConfig,
    settings: dict,
    server_now: int = 0,
    calibration_lookup: dict | None = None,
) -> dict:
    """
    MEGA BRAIN V5 Multi-Horizonte:
    Avalia M1, M2 e M5 simultaneamente com validação rigorosa de M5 e M15.
    """
    from dataclasses import replace
    from .config import TF_SECONDS

    m1_df = dfs.get("M1")
    m2_df = dfs.get("M2")
    m5_df = dfs.get("M5")
    m15_df = dfs.get("M15")

    candidates: list[dict] = []

    if m1_df is not None and len(m1_df) >= 120:
        m_m1 = replace(base_mode, timeframe="M1", htf="M5")
        a1 = analyze(m1_df, m5_df, tick, sym, flow, m_m1, settings, TF_SECONDS["M1"], m15_df, server_now, calibration_lookup)
        if a1.get("ready"):
            candidates.append(a1)

    if m2_df is not None and len(m2_df) >= 120:
        m_m2 = replace(base_mode, timeframe="M2", htf="M5")
        a2 = analyze(m2_df, m5_df, tick, sym, flow, m_m2, settings, TF_SECONDS["M2"], m15_df, server_now, calibration_lookup)
        if a2.get("ready"):
            candidates.append(a2)

    if m5_df is not None and len(m5_df) >= 120:
        m_m5 = replace(base_mode, timeframe="M5", htf="M15")
        a5 = analyze(m5_df, m15_df, tick, sym, flow, m_m5, settings, TF_SECONDS["M5"], m15_df, server_now, calibration_lookup)
        if a5.get("ready"):
            candidates.append(a5)

    if not candidates:
        return {"ready": False, "study_block": "Carregando velas multi-timeframe do MT5."}

    candidates.sort(
        key=lambda x: (
            1 if x.get("signal") else 0,
            float(x.get("score") or 0.0),
            1 if x.get("timeframe") == "M2" else 0,
        ),
        reverse=True,
    )
    best = candidates[0]
    best["evaluated_timeframes"] = [
        {
            "tf": c["timeframe"],
            "score": c["score"],
            "direction": c["direction"],
            "signal": c["signal"],
            "horizon": c.get("horizon", {}).get("short_label", c["timeframe"]),
            "duration_s": c.get("horizon", {}).get("duration_s", 90),
            "strategy": c.get("horizon", {}).get("strategy", ""),
        }
        for c in candidates
    ]
    return best
