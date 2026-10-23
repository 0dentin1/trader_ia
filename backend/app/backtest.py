"""Laboratório de Backtesting Cronológico e Validação Estatística Fora da Amostra (Parte 6).

Regras estritas:
1. Zero Look-Ahead Bias: em cada instante `t`, apenas barras fechadas de M5/M15 (`time + tf_sec <= t`)
   e o histórico passado de M1 (`<= t`) estão visíveis.
2. Regra Conservadora de Ambiguidade Intrabar: se `SL` e `TP` forem ambos tocados dentro da mesma vela
   e não houver ticks intrabar para desempate, o simulador assume SEMPRE que o `Stop Loss` foi atingido primeiro.
3. Custos reais incluídos: spread variável, bid/ask, slippage, comissão por lote e restrições de lote mínimo/margem.
4. Divisão cronológica estrita: Desenvolvimento/Ajuste (50%), Validação (25%) e Teste Fora da Amostra OOS (25%).
"""
from __future__ import annotations

import copy
import subprocess
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from . import indicators
from .analysis import analyze
from .config import ALGO_VERSION, DEFAULT_SETTINGS, MODES, REFERENCE_ALGO_VERSION
from .performance import compute_group_metrics
from .risk import build_plan
from .utils import floor_to_step, round_to_step


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, timeout=2.0)
        return out.decode("utf-8").strip()
    except Exception:  # noqa: BLE001
        return "unknown"


class SimulatedBridge:
    """Ponte simulada determinística que reproduz os cálculos de lote, lucro e margem do MT5 sem enviar ordens reais."""

    def __init__(self, contract_size: float = 100000.0, leverage: int = 100) -> None:
        self.contract_size = contract_size
        self.leverage = max(1, leverage)

    @staticmethod
    def norm_price(price: float, sym: dict) -> float:
        return round_to_step(price, float(sym.get("tick_size") or sym.get("point") or 1e-5), int(sym.get("digits") or 5))

    @staticmethod
    def norm_volume(volume: float, sym: dict) -> float:
        return floor_to_step(volume, float(sym.get("volume_step") or 0.01))

    def loss_per_lot(self, symbol: str, side: str, entry: float, sl: float, sym: dict) -> float | None:
        dist = abs(float(entry) - float(sl))
        if dist <= 0:
            return None
        tv = float(sym.get("tick_value_loss") or sym.get("tick_value") or 0.0)
        ts = float(sym.get("tick_size") or sym.get("point") or 0.0)
        if tv > 0 and ts > 0:
            return (dist / ts) * tv
        return dist * float(sym.get("contract_size") or self.contract_size)

    def calc_profit(self, symbol: str, side: str, volume: float, entry: float, close_price: float) -> float | None:
        d = 1 if side == "BUY" else -1
        diff = d * (float(close_price) - float(entry))
        tv = 1.0
        csize = self.contract_size
        return diff * csize * float(volume) * tv

    def margin_for(self, symbol: str, side: str, volume: float, price: float) -> float | None:
        return (float(volume) * self.contract_size * float(price)) / float(self.leverage)


@dataclass
class BacktestConfig:
    symbol: str = "EURUSD"
    initial_capital: float = 1000.0
    currency: str = "USD"
    mode_key: str = "MEDIANO"
    account_profile: str = "SMALL_ACCOUNT_PROTECTION"
    commission_per_lot: float = 7.0
    slippage_points: int = 2
    default_spread_points: int = 10
    leverage: int = 100
    point: float = 0.00001
    digits: int = 5
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    stops_level: int = 2
    data_source: str = "MT5_HISTORICAL_RATES"


