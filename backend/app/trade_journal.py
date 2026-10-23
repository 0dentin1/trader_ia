"""Memória Quantitativa Persistente em SQLite (`quant_memory.db`) — Parte 5.

Armazena de forma transacional, idempotente e resistente a falhas:
1. `signal_evaluations`: sinais aprovados, rejeitados ou bloqueados pela camada de risco (com deduplicação por barra).
2. `executed_trades`: operações reais executadas no MT5 (reconciliadas por position_id, com custos, slippage, MFE/MAE).
3. `position_events`: histórico de evolução da posição (deslocamento de stop, falhas de execução, fechamentos parciais).
4. `counterfactual_outcomes`: rotulagem pós-horizonte de sinais bloqueados/rejeitados (estritamente separados das operações reais).
5. `adaptive_rules_state`: versionamento e auditoria de regras adaptativas.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ALGO_VERSION, QUANT_DB_FILE

SCHEMA_VERSION = 1

MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS signal_evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT UNIQUE,
        server_time INTEGER NOT NULL,
        utc_iso TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        bar_time INTEGER NOT NULL,
        direction TEXT,
        primary_strategy_id TEXT,
        primary_strategy TEXT,
        confluence_strategies_json TEXT,
        regime_code TEXT,
        regime_detailed TEXT,
        atr REAL,
        rsi REAL,
        ema9 REAL,
        ema21 REAL,
        ema200 REAL,
        vwap REAL,
        rvol REAL,
        spread_points INTEGER,
        flow_delta REAL,
        flow_enough INTEGER,
        confluence_score REAL,
        heuristic_dir_prob REAL,
        calibrated_prob REAL,
        probability_status TEXT,
        pillars_json TEXT,
        passed_gates_json TEXT,
        failed_gates_json TEXT,
        block_reasons_json TEXT,
        guard_status TEXT,
        adaptive_mode TEXT,
        shadow_would_block INTEGER DEFAULT 0,
        shadow_reason TEXT,
        final_decision TEXT NOT NULL,
        horizon_s INTEGER DEFAULT 90,
        planned_entry REAL DEFAULT 0.0,
        planned_sl REAL DEFAULT 0.0,
        planned_tp REAL DEFAULT 0.0,
        algo_version TEXT NOT NULL,
        config_hash TEXT NOT NULL,
        is_simulated INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_sig_eval_sym_bar ON signal_evaluations(symbol, timeframe, bar_time);
    CREATE INDEX IF NOT EXISTS idx_sig_eval_decision ON signal_evaluations(final_decision, server_time);

    CREATE TABLE IF NOT EXISTS executed_trades (
        position_id INTEGER PRIMARY KEY,
        internal_trade_id TEXT NOT NULL UNIQUE,
        symbol TEXT NOT NULL,
        timeframe TEXT DEFAULT 'M1',
        primary_strategy_id TEXT DEFAULT 'UNKNOWN',
        primary_strategy TEXT DEFAULT 'Institucional',
        confluence_strategies_json TEXT DEFAULT '[]',
        regime_code TEXT DEFAULT 'UNKNOWN',
        mode_key TEXT DEFAULT 'MEDIANO',
        side TEXT NOT NULL,
        requested_volume REAL DEFAULT 0.0,
        executed_volume REAL NOT NULL,
        requested_price REAL DEFAULT 0.0,
        entry_price REAL NOT NULL,
        exit_price REAL DEFAULT 0.0,
        initial_sl REAL DEFAULT 0.0,
        initial_tp REAL DEFAULT 0.0,
        final_sl REAL DEFAULT 0.0,
        final_tp REAL DEFAULT 0.0,
        sl_confirmed INTEGER DEFAULT 0,
        planned_risk_money REAL DEFAULT 0.0,
        effective_risk_money REAL DEFAULT 0.0,
        estimated_costs_money REAL DEFAULT 0.0,
        slippage_points REAL DEFAULT 0.0,
        open_time INTEGER NOT NULL,
        close_time INTEGER DEFAULT 0,
        duration_s INTEGER DEFAULT 0,
        be_shifted_at INTEGER DEFAULT 0,
        mfe_price REAL DEFAULT 0.0,
        mae_price REAL DEFAULT 0.0,
        mfe_atr REAL DEFAULT 0.0,
        mae_atr REAL DEFAULT 0.0,
        max_favorable_points REAL DEFAULT 0.0,
        max_adverse_points REAL DEFAULT 0.0,
        max_favorable_money REAL DEFAULT 0.0,
        max_adverse_money REAL DEFAULT 0.0,
        gross_profit REAL DEFAULT 0.0,
        commission REAL DEFAULT 0.0,
        swap REAL DEFAULT 0.0,
        fee REAL DEFAULT 0.0,
        net_profit REAL DEFAULT 0.0,
        won INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'OPEN',
        exit_reason TEXT DEFAULT '',
        confluence_score_at_entry REAL DEFAULT 0.0,
        heuristic_prob_at_entry REAL DEFAULT 0.0,
        order_tickets_json TEXT DEFAULT '[]',
        deal_tickets_json TEXT DEFAULT '[]',
        partial_closes_count INTEGER DEFAULT 0,
        modify_attempts INTEGER DEFAULT 0,
        modify_failures INTEGER DEFAULT 0,
        algo_version TEXT NOT NULL,
        config_json TEXT DEFAULT '{}',
        is_simulated INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'LIVE_MT5'
    );

    CREATE INDEX IF NOT EXISTS idx_exec_trades_status ON executed_trades(status, is_simulated, close_time);
    CREATE INDEX IF NOT EXISTS idx_exec_trades_strat ON executed_trades(primary_strategy_id, regime_code, is_simulated);

    CREATE TABLE IF NOT EXISTS position_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id INTEGER NOT NULL,
        server_time INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        old_sl REAL DEFAULT 0.0,
        new_sl REAL DEFAULT 0.0,
        price_at_event REAL DEFAULT 0.0,
        details TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_pos_events_pid ON position_events(position_id, server_time);

    CREATE TABLE IF NOT EXISTS counterfactual_outcomes (
        event_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        primary_strategy_id TEXT,
        regime_code TEXT,
        block_reason TEXT,
        eval_time INTEGER NOT NULL,
        horizon_end_time INTEGER NOT NULL,
        entry_price REAL NOT NULL,
        sl_price REAL NOT NULL,
        tp_price REAL NOT NULL,
        exit_price_sim REAL NOT NULL,
        outcome_label TEXT NOT NULL,
        theoretical_r_multiple REAL NOT NULL,
        is_simulated INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS adaptive_rules_state (
        rule_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL DEFAULT 1,
        strategy_id TEXT NOT NULL,
        regime_code TEXT NOT NULL,
        symbol TEXT DEFAULT '*',
        status TEXT NOT NULL DEFAULT 'EXPERIMENTAL',
        action TEXT NOT NULL DEFAULT 'NONE',
        sample_size INTEGER NOT NULL DEFAULT 0,
        expectancy REAL NOT NULL DEFAULT 0.0,
        std_error REAL NOT NULL DEFAULT 0.0,
        profit_factor REAL NOT NULL DEFAULT 0.0,
        enabled_in_active INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    """
}


