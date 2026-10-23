"""Análise Estatística de Desempenho, Expectativa Matemática, Calibração e Sobrevivência (Partes 3.9, 4.1, 4.3 e 5.5).

Separa estritamente:
- Operações reais executadas (`is_simulated = 0`, `source = 'LIVE_MT5'`)
- Operações simuladas de backtest (`is_simulated = 1`, `source = 'BACKTEST'`)
- Oportunidades contrafactuais bloqueadas (`counterfactual_outcomes`)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from .trade_journal import TradeJournal

MIN_RELIABLE_SAMPLE = 20
MIN_CALIBRATION_SAMPLE_OOS = 30


def compute_group_metrics(trades: list[dict]) -> dict[str, Any]:
    """
    Calcula métricas estatísticas completas para uma amostra de operações:
    - Tamanho da amostra (`sample_size`) e flag de suficiência (`sample_sufficient`).
    - Expectativa líquida média por operação e decomposição `P(win)*avg_win - P(loss)*avg_loss`.
    - Profit factor, drawdown máximo, sequência máxima de losses, custos totais e incerteza (erro padrão).
    """
    n = len(trades)
    if n == 0:
        return {
            "sample_size": 0,
            "sample_sufficient": False,
            "reliability_status": "INSUFFICIENT_DATA",
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "extreme_loss": 0.0,
            "gross_total": 0.0,
            "total_costs": 0.0,
            "net_total": 0.0,
            "expectancy": 0.0,
            "expectancy_wl_formula": 0.0,
            "std_error": 0.0,
            "ci95_low": 0.0,
            "ci95_high": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "max_consecutive_losses": 0,
            "recent_deterioration": False,
        }

    # Ordena cronologicamente pelo fechamento para cálculo correto de drawdown e sequência de losses
    ordered = sorted(trades, key=lambda x: (int(x.get("close_time") or 0), int(x.get("position_id") or 0)))

    nets = [float(t.get("net_profit") or 0.0) for t in ordered]
    grosses = [float(t.get("gross_profit") or 0.0) for t in ordered]
    costs = [
        abs(float(t.get("commission") or 0.0))
        + abs(float(t.get("fee") or 0.0))
        + (abs(float(t.get("swap") or 0.0)) if float(t.get("swap") or 0.0) < 0 else 0.0)
        for t in ordered
    ]

    win_vals = [v for v in nets if v >= 0]
    loss_vals = [abs(v) for v in nets if v < 0]
    wins = len(win_vals)
    losses = len(loss_vals)

    p_win = wins / n
    p_loss = losses / n
    avg_win = sum(win_vals) / wins if wins > 0 else 0.0
    avg_loss = sum(loss_vals) / losses if losses > 0 else 0.0
    extreme_loss = max(loss_vals) if loss_vals else 0.0

    net_total = sum(nets)
    gross_total = sum(grosses)
    total_costs = sum(costs)

    expectancy = net_total / n
    expectancy_wl = (p_win * avg_win) - (p_loss * avg_loss)

    gross_wins = sum(win_vals)
    gross_losses = sum(loss_vals)
    profit_factor = (gross_wins / gross_losses) if gross_losses > 1e-9 else (99.9 if gross_wins > 0 else 0.0)

    # Desvio padrão amostral e erro padrão da expectativa
    if n >= 2:
        variance = sum((v - expectancy) ** 2 for v in nets) / (n - 1)
        std_dev = math.sqrt(max(0.0, variance))
        std_error = std_dev / math.sqrt(n)
    else:
        std_error = 0.0

    ci95_low = expectancy - 1.96 * std_error
    ci95_high = expectancy + 1.96 * std_error

    # Drawdown máximo e sequência máxima de losses na curva acumulada
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    cur_loss_streak = 0
    max_loss_streak = 0
    for v in nets:
        cum += v
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
        if v < 0:
            cur_loss_streak += 1
            if cur_loss_streak > max_loss_streak:
                max_loss_streak = cur_loss_streak
        else:
            cur_loss_streak = 0

    # Deterioração recente: compara últimas min(10, n//2) operações com a média anterior
    recent_deterioration = False
    if n >= 12:
        tail_k = min(8, n // 3)
        recent_exp = sum(nets[-tail_k:]) / tail_k
        prior_exp = sum(nets[:-tail_k]) / (n - tail_k)
        if recent_exp < 0 and prior_exp > 0 and (prior_exp - recent_exp) > std_error:
            recent_deterioration = True

    sufficient = n >= MIN_RELIABLE_SAMPLE
    if not sufficient:
        rel_status = "INSUFFICIENT_SAMPLE"
    elif expectancy > 0 and ci95_low > -0.5 * std_error:
        rel_status = "POSITIVE_EXPECTANCY"
    elif expectancy <= 0:
        rel_status = "NEGATIVE_EXPECTANCY"
    else:
        rel_status = "INCONCLUSIVE"

    return {
        "sample_size": n,
        "sample_sufficient": sufficient,
        "reliability_status": rel_status,
        "wins": wins,
        "losses": losses,
        "win_rate": round(100.0 * p_win, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "extreme_loss": round(extreme_loss, 2),
        "gross_total": round(gross_total, 2),
        "total_costs": round(total_costs, 2),
        "net_total": round(net_total, 2),
        "expectancy": round(expectancy, 2),
        "expectancy_wl_formula": round(expectancy_wl, 2),
        "std_error": round(std_error, 2),
        "ci95_low": round(ci95_low, 2),
        "ci95_high": round(ci95_high, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown": round(max_dd, 2),
        "max_consecutive_losses": max_loss_streak,
        "recent_deterioration": recent_deterioration,
    }


def compute_probability_calibration(trades: list[dict]) -> dict[str, Any]:
    """
    Avalia a calibração fora da amostra entre as pontuações/probabilidades heurísticas previstas
    no momento da entrada e a frequência real de vitórias observadas (Parte 4.1).
    Calcula Brier Score, Log Loss e tabela de calibração por faixas.
    """
    valid = []
    for t in trades:
        p_val = t.get("confluence_score_at_entry") or t.get("heuristic_prob_at_entry") or t.get("predicted_win_prob") or t.get("predicted_prob")
        if p_val is not None and float(p_val) > 0:
            valid.append(t)
    n_total = len(valid)
    # Usa a segunda metade cronológica como avaliação fora da amostra (OOS) quando houver dados
    ordered = sorted(valid, key=lambda x: int(x.get("close_time") or 0))
    oos_trades = ordered[len(ordered) // 3:] if len(ordered) >= 15 else ordered
    n_oos = len(oos_trades)

    if n_oos == 0:
        return {
            "status": "UNCALIBRATED",
            "sample_size": 0,
            "brier_score": None,
            "log_loss": None,
            "calibrated_win_prob": None,
            "bins": [],
            "note": "Sem amostra com score registrado na entrada para calibração.",
        }

    brier_sum = 0.0
    logloss_sum = 0.0
    bins_spec = [(80.0, 86.0, "80-85"), (86.0, 90.0, "86-89"), (90.0, 100.1, "90-100")]
    bins_out: list[dict] = []

    for t in oos_trades:
        raw_val = float(t.get("predicted_win_prob") or t.get("predicted_prob") or t.get("heuristic_prob_at_entry") or t.get("confluence_score_at_entry") or 50.0)
        raw_p = raw_val if raw_val <= 1.0 else (raw_val / 100.0)
        p = max(0.02, min(0.98, raw_p))
        y = 1.0 if float(t.get("net_profit") or 0.0) >= 0 else 0.0
        brier_sum += (p - y) ** 2
        logloss_sum += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))

    for lo, hi, lbl in bins_spec:
        sub = [
            t for t in oos_trades
            if lo <= float(t.get("confluence_score_at_entry") or t.get("heuristic_prob_at_entry") or 0.0) < hi
        ]
        if sub:
            pred_avg = sum(float(t.get("confluence_score_at_entry") or t.get("heuristic_prob_at_entry") or 0.0) for t in sub) / len(sub)
            obs_win = 100.0 * sum(1 for t in sub if float(t.get("net_profit") or 0.0) >= 0) / len(sub)
            bins_out.append({
                "bucket": lbl,
                "sample_size": len(sub),
                "predicted_mean_pct": round(pred_avg, 1),
                "observed_win_rate_pct": round(obs_win, 1),
                "calibration_gap_pct": round(obs_win - pred_avg, 1),
            })

    brier = round(brier_sum / n_oos, 4)
    ll = round(logloss_sum / n_oos, 4)
    obs_overall = round(100.0 * sum(1 for t in oos_trades if float(t.get("net_profit") or 0.0) >= 0) / n_oos, 1)

    status = "CALIBRATED_OOS" if n_oos >= MIN_CALIBRATION_SAMPLE_OOS else "INSUFFICIENT_SAMPLE"
    return {
        "status": status,
        "sample_size": n_oos,
        "total_recorded": n_total,
        "brier_score": brier,
        "log_loss": ll,
        "calibrated_win_prob": obs_overall if status == "CALIBRATED_OOS" else None,
        "observed_win_rate_pct": obs_overall,
        "bins": bins_out,
        "note": (
            f"Calibração OOS calculada em {n_oos} operações (Brier={brier:.4f})."
            if status == "CALIBRATED_OOS"
            else f"Amostra insuficiente para calibração estatística ({n_oos}/{MIN_CALIBRATION_SAMPLE_OOS} operações)."
        ),
    }


def build_performance_report(
    journal: TradeJournal,
    reference_equity: float = 0.0,
    is_simulated: bool = False,
    source: str = "LIVE_MT5",
) -> dict[str, Any]:
    """
    Constrói o relatório completo de desempenho quantitativo (Parte 4.3, 5.5 e 3.9).
    Separa resultados reais de resultados simulados e contrafactuais.
    """
    trades = journal.fetch_closed_trades(is_simulated=is_simulated, source=source, limit=2000)
    evals = journal.fetch_recent_evaluations(limit=500, is_simulated=is_simulated)
    overall = compute_group_metrics(trades)
    calibration = compute_probability_calibration(trades)

    # Agrupamentos: por estratégia primária, por confluência, por ativo, por timeframe, por regime e por horário
    by_primary_strat: dict[str, list[dict]] = {}
    by_confluence_strat: dict[str, list[dict]] = {}
    by_symbol: dict[str, list[dict]] = {}
    by_timeframe: dict[str, list[dict]] = {}
    by_regime: dict[str, list[dict]] = {}
    by_hour: dict[str, list[dict]] = {}

    for t in trades:
        p_strat = str(t.get("primary_strategy") or "Institucional")
        by_primary_strat.setdefault(p_strat, []).append(t)

        try:
            c_list = json.loads(t.get("confluence_strategies_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            c_list = []
        if not c_list:
            c_list = [p_strat]
        for cs in set(c_list):
            by_confluence_strat.setdefault(str(cs), []).append(t)

        sym = str(t.get("symbol") or "UNKNOWN")
        by_symbol.setdefault(sym, []).append(t)

        tf = str(t.get("timeframe") or "M1")
        by_timeframe.setdefault(tf, []).append(t)

        reg = str(t.get("regime_code") or "UNKNOWN")
        by_regime.setdefault(reg, []).append(t)

        open_ts = int(t.get("open_time") or 0)
        if open_ts > 0:
            hr = datetime.fromtimestamp(open_ts, tz=timezone.utc).strftime("%H:00 UTC")
            by_hour.setdefault(hr, []).append(t)

    # Monitoramento de sobrevivência de pequenas contas (Parte 3.9)
    ref_eq = max(reference_equity, 100.0)
    eff_risks_pct = [
        100.0 * float(t.get("effective_risk_money") or 0.0) / ref_eq
        for t in trades
        if float(t.get("effective_risk_money") or 0.0) > 0
    ]
    blocked_min_lot_count = sum(1 for e in evals if e.get("guard_status") == "BLOCKED_MIN_LOT")
    blocked_risk_count = sum(1 for e in evals if str(e.get("final_decision") or "").startswith("BLOCKED"))

    deteriorating_strategies = [
        k for k, grp in by_primary_strat.items() if compute_group_metrics(grp).get("recent_deterioration")
    ]

    return {
        "is_simulated": is_simulated,
        "source": source,
        "overall": overall,
        "calibration": calibration,
        "by_primary_strategy": {k: compute_group_metrics(v) for k, v in by_primary_strat.items()},
        "by_strategy_confluence": {k: compute_group_metrics(v) for k, v in by_confluence_strat.items()},
        "by_symbol": {k: compute_group_metrics(v) for k, v in by_symbol.items()},
        "by_timeframe": {k: compute_group_metrics(v) for k, v in by_timeframe.items()},
        "by_regime": {k: compute_group_metrics(v) for k, v in by_regime.items()},
        "by_hour": {k: compute_group_metrics(v) for k, v in sorted(by_hour.items())},
        "small_account_survival": {
            "reference_equity_used": round(ref_eq, 2),
            "avg_effective_risk_pct": round(sum(eff_risks_pct) / len(eff_risks_pct), 3) if eff_risks_pct else 0.0,
            "max_effective_risk_pct": round(max(eff_risks_pct), 3) if eff_risks_pct else 0.0,
            "avg_loss_money": overall["avg_loss"],
            "extreme_loss_money": overall["extreme_loss"],
            "max_drawdown_money": overall["max_drawdown"],
            "max_consecutive_losses": overall["max_consecutive_losses"],
            "signals_blocked_min_lot": blocked_min_lot_count,
            "signals_blocked_total_risk": blocked_risk_count,
        },
        "alerts": {
            "insufficient_sample": not overall["sample_sufficient"],
            "deteriorating_strategies": deteriorating_strategies,
        },
        "counterfactuals": journal.fetch_counterfactual_summary(),
    }
