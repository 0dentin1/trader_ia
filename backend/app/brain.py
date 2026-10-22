"""MEGA BRAIN V4 — Arquitetura Multi-Cérebros (Até 4 Moedas Simultâneas) + 5 Estratégias Institucionais,
Proibição de Contra-Tendência, Assimetria Positiva (Sem Cortar Lucro Cedo) e Stop Diário Relativo à Sessão."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from .config import MAX_CONCURRENT_TRADES, MODES, ModeConfig
from .mt5_bridge import (
    RET_NO_CHANGES,
    SYMBOL_TRADE_MODE_CLOSEONLY,
    SYMBOL_TRADE_MODE_DISABLED,
    SYMBOL_TRADE_MODE_LONGONLY,
    SYMBOL_TRADE_MODE_SHORTONLY,
    MT5Bridge,
)
from .risk import build_plan
from .settings_store import SettingsStore
from .utils import LogBook

STATE_LABELS = {
    "OFF": "Mega Brain V4 desligado · somente leitura",
    "DISCONNECTED": "MT5 desconectado",
    "STUDYING_MARKET": "Cérebros analisando 5 Estratégias Institucionais em todas as moedas",
    "EVALUATING_CONFLUENCE": "Validando alinhamento M1+M5+M15 e estratégia institucional",
    "EXECUTING_TRADE": "Disparando ordem Sniper a favor da tendência",
    "MANAGING_POSITION": "Gerenciando operação (Alvo > Stop, sem enforcar lucro)",
    "COOLDOWN": "Pausa tática curta entre disparos",
    "RISK_LOCK": "Limite de proteção da sessão atingido",
}
SIDE_PT = {"BUY": "COMPRA", "SELL": "VENDA"}


def _usd_exposure_dir(symbol: str, side: str) -> int:
    """Retorna +1 se a operação aposta na alta do USD, -1 se aposta na queda do USD, 0 caso contrário."""
    s = symbol.upper()
    d = 1 if side == "BUY" else -1
    if s.startswith("USD"):
        return d
    if s.endswith("USD"):
        return -d
    return 0


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
    last_modify: float = 0.0


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
    all_positions: list[dict] | None = None
    symbol_map: dict[str, dict] | None = None


class Brain:
    def __init__(self, bridge: MT5Bridge, store: SettingsStore, logs: LogBook) -> None:
        self.bridge = bridge
        self.store = store
        self.logs = logs
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

        # 1 Cérebro de Memória por Moeda
        self.mem: dict[str, SymbolMemory] = {}
        self.consecutive_losses = 0
        self.recovery_deficit = 0.0
        self._synced_trade_ids: set[int] = set()

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

    def lock_info(self, server_day: int | None) -> dict:
        lock = self.store.get("risk_lock")
        active = bool(lock and server_day is not None and int(lock.get("day", -1)) == int(server_day))
        return {
            "active": active,
            "reason": lock.get("reason") if active else None,
            "at": lock.get("at") if active else None,
        }

    def get_trade_meta(self, ticket: int) -> ManagedTrade | None:
        return self.trades.get(ticket)

    def public(self, server_day: int | None, active_brains_count: int = 0) -> dict:
        rec_active = self.consecutive_losses >= 1
        return {
            "enabled": self.enabled,
            "state": self.state,
            "state_label": STATE_LABELS.get(self.state, self.state),
            "detail": self.detail,
            "cooldown_until": self.cooldown_until,
            "cooldown_reason": self.cooldown_reason,
            "active_brains": active_brains_count,
            "max_concurrent": MAX_CONCURRENT_TRADES,
            "lock": self.lock_info(server_day),
            "recovery": {
                "active": rec_active,
                "consecutive_losses": self.consecutive_losses,
                "deficit": round(self.recovery_deficit, 2),
            },
            "managed": [
                {
                    "ticket": t.ticket,
                    "symbol": t.symbol,
                    "be_done": t.be_done,
                    "initial_sl": t.initial_sl,
                    "atr": t.atr,
                    "mode": t.mode_key,
                    "horizon_type": t.horizon_type,
                    "horizon_label": t.horizon_label,
                    "max_duration_s": t.max_duration_s,
                }
                for t in self.trades.values()
            ],
        }

    def reset_symbol(self) -> None:
        pass

    def on_disconnect(self) -> None:
        self._set("DISCONNECTED", "Aguardando reconexão com o terminal MT5.")

    # ------------------------------------------------------------------ comandos
    def try_enable(
        self,
        connected: bool,
        account: dict,
        terminal: dict,
        sym: dict | None,
        settings: dict,
        server_day: int | None,
        current_day_total: float = 0.0,
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

        # Se havia uma trava antiga ou se o P&L atual do dia já estava abaixo do limite antes de ligar,
        # ajusta a linha de base (baseline) para contar o Stop Diário a partir de AGORA!
        loss_lim = float(settings.get("daily_loss_limit") or 0.0)
        base_now = float(settings.get("daily_loss_baseline") or 0.0)
        if self.lock_info(server_day)["active"] or (current_day_total - base_now) <= -loss_lim:
            self.store.set("daily_loss_baseline", round(float(current_day_total), 2))
            self.store.set("risk_lock", None)

        self.enabled = True
        self.retry_after = 0.0
        acct = account.get("trade_mode", "?")
        self.logs.add(
            f"🧠 MEGA BRAIN V4 ATIVADO · conta {account.get('login')} ({acct}) · "
            f"5 Estratégias Institucionais · Até {MAX_CONCURRENT_TRADES} moedas simultâneas · Proibido Contra-Tendência",
            "success",
            settings.get("mode"),
        )
        self._set("STUDYING_MARKET", "Todos os cérebros escaneando M1/M2/M5/M15 a favor da tendência.")
        return True, "Mega Brain V4 ligado."

    def disable(self, reason: str = "Desligada pelo operador.") -> None:
        if self.enabled:
            self.logs.add(f"IA AUTÔNOMA DESLIGADA · {reason}", "warn")
        self.enabled = False
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
        all_pos = ctx.all_positions if ctx.all_positions is not None else ctx.positions
        ai_pos = [p for p in all_pos if p.get("magic") == magic]
        self._track_closures(ctx, ai_pos)

        a = ctx.analysis
        eff_min = self.required_score(ctx.mode.min_score)
        if a.get("ready") and a.get("bar_time") != self._last_bar_seen.get(ctx.symbol):
            if self._last_bar_seen.get(ctx.symbol):
                cdl = a.get("candle") or {}
                hz = a.get("horizon") or {}
                prob_n = cdl.get("prob_up", 50) if a.get("direction") == "BUY" else cdl.get("prob_down", 50)
                self.logs.add(
                    f"[CÉREBRO {ctx.symbol}] Vela {a.get('timeframe', 'M1')} · {hz.get('strategy', 'Institucional')} · "
                    f"{SIDE_PT[a['direction']]} {a['score']:.0f}% (mín {eff_min:.0f}%) · Próx. vela {prob_n:.0f}%",
                    "think",
                    ctx.mode.key,
                )
            self._last_bar_seen[ctx.symbol] = int(a["bar_time"])

        if not self.enabled:
            lock = self.lock_info(ctx.server_day)
            if lock["active"]:
                self._set("RISK_LOCK", lock["reason"] or "")
            else:
                self._set("OFF", "Ligue a IA autônoma para ativar os cérebros em todas as moedas.")
            return None

        if self.lock_info(ctx.server_day)["active"]:
            self.enabled = False
            self._set("RISK_LOCK", self.lock_info(ctx.server_day)["reason"] or "")
            return None

        if self._check_breakers(ctx, all_pos):
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

        # 2. Permite até MAX_CONCURRENT_TRADES (4) operações simultâneas em moedas diferentes!
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

        # Exige +1% de precisão adicional para cada operação simultânea já aberta
        req_score = min(92.0, eff_min + (1.0 * len(ai_pos)))

        # Conta quantas operações abertas (ainda sem Break-Even) estão expostas para cada lado do USD
        unprotected_usd_long = 0
        unprotected_usd_short = 0
        for p in ai_pos:
            p_meta = self.trades.get(p["ticket"])
            is_safe = bool(p_meta and p_meta.be_done) or float(p.get("profit") or 0.0) > 0
            if not is_safe:
                u_dir = _usd_exposure_dir(p["symbol"], p["type"])
                if u_dir > 0:
                    unprotected_usd_long += 1
                elif u_dir < 0:
                    unprotected_usd_short += 1

        best_candidate: tuple[float, str, dict] | None = None
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

            mem_ok, _, _ = self.evaluate_symbol_memory(
                sym_name, sig or s_analysis.get("direction"), sc, req_score, ctx.server_time, tf_sec
            )
            if not mem_ok:
                continue

            if self._trade_permission_sym(ctx, sym_name, s_info, sig or s_analysis.get("direction")):
                continue

            m_sym = self.mem.get(sym_name)
            if m_sym and int(s_analysis.get("bar_time") or 0) == m_sym.last_entry_bar:
                continue

            # Proteção de Correlação USD: evita abrir mais de 2 apostas iguais no USD sem que as anteriores estejam protegidas
            if sig:
                usd_cand = _usd_exposure_dir(sym_name, sig)
                if usd_cand > 0 and unprotected_usd_long >= 2:
                    continue
                if usd_cand < 0 and unprotected_usd_short >= 2:
                    continue

            if sig and sc >= req_score:
                cdl = s_analysis.get("candle") or {}
                prob_n = cdl.get("prob_up", 50.0) if sig == "BUY" else cdl.get("prob_down", 50.0)
                rank_val = sc * 0.65 + prob_n * 0.35
                if best_candidate is None or rank_val > best_candidate[0]:
                    best_candidate = (rank_val, sym_name, bundle)

        if best_candidate is not None:
            _, target_sym, bundle = best_candidate
            opened = self._execute_on_symbol(ctx, target_sym, bundle, req_score, len(ai_pos))
            if opened:
                return target_sym

        if not ai_pos:
            if a.get("ready"):
                hz = a.get("horizon") or {}
                self._set(
                    "EVALUATING_CONFLUENCE",
                    f"{ctx.symbol} · {SIDE_PT[a['direction']]} {a['score']:.0f}% (Sniper ≥ {eff_min:.0f}%) · "
                    f"{hz.get('strategy', 'Institucional')}",
                )
            else:
                self._set("STUDYING_MARKET", a.get("study_block") or "Sincronizando cérebros das moedas.")
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

    # ------------------------------------------------------------------ circuit breakers (relativo ao baseline salvo!)
    def _check_breakers(self, ctx: Ctx, all_pos: list[dict]) -> bool:
        total = float(ctx.day.get("total") or 0.0)
        baseline = float(ctx.settings.get("daily_loss_baseline") or 0.0)
        session_pnl = total - baseline
        loss = float(ctx.settings.get("daily_loss_limit") or 0.0)
        gain = float(ctx.settings.get("daily_gain_target") or 0.0)
        ccy = ctx.account.get("currency", "")
        reason = None
        if loss > 0 and session_pnl <= -loss:
            reason = f"LIMITE DE PERDA atingido na sessão: {session_pnl:+.2f} {ccy} (limite definido -{loss:.2f} {ccy})"
        elif gain > 0 and total >= gain:
            reason = f"META DIÁRIA atingida: resultado do dia {total:+.2f} {ccy} (meta {gain:.2f} {ccy})"
        if not reason:
            return False
        self.logs.add(f"⛔ {reason}. Zerando posições abertas e pausando a IA.", "error", ctx.mode.key)
        if all_pos:
            self.close_all(ctx.symbol, all_pos, ctx.sym, ctx.settings, "STOP SESSAO")
        self.store.set("risk_lock", {"day": ctx.server_day, "reason": reason, "at": datetime.now().isoformat()})
        self.enabled = False
        self._set("RISK_LOCK", reason)
        return True

    # ------------------------------------------------------------------ execução sniper
    def _execute_on_symbol(
        self, ctx: Ctx, symbol: str, bundle: dict, eff_min: float, open_trades_count: int
    ) -> bool:
        a = bundle["analysis"]
        sym_info = bundle["sym"]
        tick = bundle["tick"]
        mode = ctx.mode
        side = a["signal"]
        hz = a.get("horizon") or {}

        self._set("EXECUTING_TRADE", f"{SIDE_PT[side]} {symbol} ({hz.get('strategy', 'Sniper')})")
        rec_active = self.consecutive_losses >= 1
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
        )
        if plan is None:
            self.logs.add(f"[CÉREBRO {symbol}] Sinal de {SIDE_PT[side]} descartado: {err}", "warn", mode.key)
            self.retry_after = time.monotonic() + 10
            return False

        cdl = a.get("candle") or {}
        prob_n = cdl.get("prob_up", 50) if side == "BUY" else cdl.get("prob_down", 50)
        digits = int(sym_info["digits"])
        ccy = ctx.account.get("currency", "")
        strat_str = hz.get("strategy", "Institucional")
        self.logs.add(
            f"🎯 [SNIPER {symbol} · {strat_str}] Certeza {a['score']:.0f}% · "
            f"Próx. vela {prob_n:.0f}% ({plan.horizon_label}). "
            f"Enviando {SIDE_PT[side]} {plan.lots} lote(s) · SL {plan.sl:.{digits}f} · TP {plan.tp:.{digits}f} · "
            f"risco controlado {plan.effective_risk:.2f} {ccy}",
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

        m_sym = self.mem.setdefault(symbol, SymbolMemory(symbol=symbol))
        m_sym.last_entry_bar = int(a["bar_time"])
        m_sym.last_entry_time = ctx.server_time
        self.last_global_open_mono = time.monotonic()

        self.logs.add(
            f"⚡ Ordem EXECUTADA em {symbol} · #{res.order} · {res.volume} lote(s) @ {res.price:.{digits}f} "
            f"· Estratégia: {strat_str}",
            "success",
            mode.key,
        )

        positions = self.bridge.positions(symbol) or []
        mine = sorted([p for p in positions if p["magic"] == int(ctx.settings["magic"])], key=lambda p: p["time"])
        pos = next((p for p in mine if p["ticket"] == res.order), mine[-1] if mine else None)
        if pos is None:
            return True

        d = 1 if side == "BUY" else -1
        entry = float(pos["price_open"])
        sl = self.bridge.norm_price(entry - d * plan.sl_dist, sym_info)
        tp = self.bridge.norm_price(entry + d * plan.tp_dist, sym_info)
        if res.stops_deferred or not pos["sl"]:
            mres = self.bridge.modify_sltp(symbol, pos["ticket"], sl, tp, int(ctx.settings["magic"]), sym_info)
            if mres.ok:
                self.logs.add(f"[{symbol}] SL/TP definidos: SL {sl:.{digits}f} · TP {tp:.{digits}f}", "action", mode.key)
        else:
            sl, tp = float(pos["sl"]), float(pos["tp"])

        self.trades[pos["ticket"]] = ManagedTrade(
            ticket=pos["ticket"],
            symbol=symbol,
            side=side,
            entry=entry,
            initial_sl=sl,
            tp=tp,
            atr=float(a["atr"]),
            mode_key=mode.key,
            horizon_type=plan.horizon_type,
            horizon_label=plan.horizon_label,
            max_duration_s=plan.duration_s,
            open_server_time=int(pos.get("time") or ctx.server_time),
        )
        self.known_ai.add(pos["ticket"])
        self._set(
            "MANAGING_POSITION",
            f"#{pos['ticket']} {SIDE_PT[side]} {symbol} ({strat_str})",
        )
        return True

    # ------------------------------------------------------------------ gestão inteligente (sem enforcar o lucro cedo!)
    def _reconstruct(self, ctx: Ctx, pos: dict, sym_info: dict, analysis: dict) -> ManagedTrade:
        side = pos["type"]
        symbol = pos.get("symbol") or ctx.symbol
        d = 1 if side == "BUY" else -1
        atr = float(analysis.get("atr") or 0.0) or abs(pos["price_open"] - (pos["sl"] or pos["price_open"])) / max(
            ctx.mode.sl_atr, 1e-9
        )
        entry = float(pos["price_open"])
        sl = float(pos["sl"]) if pos["sl"] else self.bridge.norm_price(entry - d * ctx.mode.sl_atr * atr, sym_info)
        tp = float(pos["tp"]) if pos["tp"] else self.bridge.norm_price(entry + d * ctx.mode.tp_atr * atr, sym_info)
        be_done = bool(pos["sl"]) and d * (float(pos["sl"]) - entry) >= 0
        hz = analysis.get("horizon") or {}
        t = ManagedTrade(
            ticket=pos["ticket"],
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
        )
        return t

    def _manage(self, ctx: Ctx, pos: dict) -> None:
        p_sym = pos.get("symbol") or ctx.symbol
        bundle = (ctx.symbol_map or {}).get(p_sym)
        sym = (bundle.get("sym") if bundle else None) or (ctx.sym if p_sym == ctx.symbol else self.bridge.symbol_info(p_sym))
        tick = (bundle.get("tick") if bundle else None) or (ctx.tick if p_sym == ctx.symbol else self.bridge.tick(p_sym))
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
        tick_size = float(sym["tick_size"] or sym["point"])
        digits = int(sym["digits"])
        atr_now = float(analysis.get("atr") or 0.0) if analysis.get("ready") else t.atr
        atr_now = atr_now or t.atr
        cur_sl = float(pos["sl"] or 0.0)
        cur_tp = float(pos["tp"] or 0.0) or t.tp
        progress = d * (price - t.entry)
        tp_dist = abs(cur_tp - t.entry) if cur_tp else mode.tp_atr * t.atr
        progress_frac = progress / max(tp_dist, 1e-9)
        elapsed_s = max(0, ctx.server_time - int(pos.get("time") or t.open_server_time or ctx.server_time))
        net_now = float(pos.get("profit") or 0.0) + float(pos.get("swap") or 0.0)

        cdl = analysis.get("candle") if analysis.get("ready") else None
        htf = analysis.get("htf") or {}
        prob_against = (cdl["prob_down"] if d > 0 else cdl["prob_up"]) if cdl else 50.0
        rev_against = bool((cdl["bear_reversal"] if d > 0 else cdl["bull_reversal"])) if cdl else False
        engulf_against = bool((cdl["bear_engulf"] if d > 0 else cdl["bull_engulf"])) if cdl else False
        m5_turned_against = bool(htf.get("available") and htf.get("bias21", 0) * d < 0 and htf.get("bar_dir", 0) * d < 0)

        # --- CAMADA 1: COLHEITA DE LUCRO GRANDE (Só colhe se já atingiu >= 68% da meta e a vela rejeitar!) ---
        if net_now > 0 and progress_frac >= 0.68 and (rev_against or prob_against >= 64.0):
            res = self.bridge.close_position(
                pos, int(ctx.settings.get("deviation_points", 20)), int(ctx.settings["magic"]), "TraderIA HARVEST_1VELA", sym
            )
            if res.ok:
                self.logs.add(
                    f"💰 [LUCRO CHEIO COLHIDO · {p_sym}] #{pos['ticket']} fechada a {res.price:.{digits}f}: "
                    f"atingiu {progress_frac * 100:.0f}% da meta! Ganho garantido!",
                    "success",
                    mode.key,
                )
                return

        # --- CAMADA 2: RELÓGIO DE VALIDADE (Garante lucro quando a janela termina, mas NÃO realiza prejuízo à toa!) ---
        if elapsed_s >= t.max_duration_s:
            # Se o tempo previsto terminou e a operação já caminhou >= 42% da meta no lucro, embolsa o ganho!
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

        # --- CAMADA 4 & 5: BREAK-EVEN INTELIGENTE (AOS 55% DA META, TRAVANDO +25% DE LUCRO) + TRAILING SUAVE ---
        new_sl: float | None = None
        event = ""
        if cur_sl == 0.0:
            new_sl, event = t.initial_sl, "Restaurando Stop Loss inicial"
        elif not t.be_done:
            if d * (cur_sl - t.entry) > 0:
                t.be_done = True
            else:
                trigger = mode.be_value * tp_dist  # 55% do alvo!
                if progress >= trigger:
                    # Trava +25% do alvo (deixa 30% de espaço livre para o preço respirar sem tomar violino com +2 pts!)
                    be_plus = self.bridge.norm_price(t.entry + d * max(4 * tick_size, 0.25 * tp_dist), sym)
                    if d * (be_plus - cur_sl) > 0:
                        new_sl, event = be_plus, f"LUCRO PROTEGIDO (+25% da meta garantido após {progress_frac * 100:.0f}% de avanço)"
                elif not t.half_risk_done and progress >= 0.38 * tp_dist:
                    reduced_sl = self.bridge.norm_price(t.entry - d * (0.55 * abs(t.entry - t.initial_sl)), sym)
                    if d * (reduced_sl - cur_sl) > 3 * tick_size:
                        new_sl, event = reduced_sl, "RISCO REDUZIDO após avanço de 38% rumo à meta"
                        t.half_risk_done = True

        # Só faz trailing stop depois que já passou de 72% da meta, para não enforcar a operação antes do alvo!
        if (t.be_done or event.startswith("LUCRO PROTEGIDO")) and progress_frac >= 0.72:
            cand = self.bridge.norm_price(price - d * (0.35 * tp_dist), sym)
            ref = new_sl if new_sl is not None else cur_sl
            min_step = max(mode.trail_min_step_atr * atr_now, 3 * tick_size)
            if d * (cand - ref) >= min_step and d * (cand - t.entry) > 0:
                new_sl = cand
                event = (event + " + " if event else "") + "TRAILING DE LUCRO CHEIO"

        if new_sl is None:
            return

        gap = max(int(sym.get("stops_level") or 0), int(sym.get("freeze_level") or 0)) * float(sym["point"])
        if d * (price - new_sl) <= gap:
            return
        now = time.monotonic()
        if now - t.last_modify < mode.modify_interval_s:
            return
        t.last_modify = now
        res = self.bridge.modify_sltp(p_sym, pos["ticket"], new_sl, cur_tp, int(ctx.settings["magic"]), sym)
        if res.ok:
            if event.startswith("LUCRO PROTEGIDO"):
                t.be_done = True
            msg = (
                f"[{p_sym}] #{pos['ticket']} {event}. Stop movido {cur_sl:.{digits}f} → {new_sl:.{digits}f} "
                f"(preço {price:.{digits}f})"
            )
            if event.startswith("TRAILING"):
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
        now_ids = {p["ticket"] for p in ai_pos}
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
                        f"Demais cérebros seguem buscando oportunidades Sniper!",
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
