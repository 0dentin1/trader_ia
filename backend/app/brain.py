"""MEGA BRAIN V5 (QUANT) — Orquestrador Multi-Cérebros com Governança Independente de Risco,
Travas Persistentes de Sessão/Semana, Proteção Confirmada de SL/TP, Reconciliação de Execução,
Separação de P&L (Magic vs Conta Inteira), Memória Histórica SQLite e Adaptação Baseada em Evidências."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import MAX_CONCURRENT_TRADES, MODES, ModeConfig
from .mt5_bridge import (
    RET_NO_CHANGES,
    SYMBOL_TRADE_MODE_CLOSEONLY,
    SYMBOL_TRADE_MODE_DISABLED,
    SYMBOL_TRADE_MODE_LONGONLY,
    SYMBOL_TRADE_MODE_SHORTONLY,
    MT5Bridge,
)
from .risk import (
    build_plan,
    evaluate_portfolio_protection,
    is_ai_attributed,
    is_position_sl_confirmed_safe,
    usd_exposure_dir,
)
from .settings_store import SettingsStore, compute_trading_day, compute_trading_week
from .small_account_guard import classify_drawdown_state
from .utils import LogBook

if TYPE_CHECKING:
    from .adaptive_rules import AdaptiveRulesEngine
    from .trade_journal import TradeJournal

STATE_LABELS = {
    "OFF": "Mega Brain V5 Quant desligado · somente leitura",
    "DISCONNECTED": "MT5 desconectado",
    "WAITING_DATA_SYNC": "Sincronizando dados M1/M2/M5/M15 e validando cotações",
    "STUDYING_MARKET": "Cérebros analisando 5 Estratégias Institucionais em todas as moedas",
    "EVALUATING_CONFLUENCE": "Validando alinhamento M1+M5+M15, estrutura e custo de execução",
    "EXECUTING_TRADE": "Enviando ordem com validação de risco e confirmação de SL/TP",
    "MANAGING_POSITION": "Gerenciando operação (MFE/MAE, Break-Even e Trailing configurável)",
    "COOLDOWN": "Pausa tática curta entre disparos",
    "RISK_LOCK": "Trava de proteção de capital ativa na sessão/semana",
    "CRITICAL_EXECUTION_FAILURE": "Falha crítica de execução/SL — revisão obrigatória",
}
SIDE_PT = {"BUY": "COMPRA", "SELL": "VENDA"}


@dataclass
class ManagedTrade:
    ticket: int
    symbol: str
    side: str
    entry: float
    initial_sl: float
    tp: float
    atr: float
    mode_key: str
    horizon_type: str = "SCALP_1VELA"
    horizon_label: str = "⚡ Vela (90s)"
    max_duration_s: int = 90
    open_server_time: int = 0
    be_done: bool = False
    half_risk_done: bool = False
    sl_confirmed: bool = False
    last_modify: float = 0.0
    strategy: str = "Confluência Institucional"
    regime_code: str = "UNKNOWN"
    max_favorable_pts: float = 0.0
    max_adverse_pts: float = 0.0
    max_favorable_ccy: float = 0.0
    max_adverse_ccy: float = 0.0


@dataclass
class SymbolMemory:
    symbol: str
    consec_losses: int = 0
    last_loss_side: str | None = None
    last_loss_time: int = 0
    last_loss_price: float = 0.0
    quarantine_until: int = 0
    last_entry_bar: int = 0
    last_entry_time: int = 0
    wins: int = 0
    losses: int = 0


@dataclass
class Ctx:
    symbol: str
    sym: dict
    tick: dict
    analysis: dict
    positions: list[dict]
    account: dict
    terminal: dict
    day: dict
    server_time: int
    server_day: int
    mode: ModeConfig
    settings: dict
    tf_seconds: int
    server_week: int | None = None
    all_positions: list[dict] | None = None
    symbol_map: dict[str, dict] | None = None


class Brain:
    def __init__(
        self,
        bridge: MT5Bridge,
        store: SettingsStore,
        logs: LogBook,
        journal: "TradeJournal | None" = None,
        adaptive: "AdaptiveRulesEngine | None" = None,
    ) -> None:
        self.bridge = bridge
        self.store = store
        self.logs = logs
        self.journal = journal
        self.adaptive = adaptive
        self.enabled = False
        self.state = "OFF"
        self.detail = "Ligue a IA autônoma para ativar os cérebros em todas as moedas."
        self.trades: dict[int, ManagedTrade] = {}
        self.known_ai: set[int] = set()
        self.cooldown_until = 0
        self.cooldown_reason = ""
        self.retry_after = 0.0
        self.last_global_open_mono = 0.0
        self._last_bar_seen: dict[str, int] = {}
        self._last_cf_eval_mono: float = 0.0

        # 1 Cérebro de Memória por Moeda
        self.mem: dict[str, SymbolMemory] = {}
        self.consecutive_losses = 0
        self.recovery_deficit = 0.0
        self._synced_trade_ids: set[int] = set()
        self.last_risk_evaluation: dict = {}

    # ------------------------------------------------------------------ memória crítica & anti-teimosia
    def sync_from_history(self, trades: list[dict], server_now: int) -> None:
        ai_trades = [t for t in reversed(trades) if t.get("is_ai")]
        for t in ai_trades:
            pid = int(t["position_id"])
            if pid in self._synced_trade_ids:
                continue
            self._synced_trade_ids.add(pid)
            sym = str(t.get("symbol") or "")
            side = str(t.get("side") or "BUY")
            net = float(t.get("net_profit") or 0.0)
            close_t = int(t.get("close_time") or 0)
            exit_p = float(t.get("exit_price") or 0.0)
            m = self.mem.setdefault(sym, SymbolMemory(symbol=sym))
            is_recent = bool(server_now and (server_now - close_t) <= 1200)
            if net >= 0:
                m.wins += 1
                m.consec_losses = 0
                m.last_loss_side = None
                if is_recent:
                    self.consecutive_losses = 0
                    self.recovery_deficit = max(0.0, round(self.recovery_deficit - net, 2))
            else:
                m.losses += 1
                if is_recent:
                    m.consec_losses += 1
                    m.last_loss_side = side
                    m.last_loss_time = close_t
                    m.last_loss_price = exit_p
                    self.consecutive_losses += 1
                    self.recovery_deficit = round(self.recovery_deficit + abs(net), 2)
                    if m.consec_losses >= 2 and (server_now - close_t) < 600:
                        m.quarantine_until = close_t + 600

        if self.journal:
            try:
                self.journal.reconcile_completed_trades(ai_trades)
            except Exception:  # noqa: BLE001
                pass

    def evaluate_symbol_memory(
        self,
        symbol: str,
        direction: str | None,
        score: float,
        min_score: float,
        server_time: int,
        tf_seconds: int,
    ) -> tuple[bool, float, str | None]:
        m = self.mem.get(symbol)
        if not m or not server_time:
            return True, 0.0, None

        age = max(0, server_time - m.last_loss_time)
        if m.quarantine_until > server_time:
            rem = m.quarantine_until - server_time
            return False, 30.0, f"Cérebro {symbol} em quarentena pós-{m.consec_losses} perdas ({rem}s)"

        block_window = max(3 * tf_seconds, 240)
        if m.consec_losses >= 1 and m.last_loss_side == direction and age < block_window:
            rem = block_window - age
            return (
                False,
                20.0,
                f"Anti-Teimosia: bloqueado repetir {SIDE_PT.get(direction or 'BUY', '')} em {symbol} ({rem}s)",
            )

        # Intervalo mínimo após fechar operação na mesma moeda (60s para esperar nova estrutura limpa)
        if m.last_entry_time and (server_time - m.last_entry_time) < 60:
            return False, 12.0, f"Aguardando nova vela limpa em {symbol}"

        penalty = min(16.0, m.consec_losses * 6.0) if age < 600 else 0.0
        return True, penalty, None

    def required_score(self, base_min: float) -> float:
        floor = max(84.0, base_min)
        if self.consecutive_losses >= 1:
            return min(91.0, floor + 2.0)
        return floor

    # ------------------------------------------------------------------ utilidades
    def _set(self, state: str, detail: str = "") -> None:
        if state != self.state:
            self.logs.add(
                f"Estado → {state} · {STATE_LABELS.get(state, state)}" + (f" — {detail}" if detail else ""),
                "state",
            )
        self.state = state
        self.detail = detail

    def lock_info(self, server_day: int | None, server_week: int | None = None) -> dict:
        return self.store.is_lock_active(server_day, server_week)

    def get_trade_meta(self, ticket: int) -> ManagedTrade | None:
        return self.trades.get(ticket)

    def public(
        self,
        server_day: int | None,
        active_brains_count: int = 0,
        server_week: int | None = None,
    ) -> dict:
        rec_active = self.consecutive_losses >= 1
        lock_state = self.lock_info(server_day, server_week)
        return {
            "enabled": self.enabled,
            "state": self.state,
            "state_label": STATE_LABELS.get(self.state, self.state),
            "detail": self.detail,
            "cooldown_until": self.cooldown_until,
            "cooldown_reason": self.cooldown_reason,
            "active_brains": active_brains_count,
            "max_concurrent": MAX_CONCURRENT_TRADES,
            "lock": lock_state,
            "adaptive_mode": self.store.get("adaptive_mode") or "OBSERVATION",
            "account_profile": self.store.get("account_profile") or "SMALL_ACCOUNT_PROTECTION",
            "last_risk_evaluation": self.last_risk_evaluation,
            "recovery": {
                "active": rec_active,
                "consecutive_losses": self.consecutive_losses,
                "deficit": round(self.recovery_deficit, 2),
                "martingale_allowed": False,
            },
            "managed": [
                {
                    "ticket": t.ticket,
                    "symbol": t.symbol,
                    "be_done": t.be_done,
                    "sl_confirmed": t.sl_confirmed,
                    "initial_sl": t.initial_sl,
                    "atr": t.atr,
                    "mode": t.mode_key,
                    "horizon_type": t.horizon_type,
                    "horizon_label": t.horizon_label,
                    "max_duration_s": t.max_duration_s,
                    "mfe_pts": round(t.max_favorable_pts, 1),
                    "mae_pts": round(t.max_adverse_pts, 1),
                    "mfe_ccy": round(t.max_favorable_ccy, 2),
                    "mae_ccy": round(t.max_adverse_ccy, 2),
                }
                for t in self.trades.values()
            ],
        }

    def reset_symbol(self) -> None:
        pass

    def on_disconnect(self) -> None:
        self._set("DISCONNECTED", "Aguardando reconexão com o terminal MT5.")

    # ------------------------------------------------------------------ comandos (Parte 2.1: Travas persistentes)
    def try_enable(
        self,
        connected: bool,
        account: dict,
        terminal: dict,
        sym: dict | None,
        settings: dict,
        server_day: int | None,
        current_day_total: float = 0.0,
        server_time: int | None = None,
        current_week_total: float = 0.0,
    ) -> tuple[bool, str]:
        if not connected:
            return False, "MT5 desconectado."
        if sym is None:
            return False, "Nenhum ativo disponível."
        if float(settings.get("daily_loss_limit") or 0) <= 0:
            return False, "Defina um Stop Loss Diário (> 0) antes de ligar a IA."
        if not terminal.get("trade_allowed"):
            return False, "Botão 'Algo Trading' desativado no terminal MT5. Ative-o para permitir ordens."
        if not account.get("trade_allowed"):
            return False, "A conta não permite negociação (trade_allowed = False)."
        if not account.get("trade_expert"):
            return False, "A corretora não permite negociação automatizada nesta conta (trade_expert = False)."

        rollover_h = int(settings.get("broker_rollover_hour") or 0)
        eff_day = server_day
        eff_week = None
        if server_time and server_time > 0:
            eff_day = compute_trading_day(server_time, rollover_h)
            eff_week = compute_trading_week(server_time, rollover_h)
            balance = float(account.get("balance") or 0.0)
            equity = float(account.get("equity") or 0.0)
            ref_eq = min(balance, equity) if (balance > 0 and equity > 0) else max(balance, equity, 0.0)
            self.store.sync_session_rollover(
                server_time=server_time,
                current_day_total=current_day_total,
                current_week_total=current_week_total,
                current_equity=ref_eq,
            )

        # PROIBIÇÃO ESTRITA (Parte 2.1): Ligar/desligar a IA JAMAIS limpa trava de risco ou redefine baseline!
        lock = self.lock_info(eff_day, eff_week)
        if lock["active"]:
            self.enabled = False
            self._set(
                "CRITICAL_EXECUTION_FAILURE" if lock.get("lock_type") == "EXECUTION_LOCK" else "RISK_LOCK",
                lock.get("reason") or "Trava de proteção ativa.",
            )
            return (
                False,
                f"Operação bloqueada por trava persistente ({lock.get('lock_type')}): {lock.get('reason')}. "
                "A trava só é liberada automaticamente no próximo dia/semana operacional da corretora ou via desbloqueio manual auditado.",
            )

        # Verifica também se o limite diário ou semanal já foi violado antes de tentar ligar
        snap = self.store.snapshot()
        loss_lim = float(snap.get("daily_loss_limit") or 0.0)
        weekly_lim = float(snap.get("weekly_loss_limit") or 0.0)
        base_now = float(snap.get("daily_loss_baseline") or 0.0)
        session_pnl = round(float(current_day_total) - base_now, 2)
        ccy = account.get("currency", "")

        if loss_lim > 0 and session_pnl <= -loss_lim:
            reason = f"LIMITE DE PERDA atingido na sessão: {session_pnl:+.2f} {ccy} (limite definido -{loss_lim:.2f} {ccy})"
            self.store.trigger_risk_lock(
                lock_type="DAILY_LOSS_LOCK",
                reason=reason,
                server_day=eff_day,
                server_week=eff_week,
                scope="CONTA_INTEIRA" if snap.get("protect_whole_account") else "TRADER_IA_MAGIC",
            )
            self.enabled = False
            self._set("RISK_LOCK", reason)
            return False, f"Impossível ativar IA: {reason}"

        if weekly_lim > 0 and float(current_week_total) <= -weekly_lim:
            reason = f"LIMITE SEMANAL atingido: {current_week_total:+.2f} {ccy} (limite -{weekly_lim:.2f} {ccy})"
            self.store.trigger_risk_lock(
                lock_type="WEEKLY_LOSS_LOCK",
                reason=reason,
                server_day=eff_day,
                server_week=eff_week,
                scope="CONTA_INTEIRA" if snap.get("protect_whole_account") else "TRADER_IA_MAGIC",
            )
            self.enabled = False
            self._set("RISK_LOCK", reason)
            return False, f"Impossível ativar IA: {reason}"

        self.enabled = True
        self.retry_after = 0.0
        acct = account.get("trade_mode", "?")
        self.logs.add(
            f"🧠 MEGA BRAIN V5 QUANT ATIVADO · conta {account.get('login')} ({acct}) · "
            f"Perfil {snap.get('account_profile')} · Modo Adaptativo {snap.get('adaptive_mode')} · "
            f"Até {MAX_CONCURRENT_TRADES} moedas simultâneas",
            "success",
            snap.get("mode"),
        )
        self._set("STUDYING_MARKET", "Todos os cérebros escaneando M1/M2/M5/M15 a favor da tendência.")
        return True, "Mega Brain V5 Quant ligado."

    def disable(self, reason: str = "Desligada pelo operador.") -> None:
        if self.enabled:
            self.logs.add(f"IA AUTÔNOMA DESLIGADA · {reason}", "warn")
        self.enabled = False
        lock = self.store.get("risk_lock")
        if isinstance(lock, dict):
            self._set(
                "CRITICAL_EXECUTION_FAILURE" if lock.get("lock_type") == "EXECUTION_LOCK" else "RISK_LOCK",
                lock.get("reason") or reason,
            )
        else:
            self._set("OFF", reason)

    def close_all(
        self, symbol: str | None, positions: list[dict], sym_fallback: dict | None, settings: dict, reason: str
    ) -> tuple[int, int]:
        ok = fail = 0
        for p in positions:
            p_sym_name = p.get("symbol") or symbol or ""
            p_sym = self.bridge.symbol_info(p_sym_name) or sym_fallback or {}
            res = self.bridge.close_position(
                p, int(settings.get("deviation_points", 20)), int(settings["magic"]), f"TraderIA {reason[:10]}", p_sym
            )
            if res.ok:
                ok += 1
                self.logs.add(
                    f"[{reason}] Posição #{p['ticket']} ({p_sym_name}) {SIDE_PT[p['type']]} {p['volume']} zerada a {res.price}.",
                    "warn",
                )
            else:
                fail += 1
                self.logs.add(
                    f"[{reason}] FALHA ao zerar #{p['ticket']} ({p_sym_name}): [{res.retcode}] {res.message}",
                    "error",
                )
        return ok, fail

    # ------------------------------------------------------------------ ciclo principal multi-cérebros
    def step(self, ctx: Ctx) -> str | None:
        magic = int(ctx.settings["magic"])
        rollover_h = int(ctx.settings.get("broker_rollover_hour") or 0)
        eff_day = compute_trading_day(ctx.server_time, rollover_h) if ctx.server_time else ctx.server_day
        eff_week = (
            ctx.server_week
            if ctx.server_week is not None
            else (compute_trading_week(ctx.server_time, rollover_h) if ctx.server_time else None)
        )

        all_pos = ctx.all_positions if ctx.all_positions is not None else ctx.positions
        ai_pos = [p for p in all_pos if is_ai_attributed(p, magic)]
        self._track_closures(ctx, ai_pos)

        # Avaliação periódica de contrafactuais de sinais bloqueados
        if self.journal and (time.monotonic() - self._last_cf_eval_mono >= 5.0):
            self._last_cf_eval_mono = time.monotonic()
            smap = ctx.symbol_map or {ctx.symbol: {"tick": ctx.tick}}
            for s_name, bdl in smap.items():
                tk = bdl.get("tick") or {}
                mid = 0.5 * (float(tk.get("bid") or 0.0) + float(tk.get("ask") or 0.0))
                if mid > 0 and ctx.server_time > 0:
                    try:
                        self.journal.evaluate_pending_counterfactuals(s_name, mid, ctx.server_time)
                    except Exception:  # noqa: BLE001
                        pass

        a = ctx.analysis
        eff_min = self.required_score(ctx.mode.min_score)
        if a.get("ready") and a.get("bar_time") != self._last_bar_seen.get(ctx.symbol):
            if self._last_bar_seen.get(ctx.symbol):
                cdl = a.get("candle") or {}
                hz = a.get("horizon") or {}
                prob_n = cdl.get("prob_up", 50) if a.get("direction") == "BUY" else cdl.get("prob_down", 50)
                self.logs.add(
                    f"[CÉREBRO {ctx.symbol}] Vela {a.get('timeframe', 'M1')} · {hz.get('strategy', 'Institucional')} · "
                    f"{SIDE_PT[a['direction']]} Score Heurístico {a['score']:.0f} (mín {eff_min:.0f}) · "
                    f" Viés vela {prob_n:.0f}%",
                    "think",
                    ctx.mode.key,
                )
            self._last_bar_seen[ctx.symbol] = int(a["bar_time"])
            if self.journal and not self.enabled:
                self._record_bar_signal(ctx, ctx.symbol, a, ctx.tick, eff_min, "NO_TRADE_AI_OFF", "IA desligada")

        lock = self.lock_info(eff_day, eff_week)
        if not self.enabled:
            if lock["active"]:
                self._set(
                    "CRITICAL_EXECUTION_FAILURE" if lock.get("lock_type") == "EXECUTION_LOCK" else "RISK_LOCK",
                    lock.get("reason") or "",
                )
            else:
                self._set("OFF", "Ligue a IA autônoma para ativar os cérebros em todas as moedas.")
            return None

        if lock["active"]:
            self.enabled = False
            self._set(
                "CRITICAL_EXECUTION_FAILURE" if lock.get("lock_type") == "EXECUTION_LOCK" else "RISK_LOCK",
                lock.get("reason") or "",
            )
            return None

        if self._check_breakers(ctx, all_pos, ai_pos, eff_day, eff_week):
            return None

        # 1. Gerencia TODAS as posições abertas da IA em qualquer moeda
        if ai_pos:
            syms_open = ", ".join(sorted({p["symbol"] for p in ai_pos}))
            self._set(
                "MANAGING_POSITION",
                f"{len(ai_pos)}/{MAX_CONCURRENT_TRADES} op. ativa(s) ({syms_open}) · vigiando lucro e proteção",
            )
            for p in ai_pos:
                self._manage(ctx, p)

        # 2. Permite até MAX_CONCURRENT_TRADES (4) operações simultâneas em moedas diferentes
        if len(ai_pos) >= MAX_CONCURRENT_TRADES:
            return None

        if ctx.server_time < self.cooldown_until:
            if not ai_pos:
                secs = self.cooldown_until - ctx.server_time
                self._set("COOLDOWN", f"{self.cooldown_reason} · {secs}s restantes")
            return None

        if time.monotonic() < self.retry_after:
            if not ai_pos:
                self._set("COOLDOWN", f"Aguardando ({int(self.retry_after - time.monotonic())}s)")
            return None

        # Espaçamento anti-spam entre aberturas globais (10s)
        if time.monotonic() - self.last_global_open_mono < 10.0:
            return None

        sym_map = ctx.symbol_map or {
            ctx.symbol: {"sym": ctx.sym, "tick": ctx.tick, "analysis": ctx.analysis}
        }
        open_symbols = {p["symbol"] for p in all_pos}

        # Exige +1 ponto de score heurístico para cada operação simultânea já aberta
        req_score = min(92.0, eff_min + (1.0 * len(ai_pos)))

        # Parte 2.5: Posição só é considerada protegida quando SL estiver confirmado na entrada ou no lucro!
        # Lucro flutuante positivo NUNCA é tratado como proteção garantida se o SL ainda estiver em perda.
        unprotected_usd_long = 0
        unprotected_usd_short = 0
        has_any_unprotected_sl = False
        for p in ai_pos:
            p_meta = self.trades.get(p["ticket"])
            if float(p.get("sl") or 0.0) <= 0 or (p_meta is not None and not p_meta.sl_confirmed):
                has_any_unprotected_sl = True
            is_safe = is_position_sl_confirmed_safe(p) and (p_meta is None or p_meta.sl_confirmed)
            if not is_safe:
                u_dir = usd_exposure_dir(p["symbol"], p["type"])
                if u_dir > 0:
                    unprotected_usd_long += 1
                elif u_dir < 0:
                    unprotected_usd_short += 1

        if has_any_unprotected_sl:
            self._set("MANAGING_POSITION", "Bloqueado abrir novas entradas: há posição com SL ainda não confirmado.")
            return None

        best_candidate: tuple[float, str, dict, float] | None = None
        for sym_name, bundle in sym_map.items():
            if sym_name in open_symbols:
                continue
            s_analysis = bundle.get("analysis") or {}
            s_info = bundle.get("sym")
            s_tick = bundle.get("tick")
            if not s_analysis.get("ready") or not s_info or not s_tick:
                continue

            sig = s_analysis.get("signal")
            sc = float(s_analysis.get("score") or 0.0)
            tf_sec = int(bundle.get("tf_seconds") or 60)
            hz = s_analysis.get("horizon") or {}
            strat_name = str(hz.get("strategy") or (s_analysis.get("candle") or {}).get("best_strategy") or "Institucional")
            regime_code = str((s_analysis.get("regime") or {}).get("code") or "UNKNOWN")
            hz_type = str(hz.get("type") or "SCALP_1VELA")

            mem_ok, _, mem_reason = self.evaluate_symbol_memory(
                sym_name, sig or s_analysis.get("direction"), sc, req_score, ctx.server_time, tf_sec
            )
            if not mem_ok:
                if sig and self.journal:
                    self._record_bar_signal(ctx, sym_name, s_analysis, s_tick, req_score, "BLOCKED_MEMORY", mem_reason)
                continue

            perm_err = self._trade_permission_sym(ctx, sym_name, s_info, sig or s_analysis.get("direction"))
            if perm_err:
                if sig and self.journal:
                    self._record_bar_signal(ctx, sym_name, s_analysis, s_tick, req_score, "BLOCKED_PERMISSION", perm_err)
                continue

            m_sym = self.mem.get(sym_name)
            if m_sym and int(s_analysis.get("bar_time") or 0) == m_sym.last_entry_bar:
                continue

            # Adaptação controlada baseada em evidências (Parte 6)
            cand_min_score = req_score
            if self.adaptive and sig:
                adj = self.adaptive.evaluate_candidate(
                    symbol=sym_name,
                    strategy=strat_name,
                    regime=regime_code,
                    horizon=hz_type,
                    base_min_score=req_score,
                )
                if not adj["allowed"]:
                    self.logs.throttled(
                        f"adapt_blk_{sym_name}",
                        30,
                        f"[ADAPTATIVO ATIVO · {sym_name}] Bloqueado: {adj['block_reason']}",
                        "warn",
                        ctx.mode.key,
                    )
                    if self.journal:
                        self._record_bar_signal(
                            ctx, sym_name, s_analysis, s_tick, req_score, "BLOCKED_ADAPTIVE", adj["block_reason"]
                        )
                    continue
                cand_min_score = float(adj["effective_min_score"])

            # Proteção de Correlação USD e Carteira Aberta (Parte 2.5)
            if sig:
                usd_cand = usd_exposure_dir(sym_name, sig)
                if usd_cand > 0 and unprotected_usd_long >= 2:
                    if self.journal:
                        self._record_bar_signal(
                            ctx,
                            sym_name,
                            s_analysis,
                            s_tick,
                            cand_min_score,
                            "BLOCKED_CORRELATION",
                            "Exposição USD comprada já possui 2 posições sem SL confirmado no zero/lucro",
                        )
                    continue
                if usd_cand < 0 and unprotected_usd_short >= 2:
                    if self.journal:
                        self._record_bar_signal(
                            ctx,
                            sym_name,
                            s_analysis,
                            s_tick,
                            cand_min_score,
                            "BLOCKED_CORRELATION",
                            "Exposição USD vendida já possui 2 posições sem SL confirmado no zero/lucro",
                        )
                    continue

            if sig and sc >= cand_min_score:
                cdl = s_analysis.get("candle") or {}
                prob_n = cdl.get("prob_up", 50.0) if sig == "BUY" else cdl.get("prob_down", 50.0)
                rank_val = sc * 0.65 + prob_n * 0.35
                if best_candidate is None or rank_val > best_candidate[0]:
                    best_candidate = (rank_val, sym_name, bundle, cand_min_score)
            elif self.journal and s_analysis.get("bar_time") != self._last_bar_seen.get(f"j_{sym_name}"):
                self._last_bar_seen[f"j_{sym_name}"] = int(s_analysis.get("bar_time") or 0)
                blk_reason = s_analysis.get("study_block") or (
                    f"Score heurístico {sc:.1f} < mínimo {cand_min_score:.1f}"
                )
                self._record_bar_signal(
                    ctx,
                    sym_name,
                    s_analysis,
                    s_tick,
                    cand_min_score,
                    "BLOCKED_STUDY" if s_analysis.get("study_block") else "BELOW_MIN_SCORE",
                    blk_reason,
                )

        if best_candidate is not None:
            _, target_sym, bundle, cand_min = best_candidate
            opened = self._execute_on_symbol(ctx, target_sym, bundle, cand_min, len(ai_pos), all_pos)
            if opened:
                return target_sym

        if not ai_pos:
            if a.get("ready"):
                hz = a.get("horizon") or {}
                self._set(
                    "EVALUATING_CONFLUENCE",
                    f"{ctx.symbol} · {SIDE_PT[a['direction']]} Score Heurístico {a['score']:.0f} (mín ≥ {eff_min:.0f}) · "
                    f"{hz.get('strategy', 'Institucional')}",
                )
            else:
                self._set("STUDYING_MARKET", a.get("study_block") or "Sincronizando cérebros das moedas.")
        return None

    def _record_bar_signal(
        self,
        ctx: Ctx,
        symbol: str,
        analysis: dict,
        tick: dict | None,
        min_score: float,
        decision: str,
        block_reason: str | None,
        planned_sl: float | None = None,
        planned_tp: float | None = None,
    ) -> int | None:
        if not self.journal or not analysis.get("ready"):
            return None
        tk = tick or {}
        bid = float(tk.get("bid") or 0.0)
        ask = float(tk.get("ask") or 0.0)
        direction = str(analysis.get("signal") or analysis.get("direction") or "BUY")
        entry_ref = ask if direction == "BUY" else bid
        atr = float(analysis.get("atr") or 0.0)
        hz = analysis.get("horizon") or {}
        d = 1 if direction == "BUY" else -1
        sl_ref = planned_sl if planned_sl is not None else (
            entry_ref - d * float(hz.get("sl_atr") or ctx.mode.sl_atr) * atr if atr > 0 else None
        )
        tp_ref = planned_tp if planned_tp is not None else (
            entry_ref + d * float(hz.get("tp_atr") or ctx.mode.tp_atr) * atr if atr > 0 else None
        )
        cdl = analysis.get("candle") or {}
        prob_n = cdl.get("prob_up", 50.0) if direction == "BUY" else cdl.get("prob_down", 50.0)
        try:
            return self.journal.record_signal_evaluation({
                "eval_time": int(ctx.server_time or time.time()),
                "bar_time": int(analysis.get("bar_time") or 0),
                "symbol": symbol,
                "timeframe": str(analysis.get("timeframe") or "M1"),
                "horizon_type": str(hz.get("type") or "SCALP_1VELA"),
                "strategy": str(hz.get("strategy") or cdl.get("best_strategy") or "Institucional"),
                "regime_code": str((analysis.get("regime") or {}).get("code") or "UNKNOWN"),
                "direction": direction,
                "signal": analysis.get("signal"),
                "heuristic_score": float(analysis.get("score") or 0.0),
                "calibrated_prob": analysis.get("calibrated_win_probability"),
                "next_candle_bias": float(prob_n),
                "min_score_required": float(min_score),
                "decision": decision,
                "block_reason": block_reason,
                "spread_points": int(analysis.get("spread_points") or 0),
                "atr": atr,
                "entry_ref_price": entry_ref,
                "planned_sl": sl_ref,
                "planned_tp": tp_ref,
                "horizon_duration_s": int(hz.get("duration_s") or 90),
                "htf_available": bool((analysis.get("htf") or {}).get("available")),
                "structural_status": str((analysis.get("structural_room") or {}).get("status") or ""),
                "pillars": analysis.get("pillars") or [],
            })
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ permissões
    def _trade_permission_sym(self, ctx: Ctx, symbol: str, sym_info: dict, direction: str | None) -> str | None:
        if not ctx.terminal.get("connected"):
            return "Terminal MT5 sem conexão."
        if not ctx.terminal.get("trade_allowed"):
            return "Botão 'Algo Trading' desativado no MT5."
        if not ctx.account.get("trade_expert"):
            return "Conta não permite negociação automatizada."
        tm = sym_info.get("trade_mode")
        if tm in (SYMBOL_TRADE_MODE_DISABLED, SYMBOL_TRADE_MODE_CLOSEONLY):
            return f"{symbol}: negociação desabilitada ou somente fechamento."
        if tm == SYMBOL_TRADE_MODE_LONGONLY and direction == "SELL":
            return f"{symbol}: somente compras permitidas."
        if tm == SYMBOL_TRADE_MODE_SHORTONLY and direction == "BUY":
            return f"{symbol}: somente vendas permitidas."
        return None

    # ------------------------------------------------------------------ circuit breakers (Partes 2.1, 2.2 e Parte 3)
    def _check_breakers(
        self,
        ctx: Ctx,
        all_pos: list[dict],
        ai_pos: list[dict],
        eff_day: int | None,
        eff_week: int | None,
    ) -> bool:
        protect_whole = bool(ctx.settings.get("protect_whole_account", False))
        # Usa o P&L governado (IA por padrão, ou conta inteira se `protect_whole_account=True`)
        total = float(
            ctx.day.get("account_day_total" if protect_whole else "ai_day_total", ctx.day.get("total") or 0.0)
        )
        baseline = float(ctx.settings.get("daily_loss_baseline") or 0.0)
        session_pnl = float(ctx.day.get("session_net", total - baseline))
        weekly_pnl = float(
            ctx.day.get("account_weekly_net" if protect_whole else "ai_weekly_net", ctx.day.get("weekly_net") or 0.0)
        )
        loss = float(ctx.settings.get("daily_loss_limit") or 0.0)
        weekly_loss = float(ctx.settings.get("weekly_loss_limit") or 0.0)
        gain = float(ctx.settings.get("daily_gain_target") or 0.0)
        ccy = ctx.account.get("currency", "")

        # Verifica estado de drawdown progressivo de pequena conta (Parte 3.3)
        balance = float(ctx.account.get("balance") or 0.0)
        equity = float(ctx.account.get("equity") or 0.0)
        ref_eq = min(balance, equity) if (balance > 0 and equity > 0) else max(balance, equity, 0.0)
        ss = ctx.settings.get("session_state") or {}
        guard_res = classify_drawdown_state(
            reference_equity=ref_eq,
            peak_equity=float(ss.get("peak_reference_equity") or ref_eq),
            session_start_equity=float(ss.get("session_start_equity") or ref_eq),
            week_start_equity=float(ss.get("week_start_equity") or ref_eq),
            session_pnl=session_pnl,
            weekly_pnl=weekly_pnl,
            session_loss_limit_pct=float(ctx.settings.get("session_loss_limit_pct") or 1.0),
            weekly_drawdown_limit_pct=float(ctx.settings.get("weekly_drawdown_limit_pct") or 3.0),
            execution_failure=False,
        )
        dd_state = guard_res[0]
        dd_scale = guard_res[1]
        dd_reason = guard_res[-1]

        lock_type = None
        reason = None
        if loss > 0 and session_pnl <= -loss:
            lock_type = "DAILY_LOSS_LOCK"
            reason = (
                f"LIMITE DE PERDA atingido na sessão ({'Conta Inteira' if protect_whole else 'Trader IA'}): "
                f"{session_pnl:+.2f} {ccy} (limite definido -{loss:.2f} {ccy})"
            )
        elif weekly_loss > 0 and weekly_pnl <= -weekly_loss:
            lock_type = "WEEKLY_LOSS_LOCK"
            reason = (
                f"LIMITE SEMANAL atingido ({'Conta Inteira' if protect_whole else 'Trader IA'}): "
                f"{weekly_pnl:+.2f} {ccy} (limite semanal -{weekly_loss:.2f} {ccy})"
            )
        elif dd_state == "TRADING_LOCKED" and str(ctx.settings.get("account_profile")) == "SMALL_ACCOUNT_PROTECTION":
            lock_type = "DRAWDOWN_LOCK"
            reason = f"PROTEÇÃO DE PEQUENA CONTA (Drawdown Lock): {dd_reason}"
        elif gain > 0 and total >= gain:
            lock_type = "GAIN_LOCK"
            reason = f"META DIÁRIA atingida: resultado {total:+.2f} {ccy} (meta {gain:.2f} {ccy})"

        if not reason or not lock_type:
            return False

        # Parte 2.2: Nunca fechar posições manuais/externas silenciosamente a menos que `protect_whole_account=True`
        positions_to_close = all_pos if protect_whole else ai_pos
        scope_desc = "todas as posições da conta" if protect_whole else "posições do Trader IA (magic)"
        self.logs.add(
            f"⛔ {reason}. Encerrando {scope_desc} ({len(positions_to_close)} op.) e aplicando trava persistente.",
            "error",
            ctx.mode.key,
        )
        if positions_to_close:
            self.close_all(ctx.symbol, positions_to_close, ctx.sym, ctx.settings, "STOP SESSAO")

        self.store.trigger_risk_lock(
            lock_type=lock_type,
            reason=reason,
            server_day=eff_day,
            server_week=eff_week,
            scope="CONTA_INTEIRA" if protect_whole else "TRADER_IA_MAGIC",
        )
        self.enabled = False
        self._set("RISK_LOCK", reason)
        return True

    # ------------------------------------------------------------------ execução com validação independente e SL/TP confirmado
    def _execute_on_symbol(
        self,
        ctx: Ctx,
        symbol: str,
        bundle: dict,
        eff_min: float,
        open_trades_count: int,
        all_pos: list[dict],
    ) -> bool:
        a = bundle["analysis"]
        sym_info = bundle["sym"]
        tick = bundle["tick"]
        mode = ctx.mode
        side = a["signal"]
        hz = a.get("horizon") or {}

        self._set("EXECUTING_TRADE", f"{SIDE_PT[side]} {symbol} ({hz.get('strategy', 'Sniper')})")
        rec_active = self.consecutive_losses >= 1
        session_pnl = float(ctx.day.get("session_net") or 0.0)
        weekly_pnl = float(ctx.day.get("weekly_net") or 0.0)

        sym_info_map = {
            k: v.get("sym") for k, v in (ctx.symbol_map or {}).items() if isinstance(v, dict) and v.get("sym")
        }

        plan, err = build_plan(
            self.bridge,
            symbol,
            sym_info,
            tick,
            side,
            float(a["atr"]),
            mode,
            ctx.settings,
            ctx.account,
            self.consecutive_losses,
            rec_active,
            horizon=hz,
            open_trades_count=open_trades_count,
            open_positions=all_pos,
            symbol_map=sym_info_map,
            session_pnl=session_pnl,
            weekly_pnl=weekly_pnl,
            server_now=ctx.server_time,
        )
        if plan is None:
            self.last_risk_evaluation = {
                "approved": False,
                "symbol": symbol,
                "side": side,
                "reason": err,
                "at": ctx.server_time,
            }
            self.logs.add(f"[GUARDIÃO DE RISCO · {symbol}] Entrada {SIDE_PT[side]} bloqueada: {err}", "warn", mode.key)
            if self.journal:
                self._record_bar_signal(ctx, symbol, a, tick, eff_min, "BLOCKED_RISK_GUARD", err)
            self.retry_after = time.monotonic() + 10
            return False

        self.last_risk_evaluation = plan.small_account_guard or {
            "approved": True,
            "symbol": symbol,
            "side": side,
            "reason": plan.note,
        }

        cdl = a.get("candle") or {}
        prob_n = cdl.get("prob_up", 50) if side == "BUY" else cdl.get("prob_down", 50)
        digits = int(sym_info["digits"])
        ccy = ctx.account.get("currency", "")
        strat_str = str(hz.get("strategy") or cdl.get("best_strategy") or "Institucional")
        regime_code = str((a.get("regime") or {}).get("code") or "UNKNOWN")

        eval_id = self._record_bar_signal(
            ctx,
            symbol,
            a,
            tick,
            eff_min,
            "EXECUTED",
            None,
            planned_sl=plan.sl,
            planned_tp=plan.tp,
        )

        self.logs.add(
            f"🎯 [EXECUÇÃO {symbol} · {strat_str}] Score Heurístico {a['score']:.0f} · "
            f"Viés vela {prob_n:.0f}% ({plan.horizon_label}). "
            f"Enviando {SIDE_PT[side]} {plan.lots} lote(s) · SL {plan.sl:.{digits}f} · TP {plan.tp:.{digits}f} · "
            f"risco efetivo {plan.effective_risk:.2f} {ccy} ({plan.effective_risk_pct:.2f}%)",
            "action",
            mode.key,
        )

        res = self.bridge.market_order(
            symbol,
            side,
            plan.lots,
            plan.sl,
            plan.tp,
            int(ctx.settings.get("deviation_points", 20)),
            int(ctx.settings["magic"]),
            f"TraderIA {mode.key}",
            sym_info,
        )
        if not res.ok:
            self.logs.add(f"Ordem REJEITADA pelo MT5 ({symbol}): [{res.retcode}] {res.message}", "error", mode.key)
            self.retry_after = time.monotonic() + 10
            return False

        if res.is_partial_fill:
            self.logs.add(
                f"⚠️ [{symbol}] Execução PARCIAL detectada: solicitado {res.volume_requested} lote(s), "
                f"executado {res.volume} lote(s).",
                "warn",
                mode.key,
            )

        m_sym = self.mem.setdefault(symbol, SymbolMemory(symbol=symbol))
        m_sym.last_entry_bar = int(a["bar_time"])
        m_sym.last_entry_time = ctx.server_time
        self.last_global_open_mono = time.monotonic()

        self.logs.add(
            f"⚡ Ordem EXECUTADA em {symbol} · #{res.order} (deal #{res.deal}) · {res.volume} lote(s) @ {res.price:.{digits}f} "
            f"· Estratégia: {strat_str}",
            "success",
            mode.key,
        )

        # Parte 2.8: Reconciliação explícita ordem -> deal -> posição (sem usar cegamente mine[-1])
        pos = self.bridge.reconcile_position_after_order(
            symbol=symbol,
            magic=int(ctx.settings["magic"]),
            order_res=res,
            side=side,
            open_after_ts=max(0, ctx.server_time - 30),
        )
        if pos is None:
            # Segunda tentativa imediata após breve pausa para terminais ECN lentos
            time.sleep(0.15)
            pos = self.bridge.reconcile_position_after_order(
                symbol=symbol,
                magic=int(ctx.settings["magic"]),
                order_res=res,
                side=side,
                open_after_ts=max(0, ctx.server_time - 60),
            )

        if pos is None:
            err_msg = (
                f"Falha crítica de reconciliação em {symbol}: ordem #{res.order} / deal #{res.deal} executada, "
                "mas posição correspondente não foi localizada para confirmar SL/TP."
            )
            self.logs.add(f"🚨 {err_msg}", "error", mode.key)
            self.store.trigger_risk_lock(
                lock_type="EXECUTION_LOCK",
                reason=err_msg,
                server_day=ctx.server_day,
                server_week=ctx.server_week,
                scope="TRADER_IA_MAGIC",
            )
            self.enabled = False
            self._set("CRITICAL_EXECUTION_FAILURE", err_msg)
            return False

        d = 1 if side == "BUY" else -1
        entry = float(pos["price_open"])
        desired_sl = self.bridge.norm_price(entry - d * plan.sl_dist, sym_info)
        desired_tp = self.bridge.norm_price(entry + d * plan.tp_dist, sym_info)

        # Parte 2.7: Proteção confirmada de SL e TP com verificação real na posição e protocolo de emergência
        ok_sltp, confirmed_sl, confirmed_tp, sltp_msg = self.bridge.confirm_or_apply_sltp(
            symbol=symbol,
            ticket=int(pos["ticket"]),
            desired_sl=desired_sl,
            desired_tp=desired_tp,
            magic=int(ctx.settings["magic"]),
            sym=sym_info,
            max_attempts=3,
        )

        if not ok_sltp or confirmed_sl <= 0:
            emerg_msg = (
                f"FALHA CRÍTICA DE PROTEÇÃO em {symbol} #{pos['ticket']}: SL/TP não pôde ser confirmado ({sltp_msg}). "
                "Acionando fechamento de emergência da posição desprotegida!"
            )
            self.logs.add(f"🚨 {emerg_msg}", "error", mode.key)
            close_res = self.bridge.close_position(
                pos,
                int(ctx.settings.get("deviation_points", 20)),
                int(ctx.settings["magic"]),
                "TraderIA EMERGENCY_NO_SL",
                sym_info,
            )
            if close_res.ok:
                self.logs.add(
                    f"🛡️ Posição desprotegida #{pos['ticket']} ({symbol}) encerrada em emergência a {close_res.price}.",
                    "warn",
                    mode.key,
                )
            else:
                self.logs.add(
                    f"🚨 CRÍTICO: Não foi possível encerrar #{pos['ticket']} ({symbol}) automaticamente: "
                    f"[{close_res.retcode}] {close_res.message}",
                    "error",
                    mode.key,
                )
            self.store.trigger_risk_lock(
                lock_type="EXECUTION_LOCK",
                reason=emerg_msg,
                server_day=ctx.server_day,
                server_week=ctx.server_week,
                scope="TRADER_IA_MAGIC",
            )
            self.enabled = False
            self._set("CRITICAL_EXECUTION_FAILURE", emerg_msg)
            return False

        self.logs.add(
            f"[{symbol}] Proteção SL/TP confirmada em #{pos['ticket']}: "
            f"SL {confirmed_sl:.{digits}f} · TP {confirmed_tp:.{digits}f}",
            "action",
            mode.key,
        )

        self.trades[pos["ticket"]] = ManagedTrade(
            ticket=int(pos["ticket"]),
            symbol=symbol,
            side=side,
            entry=entry,
            initial_sl=confirmed_sl,
            tp=confirmed_tp,
            atr=float(a["atr"]),
            mode_key=mode.key,
            horizon_type=plan.horizon_type,
            horizon_label=plan.horizon_label,
            max_duration_s=plan.duration_s,
            open_server_time=int(pos.get("time") or ctx.server_time),
            sl_confirmed=True,
            strategy=strat_str,
            regime_code=regime_code,
        )
        self.known_ai.add(int(pos["ticket"]))

        if self.journal:
            point = float(sym_info.get("point") or 1e-9)
            slip_pts = d * (entry - plan.entry) / point if point > 0 else 0.0
            try:
                self.journal.record_trade_open({
                    "position_id": int(pos["ticket"]),
                    "order_ticket": int(res.order or 0),
                    "deal_ticket": int(res.deal or 0),
                    "signal_eval_id": eval_id,
                    "symbol": symbol,
                    "side": side,
                    "mode_key": mode.key,
                    "account_profile": str(ctx.settings.get("account_profile") or "SMALL_ACCOUNT_PROTECTION"),
                    "timeframe": str(a.get("timeframe") or "M1"),
                    "horizon_type": plan.horizon_type,
                    "horizon_label": plan.horizon_label,
                    "max_duration_s": plan.duration_s,
                    "strategy": strat_str,
                    "regime_code": regime_code,
                    "heuristic_score": float(a.get("score") or 0.0),
                    "calibrated_prob": a.get("calibrated_win_probability"),
                    "next_candle_bias": float(prob_n),
                    "volume_requested": float(plan.lots),
                    "volume_executed": float(res.volume or pos.get("volume") or plan.lots),
                    "is_partial_fill": bool(res.is_partial_fill),
                    "requested_price": float(plan.entry),
                    "entry_price": entry,
                    "slippage_points": round(slip_pts, 2),
                    "spread_points_at_entry": int(plan.spread_points),
                    "atr_at_entry": float(a.get("atr") or 0.0),
                    "initial_sl": confirmed_sl,
                    "initial_tp": confirmed_tp,
                    "sl_confirmed": True,
                    "planned_risk_money": float(plan.risk_money),
                    "effective_risk_money": float(plan.effective_risk),
                    "effective_risk_pct": float(plan.effective_risk_pct),
                    "estimated_costs_money": float(plan.estimated_costs),
                    "reference_equity_at_entry": float(
                        min(float(ctx.account.get("balance") or 0.0), float(ctx.account.get("equity") or 0.0))
                    ),
                    "open_time": int(pos.get("time") or ctx.server_time),
                })
            except Exception:  # noqa: BLE001
                pass

        self._set(
            "MANAGING_POSITION",
            f"#{pos['ticket']} {SIDE_PT[side]} {symbol} ({strat_str})",
        )
        return True

    # ------------------------------------------------------------------ gestão inteligente (Parte 2.10 e Parte 5.2)
    def _reconstruct(self, ctx: Ctx, pos: dict, sym_info: dict, analysis: dict) -> ManagedTrade:
        side = pos["type"]
        symbol = pos.get("symbol") or ctx.symbol
        d = 1 if side == "BUY" else -1
        atr = float(analysis.get("atr") or 0.0) or abs(pos["price_open"] - (pos["sl"] or pos["price_open"])) / max(
            ctx.mode.sl_atr, 1e-9
        )
        entry = float(pos["price_open"])
        has_sl = float(pos.get("sl") or 0.0) > 0
        sl = float(pos["sl"]) if has_sl else self.bridge.norm_price(entry - d * ctx.mode.sl_atr * atr, sym_info)
        tp = float(pos["tp"]) if pos.get("tp") else self.bridge.norm_price(entry + d * ctx.mode.tp_atr * atr, sym_info)
        be_done = has_sl and d * (float(pos["sl"]) - entry) >= 0
        hz = analysis.get("horizon") or {}
        t = ManagedTrade(
            ticket=int(pos["ticket"]),
            symbol=symbol,
            side=side,
            entry=entry,
            initial_sl=sl,
            tp=tp,
            atr=atr,
            mode_key=ctx.mode.key,
            horizon_type=str(hz.get("type") or "SCALP_1VELA"),
            horizon_label=str(hz.get("label") or "⚡ Vela (90s)"),
            max_duration_s=int(hz.get("duration_s") or 120),
            open_server_time=int(pos.get("time") or ctx.server_time),
            be_done=be_done,
            sl_confirmed=has_sl,
            strategy=str(hz.get("strategy") or "Confluência Institucional"),
            regime_code=str((analysis.get("regime") or {}).get("code") or "UNKNOWN"),
        )
        return t

    def _manage(self, ctx: Ctx, pos: dict) -> None:
        p_sym = pos.get("symbol") or ctx.symbol
        bundle = (ctx.symbol_map or {}).get(p_sym)
        sym = (bundle.get("sym") if bundle else None) or (
            ctx.sym if p_sym == ctx.symbol else self.bridge.symbol_info(p_sym)
        )
        tick = (bundle.get("tick") if bundle else None) or (
            ctx.tick if p_sym == ctx.symbol else self.bridge.tick(p_sym)
        )
        analysis = (bundle.get("analysis") if bundle else None) or (ctx.analysis if p_sym == ctx.symbol else {})
        if not sym or not tick:
            return

        t = self.trades.get(pos["ticket"])
        if t is None:
            t = self._reconstruct(ctx, pos, sym, analysis)
            self.trades[pos["ticket"]] = t
            self.known_ai.add(pos["ticket"])

        mode = MODES.get(t.mode_key, ctx.mode)
        d = 1 if t.side == "BUY" else -1
        price = float(tick["bid"] if t.side == "BUY" else tick["ask"])
        point = float(sym.get("point") or 1e-9)
        tick_size = float(sym["tick_size"] or point)
        digits = int(sym["digits"])
        atr_now = float(analysis.get("atr") or 0.0) if analysis.get("ready") else t.atr
        atr_now = atr_now or t.atr
        cur_sl = float(pos.get("sl") or 0.0)
        cur_tp = float(pos.get("tp") or 0.0) or t.tp
        progress = d * (price - t.entry)
        tp_dist = abs(cur_tp - t.entry) if cur_tp else mode.tp_atr * t.atr
        progress_frac = progress / max(tp_dist, 1e-9)
        elapsed_s = max(0, ctx.server_time - int(pos.get("time") or t.open_server_time or ctx.server_time))
        net_now = float(pos.get("profit") or 0.0) + float(pos.get("swap") or 0.0)

        # Parte 5.2: Atualização prospectiva contínua de MFE e MAE (em pontos e moeda da conta)
        excursion_pts = progress / point if point > 0 else 0.0
        fav_pts = max(0.0, excursion_pts)
        adv_pts = max(0.0, -excursion_pts)
        fav_ccy = max(0.0, net_now)
        adv_ccy = max(0.0, -net_now)
        t.max_favorable_pts = max(t.max_favorable_pts, fav_pts)
        t.max_adverse_pts = max(t.max_adverse_pts, adv_pts)
        t.max_favorable_ccy = max(t.max_favorable_ccy, fav_ccy)
        t.max_adverse_ccy = max(t.max_adverse_ccy, adv_ccy)
        if self.journal:
            try:
                self.journal.update_position_excursion(
                    position_id=int(pos["ticket"]),
                    favorable_pts=fav_pts,
                    adverse_pts=adv_pts,
                    favorable_ccy=fav_ccy,
                    adverse_ccy=adv_ccy,
                )
            except Exception:  # noqa: BLE001
                pass

        cdl = analysis.get("candle") if analysis.get("ready") else None
        htf = analysis.get("htf") or {}
        prob_against = (cdl["prob_down"] if d > 0 else cdl["prob_up"]) if cdl else 50.0
        rev_against = bool((cdl["bear_reversal"] if d > 0 else cdl["bull_reversal"])) if cdl else False
        engulf_against = bool((cdl["bear_engulf"] if d > 0 else cdl["bull_engulf"])) if cdl else False
        m5_turned_against = bool(
            htf.get("available") and htf.get("bias21", 0) * d < 0 and htf.get("bar_dir", 0) * d < 0
        )

        # --- CAMADA 1: COLHEITA DE LUCRO GRANDE (>= 68% da meta + rejeição na vela) ---
        if net_now > 0 and progress_frac >= 0.68 and (rev_against or prob_against >= 64.0):
            res = self.bridge.close_position(
                pos, int(ctx.settings.get("deviation_points", 20)), int(ctx.settings["magic"]), "TraderIA HARVEST_1VELA", sym
            )
            if res.ok:
                self.logs.add(
                    f"💰 [LUCRO CHEIO COLHIDO · {p_sym}] #{pos['ticket']} fechada a {res.price:.{digits}f}: "
                    f"atingiu {progress_frac * 100:.0f}% da meta!",
                    "success",
                    mode.key,
                )
                return

        # --- CAMADA 2: RELÓGIO DE VALIDADE (Garante lucro quando a janela termina, sem fechar no prejuízo à toa) ---
        if elapsed_s >= t.max_duration_s:
            if net_now > 0 and progress_frac >= 0.42 and prob_against >= 52.0:
                res = self.bridge.close_position(
                    pos, int(ctx.settings.get("deviation_points", 20)), int(ctx.settings["magic"]), "TraderIA TIME_STOP_WIN", sym
                )
                if res.ok:
                    self.logs.add(
                        f"⏱️ [JANELA CONCLUÍDA NO LUCRO] #{pos['ticket']} ({p_sym}) encerrada com lucro após {elapsed_s}s!",
                        "success",
                        mode.key,
                    )
                    return

        # --- CAMADA 3: DEFESA CRÍTICA SOMENTE SE A TENDÊNCIA DO M5 E A VELA ENGOLFAREM CONTRA ---
        if (
            not t.be_done
            and elapsed_s >= 45
            and m5_turned_against
            and engulf_against
            and prob_against >= 74.0
            and -0.75 * atr_now <= progress <= -0.30 * atr_now
        ):
            res = self.bridge.close_position(
                pos, int(ctx.settings.get("deviation_points", 20)), int(ctx.settings["magic"]), "TraderIA SMART_DEFENSE", sym
            )
            if res.ok:
                self.logs.add(
                    f"🛡️ [DEFESA M5 · {p_sym}] #{pos['ticket']} encerrada cedo: tendência M5 virou contra ({prob_against:.0f}%).",
                    "warn",
                    mode.key,
                )
                return

        # --- CAMADA 4 & 5: BREAK-EVEN E TRAILING STOP RESPEITANDO `mode.be_mode`, `mode.be_value`, `mode.trail_mode`, `mode.trail_value` (Parte 2.10) ---
        new_sl: float | None = None
        event = ""
        ev_type = ""
        if cur_sl == 0.0:
            new_sl, event, ev_type = t.initial_sl, "Restaurando Stop Loss inicial obrigatório", "RESTORE_SL"
        elif not t.be_done:
            if d * (cur_sl - t.entry) >= 0:
                t.be_done = True
                t.sl_confirmed = True
            else:
                # Respeita `mode.be_mode` ("atr" ou "target_frac") e `mode.be_value`
                if mode.be_mode == "atr":
                    trigger = mode.be_value * atr_now
                else:
                    trigger = mode.be_value * tp_dist

                if progress >= trigger:
                    be_plus = self.bridge.norm_price(t.entry + d * max(4 * tick_size, 0.25 * tp_dist), sym)
                    if d * (be_plus - cur_sl) > 0:
                        new_sl = be_plus
                        event = f"LUCRO PROTEGIDO (+25% da meta garantido após {progress_frac * 100:.0f}% de avanço)"
                        ev_type = "BREAK_EVEN"
                elif not t.half_risk_done and progress >= 0.38 * tp_dist:
                    reduced_sl = self.bridge.norm_price(t.entry - d * (0.55 * abs(t.entry - t.initial_sl)), sym)
                    if d * (reduced_sl - cur_sl) > 3 * tick_size:
                        new_sl = reduced_sl
                        event = "RISCO REDUZIDO após avanço de 38% rumo à meta"
                        ev_type = "HALF_RISK"
                        t.half_risk_done = True

        # Respeita `mode.trail_mode` ("atr", "atr_tick", "ema9") e `mode.trail_value` após proteção de Break-Even
        if (t.be_done or ev_type == "BREAK_EVEN") and progress_frac >= 0.72:
            ind = (analysis.get("indicators") or {}) if analysis.get("ready") else {}
            ema9_val = float(ind.get("ema9") or 0.0)
            if mode.trail_mode == "ema9" and ema9_val > 0:
                cand_raw = ema9_val - d * (mode.trail_value * atr_now)
            elif mode.trail_mode == "atr":
                cand_raw = price - d * (mode.trail_value * atr_now)
            else:  # "atr_tick"
                trail_dist = min(mode.trail_value * atr_now, 0.35 * tp_dist)
                cand_raw = price - d * trail_dist

            cand = self.bridge.norm_price(cand_raw, sym)
            ref = new_sl if new_sl is not None else cur_sl
            min_step = max(mode.trail_min_step_atr * atr_now, 3 * tick_size)
            if d * (cand - ref) >= min_step and d * (cand - t.entry) > 0:
                new_sl = cand
                event = (event + " + " if event else "") + f"TRAILING ({mode.trail_mode.upper()})"
                ev_type = "TRAILING"

        if new_sl is None:
            return

        gap = max(int(sym.get("stops_level") or 0), int(sym.get("freeze_level") or 0)) * point
        if d * (price - new_sl) <= gap:
            return
        now = time.monotonic()
        if now - t.last_modify < mode.modify_interval_s:
            return
        t.last_modify = now
        res = self.bridge.modify_sltp(p_sym, pos["ticket"], new_sl, cur_tp, int(ctx.settings["magic"]), sym)
        if res.ok:
            t.sl_confirmed = True
            if ev_type == "BREAK_EVEN" or d * (new_sl - t.entry) >= 0:
                t.be_done = True
            if self.journal and ev_type:
                try:
                    self.journal.record_position_event(
                        position_id=int(pos["ticket"]),
                        event_time=ctx.server_time,
                        event_type=ev_type,
                        old_sl=cur_sl,
                        new_sl=new_sl,
                        price=price,
                        detail=event,
                    )
                except Exception:  # noqa: BLE001
                    pass
            msg = (
                f"[{p_sym}] #{pos['ticket']} {event}. Stop movido {cur_sl:.{digits}f} → {new_sl:.{digits}f} "
                f"(preço {price:.{digits}f})"
            )
            if ev_type == "TRAILING":
                self.logs.throttled(f"trail_{pos['ticket']}", 5, msg, "action", mode.key)
            else:
                self.logs.add(msg, "action", mode.key)
        elif res.retcode != RET_NO_CHANGES:
            self.logs.throttled(
                f"modfail_{pos['ticket']}",
                10,
                f"Falha ao modificar SL #{pos['ticket']} ({p_sym}): [{res.retcode}] {res.message}",
                "error",
                mode.key,
            )

    # ------------------------------------------------------------------ fechamentos & atualização de memória
    def _track_closures(self, ctx: Ctx, ai_pos: list[dict]) -> None:
        now_ids = {int(p["ticket"]) for p in ai_pos}
        for tk in list(self.known_ai - now_ids):
            deals = self.bridge.deals_for_position(tk)
            pnl = sum(
                float(x["profit"]) + float(x["swap"]) + float(x["commission"]) + float(x["fee"]) for x in deals
            )
            outs = [x for x in deals if x["entry"] in ("OUT", "INOUT", "OUT_BY")]
            ins = [x for x in deals if x["entry"] == "IN"]
            reason = outs[-1]["reason"] if outs else "?"
            closed_meta = self.trades.get(tk)
            closed_sym = (
                (outs[-1].get("symbol") if outs else None)
                or (closed_meta.symbol if closed_meta else None)
                or ctx.symbol
            )
            side = (ins[0].get("type") if ins else None) or (closed_meta.side if closed_meta else "BUY")
            exit_p = float(outs[-1].get("price") or 0.0) if outs else 0.0
            ccy = ctx.account.get("currency", "")

            self._synced_trade_ids.add(int(tk))
            m = self.mem.setdefault(closed_sym, SymbolMemory(symbol=closed_sym))
            if pnl >= 0:
                m.wins += 1
                m.consec_losses = 0
                m.last_loss_side = None
                self.consecutive_losses = 0
                self.recovery_deficit = max(0.0, round(self.recovery_deficit - pnl, 2))
                self.logs.add(
                    f"✅ Posição #{tk} ({closed_sym}) encerrada no LUCRO ({reason}): {pnl:+.2f} {ccy}",
                    "success",
                    ctx.mode.key,
                )
                self.cooldown_until = ctx.server_time + 12
                self.cooldown_reason = "Lucro realizado · escaneando próxima oportunidade"
            else:
                m.losses += 1
                m.consec_losses += 1
                m.last_loss_side = side
                m.last_loss_time = ctx.server_time
                m.last_loss_price = exit_p
                self.consecutive_losses += 1
                self.recovery_deficit = round(self.recovery_deficit + abs(pnl), 2)
                if m.consec_losses >= 2:
                    m.quarantine_until = ctx.server_time + 600
                    self.logs.add(
                        f"🛡️ Posição #{tk} ({closed_sym}) encerrada ({pnl:+.2f} {ccy}). "
                        f"Cérebro {closed_sym} em QUARENTENA por 10 min. "
                        f"Demais cérebros seguem buscando oportunidades!",
                        "warn",
                        ctx.mode.key,
                    )
                else:
                    self.logs.add(
                        f"⚠️ Posição #{tk} ({closed_sym}) encerrada ({pnl:+.2f} {ccy}). "
                        f"Anti-Teimosia ativado em {closed_sym} ({SIDE_PT.get(side, side)} bloqueado por 4 min).",
                        "error",
                        ctx.mode.key,
                    )
                self.cooldown_until = ctx.server_time + 20
                self.cooldown_reason = "Reavaliando cérebros das moedas pós-loss"

            self.known_ai.discard(tk)
            self.trades.pop(tk, None)
        self.known_ai |= now_ids
