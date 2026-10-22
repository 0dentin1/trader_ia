"""Gestão de risco V4 (MEGA BRAIN): Blindagem de Banca (de R$50 / €100 até $100k+),
Stop Estrutural Anti-Violino, Assimetria Positiva Obrigatória (Alvo >= 1.35x Stop) e P&L."""
from __future__ import annotations

from dataclasses import dataclass

from .config import ModeConfig
from .mt5_bridge import MT5Bridge


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
    horizon_type: str = "SCALP_1VELA"
    horizon_label: str = "⚡ Vela (90s)"
    duration_s: int = 90
    note: str = ""


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
) -> tuple[TradePlan | None, str]:
    """
    Calcula entrada, SL estrutural (nunca curto demais para evitar violino em 6s),
    TP sempre >= 1.35x SL (para que toda vitória seja maior que a perda) e
    lote blindado (seguro tanto para bancas de €100/R$50 quanto de $100.000).
    """
    d = 1 if side == "BUY" else -1
    entry = float(tick["ask"] if side == "BUY" else tick["bid"])
    point = float(sym["point"])
    spread = max(0.0, float(tick["ask"]) - float(tick["bid"]))
    broker_min_dist = (int(sym.get("stops_level") or 0) + 2) * point + spread

    # Piso estrutural de 12 pontos (1.2 pips) + spread: impede stops de 3-5 pontos que tomam violino em segundos
    structural_floor = max(broker_min_dist, 12.0 * point + spread)

    hz = horizon or {}
    hz_type = str(hz.get("type") or "SCALP_1VELA")
    hz_label = str(hz.get("label") or "⚡ Tiro Sniper de Vela (90s)")
    dur_s = int(hz.get("duration_s") or 90)
    sl_mult = float(hz.get("sl_atr") or mode.sl_atr)
    tp_mult = float(hz.get("tp_atr") or mode.tp_atr)

    # Garante sempre que o Alvo (TP) seja no mínimo 1.35x a 1.50x maior que o Stop (SL)
    min_rr = 1.45 if recovery_active else 1.35
    tp_mult = max(tp_mult, sl_mult * min_rr)

    sl_dist = max(sl_mult * atr, structural_floor)
    tp_dist = max(tp_mult * atr, sl_dist * min_rr)
    sl = bridge.norm_price(entry - d * sl_dist, sym)
    tp = bridge.norm_price(entry + d * tp_dist, sym)

    balance = float(account.get("balance") or 0.0)
    equity = float(account.get("equity") or 0.0)
    capital = min(balance, equity) if balance > 0 and equity > 0 else max(balance, equity)
    if capital <= 0:
        return None, "Capital líquido indisponível ou zerado."

    risk_pct = float(settings.get("risk_pct", {}).get(mode.key, mode.risk_default))
    # Teto prudente de risco por tiro individual (0.20% a 0.55%) para proteger qualquer tamanho de banca
    risk_pct = min(risk_pct, 0.55)
    note_parts: list[str] = [hz_label]

    if consecutive_losses >= 2:
        risk_pct *= 0.65
        note_parts.append("blindagem pós-loss (-35% exposição)")
    elif recovery_active:
        risk_pct *= 0.85
        note_parts.append("recuperação com R/R 1:1.45+")

    if open_trades_count >= 1:
        # Divide suavemente a exposição quando opera múltiplas moedas simultâneas (até 4)
        scale_conc = max(0.55, 1.0 - 0.15 * open_trades_count)
        risk_pct *= scale_conc
        note_parts.append(f"{open_trades_count + 1}ª moeda simultânea")

    risk_money = capital * risk_pct / 100.0

    loss_1 = bridge.loss_per_lot(symbol, side, entry, sl, sym)
    if not loss_1 or loss_1 <= 0:
        return None, "Não foi possível calcular o valor do risco por lote (order_calc_profit)."

    raw = risk_money / loss_1
    vmin, vmax = float(sym["volume_min"]), float(sym["volume_max"])

    # BLINDAGEM UNIVERSAL DE ALAVANCAGEM (Para bancas de R$50 / €100 até $100.000):
    # Limita o lote máximo a 1.0 lote a cada $15.000 de banca (ex: banca de $100 -> 0.01 lote; banca de $96k -> máx ~6.4 lotes).
    # Isso impede que um ATR pequeno multiplique o lote para 30-50 lotes e cause uma perda grande!
    max_safe_lots = max(vmin, round(capital / 15000.0, 2))
    lots = bridge.norm_volume(min(raw, max_safe_lots), sym)
    if raw > max_safe_lots:
        note_parts.append(f"lote blindado ({lots} máx p/ proteger banca)")

    if lots < vmin:
        lots = vmin
        note_parts.append("lote mínimo (0.01)")
    lots = min(lots, vmax)

    # Para bancas pequenas (ex.: $50 a $200), verifica se o risco de 0.01 lote cabe com segurança (<= 3.5% da banca)
    effective = loss_1 * lots
    if capital <= 500.0 and effective > capital * 0.035:
        return None, (
            f"Proteção de Banca Pequena ({capital:.2f}): o stop atual custaria {effective:.2f} "
            f"(>{3.5:.1f}% da banca). Aguardando vela com stop mais curto."
        )

    margin_free = float(account.get("margin_free") or 0.0)
    margin = bridge.margin_for(symbol, side, lots, entry)
    if margin is not None and margin > 0 and margin > margin_free * 0.80:
        scaled = bridge.norm_volume(lots * (margin_free * 0.80) / margin, sym)
        if scaled < vmin:
            return None, f"Margem livre insuficiente ({margin_free:.2f}) para o lote mínimo ({vmin})."
        lots = scaled
        effective = loss_1 * lots
        note_parts.append("ajustado pela margem livre")

    note = " · ".join(note_parts)
    hard_cap = capital * mode.risk_max / 100.0 * 1.5
    if capital > 500.0 and effective > hard_cap:
        return None, (
            f"Risco efetivo {effective:.2f} com {lots} lote(s) excede o teto de segurança "
            f"({hard_cap:.2f}). Operação bloqueada."
        )
    return TradePlan(
        side=side,
        entry=entry,
        sl=sl,
        tp=tp,
        sl_dist=sl_dist,
        tp_dist=tp_dist,
        lots=lots,
        risk_money=risk_money,
        effective_risk=effective,
        horizon_type=hz_type,
        horizon_label=hz_label,
        duration_s=dur_s,
        note=note,
    ), ""


