"""Motor de Análise Quantitativa V4 (MEGA BRAIN) — 5 Estratégias Institucionais Consagradas
(Pullback EMA 9/21, SMC Liquidity Sweep, Volatility Squeeze Breakout, VWAP Bounce e Sincronia MTF),
Proibição Absoluta de Contra-Tendência e Relógio de Validade da Vela."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PILLAR_NAMES, ModeConfig

REGIME_PT = {
    "TREND_UP": "Tendência Institucional de Alta",
    "TREND_DOWN": "Tendência Institucional de Baixa",
    "PULLBACK_UP": "Pullback em Tendência de Alta (Oportunidade)",
    "PULLBACK_DOWN": "Pullback em Tendência de Baixa (Oportunidade)",
    "RANGE": "Consolidação / Lateral",
    "HIGH_VOL": "Explosão de Volatilidade",
    "UNKNOWN": "Indefinido",
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


def _htf_summary(htf_df: pd.DataFrame | None) -> dict:
    """Resumo completo do Timeframe Superior (M5 ou M15) para garantir alinhamento de tendência."""
    if htf_df is None or len(htf_df) < 35:
        return {
            "available": False,
            "trend": 0,
            "bias21": 0,
            "bias9": 0,
            "bar_dir": 0,
            "bar_body_atr": 0.0,
            "atr": 0.0,
            "rsi": 50.0,
        }
    last = htf_df.iloc[-1]
    prev = htf_df.iloc[-2]
    c = float(last["close"])
    o = float(last["open"])
    h = float(last["high"])
    l = float(last["low"])
    e9 = float(last["ema9"]) if pd.notna(last["ema9"]) else c
    e21 = float(last["ema21"]) if pd.notna(last["ema21"]) else c
    e200 = float(last["ema200"]) if pd.notna(last["ema200"]) else e21
    atr_h = float(last["atr"]) if pd.notna(last["atr"]) and float(last["atr"]) > 0 else max(abs(h - l), 1e-9)
    rsi_h = float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0

    body = c - o
    prev_body = float(prev["close"]) - float(prev["open"])

    # Tendência estrutural do timeframe superior
    if c > e21 and e9 >= e21:
        bias21 = 1
    elif c < e21 and e9 <= e21:
        bias21 = -1
    else:
        bias21 = 1 if c >= e21 else -1

    if c > e200 and e21 >= e200:
        trend = 1
    elif c < e200 and e21 <= e200:
        trend = -1
    else:
        trend = bias21

    bias9 = 1 if c >= e9 else -1
    bar_dir = 1 if body > 0.04 * atr_h else (-1 if body < -0.04 * atr_h else (1 if prev_body >= 0 else -1))

    return {
        "available": True,
        "trend": trend,
        "bias21": bias21,
        "bias9": bias9,
        "bar_dir": bar_dir,
        "bar_body_atr": round(body / atr_h, 3),
        "atr": atr_h,
        "rsi": round(rsi_h, 1),
    }


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
    Motor V4: Lê a anatomia das velas (B3, B2, B1, B0) + detecta as 5 Estratégias Institucionais
    SEMPRE A FAVOR da tendência principal (proibindo vendas em tendência de alta e compras em tendência de baixa).
    """
    eps = max(atr * 0.05, 1e-9)

    # Vela atual (B0)
    o0, h0, l0, c0 = float(opens[-1]), float(highs[-1]), float(lows[-1]), float(closes[-1])
    rng0 = max(h0 - l0, eps)
    body0 = c0 - o0
    abs_body0 = abs(body0)
    uw0_pct = (h0 - max(o0, c0)) / rng0
    lw0_pct = (min(o0, c0) - l0) / rng0
    pos0 = (c0 - l0) / rng0
    stretch0_atr = abs_body0 / max(atr, 1e-9)

    # Vela anterior fechada (B1)
    o1, h1, l1, c1 = float(opens[-2]), float(highs[-2]), float(lows[-2]), float(closes[-2])
    rng1 = max(h1 - l1, eps)
    body1 = c1 - o1
    abs_body1 = abs(body1)
    uw1_pct = (h1 - max(o1, c1)) / rng1
    lw1_pct = (min(o1, c1) - l1) / rng1
    body1_pct = abs_body1 / rng1
    pos1 = (c1 - l1) / rng1

    # Velas B2 e B3
    o2, h2, l2, c2 = float(opens[-3]), float(highs[-3]), float(lows[-3]), float(closes[-3])
    rng2 = max(h2 - l2, eps)
    body2 = c2 - o2
    uw2_pct = (h2 - max(o2, c2)) / rng2
    lw2_pct = (min(o2, c2) - l2) / rng2

    o3, c3 = float(opens[-4]), float(closes[-4])
    body3 = c3 - o3

    e9, e21, e200 = float(ema9s[-1]), float(ema21s[-1]), float(ema200s[-1])
    vwap_now = float(vwaps[-1]) if np.isfinite(vwaps[-1]) else e21

    # Padrões de vela
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

    # --- DETECÇÃO DAS 5 ESTRATÉGIAS INSTITUCIONAIS (Para COMPRA e para VENDA) ---
    m1_up_trend = c0 >= e21 and e9 >= e21 - 0.05 * atr
    m1_dn_trend = c0 <= e21 and e9 <= e21 + 0.05 * atr
    m5_up = not htf_m5["available"] or (htf_m5["bias21"] > 0 and htf_m5["bar_body_atr"] >= -0.12)
    m5_dn = not htf_m5["available"] or (htf_m5["bias21"] < 0 and htf_m5["bar_body_atr"] <= 0.12)
    m15_up = not htf_m15["available"] or htf_m15["trend"] >= 0
    m15_dn = not htf_m15["available"] or htf_m15["trend"] <= 0

    # 1. PULLBACK INSTITUCIONAL NA EMA 9/21 + IGNIÇÃO (Favor da Tendência)
    touched_ema_up = (min(l1, l0) <= max(e9, e21) + 0.18 * atr) and (c0 > e9) and (body0 > 0 or c1 > o1)
    touched_ema_dn = (max(h1, h0) >= min(e9, e21) - 0.18 * atr) and (c0 < e9) and (body0 < 0 or c1 < o1)
    strat_pullback_buy = bool(m1_up_trend and m5_up and touched_ema_up and (b1_bull_hammer or b1_bull_engulf or broke_prev_high or b0_bull_pin))
    strat_pullback_sell = bool(m1_dn_trend and m5_dn and touched_ema_dn and (b1_bear_star or b1_bear_engulf or broke_prev_low or b0_bear_pin))

    # 2. SMC LIQUIDITY SWEEP (Varredura de Liquidez de Micro-Fundo/Topo a Favor do M5)
    min_prev5 = float(np.min(lows[-7:-2]))
    max_prev5 = float(np.max(highs[-7:-2]))
    swept_low = (min(l1, l0) <= min_prev5 + 0.05 * atr) and (c0 > min_prev5) and (lw1_pct >= 0.36 or lw0_pct >= 0.36 or b1_bull_engulf)
    swept_high = (max(h1, h0) >= max_prev5 - 0.05 * atr) and (c0 < max_prev5) and (uw1_pct >= 0.36 or uw0_pct >= 0.36 or b1_bear_engulf)
    strat_smc_buy = bool(m5_up and swept_low and c0 >= o0)
    strat_smc_sell = bool(m5_dn and swept_high and c0 <= o0)

    # 3. VOLATILITY SQUEEZE BREAKOUT (Rompimento de Compressão)
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

    # 5. MULTI-TIMEFRAME FULL MOMENTUM (M1 + M5 + M15 100% Sincronizados)
    strat_mtf_buy = bool(
        m1_up_trend and m5_up and m15_up and htf_m5.get("bar_dir", 0) > 0
        and body1 > 0 and body0 > 0.04 * atr and uw0_pct < 0.28 and stretch0_atr < 0.72
    )
    strat_mtf_sell = bool(
        m1_dn_trend and m5_dn and m15_dn and htf_m5.get("bar_dir", 0) < 0
        and body1 < 0 and body0 < -0.04 * atr and lw0_pct < 0.28 and stretch0_atr < 0.72
    )

    buy_strats: list[str] = []
    if strat_pullback_buy:
        buy_strats.append("Pullback Institucional EMA 9/21")
    if strat_smc_buy:
        buy_strats.append("SMC Varredura de Liquidez (Fundo)")
    if strat_squeeze_buy:
        buy_strats.append("Explosão de Compressão (Breakout)")
    if strat_vwap_buy:
        buy_strats.append("Defesa Institucional na VWAP")
    if strat_mtf_buy:
        buy_strats.append("Fluxo Sincronizado M1+M5+M15")

    sell_strats: list[str] = []
    if strat_pullback_sell:
        sell_strats.append("Pullback Institucional EMA 9/21")
    if strat_smc_sell:
        sell_strats.append("SMC Varredura de Liquidez (Topo)")
    if strat_squeeze_sell:
        sell_strats.append("Explosão de Compressão (Breakout)")
    if strat_vwap_sell:
        sell_strats.append("Rejeição Institucional na VWAP")
    if strat_mtf_sell:
        sell_strats.append("Fluxo Sincronizado M1+M5+M15")

    # --- Probabilidade da Próxima Vela (Alinhada com Tendência + Vela + Fluxo) ---
    edge = 0.0
    # Peso forte da tendência M5 e M1 (evita prever queda quando o mercado está em tendência de alta!)
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

    # --- VETOS INEGOCIÁVEIS (Anti-Loss / Proibição de Contra-Tendência e Fim de Vela) ---
    veto_buy: list[str] = []
    veto_sell: list[str] = []

    # 1. PROIBIDO OPERAR CONTRA A TENDÊNCIA DO M5/M1
    if not m5_up:
        veto_buy.append("Proibido Comprar contra a tendência de Baixa do M5")
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

    if not m5_dn:
        veto_sell.append("Proibido Vender contra a tendência de Alta do M5")
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

    # Descrições claras
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
        "next_dir": next_dir,
        "prev_desc": prev_desc,
        "curr_desc": curr_desc,
        "wick_desc": wick_desc,
        "wick_pressure": round(float(wick_net), 3),
        "buy_strategies": buy_strats,
        "sell_strategies": sell_strats,
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
    Define o Horizonte Temporal e garante SEMPRE R/R POSITIVO (Alvo tp_atr > Stop sl_atr),
    para que os ganhos nunca sejam menores que as perdas!
    """
    side_up = d > 0
    strats = cdl["buy_strategies"] if side_up else cdl["sell_strategies"]
    strat_name = strats[0] if strats else "Impulso de Vela A Favor da Tendência"
    m15_aligned = bool(htf_m15.get("available") and htf_m15.get("trend", 0) * d > 0)

    # Caso 1: Onda de Tendência (3 a 5 min) — M1 + M5 + M15 sincronizados com amplo espaço (>= 2.0 ATR)
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
            "reason": f"{strat_name} · M1+M5+M15 alinhados (Alvo {tp_atr}x vs Stop {sl_atr}x)",
        }

    # Caso 2: Impulso de 2-3 Velas (2 a 3 min) — espaço livre >= 1.50 ATR
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
            "reason": f"{strat_name} · válido por {dur_s}s (Alvo {tp_atr}x > Stop {sl_atr}x)",
        }

    # Caso 3: Tiro Sniper de 1-2 Velas (75s a 110s) — SEMPRE com Alvo (1.45x) > Stop (1.15x)!
    dur_s = min(110, max(75, bar_remaining_s + 60))
    sl_atr = 1.15
    tp_atr = round(float(np.clip(max(1.45, room_atr * 0.78), 1.45, 1.65)), 2)
    return {
        "type": "SCALP_1VELA",
        "label": f"⚡ Tiro Sniper de Vela ({dur_s}s)",
        "short_label": f"⚡ Vela ({dur_s}s)",
        "timeframe": timeframe,
        "duration_s": int(dur_s),
        "tp_atr": tp_atr,
        "sl_atr": sl_atr,
        "strategy": strat_name,
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
) -> dict:
    if df is None or len(df) < 120 or tick is None or sym is None:
        return {"ready": False, "study_block": "Carregando histórico de velas do MT5."}

    last = df.iloc[-1]
    atr = _f(last["atr"])
    e9, e21, e200 = _f(last["ema9"]), _f(last["ema21"]), _f(last["ema200"])
    vwap_v = _f(last.get("vwap")) or e21
    vwap_std = _f(last.get("vwap_sd")) or atr
    rsi_v, k_v, d_v = _f(last["rsi"]), _f(last["stoch_k"]), _f(last["stoch_d"])
    adx_v, pdi, mdi = _f(last["adx"]), _f(last["plus_di"]), _f(last["minus_di"])
    rvol = _f(last["rvol"]) or 0.0

    if not atr or atr <= 0 or None in (e9, e21, e200, vwap_v, rsi_v, k_v, d_v, adx_v, pdi, mdi):
        return {"ready": False, "study_block": "Indicadores em aquecimento."}

    closes = df["close"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    ema9s = df["ema9"].to_numpy(dtype=float)
    ema21s = df["ema21"].to_numpy(dtype=float)
    ema200s = df["ema200"].to_numpy(dtype=float)
    vwaps = df["vwap"].to_numpy(dtype=float)
    atrs = df["atr"].to_numpy(dtype=float)

    point = float(sym.get("point") or 1e-5)
    digits = int(sym.get("digits") or 5)
    bid, ask = float(tick["bid"]), float(tick["ask"])
    spread_price = max(0.0, ask - bid)
    spread_points = int(round(spread_price / point)) if point > 0 else 0
    price = float(closes[-1])

    bar_time = int(last["time"])
    now_ref = server_now if server_now > 0 else int(tick.get("time") or bar_time)
    bar_elapsed_s = max(0, min(tf_seconds, now_ref - bar_time))
    bar_remaining_s = max(0, tf_seconds - bar_elapsed_s)

    atr_med = float(np.nanmedian(atrs[-60:])) or atr
    atr_ratio = atr / atr_med if atr_med > 0 else 1.0
    slope = (ema200s[-1] - ema200s[-10]) / atr if np.isfinite(ema200s[-10]) else 0.0
    vwap_dist_atr = (price - vwap_v) / atr

    delta = float(flow.get("delta") or 0.0)
    accel = float(flow.get("acceleration") or 0.0)
    flow_ok = bool(flow.get("enough"))

    htf_s = _htf_summary(htf_df)
    htf_m15_s = _htf_summary(htf_m15_df) if htf_m15_df is not None else {"available": False, "trend": 0}

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

    # Espaço livre até o topo/fundo das últimas 24 velas (excluindo a vela atual)
    swing_high = float(np.max(highs[-25:-1]))
    swing_low = float(np.min(lows[-25:-1]))
    room_up_atr = (swing_high - price) / atr if price < swing_high - 0.05 * atr else 2.20
    room_dn_atr = (price - swing_low) / atr if price > swing_low + 0.05 * atr else 2.20
    room_up_atr = float(np.clip(room_up_atr, 0.15, 2.80))
    room_dn_atr = float(np.clip(room_dn_atr, 0.15, 2.80))

    # Regime de mercado
    if spread_price > 0.30 * atr or atr_ratio > 2.5:
        regime = "HIGH_VOL"
    elif cdl["buy_strategies"] and price >= e21:
        regime = "PULLBACK_UP" if "Pullback" in cdl["buy_strategies"][0] or "SMC" in cdl["buy_strategies"][0] else "TREND_UP"
    elif cdl["sell_strategies"] and price <= e21:
        regime = "PULLBACK_DOWN" if "Pullback" in cdl["sell_strategies"][0] or "SMC" in cdl["sell_strategies"][0] else "TREND_DOWN"
    elif adx_v >= 16 and pdi > mdi and price >= e21:
        regime = "TREND_UP"
    elif adx_v >= 16 and mdi > pdi and price <= e21:
        regime = "TREND_DOWN"
    else:
        regime = "RANGE"

    w = mode.weights
    max_spread = int(settings.get("max_spread_points", 25))
    atr_points = atr / max(point, 1e-9)

    def build_side(d: int) -> tuple[list[dict], float, list[dict], dict, list[str]]:
        side_up = d > 0
        prob_next = cdl["prob_up"] if side_up else cdl["prob_down"]
        vetoes = list(cdl["veto_buy"] if side_up else cdl["veto_sell"])
        strats = cdl["buy_strategies"] if side_up else cdl["sell_strategies"]
        has_strat = len(strats) > 0
        strat_label = strats[0] if has_strat else "Aguardando setup institucional"
        room_atr = room_up_atr if side_up else room_dn_atr

        # Veto de volatilidade mínima: nunca opera quando a vela inteira tem menos de 6 pontos (0.6 pip)
        if atr_points < 6.0:
            vetoes.append(f"Volatilidade muito baixa neste timeframe (ATR {atr_points:.1f} pts < 6 pts)")

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
            f"{strat_label} · Próx. Vela: {prob_next:.0f}% {'ALTA' if side_up else 'BAIXA'}",
            [
                (f"Estratégia ativa: {strat_label}", has_strat, 0.40),
                (f"Probabilidade da próxima vela ≥ 66% ({prob_next:.0f}%)", prob_next >= 66.0, 0.35),
                (f"Vela atual e pavios confirmando direção ({cdl['wick_desc']})", bool(b0_favor and wicks_ok), 0.25),
            ],
            continuous_score=p1_score,
        )

        # --- PILAR 2: Alinhamento Obrigatório de Tendência M1 + M5 + M15 (Peso 2.5) ---
        m1_trend_ok = (price >= e21 and e9 >= e21 - 0.05 * atr) if side_up else (price <= e21 and e9 <= e21 + 0.05 * atr)
        m5_trend_ok = not htf_s["available"] or (htf_s["bias21"] * d > 0 and htf_s["bar_body_atr"] * d >= -0.10)
        m15_trend_ok = not htf_m15_s["available"] or (htf_m15_s["trend"] * d >= 0)

        p2_score = (
            (0.40 if m1_trend_ok else 0.0)
            + (0.40 if m5_trend_ok else 0.0)
            + (0.20 if m15_trend_ok else 0.05)
        )
        p2 = _pillar(
            2,
            w[1],
            f"M1 {'A Favor' if m1_trend_ok else 'Contra'} · M5 {'A Favor' if m5_trend_ok else 'Contra'} · M15 {'A Favor' if m15_trend_ok else 'Contra'}",
            [
                ("Tendência M1 a favor (Preço e EMA 9/21 alinhados)", bool(m1_trend_ok), 0.40),
                ("Tendência M5 obrigatoriamente a favor (Proibido Contra-Tendência)", bool(m5_trend_ok), 0.40),
                ("Tendência Macro M15 alinhada", bool(m15_trend_ok), 0.20),
            ],
            continuous_score=p2_score,
        )

        # --- PILAR 3: Espaço Livre até Topo/Fundo (R/R Positivo) (Peso 1.8) ---
        broke_sr = (price >= swing_high) if side_up else (price <= swing_low)
        enough_room = room_atr >= 1.15 or (broke_sr and (cdl["bull_impulse"] if side_up else cdl["bear_impulse"]))
        if not enough_room:
            vetoes.append(
                f"Espaço curto até {'Resistência (Topo)' if side_up else 'Suporte (Fundo)'} ({room_atr:.2f} ATR < 1.15 ATR)"
            )
        p3_score = _clamp((room_atr - 0.50) / 1.30, 0.0, 1.0) if not broke_sr else 0.92
        p3 = _pillar(
            3,
            w[2],
            f"Espaço livre: {room_atr:.2f} ATR · Alvo {horizon['tp_atr']}x > Stop {horizon['sl_atr']}x",
            [
                (f"Espaço livre ≥ 1,15 ATR até topo/fundo ({room_atr:.2f} ATR)", bool(enough_room), 0.55),
                (f"Retorno maior que o Risco (Alvo {horizon['tp_atr']}x vs Stop {horizon['sl_atr']}x)", horizon["tp_atr"] > horizon["sl_atr"] * 1.2, 0.45),
            ],
            continuous_score=p3_score,
        )

        # --- PILAR 4: Fluxo Real de Ticks & Ignição de Volume (Peso 1.4) ---
        intrabar_push = d * cdl["b0_body"] >= 0.05 * atr or (cdl["broke_prev_high"] if side_up else cdl["broke_prev_low"])
        flow_aligned = (flow_ok and d * delta >= 0.14) or (not flow_ok and intrabar_push and rvol >= 0.90)
        if flow_ok and d * delta < -0.10:
            vetoes.append(f"Fluxo de ticks em tempo real está contra ({delta * 100:+.0f}%)")
        if flow_ok:
            s_delta = _clamp((d * delta + 0.05) / 0.50, 0.0, 1.0)
            s_rvol = _clamp(rvol / 1.20, 0.25, 1.0)
            p4_score = _clamp(s_delta * 0.65 + s_rvol * 0.35)
        else:
            p4_score = 0.68 if (intrabar_push and rvol >= 0.85) else 0.30
        p4 = _pillar(
            4,
            w[3],
            f"Fluxo {delta * 100:+.0f}% · RVOL {rvol:.2f}x · Acel {accel:.2f}x",
            [
                (f"Fluxo de ticks empurrando a favor ({delta * 100:+.0f}%)", bool(flow_aligned), 0.50),
                (f"Volume ativo na vela (RVOL {rvol:.2f}x ≥ {mode.rvol_min:.2f}x)", bool(rvol >= mode.rvol_min), 0.50),
            ],
            continuous_score=p4_score,
        )

        # --- PILAR 5: Eficiência Matemática (Spread vs Alvo) (Peso 1.0) ---
        target_price = horizon["tp_atr"] * atr
        spread_to_tp = spread_price / max(target_price, 1e-9)
        spread_ok = spread_points <= max_spread and spread_to_tp <= 0.15 and atr_points >= 6.0
        if spread_to_tp > 0.16:
            vetoes.append(f"Spread consome {spread_to_tp * 100:.0f}% do alvo (mínimo exigido ≤ 15%)")
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

        gates = [
            {"label": f"Estratégia Institucional confirmada ({strat_label})", "ok": has_strat and len(vetoes) == 0},
            {"label": f"Favor da Tendência M1 + M5 (Proibido Contra-Tendência)", "ok": m1_trend_ok and m5_trend_ok},
            {"label": f"Espaço livre ≥ 1,15 ATR ({room_atr:.2f} ATR) & Alvo > Stop", "ok": enough_room},
            {"label": f"Spread baixo ({spread_to_tp * 100:.0f}% do alvo ≤ 15%) & ATR ativo", "ok": spread_ok},
            {"label": f"Pilares institucionais aprovados ({greens}/6 ≥ {mode.min_green_pillars})", "ok": greens >= mode.min_green_pillars},
        ]
        return ps, final_score, gates, horizon, vetoes

    p_buy, s_buy, g_buy, h_buy, v_buy = build_side(1)
    p_sell, s_sell, g_sell, h_sell, v_sell = build_side(-1)

    if s_buy >= s_sell:
        d_best = 1
        ps, score, gates, horizon, vetoes_active = p_buy, s_buy, g_buy, h_buy, v_buy
    else:
        d_best = -1
        ps, score, gates, horizon, vetoes_active = p_sell, s_sell, g_sell, h_sell, v_sell

    all_gates = all(x["ok"] for x in gates)
    signal = ("BUY" if d_best > 0 else "SELL") if (score >= mode.min_score and all_gates and not vetoes_active) else None

    study_block = None
    if vetoes_active:
        study_block = vetoes_active[0]
    elif not all_gates:
        failed = [x["label"] for x in gates if not x["ok"]]
        if failed:
            study_block = "Aguardando: " + failed[0]

    return {
        "ready": True,
        "mode": mode.key,
        "timeframe": mode.timeframe,
        "htf_tf": mode.htf,
        "spread_points": spread_points,
        "regime": {
            "code": regime,
            "label": REGIME_PT.get(regime, regime),
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
        "score_buy": s_buy,
        "score_sell": s_sell,
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
    }


def analyze_multi_horizon(
    dfs: dict[str, pd.DataFrame | None],
    tick: dict | None,
    sym: dict | None,
    flow: dict,
    base_mode: ModeConfig,
    settings: dict,
    server_now: int = 0,
) -> dict:
    """
    MEGA BRAIN V4 Multi-Horizonte:
    Avalia M1, M2 e M5 simultaneamente com as 5 Estratégias Institucionais e seleciona
    o horizonte onde a tendência M1+M5+M15 e a vela oferecem a maior assertividade real.
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
        a1 = analyze(m1_df, m5_df, tick, sym, flow, m_m1, settings, TF_SECONDS["M1"], m15_df, server_now)
        if a1.get("ready"):
            candidates.append(a1)

    if m2_df is not None and len(m2_df) >= 120:
        m_m2 = replace(base_mode, timeframe="M2", htf="M5")
        a2 = analyze(m2_df, m5_df, tick, sym, flow, m_m2, settings, TF_SECONDS["M2"], m15_df, server_now)
        if a2.get("ready"):
            candidates.append(a2)

    if m5_df is not None and len(m5_df) >= 120:
        m_m5 = replace(base_mode, timeframe="M5", htf="M15")
        a5 = analyze(m5_df, m15_df, tick, sym, flow, m_m5, settings, TF_SECONDS["M5"], m15_df, server_now)
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
        }
        for c in candidates
    ]
    return best