def compute_config_hash(settings: dict) -> str:
    relevant = {
        k: settings.get(k)
        for k in (
            "mode",
            "account_profile",
            "limit_mode",
            "daily_loss_limit",
            "daily_loss_pct",
            "max_planned_risk_pct",
            "max_aggregate_risk_pct",
            "max_spread_points",
            "risk_pct",
            "adaptive_mode",
        )
    }
    raw = json.dumps(relevant, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


class TradeJournal:
    """Gerenciador SQLite thread-safe da Memória Quantitativa Persistente."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or QUANT_DB_FILE
        self._lock = threading.Lock()
        self._dedup_cache: dict[tuple, int] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);"
                    )
                    cur = conn.execute("SELECT MAX(version) as v FROM schema_migrations;").fetchone()
                    current_v = int(cur["v"] or 0) if cur else 0
                    for v in sorted(MIGRATIONS.keys()):
                        if v > current_v:
                            conn.executescript(MIGRATIONS[v])
                            conn.execute(
                                "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?);",
                                (v, datetime.now(timezone.utc).isoformat()),
                            )
                    conn.commit()
            except sqlite3.Error as exc:
                print(f"[TradeJournal] Erro ao inicializar SQLite: {exc!r}", flush=True)

    # ------------------------------------------------------------------ 5.2 Avaliações de sinal (com deduplicação)
    def record_signal_evaluation(
        self,
        data: dict | None = None,
        *,
        symbol: str = "",
        analysis: dict | None = None,
        final_decision: str = "APPROVED",
        settings: dict | None = None,
        server_time: int = 0,
        guard_status: str = "NOT_EVALUATED",
        extra_block_reasons: list[str] | None = None,
        shadow_would_block: bool = False,
        shadow_reason: str = "",
        planned_entry: float = 0.0,
        planned_sl: float = 0.0,
        planned_tp: float = 0.0,
        is_simulated: bool = False,
        **extra,
    ) -> int | None:
        """
        Registra uma avaliação relevante de sinal (APPROVED, BLOCKED_RISK, BLOCKED_MEMORY, REJECTED_GATE).
        Aceita dicionário direto ou argumentos nomeados e retorna o ID inteiro da avaliação.
        """
        if data:
            d = dict(data)
            symbol = str(d.get("symbol") or symbol or "EURUSD")
            tf = str(d.get("timeframe") or "M1")
            bar_time = int(d.get("bar_time") or 0)
            direction = str(d.get("direction") or "NONE")
            final_decision = str(d.get("decision") or d.get("final_decision") or final_decision)
            strat_name = str(d.get("strategy") or d.get("primary_strategy") or "Institucional")
            strat_id = str(d.get("strategy_id") or d.get("primary_strategy_id") or strat_name)
            regime_code = str(d.get("regime_code") or "UNKNOWN")
            score = float(d.get("heuristic_score") or d.get("score") or 0.0)
            prob_h = float(d.get("next_candle_bias") or 50.0)
            cal_prob = d.get("calibrated_prob")
            guard_status = str(d.get("guard_status") or guard_status)
            block = d.get("block_reason")
            blocks = [str(block)] if block else list(extra_block_reasons or [])
            planned_entry = float(d.get("entry_ref_price") or d.get("planned_entry") or planned_entry)
            planned_sl = float(d.get("planned_sl") or planned_sl)
            planned_tp = float(d.get("planned_tp") or planned_tp)
            horizon_s = int(d.get("horizon_duration_s") or d.get("horizon_s") or 90)
            spread_pts = int(d.get("spread_points") or 0)
            atr_val = float(d.get("atr") or 0.0)
            server_time = int(d.get("eval_time") or d.get("server_time") or server_time or time.time())
            conf_strats = [strat_name]
            passed_gates = ["GATES_OK"]
            failed_gates = []
            pillars = d.get("pillars") or []
            prob_stat = "CALIBRATED" if cal_prob is not None else "UNCALIBRATED"
            rsi_val, ema9_val, ema21_val, ema200_val, vwap_val, rvol_val = 50.0, 0.0, 0.0, 0.0, 0.0, 0.0
            flw_delta, flw_enough = 0.0, 1
            cfg_hash = compute_config_hash(settings or {})
        else:
            if not analysis or not analysis.get("ready"):
                return None
            tf = str(analysis.get("timeframe") or "M1")
            bar_time = int(analysis.get("bar_time") or 0)
            direction = str(analysis.get("direction") or "NONE")
            hz = analysis.get("horizon") or {}
            cdl = analysis.get("candle") or {}
            reg = analysis.get("regime") or {}
            ind = analysis.get("indicators") or {}
            flw = analysis.get("flow") or {}
            cal = analysis.get("calibration") or {}
            gates = analysis.get("gates") or []
            pillars = analysis.get("pillars") or []
            passed_gates = [g["label"] for g in gates if g.get("ok")]
            failed_gates = [g["label"] for g in gates if not g.get("ok")]
            vetoes = (cdl.get("veto_buy") if direction == "BUY" else cdl.get("veto_sell")) or []
            blocks = list(vetoes)
            if analysis.get("study_block") and analysis["study_block"] not in blocks:
                blocks.append(str(analysis["study_block"]))
            if extra_block_reasons:
                for r in extra_block_reasons:
                    if r and r not in blocks:
                        blocks.append(r)
            strat_name = str(hz.get("strategy") or "Aguardando Setup")
            strat_id = str(hz.get("strategy_id") or "NONE")
            regime_code = str(reg.get("code") or "UNKNOWN")
            score = float(analysis.get("score") or 0.0)
            prob_h = float(cdl.get("prob_up", 50.0) if direction == "BUY" else cdl.get("prob_down", 50.0))
            conf_strats = hz.get("confluence_strategies") or (
                cdl.get("buy_strategies") if direction == "BUY" else cdl.get("sell_strategies")
            ) or []
            cal_prob = cal.get("calibrated_win_prob")
            prob_stat = str(cal.get("probability_status") or "UNCALIBRATED")
            rsi_val = float(ind.get("rsi") or 50.0)
            ema9_val = float(ind.get("ema9") or 0.0)
            ema21_val = float(ind.get("ema21") or 0.0)
            ema200_val = float(ind.get("ema200") or 0.0)
            vwap_val = float(ind.get("vwap") or 0.0)
            rvol_val = float(ind.get("rvol") or 0.0)
            spread_pts = int(analysis.get("spread_points") or 0)
            atr_val = float(analysis.get("atr") or 0.0)
            flw_delta = float(flw.get("delta") or 0.0)
            flw_enough = 1 if flw.get("enough") else 0
            horizon_s = int(hz.get("duration_s") or 90)
            cfg_hash = compute_config_hash(settings or {})

        dedup_key = (symbol, tf, bar_time, direction, final_decision, guard_status)

        with self._lock:
            if self._dedup_cache.get(dedup_key) == bar_time and final_decision != "EXECUTED":
                return None
            self._dedup_cache[dedup_key] = bar_time
            if len(self._dedup_cache) > 2000:
                self._dedup_cache.clear()

            raw_id = f"{symbol}:{tf}:{bar_time}:{direction}:{final_decision}:{guard_status}:{time.time()}"
            event_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:20]

            try:
                with self._connect() as conn:
                    cur = conn.execute(
                        """
                        INSERT OR REPLACE INTO signal_evaluations (
                            event_id, server_time, utc_iso, symbol, timeframe, bar_time,
                            direction, primary_strategy_id, primary_strategy, confluence_strategies_json,
                            regime_code, regime_detailed, atr, rsi, ema9, ema21, ema200, vwap, rvol,
                            spread_points, flow_delta, flow_enough, confluence_score, heuristic_dir_prob,
                            calibrated_prob, probability_status, pillars_json, passed_gates_json,
                            failed_gates_json, block_reasons_json, guard_status, adaptive_mode,
                            shadow_would_block, shadow_reason, final_decision, horizon_s,
                            planned_entry, planned_sl, planned_tp, algo_version, config_hash, is_simulated
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        );
                        """,
                        (
                            event_id,
                            int(server_time or time.time()),
                            datetime.now(timezone.utc).isoformat(),
                            symbol,
                            tf,
                            bar_time,
                            direction,
                            strat_id,
                            strat_name,
                            json.dumps(conf_strats, ensure_ascii=False),
                            regime_code,
                            regime_code,
                            atr_val,
                            rsi_val,
                            ema9_val,
                            ema21_val,
                            ema200_val,
                            vwap_val,
                            rvol_val,
                            spread_pts,
                            flw_delta,
                            flw_enough,
                            score,
                            prob_h,
                            cal_prob,
                            prob_stat,
                            json.dumps(
                                [{"id": p.get("id"), "score": p.get("score"), "ok": p.get("ok")} for p in pillars]
                                if pillars else [],
                                ensure_ascii=False,
                            ),
                            json.dumps(passed_gates, ensure_ascii=False),
                            json.dumps(failed_gates, ensure_ascii=False),
                            json.dumps(blocks, ensure_ascii=False),
                            guard_status,
                            str((settings or {}).get("adaptive_mode") or "OBSERVATION"),
                            1 if shadow_would_block else 0,
                            shadow_reason,
                            final_decision,
                            horizon_s,
                            float(planned_entry),
                            float(planned_sl),
                            float(planned_tp),
                            ALGO_VERSION,
                            cfg_hash,
                            1 if is_simulated else 0,
                        ),
                    )
                    conn.commit()
                    return int(cur.lastrowid or 1)
            except sqlite3.Error as exc:
                print(f"[TradeJournal] Erro ao gravar signal_evaluation: {exc!r}", flush=True)
                return None

    # ------------------------------------------------------------------ 5.3 & 5.4 Registro e evolução de operações
    def record_trade_open(
        self,
        data: dict | None = None,
        *,
        position_id: int = 0,
        symbol: str = "",
        timeframe: str = "M1",
        primary_strategy_id: str = "UNKNOWN",
        primary_strategy: str = "Institucional",
        confluence_strategies: list[str] | None = None,
        regime_code: str = "UNKNOWN",
        mode_key: str = "MEDIANO",
        side: str = "BUY",
        requested_volume: float = 0.0,
        executed_volume: float = 0.0,
        requested_price: float = 0.0,
        entry_price: float = 0.0,
        initial_sl: float = 0.0,
        initial_tp: float = 0.0,
        sl_confirmed: bool = True,
        planned_risk_money: float = 0.0,
        effective_risk_money: float = 0.0,
        estimated_costs_money: float = 0.0,
        slippage_points: float = 0.0,
        open_time: int = 0,
        confluence_score_at_entry: float = 0.0,
        heuristic_prob_at_entry: float = 0.0,
        order_ticket: int = 0,
        deal_ticket: int = 0,
        settings: dict | None = None,
        is_simulated: bool = False,
        source: str = "LIVE_MT5",
        **extra,
    ) -> int:
        if data:
            d = dict(data)
            position_id = int(d.get("position_id") or position_id or 1)
            symbol = str(d.get("symbol") or symbol or "EURUSD")
            timeframe = str(d.get("timeframe") or timeframe)
            primary_strategy = str(d.get("strategy") or d.get("primary_strategy") or primary_strategy)
            primary_strategy_id = str(d.get("strategy_id") or d.get("primary_strategy_id") or primary_strategy)
            regime_code = str(d.get("regime_code") or regime_code)
            mode_key = str(d.get("mode_key") or mode_key)
            side = str(d.get("side") or side)
            requested_volume = float(d.get("volume_requested") or d.get("requested_volume") or requested_volume or 0.01)
            executed_volume = float(d.get("volume_executed") or d.get("executed_volume") or executed_volume or requested_volume)
            requested_price = float(d.get("requested_price") or requested_price or d.get("entry_price") or entry_price)
            entry_price = float(d.get("entry_price") or entry_price)
            initial_sl = float(d.get("initial_sl") or initial_sl)
            initial_tp = float(d.get("initial_tp") or initial_tp)
            sl_confirmed = bool(d.get("sl_confirmed", sl_confirmed))
            planned_risk_money = float(d.get("planned_risk_money") or planned_risk_money)
            effective_risk_money = float(d.get("effective_risk_money") or effective_risk_money)
            estimated_costs_money = float(d.get("estimated_costs_money") or estimated_costs_money)
            slippage_points = float(d.get("slippage_points") or slippage_points)
            open_time = int(d.get("open_time") or open_time or time.time())
            confluence_score_at_entry = float(d.get("heuristic_score") or d.get("confluence_score_at_entry") or confluence_score_at_entry)
            heuristic_prob_at_entry = float(d.get("calibrated_prob") or d.get("heuristic_prob_at_entry") or heuristic_prob_at_entry)
            order_ticket = int(d.get("order_ticket") or order_ticket)
            deal_ticket = int(d.get("deal_ticket") or deal_ticket)
            confluence_strategies = d.get("confluence_strategies") or confluence_strategies or []
            settings = d.get("settings") or settings or {}
            is_simulated = bool(d.get("is_simulated", is_simulated))
            source = str(d.get("source") or source)

        internal_id = f"{source}:{position_id}:{open_time}"
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO executed_trades (
                            position_id, internal_trade_id, symbol, timeframe,
                            primary_strategy_id, primary_strategy, confluence_strategies_json,
                            regime_code, mode_key, side, requested_volume, executed_volume,
                            requested_price, entry_price, initial_sl, initial_tp, final_sl, final_tp,
                            sl_confirmed, planned_risk_money, effective_risk_money, estimated_costs_money,
                            slippage_points, open_time, mfe_price, mae_price, confluence_score_at_entry,
                            heuristic_prob_at_entry, order_tickets_json, deal_tickets_json,
                            algo_version, config_json, is_simulated, source, status
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN'
                        )
                        ON CONFLICT(position_id) DO UPDATE SET
                            sl_confirmed = excluded.sl_confirmed,
                            final_sl = CASE WHEN excluded.initial_sl > 0 THEN excluded.initial_sl ELSE executed_trades.final_sl END,
                            final_tp = CASE WHEN excluded.initial_tp > 0 THEN excluded.initial_tp ELSE executed_trades.final_tp END;
                        """,
                        (
                            int(position_id),
                            internal_id,
                            symbol,
                            timeframe,
                            primary_strategy_id or "UNKNOWN",
                            primary_strategy or "Institucional",
                            json.dumps(confluence_strategies or [], ensure_ascii=False),
                            regime_code or "UNKNOWN",
                            mode_key,
                            side,
                            float(requested_volume),
                            float(executed_volume),
                            float(requested_price),
                            float(entry_price),
                            float(initial_sl),
                            float(initial_tp),
                            float(initial_sl),
                            float(initial_tp),
                            1 if sl_confirmed else 0,
                            float(planned_risk_money),
                            float(effective_risk_money),
                            float(estimated_costs_money),
                            float(slippage_points),
                            int(open_time),
                            float(entry_price),
                            float(entry_price),
                            float(confluence_score_at_entry),
                            float(heuristic_prob_at_entry),
                            json.dumps([int(order_ticket)] if order_ticket else []),
                            json.dumps([int(deal_ticket)] if deal_ticket else []),
                            ALGO_VERSION,
                            json.dumps({"hash": compute_config_hash(settings or {})}),
                            1 if is_simulated else 0,
                            source,
                        ),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                print(f"[TradeJournal] Erro em record_trade_open: {exc!r}", flush=True)
        return int(position_id)

    def update_position_excursion(
        self,
        *,
        position_id: int,
        favorable_pts: float = 0.0,
        adverse_pts: float = 0.0,
        favorable_ccy: float = 0.0,
        adverse_ccy: float = 0.0,
        mfe_price: float = 0.0,
        mae_price: float = 0.0,
        mfe_atr: float = 0.0,
        mae_atr: float = 0.0,
        max_favorable_money: float = 0.0,
        max_adverse_money: float = 0.0,
        current_sl: float = 0.0,
        current_tp: float = 0.0,
        be_shifted_at: int = 0,
        modify_attempts: int = 0,
        modify_failures: int = 0,
        **extra,
    ) -> None:
        """Atualiza prospectivamente MFE e MAE da posição aberta sem jamais usar dados futuros."""
        fav_m = max(float(favorable_ccy), float(max_favorable_money))
        adv_m = max(float(adverse_ccy), float(max_adverse_money))
        fav_p = float(favorable_pts)
        adv_p = float(adverse_pts)
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        UPDATE executed_trades SET
                            max_favorable_points = MAX(max_favorable_points, ?),
                            max_adverse_points = MAX(max_adverse_points, ?),
                            max_favorable_money = MAX(max_favorable_money, ?),
                            max_adverse_money = MAX(max_adverse_money, ?),
                            mfe_price = CASE WHEN ? > 0 THEN ? ELSE mfe_price END,
                            mae_price = CASE WHEN ? > 0 THEN ? ELSE mae_price END,
                            mfe_atr = MAX(mfe_atr, ?),
                            mae_atr = MAX(mae_atr, ?),
                            final_sl = CASE WHEN ? > 0 THEN ? ELSE final_sl END,
                            final_tp = CASE WHEN ? > 0 THEN ? ELSE final_tp END,
                            be_shifted_at = CASE WHEN be_shifted_at = 0 AND ? > 0 THEN ? ELSE be_shifted_at END,
                            modify_attempts = MAX(modify_attempts, ?),
                            modify_failures = MAX(modify_failures, ?)
                        WHERE position_id = ?;
                        """,
                        (
                            fav_p,
                            adv_p,
                            round(fav_m, 2),
                            round(adv_m, 2),
                            float(mfe_price),
                            float(mfe_price),
                            float(mae_price),
                            float(mae_price),
                            round(float(mfe_atr), 4),
                            round(float(mae_atr), 4),
                            float(current_sl),
                            float(current_sl),
                            float(current_tp),
                            float(current_tp),
                            int(be_shifted_at),
                            int(be_shifted_at),
                            int(modify_attempts),
                            int(modify_failures),
                            int(position_id),
                        ),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                print(f"[TradeJournal] Erro em update_position_excursion: {exc!r}", flush=True)

    def record_position_event(
        self,
        position_id: int,
        server_time: int = 0,
        event_type: str = "",
        old_sl: float = 0.0,
        new_sl: float = 0.0,
        price_at_event: float = 0.0,
        details: str = "",
        event_time: int | None = None,
        price: float | None = None,
        detail: str | None = None,
        **extra,
    ) -> None:
        t = int(event_time if event_time is not None else (server_time or time.time()))
        p = float(price if price is not None else price_at_event)
        d = str(detail if detail is not None else details)
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO position_events (
                            position_id, server_time, event_type, old_sl, new_sl, price_at_event, details
                        ) VALUES (?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            int(position_id),
                            t,
                            str(event_type),
                            float(old_sl),
                            float(new_sl),
                            p,
                            d,
                        ),
                    )
                    conn.commit()
            except sqlite3.Error:
                pass

    def reconcile_completed_trades(self, completed_trades: list[dict], is_simulated: bool = False, source: str = "LIVE_MT5") -> int:
        """
        Sincroniza de forma idempotente as operações encerradas e reconciliadas do MT5 com o banco SQLite.
        Nunca duplica resultados quando reprocessado várias vezes!
        """
        if not completed_trades:
            return 0
        count = 0
        with self._lock:
            try:
                with self._connect() as conn:
                    for t in completed_trades:
                        if not t.get("is_ai") and source == "LIVE_MT5":
                            continue
                        pid = int(t["position_id"])
                        open_t = int(t.get("open_time") or 0)
                        close_t = int(t.get("close_time") or 0)
                        dur_s = max(0, close_t - open_t)
                        net = float(t.get("net_profit") or 0.0)
                        gross = float(t.get("gross_profit") or 0.0)
                        comm = float(t.get("commission") or 0.0)
                        swap = float(t.get("swap") or 0.0)
                        won = 1 if net >= 0 else 0
                        internal_id = f"{source}:{pid}:{open_t}"

                        conn.execute(
                            """
                            INSERT INTO executed_trades (
                                position_id, internal_trade_id, symbol, mode_key, side,
                                executed_volume, entry_price, exit_price, open_time, close_time,
                                duration_s, gross_profit, commission, swap, net_profit, won,
                                status, exit_reason, order_tickets_json, deal_tickets_json,
                                partial_closes_count, algo_version, is_simulated, source
                            ) VALUES (
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', ?, ?, ?, ?, ?, ?, ?
                            )
                            ON CONFLICT(position_id) DO UPDATE SET
                                exit_price = excluded.exit_price,
                                close_time = excluded.close_time,
                                duration_s = excluded.duration_s,
                                gross_profit = excluded.gross_profit,
                                commission = excluded.commission,
                                swap = excluded.swap,
                                net_profit = excluded.net_profit,
                                won = excluded.won,
                                status = 'CLOSED',
                                exit_reason = excluded.exit_reason,
                                order_tickets_json = excluded.order_tickets_json,
                                deal_tickets_json = excluded.deal_tickets_json,
                                partial_closes_count = excluded.partial_closes_count;
                            """,
                            (
                                pid,
                                internal_id,
                                str(t.get("symbol") or ""),
                                str(t.get("mode") or "MEDIANO"),
                                str(t.get("side") or "BUY"),
                                float(t.get("volume") or 0.0),
                                float(t.get("entry_price") or 0.0),
                                float(t.get("exit_price") or 0.0),
                                open_t,
                                close_t,
                                dur_s,
                                gross,
                                comm,
                                swap,
                                net,
                                won,
                                str(t.get("exit_reason") or "Encerrado"),
                                json.dumps(t.get("order_tickets") or []),
                                json.dumps(t.get("deal_tickets") or []),
                                int(t.get("partial_closes_count") or 1),
                                ALGO_VERSION,
                                1 if is_simulated else 0,
                                source,
                            ),
                        )
                        count += 1
                    conn.commit()
            except sqlite3.Error as exc:
                print(f"[TradeJournal] Erro em reconcile_completed_trades: {exc!r}", flush=True)
        return count

    # ------------------------------------------------------------------ 5.8 Oportunidades rejeitadas (Contrafactuais)
    def evaluate_pending_counterfactuals(self, symbol: str, df_m1: Any, server_now: int) -> int:
        """
        Rotula o resultado teórico de sinais bloqueados/rejeitados SOMENTE depois que a janela
        (`server_time + horizon_s`) já terminou, usando estritamente dados posteriores à entrada.
        Identificados como `is_simulated = 1` em `counterfactual_outcomes`, separados de trades reais.
        """
        if df_m1 is None or len(df_m1) < 10 or server_now <= 0:
            return 0
        labeled = 0
        with self._lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT s.event_id, s.symbol, s.direction, s.primary_strategy_id, s.regime_code,
                               s.block_reasons_json, s.server_time, s.horizon_s,
                               s.planned_entry, s.planned_sl, s.planned_tp
                        FROM signal_evaluations s
                        LEFT JOIN counterfactual_outcomes c ON s.event_id = c.event_id
                        WHERE c.event_id IS NULL
                          AND s.symbol = ?
                          AND s.final_decision LIKE 'BLOCKED%'
                          AND s.planned_entry > 0 AND s.planned_sl > 0 AND s.planned_tp > 0
                          AND (s.server_time + s.horizon_s) <= ?
                        LIMIT 25;
                        """,
                        (symbol, int(server_now)),
                    ).fetchall()

                    if not rows:
                        return 0

                    times = df_m1["time"].to_numpy(dtype=int)
                    highs = df_m1["high"].to_numpy(dtype=float)
                    lows = df_m1["low"].to_numpy(dtype=float)
                    closes = df_m1["close"].to_numpy(dtype=float)

                    for r in rows:
                        t_start = int(r["server_time"])
                        t_end = t_start + int(r["horizon_s"] or 90)
                        mask = (times >= t_start) & (times <= t_end)
                        if not mask.any():
                            continue

                        w_highs = highs[mask]
                        w_lows = lows[mask]
                        w_closes = closes[mask]
                        entry = float(r["planned_entry"])
                        sl = float(r["planned_sl"])
                        tp = float(r["planned_tp"])
                        side = str(r["direction"] or "BUY")
                        risk_dist = max(abs(entry - sl), 1e-9)

                        outcome = "TIME_EXIT"
                        exit_p = float(w_closes[-1])
                        # Regra conservadora: se tanto SL quanto TP foram tocados na janela, assume SL primeiro!
                        if side == "BUY":
                            hit_sl = bool((w_lows <= sl).any())
                            hit_tp = bool((w_highs >= tp).any())
                            if hit_sl:
                                outcome = "SIM_SL_HIT"
                                exit_p = sl
                            elif hit_tp:
                                outcome = "SIM_TP_HIT"
                                exit_p = tp
                            r_mult = (exit_p - entry) / risk_dist
                        else:
                            hit_sl = bool((w_highs >= sl).any())
                            hit_tp = bool((w_lows <= tp).any())
                            if hit_sl:
                                outcome = "SIM_SL_HIT"
                                exit_p = sl
                            elif hit_tp:
                                outcome = "SIM_TP_HIT"
                                exit_p = tp
                            r_mult = (entry - exit_p) / risk_dist

                        blocks = json.loads(r["block_reasons_json"] or "[]")
                        block_str = blocks[0] if blocks else "Bloqueado"
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO counterfactual_outcomes (
                                event_id, symbol, direction, primary_strategy_id, regime_code,
                                block_reason, eval_time, horizon_end_time, entry_price, sl_price,
                                tp_price, exit_price_sim, outcome_label, theoretical_r_multiple, is_simulated
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1);
                            """,
                            (
                                r["event_id"],
                                r["symbol"],
                                side,
                                r["primary_strategy_id"],
                                r["regime_code"],
                                block_str,
                                t_start,
                                t_end,
                                entry,
                                sl,
                                tp,
                                exit_p,
                                outcome,
                                round(float(r_mult), 3),
                            ),
                        )
                        labeled += 1
                    conn.commit()
            except sqlite3.Error:
                pass
        return labeled

    # ------------------------------------------------------------------ consultas para performance & frontend
    def fetch_closed_trades(self, *, is_simulated: bool = False, source: str | None = "LIVE_MT5", limit: int = 1000) -> list[dict]:
        with self._lock:
            try:
                with self._connect() as conn:
                    if source:
                        rows = conn.execute(
                            """
                            SELECT * FROM executed_trades
                            WHERE status = 'CLOSED' AND is_simulated = ? AND source = ?
                            ORDER BY close_time DESC LIMIT ?;
                            """,
                            (1 if is_simulated else 0, source, int(limit)),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """
                            SELECT * FROM executed_trades
                            WHERE status = 'CLOSED' AND is_simulated = ?
                            ORDER BY close_time DESC LIMIT ?;
                            """,
                            (1 if is_simulated else 0, int(limit)),
                        ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error:
                return []

    def list_trades(self, only_closed: bool = True, limit: int = 500, is_simulated: bool = False) -> list[dict]:
        return self.fetch_closed_trades(is_simulated=is_simulated, limit=limit)

    def list_signal_evaluations(self, limit: int = 500, is_simulated: bool = False) -> list[dict]:
        return self.fetch_recent_evaluations(limit=limit, is_simulated=is_simulated)

    def get_summary_counters(self) -> dict[str, int]:
        with self._lock:
            try:
                with self._connect() as conn:
                    t_count = conn.execute("SELECT COUNT(*) FROM executed_trades;").fetchone()[0]
                    s_count = conn.execute("SELECT COUNT(*) FROM signal_evaluations;").fetchone()[0]
                    c_count = conn.execute("SELECT COUNT(*) FROM counterfactual_outcomes;").fetchone()[0]
                    return {"trades": int(t_count), "evaluations": int(s_count), "counterfactuals": int(c_count)}
            except Exception:
                return {"trades": 0, "evaluations": 0, "counterfactuals": 0}

    def fetch_recent_evaluations(self, limit: int = 100, is_simulated: bool = False) -> list[dict]:
        with self._lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT * FROM signal_evaluations
                        WHERE is_simulated = ?
                        ORDER BY server_time DESC LIMIT ?;
                        """,
                        (1 if is_simulated else 0, int(limit)),
                    ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error:
                return []

    def fetch_counterfactual_summary(self) -> dict:
        with self._lock:
            try:
                with self._connect() as conn:
                    rows = conn.execute("SELECT * FROM counterfactual_outcomes ORDER BY eval_time DESC LIMIT 200;").fetchall()
                    items = [dict(r) for r in rows]
                    n = len(items)
                    saved_losses = sum(1 for x in items if x["theoretical_r_multiple"] < 0)
                    missed_wins = sum(1 for x in items if x["theoretical_r_multiple"] > 0)
                    avg_r = round(sum(float(x["theoretical_r_multiple"]) for x in items) / n, 3) if n > 0 else 0.0
                    return {
                        "is_simulated": True,
                        "note": "Resultados contrafactuais simulados (NÃO incluídos no lucro real).",
                        "sample_size": n,
                        "blocked_would_have_lost": saved_losses,
                        "blocked_would_have_won": missed_wins,
                        "avg_theoretical_r": avg_r,
                        "recent": items[:15],
                    }
            except sqlite3.Error:
                return {"is_simulated": True, "sample_size": 0, "blocked_would_have_lost": 0, "blocked_would_have_won": 0, "avg_theoretical_r": 0.0, "recent": []}