def realized_today(deals: list[dict]) -> float:
    """Soma resultado real (lucro + swap + comissão + taxas) dos negócios de compra/venda do dia."""
    total = 0.0
    for d in deals:
        if d.get("type_raw") not in (0, 1):
            continue
        total += (
            float(d.get("profit") or 0)
            + float(d.get("swap") or 0)
            + float(d.get("commission") or 0)
            + float(d.get("fee") or 0)
        )
    return total


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
    if "PANIC" in comment or "CLOSE" in comment or "ENCERRAR" in comment:
        return "Encerrado pelo Operador / IA"
    if "CIRCUIT" in comment or "STOP DI" in comment or "META" in comment:
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
    """Agrupa deals reais do MT5 por position_id em operações completas (entrada -> saída, duração, P&L)."""
    from datetime import datetime

    by_pos: dict[int, list[dict]] = {}
    for d in deals:
        if d.get("type_raw") not in (0, 1):
            continue
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

        first_in = in_deals[0] if in_deals else group_sorted[0]
        last_out = out_deals[-1]

        if in_deals:
            side = first_in.get("type", "BUY")
            in_vol = sum(float(x.get("volume") or 0.0) for x in in_deals)
            entry_price = (
                sum(float(x.get("price") or 0.0) * float(x.get("volume") or 0.0) for x in in_deals) / in_vol
                if in_vol > 0
                else float(first_in.get("price") or 0.0)
            )
        else:
            side = "SELL" if last_out.get("type") == "BUY" else "BUY"
            in_vol = 0.0
            entry_price = float(first_in.get("price") or 0.0)

        out_vol = sum(float(x.get("volume") or 0.0) for x in out_deals)
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