def validate_historical_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Valida timestamps, ordenação, duplicações, lacunas (gaps) e integridade de preços OHLC."""
    if df is None or df.empty:
        return {"valid": False, "error": "DataFrame vazio ou ausente.", "bars": 0}
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        return {"valid": False, "error": f"Colunas obrigatórias ausentes: {sorted(missing)}", "bars": len(df)}

    times = df["time"].to_numpy(dtype=np.int64)
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)

    if not (np.isfinite(opens).all() and np.isfinite(highs).all() and np.isfinite(lows).all() and np.isfinite(closes).all()):
        return {"valid": False, "error": "Preços contêm NaN ou infinito.", "bars": len(df)}
    if (opens <= 0).any() or (highs <= 0).any() or (lows <= 0).any() or (closes <= 0).any():
        return {"valid": False, "error": "Preços menores ou iguais a zero detectados.", "bars": len(df)}
    if (highs < lows).any() or (highs < np.maximum(opens, closes) - 1e-9).any() or (lows > np.minimum(opens, closes) + 1e-9).any():
        return {"valid": False, "error": "Inconsistência OHLC (high < low ou fora de open/close).", "bars": len(df)}

    diffs = np.diff(times)
    duplicates = int(np.sum(diffs == 0))
    out_of_order = int(np.sum(diffs < 0))
    if out_of_order > 0 or duplicates > 0:
        return {
            "valid": False,
            "error": f"Timestamps fora de ordem ({out_of_order}) ou duplicados ({duplicates}).",
            "bars": len(df),
        }

    median_step = int(np.median(diffs)) if len(diffs) > 0 else 60
    gaps = int(np.sum(diffs > median_step * 5)) if len(diffs) > 0 else 0
    return {
        "valid": True,
        "bars": len(df),
        "start_time": int(times[0]),
        "end_time": int(times[-1]),
        "median_step_s": median_step,
        "gaps_detected": gaps,
        "duplicates": duplicates,
    }


def _resample_htf_from_m1(df_m1: pd.DataFrame, tf_seconds: int) -> pd.DataFrame:
    """Constrói barras de M5/M15 a partir de M1 respeitando estritamente os buckets temporais."""
    work = df_m1.copy()
    work["bucket"] = (work["time"] // tf_seconds) * tf_seconds
    agg = work.groupby("bucket", as_index=False).agg(
        time=("bucket", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        tick_volume=("tick_volume", "sum") if "tick_volume" in work.columns else ("close", "count"),
    )
    return indicators.compute(agg)


def run_backtest_segment(
    df_m1_raw: pd.DataFrame,
    cfg: BacktestConfig,
    settings_override: dict | None = None,
    df_m5_raw: pd.DataFrame | None = None,
    df_m15_raw: pd.DataFrame | None = None,
    start_idx: int = 130,
    end_idx: int | None = None,
    use_v4_reference_rules: bool = False,
) -> dict[str, Any]:
    """
    Executa o replay cronológico barra a barra sem Look-Ahead Bias (Partes 6.1, 6.2, 6.3 e 6.4).
    """
    val = validate_historical_dataframe(df_m1_raw)
    if not val["valid"]:
        return {"ok": False, "error": val["error"], "validation": val}
    if len(df_m1_raw) < 160:
        return {
            "ok": False,
            "error": f"Histórico insuficiente para backtest ({len(df_m1_raw)} barras < 160 mínimas).",
            "validation": val,
        }

    df_m1 = indicators.compute(df_m1_raw)
    df_m5 = indicators.compute(df_m5_raw) if (df_m5_raw is not None and len(df_m5_raw) >= 40) else _resample_htf_from_m1(df_m1_raw, 300)
    df_m15 = indicators.compute(df_m15_raw) if (df_m15_raw is not None and len(df_m15_raw) >= 40) else _resample_htf_from_m1(df_m1_raw, 900)

    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["account_profile"] = cfg.account_profile
    settings["mode"] = cfg.mode_key
    if settings_override:
        settings.update(settings_override)

    mode = MODES.get(cfg.mode_key, MODES["MEDIANO"])
    bridge = SimulatedBridge(leverage=cfg.leverage)
    sym_info = {
        "name": cfg.symbol,
        "digits": cfg.digits,
        "point": cfg.point,
        "tick_size": cfg.point,
        "tick_value": 1.0,
        "tick_value_loss": 1.0,
        "contract_size": 100000.0,
        "volume_min": cfg.volume_min,
        "volume_max": cfg.volume_max,
        "volume_step": cfg.volume_step,
        "stops_level": cfg.stops_level,
        "freeze_level": 0,
        "trade_mode": 4,
        "currency_profit": cfg.currency,
    }

    balance = float(cfg.initial_capital)
    equity = float(cfg.initial_capital)
    session_start_eq = balance
    week_start_eq = balance
    peak_eq = balance
    settings["session_state"] = {
        "trading_day": int(df_m1["time"].iloc[0]) // 86400,
        "trading_week": (int(df_m1["time"].iloc[0]) // 86400 + 3) // 7,
        "session_start_equity": session_start_eq,
        "week_start_equity": week_start_eq,
        "peak_equity": peak_eq,
        "drawdown_state": "NORMAL",
    }

    stop_i = min(len(df_m1), end_idx if end_idx is not None else len(df_m1))
    start_i = max(125, start_idx)

    m5_times = df_m5["time"].to_numpy(dtype=np.int64)
    m15_times = df_m15["time"].to_numpy(dtype=np.int64)

    open_pos: dict | None = None
    completed_trades: list[dict] = []
    blocked_signals_count = 0
    blocked_min_lot_count = 0
    intrabar_ambiguous_count = 0
    max_exposure_lots = 0.0
    max_margin_used = 0.0
    session_pnl = 0.0
    weekly_pnl = 0.0
    cur_day = int(df_m1["time"].iloc[start_i]) // 86400
    cur_week = (cur_day + 3) // 7

    for i in range(start_i, stop_i):
        row = df_m1.iloc[i]
        t_bar = int(row["time"])
        bar_day = t_bar // 86400
        bar_week = (bar_day + 3) // 7

        if bar_day != cur_day:
            cur_day = bar_day
            session_pnl = 0.0
            session_start_eq = balance
            settings["session_state"]["session_start_equity"] = session_start_eq
        if bar_week != cur_week:
            cur_week = bar_week
            weekly_pnl = 0.0
            week_start_eq = balance
            settings["session_state"]["week_start_equity"] = week_start_eq

        sp_pts = int(row["spread"]) if ("spread" in row and pd.notna(row["spread"]) and float(row["spread"]) > 0) else cfg.default_spread_points
        sp_price = sp_pts * cfg.point
        c_price = float(row["close"])
        h_price = float(row["high"])
        l_price = float(row["low"])
        o_price = float(row["open"])
        bid = c_price
        ask = c_price + sp_price

        # 1. Gerencia posição aberta (se existir) verificando a barra atual
        if open_pos is not None:
            side = open_pos["side"]
            d = 1 if side == "BUY" else -1
            sl = open_pos["sl"]
            tp = open_pos["tp"]
            vol = open_pos["volume"]
            entry = open_pos["entry_price"]

            # Verifica se SL ou TP foram atingidos dentro da barra [l_price, h_price]
            if side == "BUY":
                hit_sl = l_price <= sl
                hit_tp = h_price >= tp
            else:
                # Na venda, stop e TP são acionados pelo Ask (preço + spread)
                hit_sl = (h_price + sp_price) >= sl
                hit_tp = (l_price + sp_price) <= tp

            closed_now = False
            exit_p = c_price if side == "BUY" else (c_price + sp_price)
            exit_reason = ""

            # REGRA CONSERVADORA DE AMBIGUIDADE INTRABAR (Parte 6.2):
            # Se tanto SL quanto TP puderam ser atingidos na mesma barra, assume SEMPRE o Stop Loss!
            if hit_sl and hit_tp:
                intrabar_ambiguous_count += 1
                closed_now = True
                exit_p = sl - d * (cfg.slippage_points * cfg.point)
                exit_reason = "SL_INTRABAR_CONSERVATIVE"
            elif hit_sl:
                closed_now = True
                exit_p = sl - d * (cfg.slippage_points * cfg.point)
                exit_reason = "STOP_LOSS"
            elif hit_tp:
                closed_now = True
                exit_p = tp
                exit_reason = "TAKE_PROFIT"
            elif (t_bar - open_pos["open_time"]) >= open_pos["max_duration_s"]:
                # Fim do horizonte: se estiver no lucro >= 42% do alvo, realiza
                tp_dist = abs(tp - entry)
                prog = d * (exit_p - entry) / max(tp_dist, 1e-9)
                if prog >= 0.42:
                    closed_now = True
                    exit_reason = "TIME_STOP_WIN"

            if not closed_now:
                # Verifica Break-Even aos 55% do alvo (usando fechamento da barra)
                tp_dist = abs(tp - entry)
                prog = d * (exit_p - entry)
                if not open_pos["be_done"] and prog >= mode.be_value * tp_dist:
                    open_pos["sl"] = bridge.norm_price(entry + d * (0.25 * tp_dist), sym_info)
                    open_pos["be_done"] = True

            if closed_now:
                gross = float(bridge.calc_profit(cfg.symbol, side, vol, entry, exit_p) or 0.0)
                comm = -abs(cfg.commission_per_lot * vol)
                net = round(gross + comm, 2)
                balance = round(balance + net, 2)
                equity = balance
                if equity > peak_eq:
                    peak_eq = equity
                    settings["session_state"]["peak_equity"] = peak_eq
                session_pnl = round(session_pnl + net, 2)
                weekly_pnl = round(weekly_pnl + net, 2)

                completed_trades.append({
                    "position_id": len(completed_trades) + 1,
                    "symbol": cfg.symbol,
                    "timeframe": "M1",
                    "primary_strategy_id": open_pos["strategy_id"],
                    "primary_strategy": open_pos["strategy"],
                    "confluence_strategies_json": open_pos["confluence_json"],
                    "regime_code": open_pos["regime_code"],
                    "mode_key": cfg.mode_key,
                    "side": side,
                    "volume": vol,
                    "entry_price": entry,
                    "exit_price": round(exit_p, cfg.digits),
                    "open_time": open_pos["open_time"],
                    "close_time": t_bar,
                    "duration_s": max(60, t_bar - open_pos["open_time"]),
                    "gross_profit": round(gross, 2),
                    "commission": round(comm, 2),
                    "swap": 0.0,
                    "fee": 0.0,
                    "net_profit": net,
                    "won": net >= 0,
                    "effective_risk_money": open_pos["effective_risk"],
                    "confluence_score_at_entry": open_pos["score"],
                    "heuristic_prob_at_entry": open_pos["prob"],
                    "exit_reason": exit_reason,
                    "is_simulated": True,
                    "source": "BACKTEST",
                })
                open_pos = None
                continue

        # 2. Se não há posição aberta, avalia sinal na barra `i` SEM LOOK-AHEAD BIAS:
        # Apenas barras M1 até `i` (`iloc[max(0, i-200):i+1]`) e apenas barras M5/M15 JÁ FECHADAS (`time + tf_sec <= t_bar`)!
        sub_m1 = df_m1.iloc[max(0, i - 200) : i + 1]
        closed_m5_mask = (m5_times + 300) <= t_bar
        closed_m15_mask = (m15_times + 900) <= t_bar
        sub_m5 = df_m5.loc[closed_m5_mask].tail(120) if closed_m5_mask.any() else None
        sub_m15 = df_m15.loc[closed_m15_mask].tail(100) if closed_m15_mask.any() else None

        body_bar = c_price - o_price
        rng_bar = max(h_price - l_price, cfg.point)
        sim_delta = float(np.clip((body_bar / rng_bar) * 0.65, -0.95, 0.95))
        flow_sim = {
            "buy": 100.0 if sim_delta >= 0 else 40.0,
            "sell": 40.0 if sim_delta >= 0 else 100.0,
            "delta": sim_delta,
            "ticks": 50,
            "velocity": 1.5,
            "velocity_avg": 1.2,
            "acceleration": 1.25,
            "enough": True,
        }
        tick_sim = {"bid": bid, "ask": ask, "time": t_bar, "time_msc": t_bar * 1000}

        a = analyze(
            df=sub_m1,
            htf_df=sub_m5,
            tick=tick_sim,
            sym=sym_info,
            flow=flow_sim,
            mode=mode,
            settings=settings,
            tf_seconds=60,
            htf_m15_df=sub_m15,
            server_now=t_bar,
        )
        if not a.get("ready") or not a.get("signal"):
            continue

        sig = a["signal"]
        account_sim = {
            "currency": cfg.currency,
            "balance": balance,
            "equity": equity,
            "margin_free": equity,
            "leverage": cfg.leverage,
        }
        plan, err = build_plan(
            bridge=bridge,  # type: ignore[arg-type]
            symbol=cfg.symbol,
            sym=sym_info,
            tick=tick_sim,
            side=sig,
            atr=float(a["atr"]),
            mode=mode,
            settings=settings,
            account=account_sim,
            consecutive_losses=0,
            recovery_active=False,
            horizon=a.get("horizon"),
            open_trades_count=0,
            open_positions=[],
            session_pnl=session_pnl,
            weekly_pnl=weekly_pnl,
            server_now=t_bar,
        )
        if plan is None:
            blocked_signals_count += 1
            if "lote mínimo" in err.lower():
                blocked_min_lot_count += 1
            continue

        # Executa entrada simulada aplicando slippage realista de entrada
        d = 1 if sig == "BUY" else -1
        exec_entry = bridge.norm_price(plan.entry + d * (cfg.slippage_points * cfg.point), sym_info)
        exec_sl = bridge.norm_price(exec_entry - d * plan.sl_dist, sym_info)
        exec_tp = bridge.norm_price(exec_entry + d * plan.tp_dist, sym_info)
        margin_used = float(bridge.margin_for(cfg.symbol, sig, plan.lots, exec_entry) or 0.0)
        max_exposure_lots = max(max_exposure_lots, plan.lots)
        max_margin_used = max(max_margin_used, margin_used)

        hz = a.get("horizon") or {}
        cdl = a.get("candle") or {}
        open_pos = {
            "side": sig,
            "volume": plan.lots,
            "entry_price": exec_entry,
            "sl": exec_sl,
            "tp": exec_tp,
            "open_time": t_bar,
            "max_duration_s": plan.duration_s,
            "be_done": False,
            "effective_risk": plan.effective_risk,
            "strategy_id": str(hz.get("strategy_id") or "UNKNOWN"),
            "strategy": str(hz.get("strategy") or "Institucional"),
            "confluence_json": str(hz.get("confluence_strategies") or []),
            "regime_code": str(a.get("regime", {}).get("detailed_code") or a.get("regime", {}).get("code") or "UNKNOWN"),
            "score": float(a.get("score") or 0.0),
            "prob": float(cdl.get("prob_up", 50.0) if sig == "BUY" else cdl.get("prob_down", 50.0)),
        }

    metrics = compute_group_metrics(completed_trades)
    by_strat: dict[str, list[dict]] = {}
    by_reg: dict[str, list[dict]] = {}
    for t in completed_trades:
        by_strat.setdefault(t["primary_strategy"], []).append(t)
        by_reg.setdefault(t["regime_code"], []).append(t)

    return {
        "ok": True,
        "is_simulated": True,
        "algo_version": REFERENCE_ALGO_VERSION if use_v4_reference_rules else ALGO_VERSION,
        "git_commit": get_git_commit(),
        "symbol": cfg.symbol,
        "data_source": cfg.data_source,
        "period": {
            "start_time": int(df_m1["time"].iloc[start_i]),
            "end_time": int(df_m1["time"].iloc[stop_i - 1]),
            "bars_evaluated": int(stop_i - start_i),
        },
        "assumptions": {
            "initial_capital": cfg.initial_capital,
            "currency": cfg.currency,
            "account_profile": cfg.account_profile,
            "commission_per_lot": cfg.commission_per_lot,
            "slippage_points": cfg.slippage_points,
            "default_spread_points": cfg.default_spread_points,
            "intrabar_ambiguity_rule": "CONSERVATIVE_SL_FIRST",
            "look_ahead_prevention": "STRICT_CLOSED_HTF_AND_PAST_WINDOW",
        },
        "capital": {
            "initial": round(cfg.initial_capital, 2),
            "final": round(balance, 2),
            "return_pct": round(100.0 * (balance - cfg.initial_capital) / max(cfg.initial_capital, 1e-9), 2),
            "max_exposure_lots": round(max_exposure_lots, 2),
            "max_margin_used": round(max_margin_used, 2),
        },
        "execution_counts": {
            "total_trades": metrics["sample_size"],
            "signals_blocked_by_risk": blocked_signals_count,
            "signals_blocked_by_min_lot": blocked_min_lot_count,
            "intrabar_ambiguous_resolved_to_sl": intrabar_ambiguous_count,
        },
        "metrics": metrics,
        "by_strategy": {k: compute_group_metrics(v) for k, v in by_strat.items()},
        "by_regime": {k: compute_group_metrics(v) for k, v in by_reg.items()},
        "trades": completed_trades,
    }


def run_walk_forward_validation(
    df_m1_raw: pd.DataFrame,
    cfg: BacktestConfig,
    settings_override: dict | None = None,
) -> dict[str, Any]:
    """
    Separa os dados cronologicamente em 3 conjuntos independentes (Parte 6.5):
    1. Desenvolvimento e Ajuste (`TRAIN`: primeiros 50%)
    2. Validação de Parâmetros (`VALIDATION`: 50% a 75%)
    3. Teste Final Fora da Amostra (`TEST_OOS`: 75% a 100%)
    Inclui janela de purga (purge gap de 15 barras) entre as divisões para impedir vazamento temporal.
    """
    n = len(df_m1_raw)
    if n < 360:
        return {
            "ok": False,
            "error": f"Dados insuficientes para divisão cronológica Train/Val/Test ({n} barras < 360 mínimas).",
        }

    usable_start = 130
    span = n - usable_start
    train_end = usable_start + int(span * 0.50)
    val_start = min(n - 40, train_end + 15)
    val_end = usable_start + int(span * 0.75)
    test_start = min(n - 20, val_end + 15)

    train_res = run_backtest_segment(df_m1_raw, cfg, settings_override, start_idx=usable_start, end_idx=train_end)
    val_res = run_backtest_segment(df_m1_raw, cfg, settings_override, start_idx=val_start, end_idx=val_end)
    oos_res = run_backtest_segment(df_m1_raw, cfg, settings_override, start_idx=test_start, end_idx=n)

    return {
        "ok": True,
        "is_simulated": True,
        "methodology": "CHRONOLOGICAL_SPLIT_50_25_25_WITH_15BAR_PURGE",
        "algo_version": ALGO_VERSION,
        "git_commit": get_git_commit(),
        "total_bars": n,
        "splits": {
            "train": train_res,
            "validation": val_res,
            "test_out_of_sample": oos_res,
        },
    }
