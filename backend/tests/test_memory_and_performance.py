from __future__ import annotations
"""Testes da Memória Quantitativa SQLite (TradeJournal), MFE/MAE e Calibração de Probabilidade (Parte 5)."""
from pathlib import Path
import pytest
from app.trade_journal import TradeJournal
from app.performance import compute_group_metrics, compute_probability_calibration


def test_trade_journal_sqlite_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_quant.db"
    journal = TradeJournal(db_file)

    # 1. Registra avaliação de sinal
    eval_id = journal.record_signal_evaluation({
        "eval_time": 1000,
        "bar_time": 960,
        "symbol": "EURUSD",
        "timeframe": "M1",
        "horizon_type": "SCALP_1VELA",
        "strategy": "Pullback EMA",
        "regime_code": "TREND_UP",
        "direction": "BUY",
        "signal": "BUY",
        "heuristic_score": 88.0,
        "calibrated_prob": 0.62,
        "min_score_required": 86.0,
        "decision": "EXECUTED",
        "block_reason": None,
        "spread_points": 1,
        "atr": 0.0010,
        "entry_ref_price": 1.1000,
        "planned_sl": 1.0985,
        "planned_tp": 1.1025,
        "horizon_duration_s": 90,
    })
    assert eval_id > 0

    # 2. Registra abertura de trade
    trade_id = journal.record_trade_open({
        "position_id": 9991,
        "order_ticket": 1201,
        "deal_ticket": 3401,
        "signal_eval_id": eval_id,
        "symbol": "EURUSD",
        "side": "BUY",
        "mode_key": "LEVE",
        "strategy": "Pullback EMA",
        "regime_code": "TREND_UP",
        "heuristic_score": 88.0,
        "calibrated_prob": 0.62,
        "volume_executed": 0.02,
        "entry_price": 1.1000,
        "initial_sl": 1.0985,
        "initial_tp": 1.1025,
        "sl_confirmed": True,
        "planned_risk_money": 3.0,
        "effective_risk_money": 3.0,
        "open_time": 1000,
    })
    assert trade_id > 0

    # 3. Atualiza MFE e MAE prospectivos
    journal.update_position_excursion(
        position_id=9991,
        favorable_pts=15.0,
        adverse_pts=3.0,
        favorable_ccy=3.0,
        adverse_ccy=0.6,
    )

    # 4. Registra evento de Break-Even
    journal.record_position_event(
        position_id=9991,
        event_time=1045,
        event_type="BREAK_EVEN",
        old_sl=1.0985,
        new_sl=1.1005,
        price=1.1018,
        detail="LUCRO PROTEGIDO",
    )

    # 5. Reconcilia encerramento do trade
    closed_list = [{
        "position_id": 9991,
        "symbol": "EURUSD",
        "side": "BUY",
        "volume": 0.02,
        "entry_price": 1.1000,
        "exit_price": 1.1022,
        "open_time": 1000,
        "close_time": 1080,
        "duration_s": 80,
        "net_profit": 4.40,
        "won": True,
        "is_ai": True,
        "exit_reason": "Take Profit",
    }]
    count = journal.reconcile_completed_trades(closed_list)
    assert count == 1

    trades = journal.fetch_closed_trades()
    assert len(trades) == 1
    assert trades[0]["net_profit"] == 4.40
    assert trades[0]["max_favorable_points"] >= 15.0


def test_performance_metrics_and_calibration():
    sample_trades = [
        {"net_profit": +20.0, "won": 1, "predicted_win_prob": 0.70},
        {"net_profit": +15.0, "won": 1, "predicted_win_prob": 0.65},
        {"net_profit": -10.0, "won": 0, "predicted_win_prob": 0.60},
        {"net_profit": +25.0, "won": 1, "predicted_win_prob": 0.75},
        {"net_profit": -12.0, "won": 0, "predicted_win_prob": 0.55},
    ]
    metrics = compute_group_metrics(sample_trades)
    assert metrics["sample_size"] == 5
    assert metrics["wins"] == 3
    assert metrics["losses"] == 2
    assert metrics["win_rate"] == 60.0
    assert metrics["expectancy"] > 0
    assert metrics["profit_factor"] > 1.0

    cal = compute_probability_calibration(sample_trades)
    assert cal["brier_score"] is not None
    assert 0.0 <= cal["brier_score"] <= 1.0
