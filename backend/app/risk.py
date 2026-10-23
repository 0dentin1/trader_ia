"""Camada Independente de Risco, Proteção de Carteira, Dimensionamento de Lote e Reconciliação de P&L (Parte 2 e Parte 3)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from .config import MAX_TICK_AGE_S, ModeConfig
from .mt5_bridge import (
    SYMBOL_TRADE_MODE_CLOSEONLY,
    SYMBOL_TRADE_MODE_DISABLED,
    SYMBOL_TRADE_MODE_LONGONLY,
    SYMBOL_TRADE_MODE_SHORTONLY,
    MT5Bridge,
)
from .settings_store import compute_trading_day, compute_trading_week
from .small_account_guard import (
    SmallAccountEvaluation,
    evaluate_small_account_guard,
    resolve_profile_limits,
)

KNOWN_CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "BRL", "XAU", "XAG", "BTC")


def parse_currency_pair(symbol: str) -> tuple[str | None, str | None]:
    """Extrai moeda base e moeda de cotação de um símbolo padrão (ex: EURUSD -> ('EUR', 'USD'))."""
    s = (symbol or "").upper().strip()
    clean_s = "".join(ch for ch in s if ch.isalpha())
    if len(clean_s) >= 6:
        b, q = clean_s[:3], clean_s[3:6]
        if b in KNOWN_CURRENCIES or q in KNOWN_CURRENCIES:
            return b, q
    return None, None


def currency_exposures(symbol: str, side: str) -> dict[str, int]:
    """Retorna direção da exposição (+1 comprado, -1 vendido) por moeda componente do par."""
    base, quote = parse_currency_pair(symbol)
    d = 1 if side == "BUY" else -1
    out: dict[str, int] = {}
    if base:
        out[base] = d
    if quote:
        out[quote] = -d
    return out


def usd_exposure_dir(symbol: str, side: str) -> int:
    """Retorna +1 se a operação aposta na alta do USD, -1 se aposta na queda do USD, 0 caso contrário."""
    return currency_exposures(symbol, side).get("USD", 0)


def is_position_sl_confirmed_safe(pos: dict) -> bool:
    """
    Uma posição aberta só é considerada protegida contra perda se possuir SL confirmado no MT5
    no preço de entrada ou a favor da operação. Lucro flutuante momentâneo NÃO conta como proteção (Parte 2.6).
    """
    sl = float(pos.get("sl") or 0.0)
    entry = float(pos.get("price_open") or 0.0)
    if sl <= 0.0 or entry <= 0.0:
        return False
    d = 1 if pos.get("type") == "BUY" else -1
    return d * (sl - entry) >= -1e-9


def estimate_open_position_risk(
    bridge: MT5Bridge,
    pos: dict,
    sym_info: dict | None = None,
) -> tuple[float, bool]:
    """
    Calcula o risco monetário residual de uma posição aberta até o seu Stop Loss confirmado.
    Retorna (risk_money, is_unprotected).
    Se a posição não tiver SL confirmado (sl <= 0), retorna is_unprotected = True.
    """
    sl = float(pos.get("sl") or 0.0)
    entry = float(pos.get("price_open") or 0.0)
    vol = float(pos.get("volume") or 0.0)
    side = str(pos.get("type") or "BUY")
    symbol = str(pos.get("symbol") or "")

    if sl <= 0.0 or entry <= 0.0 or vol <= 0.0:
        return 0.0, True

    if is_position_sl_confirmed_safe(pos):
        return 0.0, False

    pnl_at_sl = bridge.calc_profit(symbol, side, vol, entry, sl)
    if pnl_at_sl is not None:
        return max(0.0, -float(pnl_at_sl)), False

    if sym_info:
        loss_1 = bridge.loss_per_lot(symbol, side, entry, sl, sym_info)
        if loss_1 and loss_1 > 0:
            return max(0.0, float(loss_1) * vol), False

    # Política conservadora se não for possível calcular exatamente
    floating = float(pos.get("profit") or 0.0)
    return max(0.0, -floating), False


def evaluate_portfolio_protection(
    bridge: MT5Bridge,
    open_positions: list[dict],
    candidate_symbol: str | None = None,
    candidate_side: str | None = None,
    symbol_map: dict[str, dict] | None = None,
    max_same_currency_unprotected: int = 2,
) -> dict:
    """
    Avalia o risco no nível da carteira (Parte 2.6):
    - Risco residual de cada posição aberta até seu stop.
    - Risco agregado das posições abertas.
    - Concentração por ativo e exposição comum às mesmas moedas (USD, EUR, GBP, JPY, etc.).
    - Existência de posições sem SL confirmado.
    """
    total_open_risk = 0.0
    has_unprotected = False
    unprotected_tickets: list[int] = []
    ccy_directional_counts: dict[tuple[str, int], int] = {}
    same_symbol_open = False

    for p in open_positions:
        p_sym = str(p.get("symbol") or "")
        if candidate_symbol and p_sym == candidate_symbol:
            same_symbol_open = True
        s_info = None
        if symbol_map and p_sym in symbol_map:
            raw_s = symbol_map[p_sym]
            s_info = raw_s.get("sym") if isinstance(raw_s, dict) and "sym" in raw_s else raw_s
        risk_m, unprot = estimate_open_position_risk(bridge, p, s_info)
        total_open_risk += risk_m
        if unprot:
            has_unprotected = True
            unprotected_tickets.append(int(p.get("ticket") or 0))
        if not is_position_sl_confirmed_safe(p):
            for ccy, dir_sign in currency_exposures(p_sym, str(p.get("type") or "BUY")).items():
                key = (ccy, dir_sign)
                ccy_directional_counts[key] = ccy_directional_counts.get(key, 0) + 1

    corr_block_reason: str | None = None
    if same_symbol_open:
        corr_block_reason = f"Já existe posição aberta no ativo {candidate_symbol}."
    elif candidate_symbol and candidate_side:
        cand_exp = currency_exposures(candidate_symbol, candidate_side)
        for ccy, dir_sign in cand_exp.items():
            existing = ccy_directional_counts.get((ccy, dir_sign), 0)
            if existing >= max_same_currency_unprotected:
                dir_lbl = "ALTA" if dir_sign > 0 else "BAIXA"
                corr_block_reason = (
                    f"Concentração/correlação cambial: já existem {existing} posições expostas na {dir_lbl} "
                    f"de {ccy} sem proteção no zero a zero."
                )
                break

    return {
        "aggregate_open_risk_money": round(total_open_risk, 4),
        "has_unprotected_position": has_unprotected,
        "unprotected_tickets": unprotected_tickets,
        "same_symbol_open": same_symbol_open,
        "correlation_blocked_reason": corr_block_reason,
        "currency_exposure_counts": {f"{k[0]}_{'LONG' if k[1] > 0 else 'SHORT'}": v for k, v in ccy_directional_counts.items()},
    }


@dataclass
class TradePlan:
    side: str
    entry: float
    sl: float
    tp: float
    sl_dist: float
    tp_dist: float
    lots: float
    risk_money: float
    effective_risk: float
    estimated_costs: float = 0.0
    spread_points: int = 0
    horizon_type: str = "SCALP_1VELA"
    horizon_label: str = "⚡ Vela (90s)"
    duration_s: int = 90
    note: str = ""
    guard_status: str = "APPROVED"
    guard_evaluation: dict = field(default_factory=dict)

    @property
    def small_account_guard(self) -> dict:
        return self.guard_evaluation

    @property
    def effective_risk_pct(self) -> float:
        return float(self.guard_evaluation.get("effective_risk_pct") or 0.0)

    def to_dict(self) -> dict:
        return asdict(self)


def build_plan(
    bridge: MT5Bridge,
    symbol: str,
    sym: dict,
    tick: dict,
    side: str,
    atr: float,
    mode: ModeConfig,
    settings: dict,
    account: dict,
    consecutive_losses: int = 0,
    recovery_active: bool = False,
    horizon: dict | None = None,
    open_trades_count: int = 0,
    open_positions: list[dict] | None = None,
    symbol_map: dict[str, dict] | None = None,
    session_pnl: float = 0.0,
    weekly_pnl: float = 0.0,
    server_now: int = 0,
) -> tuple[TradePlan | None, str]:
    """
    Camada Independente de Validação de Risco e Cálculo de Lote (Partes 2.4, 2.5, 2.6 e Parte 3).
    Procedimento estrito:
    1. Valida integridade e atualidade dos dados, ativo, cotação, spread e conexão.
    2. Calcula a distância do stop pela estrutura real e ATR (sem encolher stop para forçar lote).
    3. Calcula o orçamento de risco monetário autorizado na moeda da conta.
    4. Calcula o volume com especificações reais do ativo, perda no stop e margem de custos.
    5. Aplica limites de volume e margem sem JAMAIS forçar o lote mínimo se ele exceder o orçamento de risco.
    6. Recalcula o risco efetivo final e valida via `evaluate_small_account_guard` e carteira.
    """
    # 1. Validação da integridade de dados e permissões do ativo
    if not sym or not tick or not account:
        return None, "Operação bloqueada: dados de ativo, cotação ou conta ausentes."

    if not atr or atr <= 0:
        return None, "Operação bloqueada: ATR inválido ou zerado."

    bid = float(tick.get("bid") or 0.0)
    ask = float(tick.get("ask") or 0.0)
    point = float(sym.get("point") or 0.0)
    if bid <= 0 or ask <= 0 or ask < bid or point <= 0:
        return None, "Operação bloqueada: cotação bid/ask ou point inválido."

    tick_time = int(tick.get("time") or 0)
    if server_now > 0 and tick_time > 0 and abs(server_now - tick_time) > MAX_TICK_AGE_S:
        return None, f"Operação bloqueada: cotação desatualizada ({abs(server_now - tick_time)}s > {MAX_TICK_AGE_S}s)."

    tm = sym.get("trade_mode")
    if tm in (SYMBOL_TRADE_MODE_DISABLED, SYMBOL_TRADE_MODE_CLOSEONLY):
        return None, f"Operação bloqueada: ativo {symbol} desabilitado ou apenas fechamento."
    if tm == SYMBOL_TRADE_MODE_LONGONLY and side == "SELL":
        return None, f"Operação bloqueada: ativo {symbol} permite apenas compras."
    if tm == SYMBOL_TRADE_MODE_SHORTONLY and side == "BUY":
        return None, f"Operação bloqueada: ativo {symbol} permite apenas vendas."

    spread = max(0.0, ask - bid)
    spread_points = int(round(spread / point))
    max_spread = int(settings.get("max_spread_points") or 25)
    if spread_points > max_spread:
        return None, f"Operação bloqueada: spread atual ({spread_points} pts) excede o máximo configurado ({max_spread} pts)."

    # 2. Distância de stop e alvo pelas condições reais do mercado (sem redução artificial)
    d = 1 if side == "BUY" else -1
    entry = ask if side == "BUY" else bid
    broker_min_dist = (int(sym.get("stops_level") or 0) + 2) * point + spread
    structural_floor = max(broker_min_dist, 12.0 * point + spread)

    hz = horizon or {}
    hz_type = str(hz.get("type") or "SCALP_1VELA")
    hz_label = str(hz.get("label") or "⚡ Tiro Sniper de Vela (90s)")
    dur_s = int(hz.get("duration_s") or 90)
    sl_mult = float(hz.get("sl_atr") or mode.sl_atr)
    tp_mult = float(hz.get("tp_atr") or mode.tp_atr)

    # R/R mínimo positivo (NUNCA altera risco por recuperação; apenas mantém assimetria saudável)
    min_rr = 1.35
    tp_mult = max(tp_mult, sl_mult * min_rr)

    sl_dist = max(sl_mult * atr, structural_floor)
    tp_dist = max(tp_mult * atr, sl_dist * min_rr)
    sl = bridge.norm_price(entry - d * sl_dist, sym)
    tp = bridge.norm_price(entry + d * tp_dist, sym)

    # 3. Capital de referência e perfil de risco (Zero Martingale: nunca aumenta risco pós-loss)
    balance = float(account.get("balance") or 0.0)
    equity = float(account.get("equity") or 0.0)
    capital = min(balance, equity) if (balance > 0 and equity > 0) else max(balance, equity, 0.0)
    if capital <= 0:
        return None, "Operação bloqueada: capital líquido indisponível ou zerado."

    profile_limits = resolve_profile_limits(settings)
    user_mode_risk = float(settings.get("risk_pct", {}).get(mode.key, mode.risk_default))
    # Respeita o teto de risco planejado do perfil (0.25% alvo / 0.50% teto em SMALL_ACCOUNT_PROTECTION)
    profile_name = str(settings.get("account_profile") or "SMALL_ACCOUNT_PROTECTION").upper()
    if profile_name == "SMALL_ACCOUNT_PROTECTION":
        base_risk_pct = min(user_mode_risk, profile_limits["target_risk_pct"], profile_limits["max_planned_risk_pct"])
    else:
        base_risk_pct = min(user_mode_risk, profile_limits["max_planned_risk_pct"])

    note_parts: list[str] = [hz_label]
    if consecutive_losses >= 2:
        base_risk_pct *= 0.75
        note_parts.append("redução preventiva pós-losses (-25%)")

    if open_trades_count >= 1:
        scale_conc = max(0.60, 1.0 - 0.15 * open_trades_count)
        base_risk_pct *= scale_conc
        note_parts.append(f"{open_trades_count + 1}ª posição simultânea")

    # 4. Avaliação de carteira e custos por lote
    portfolio = evaluate_portfolio_protection(
        bridge=bridge,
        open_positions=open_positions or [],
        candidate_symbol=symbol,
        candidate_side=side,
        symbol_map=symbol_map,
    )

    loss_1 = bridge.loss_per_lot(symbol, side, entry, sl, sym)
    if not loss_1 or loss_1 <= 0:
        return None, "Operação bloqueada: não foi possível calcular o valor do risco por lote (order_calc_profit)."

    # Custos de execução conservadores (slippage esperado de 2 pontos + buffer operacional),
    # sem contar o spread duas vezes pois `entry` (Ask na Compra / Bid na Venda) já embute o spread na distância até `sl`.
    slippage_pts = min(int(settings.get("deviation_points") or 20), 3)
    slippage_price = slippage_pts * point
    cost_per_lot = loss_1 * (slippage_price / max(sl_dist, 1e-9))
    unit_total_risk = loss_1 + cost_per_lot

    # Pré-avaliação para obter o fator de escala de drawdown (NORMAL=1.0, CAUTION=0.75, REDUCED=0.50)
    pre_eval = evaluate_small_account_guard(
        account=account,
        sym=sym,
        settings=settings,
        requested_risk_pct=base_risk_pct,
        loss_per_lot_at_sl=loss_1,
        estimated_costs_per_lot=cost_per_lot,
        final_volume=float(sym.get("volume_min") or 0.01),
        margin_required=0.0,
        open_portfolio_risk_money=portfolio["aggregate_open_risk_money"],
        session_pnl=session_pnl,
        weekly_pnl=weekly_pnl,
        has_unprotected_position=portfolio["has_unprotected_position"],
        correlation_blocked_reason=portfolio["correlation_blocked_reason"],
    )
    if not pre_eval.approved:
        return None, pre_eval.reason

    effective_target_pct = pre_eval.target_risk_pct
    planned_risk_money = capital * effective_target_pct / 100.0
    allowed_max_risk_money = capital * pre_eval.max_planned_risk_pct / 100.0

    # 5. Dimensionamento do lote
    vmin = float(sym.get("volume_min") or 0.01)
    vmax = float(sym.get("volume_max") or 100.0)
    raw = planned_risk_money / unit_total_risk
    max_safe_lots = max(vmin, round(capital / 15000.0, 2))
    capped_raw = min(raw, max_safe_lots, vmax)

    if capped_raw < vmin:
        # Só utiliza o lote mínimo se o risco efetivo do lote mínimo couber dentro do orçamento máximo autorizado!
        if unit_total_risk * vmin <= allowed_max_risk_money + 1e-6:
            lots = vmin
            note_parts.append(f"lote mínimo ({vmin}) dentro do teto de risco")
        else:
            return None, (
                "Operação bloqueada: o lote mínimo permitido neste ativo ultrapassa o risco máximo configurado para sua conta "
                f"(lote mín. {vmin} arrisca {unit_total_risk * vmin:.2f} {pre_eval.currency}, "
                f"acima do teto de {allowed_max_risk_money:.2f} {pre_eval.currency})."
            )
    else:
        lots = bridge.norm_volume(capped_raw, sym)
        if raw > max_safe_lots:
            note_parts.append(f"teto de alavancagem ({lots} lotes)")

    lots = min(lots, vmax)

    # 6. Verificação e ajuste por margem livre (sem forçar abaixo de vmin)
    margin_free = float(account.get("margin_free") or 0.0)
    margin_req = bridge.margin_for(symbol, side, lots, entry)
    if margin_req is not None and margin_req > 0 and margin_req > margin_free * 0.80:
        if margin_free <= 0:
            return None, f"Operação bloqueada: margem livre insuficiente ({margin_free:.2f})."
        scaled = bridge.norm_volume(lots * (margin_free * 0.80) / margin_req, sym)
        if scaled < vmin:
            return None, (
                f"Operação bloqueada: margem livre insuficiente ({margin_free:.2f}) "
                f"para suportar o lote mínimo ({vmin}, requer {margin_req:.2f})."
            )
        lots = scaled
        margin_req = bridge.margin_for(symbol, side, lots, entry)
        note_parts.append("ajustado pela margem livre")

    # 7. Validação final com o volume efetivo
    final_eval = evaluate_small_account_guard(
        account=account,
        sym=sym,
        settings=settings,
        requested_risk_pct=base_risk_pct,
        loss_per_lot_at_sl=loss_1,
        estimated_costs_per_lot=cost_per_lot,
        final_volume=lots,
        margin_required=margin_req,
        open_portfolio_risk_money=portfolio["aggregate_open_risk_money"],
        session_pnl=session_pnl,
        weekly_pnl=weekly_pnl,
        has_unprotected_position=portfolio["has_unprotected_position"],
        correlation_blocked_reason=portfolio["correlation_blocked_reason"],
    )
    if not final_eval.approved:
        return None, final_eval.reason

    effective_risk = round(unit_total_risk * lots, 2)
    est_costs = round(cost_per_lot * lots, 2)
    note = " · ".join(note_parts)

    return TradePlan(
        side=side,
        entry=entry,
        sl=sl,
        tp=tp,
        sl_dist=sl_dist,
        tp_dist=tp_dist,
        lots=lots,
        risk_money=round(planned_risk_money, 2),
        effective_risk=effective_risk,
        estimated_costs=est_costs,
        spread_points=spread_points,
        horizon_type=hz_type,
        horizon_label=hz_label,
        duration_s=dur_s,
        note=note,
        guard_status=final_eval.status,
        guard_evaluation=final_eval.to_dict(),
    ), ""


def deal_net_pnl(d: dict) -> float:
    """Resultado líquido de um deal individual (profit + swap + commission + fee)."""
    return (
        float(d.get("profit") or 0.0)
        + float(d.get("swap") or 0.0)
        + float(d.get("commission") or 0.0)
        + float(d.get("fee") or 0.0)
    )


def is_ai_attributed(item: dict, magic: int) -> bool:
    """Identifica de forma confiável se um deal ou posição pertence ao Trader IA."""
    if int(item.get("magic") or 0) == int(magic):
        return True
    comment = str(item.get("comment") or "")
    return "TraderIA" in comment


def realized_today(deals: list[dict], magic: int | None = None) -> float:
    """
    Soma resultado líquido realizado dos negócios de compra/venda do dia.
    Se `magic` for informado, contabiliza apenas os deals atribuídos ao Trader IA.
    """
    total = 0.0
    for d in deals:
        if d.get("type_raw") not in (0, 1):
            continue
        if magic is not None and not is_ai_attributed(d, magic):
            continue
        total += deal_net_pnl(d)
    return round(total, 2)


def compute_financial_breakdown(
    all_deals: list[dict],
    open_positions: list[dict],
    account: dict,
    magic: int,
    server_time: int,
    settings: dict,
    trade_summary: dict | None = None,
) -> dict:
    """
    Separa de maneira consistente todos os componentes financeiros (Parte 2.2):
    - P&L realizado do Trader IA vs da conta inteira.
    - P&L flutuante das posições do Trader IA vs da conta inteira.
    - P&L líquido da sessão, diário e semanal.
    - Equity de referência e linha de base utilizada nos limites.
    - Posições abertas NUNCA são tratadas como lucro realizado.
    """
    rollover_h = int(settings.get("session_rollover_hour") or 0)
    cur_day = compute_trading_day(server_time, rollover_h) if server_time else 0
    cur_week = compute_trading_week(server_time, rollover_h) if server_time else 0
    day_start_ts = cur_day * 86400 + rollover_h * 3600 if cur_day > 0 else 0
    week_start_ts = (cur_week * 7 - 3) * 86400 + rollover_h * 3600 if cur_week > 0 else 0

    ai_realized_day = 0.0
    account_realized_day = 0.0
    ai_realized_week = 0.0
    account_realized_week = 0.0
    ai_realized_all = 0.0
    account_realized_all = 0.0

    for d in all_deals:
        if d.get("type_raw") not in (0, 1):
            continue
        # Apenas deals que efetivamente realizam resultado ou cobram comissão de entrada/saída
        net = deal_net_pnl(d)
        t_deal = int(d.get("time") or 0)
        mine = is_ai_attributed(d, magic)

        account_realized_all += net
        if mine:
            ai_realized_all += net

        if t_deal >= week_start_ts:
            account_realized_week += net
            if mine:
                ai_realized_week += net

        if t_deal >= day_start_ts:
            account_realized_day += net
            if mine:
                ai_realized_day += net

    ai_positions = [p for p in open_positions if is_ai_attributed(p, magic)]
    ai_floating = sum(float(p.get("profit") or 0.0) + float(p.get("swap") or 0.0) for p in ai_positions)
    account_floating = (
        float(account.get("profit"))
        if account.get("profit") is not None
        else sum(float(p.get("profit") or 0.0) + float(p.get("swap") or 0.0) for p in open_positions)
    )

    ai_day_total = round(ai_realized_day + ai_floating, 2)
    account_day_total = round(account_realized_day + account_floating, 2)
    ai_weekly_total = round(ai_realized_week + ai_floating, 2)
    account_weekly_total = round(account_realized_week + account_floating, 2)

    protect_whole = bool(settings.get("protect_whole_account", False))
    baseline = float(settings.get("daily_loss_baseline") or 0.0)

    governed_realized_day = account_realized_day if protect_whole else ai_realized_day
    governed_floating = account_floating if protect_whole else ai_floating
    governed_day_total = account_day_total if protect_whole else ai_day_total
    governed_weekly_total = account_weekly_total if protect_whole else ai_weekly_total
    session_net = round(governed_day_total - baseline, 2)

    balance = float(account.get("balance") or 0.0)
    equity = float(account.get("equity") or 0.0)
    ref_equity = min(balance, equity) if (balance > 0 and equity > 0) else max(balance, equity, 0.0)
    ss = settings.get("session_state") or {}
    session_start_eq = float(ss.get("session_start_equity") or ref_equity or 0.0)
    week_start_eq = float(ss.get("week_start_equity") or ref_equity or 0.0)

    tsum = trade_summary or {}
    return {
        # Campos governados para compatibilidade direta com o painel e motor
        "realized": round(governed_realized_day, 2),
        "floating": round(governed_floating, 2),
        "total": round(governed_day_total, 2),
        "session_net": session_net,
        "weekly_net": round(governed_weekly_total, 2),
        # Separação explícita Trader IA vs Conta Inteira (Parte 2.2)
        "ai_realized_today": round(ai_realized_day, 2),
        "ai_floating": round(ai_floating, 2),
        "ai_day_total": ai_day_total,
        "ai_weekly_net": ai_weekly_total,
        "ai_realized_all_time": round(ai_realized_all, 2),
        "account_realized_today": round(account_realized_day, 2),
        "account_floating": round(account_floating, 2),
        "account_day_total": account_day_total,
        "account_weekly_net": account_weekly_total,
        "account_realized_all_time": round(account_realized_all, 2),
        # Referências de capital e linha de base
        "reference_equity": round(ref_equity, 2),
        "session_start_equity": round(session_start_eq, 2),
        "week_start_equity": round(week_start_eq, 2),
        "baseline_used": round(baseline, 2),
        "protect_whole_account": protect_whole,
        "scope_label": "CONTA_INTEIRA" if protect_whole else "TRADER_IA_MAGIC",
        # Resumo histórico acumulado
        "all_time": round(account_realized_all + account_floating, 2),
        "net_closed": round(float(tsum.get("net_total") or account_realized_all), 2),
        "trades_total": int(tsum.get("total_trades") or 0),
        "trades_wins": int(tsum.get("wins") or 0),
    }


def _exit_reason_label(deal: dict) -> str:
    comment = str(deal.get("comment") or "").upper()
    reason = str(deal.get("reason") or "")
    if "HARVEST" in comment or "SMART_TP" in comment:
        return "Lucro de Vela Colhido pela IA"
    if "TIME_STOP_WIN" in comment:
        return "Lucro Garantido no Fim da Vela (IA)"
    if "TIME_STOP" in comment or "HORIZON" in comment:
        return "Fim do Tempo da Previsão (IA)"
    if "DEFENSE" in comment:
        return "Defesa Antecipada da IA"
    if "EMERGENCY_NO_SL" in comment:
        return "Fechamento de Emergência (SL não confirmado)"
    if "PANIC" in comment or "CLOSE" in comment or "ENCERRAR" in comment:
        return "Encerrado pelo Operador / IA"
    if "CIRCUIT" in comment or "STOP DI" in comment or "STOP SESSAO" in comment or "META" in comment:
        return "Trava Diária (Circuit Breaker)"
    if "[TP" in comment or reason == "Take Profit":
        return "Bateu na Meta (Take Profit)"
    if "[SL" in comment or reason == "Stop Loss":
        return "Stop de Proteção (SL / Trailing)"
    if reason == "Robô":
        return "Encerrado pela IA Autônoma"
    if reason == "Manual":
        return "Encerrado Manualmente"
    return reason or "Encerrado"


def summarize_trades(deals: list[dict], magic: int, server_offset_s: int = 0) -> dict:
    """
    Agrupa deals reais do MT5 por position_id em operações completas (entrada -> saída, duração, P&L).
    Reconcilia entradas, saídas parciais, comissões, swaps e taxas sem dupla contagem.
    """
    by_pos: dict[int, list[dict]] = {}
    seen_tickets: set[int] = set()
    for d in deals:
        if d.get("type_raw") not in (0, 1):
            continue
        tkt = int(d.get("ticket") or 0)
        if tkt > 0:
            if tkt in seen_tickets:
                continue
            seen_tickets.add(tkt)
        pid = int(d.get("position_id") or 0)
        if pid <= 0:
            continue
        by_pos.setdefault(pid, []).append(d)

    today_str = datetime.now().strftime("%Y-%m-%d")
    trades: list[dict] = []

    for pid, group in by_pos.items():
        group_sorted = sorted(group, key=lambda x: (x.get("time_msc") or (x["time"] * 1000), x["ticket"]))
        in_deals = [x for x in group_sorted if x.get("entry") == "IN"]
        out_deals = [x for x in group_sorted if x.get("entry") in ("OUT", "INOUT", "OUT_BY")]
        if not out_deals:
            continue

        in_vol = sum(float(x.get("volume") or 0.0) for x in in_deals)
        out_vol = sum(float(x.get("volume") or 0.0) for x in out_deals)
        # Se houve apenas fechamento parcial e a posição ainda tem saldo aberto, não marca como totalmente encerrada
        is_partial_only = in_vol > 0 and out_vol < (in_vol - 1e-6)
        if is_partial_only:
            continue

        first_in = in_deals[0] if in_deals else group_sorted[0]
        last_out = out_deals[-1]

        if in_deals:
            side = first_in.get("type", "BUY")
            entry_price = (
                sum(float(x.get("price") or 0.0) * float(x.get("volume") or 0.0) for x in in_deals) / in_vol
                if in_vol > 0
                else float(first_in.get("price") or 0.0)
            )
        else:
            side = "SELL" if last_out.get("type") == "BUY" else "BUY"
            entry_price = float(first_in.get("price") or 0.0)

        exit_price = (
            sum(float(x.get("price") or 0.0) * float(x.get("volume") or 0.0) for x in out_deals) / out_vol
            if out_vol > 0
            else float(last_out.get("price") or 0.0)
        )
        volume = out_vol if out_vol > 0 else in_vol

        open_time = int(first_in["time"])
        close_time = int(last_out["time"])
        open_local = open_time - server_offset_s
        close_local = close_time - server_offset_s
        duration_s = max(0, close_time - open_time)

        gross = sum(float(x.get("profit") or 0.0) for x in group_sorted)
        comm = sum(float(x.get("commission") or 0.0) + float(x.get("fee") or 0.0) for x in group_sorted)
        swap = sum(float(x.get("swap") or 0.0) for x in group_sorted)
        net = gross + comm + swap

        comments = " ".join(str(x.get("comment") or "") for x in group_sorted)
        is_ai = any(int(x.get("magic") or 0) == int(magic) for x in group_sorted) or ("TraderIA" in comments)
        mode_used = None
        for m in ("LEVE", "MEDIANO", "ARRISCADO"):
            if m in comments.upper():
                mode_used = m
                break

        trades.append({
            "position_id": pid,
            "symbol": last_out.get("symbol") or first_in.get("symbol") or "",
            "side": side,
            "volume": round(volume, 2),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "open_time": open_time,
            "close_time": close_time,
            "open_time_local": open_local,
            "close_time_local": close_local,
            "duration_s": duration_s,
            "gross_profit": round(gross, 2),
            "commission": round(comm, 2),
            "swap": round(swap, 2),
            "net_profit": round(net, 2),
            "won": net >= 0,
            "is_ai": is_ai,
            "mode": mode_used,
            "exit_reason": _exit_reason_label(last_out),
            "is_today": datetime.fromtimestamp(close_local).strftime("%Y-%m-%d") == today_str,
            "deal_tickets": [int(x.get("ticket") or 0) for x in group_sorted],
            "order_tickets": [int(x.get("order") or 0) for x in group_sorted],
            "partial_fills_count": len(in_deals),
            "partial_closes_count": len(out_deals),
        })

    trades.sort(key=lambda t: t["close_time"], reverse=True)
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["won"])
    losses = total_trades - wins
    net_total = round(sum(t["net_profit"] for t in trades), 2)
    net_today = round(sum(t["net_profit"] for t in trades if t["is_today"]), 2)
    avg_dur = int(round(sum(t["duration_s"] for t in trades) / total_trades)) if total_trades > 0 else 0

    return {
        "trades": trades,
        "summary": {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(100.0 * wins / total_trades, 1) if total_trades > 0 else 0.0,
            "net_total": net_total,
            "net_today": net_today,
            "avg_duration_s": avg_dur,
        },
    }
