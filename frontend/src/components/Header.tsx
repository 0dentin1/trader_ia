import { memo, useState } from "react";
import { Bot, Cpu, OctagonX, Power, Radar, RefreshCw, Wifi, WifiOff, Zap } from "lucide-react";
import type { HistoryMsg, MetaMsg, SnapshotMsg } from "../types";
import { cx, fmtMoney, fmtPrice, fmtSigned, pnlColor } from "../lib/format";
import type { TerminalApi } from "../hooks/useTerminal";

interface Props {
  snap: SnapshotMsg | null;
  meta: MetaMsg | null;
  history: HistoryMsg | null;
  send: TerminalApi["send"];
}

function Stat({
  label,
  sub,
  value,
  className,
}: {
  label: string;
  sub?: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col px-2 py-0.5 sm:min-w-[95px] sm:flex-initial xl:px-2.5">
      <span className="truncate text-[9px] font-semibold uppercase tracking-wider text-slate-400">{label}</span>
      <span
        className={cx("num whitespace-nowrap text-[11px] font-extrabold sm:text-xs xl:text-sm", className ?? "text-slate-100")}
      >
        {value}
      </span>
      {sub && <span className="truncate text-[9px] text-slate-500">{sub}</span>}
    </div>
  );
}

function HeaderImpl({ snap, meta, history, send }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const acc = snap?.account ?? {};
  const term = snap?.conn.terminal ?? {};
  const ccy = acc.currency ?? "USD";
  const connected = !!snap?.conn.mt5;
  const ai = snap?.ai;
  const digits = snap?.symbol_info.digits ?? 5;
  const lockActive = !!ai?.lock.active;
  const autoSymbol = meta?.settings.auto_select_symbol ?? true;

  const floating = snap?.day.floating ?? 0;
  const hasOpen = (snap?.positions.length ?? 0) > 0;
  const closedProfit = history?.summary?.net_total ?? snap?.day.net_closed ?? 0;
  const totalWithFloating = closedProfit + floating;
  const wins = history?.summary?.wins ?? snap?.day.trades_wins ?? 0;
  const totalTrades = history?.summary?.total_trades ?? snap?.day.trades_total ?? 0;

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };

  const toggleAI = () => {
    if (!ai) return;
    if (!ai.enabled) {
      const real = acc.trade_mode === "REAL";
      const ok = window.confirm(
        `${real ? "⚠️ CONTA REAL ⚠️\n\n" : ""}Ligar a IA AUTÔNOMA V2?\n\n` +
          (autoSymbol
            ? "O Radar Multi-Moedas da IA analisará todas as moedas disponíveis simultaneamente, escolherá a melhor oportunidade sozinha (avaliando corpo, rabo e próxima vela) e operará automaticamente no MT5."
            : `A IA operará em ${snap?.symbol} analisando corpo, rabo e próxima vela automaticamente no MT5.`),
      );
      if (!ok) return;
    }
    void run("ai", () => send("set_ai", { enabled: !ai.enabled }));
  };

  const toggleAutoSymbol = () => {
    void run("autosym", () => send("set_auto_symbol", { enabled: !autoSymbol }));
  };

  const panic = () => void run("panic", () => send("panic_close"));

  return (
    <header className="sticky top-0 z-30 flex flex-wrap items-center justify-between gap-2 border-b border-ink-700 bg-ink-900/95 px-2.5 py-1.5 backdrop-blur sm:px-3">
      {/* LOGO + STATUS MT5 + RADAR AUTOMÁTICO DE MOEDAS */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 pr-1">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-accent/15 text-accent">
            <Cpu size={16} />
          </div>
          <div className="leading-tight">
            <div className="text-xs font-extrabold tracking-wide text-white sm:text-sm">TRADER·IA</div>
            <div className="flex flex-wrap items-center gap-1 text-[9.5px] text-slate-400">
              {connected ? <Wifi size={10} className="text-bull" /> : <WifiOff size={10} className="text-bear" />}
              <span className={connected ? "font-semibold text-bull" : "font-semibold text-bear"}>
                {connected ? "MT5 ON" : "Offline"}
              </span>
              {acc.trade_mode && (
                <span
                  className={cx(
                    "rounded px-1 text-[8.5px] font-bold",
                    acc.trade_mode === "REAL" ? "bg-bear/20 text-bear" : "bg-accent/20 text-accent",
                  )}
                >
                  {acc.trade_mode}
                </span>
              )}
              <span className={term.trade_allowed ? "text-bull" : "text-warn"}>
                · Algo {term.trade_allowed ? "ON" : "OFF"}
              </span>
            </div>
          </div>
        </div>

        {/* PASSO 1: RADAR AUTOMÁTICO DE MOEDAS + MOEDA EM FOCO */}
        <div className="flex items-center gap-2 rounded border border-accent/40 bg-ink-850 px-2 py-1">
          <button
            onClick={toggleAutoSymbol}
            disabled={!connected || busy === "autosym"}
            title={
              autoSymbol
                ? "Radar Automático LIGADO: a IA escaneia todas as moedas sozinha e escolhe a melhor. Clique se quiser travar em 1 moeda."
                : "Modo Manual: a IA opera apenas a moeda escolhida ao lado. Clique para ativar o Radar Automático."
            }
            className={cx(
              "flex items-center gap-1 rounded px-2 py-1 text-[10px] font-extrabold transition",
              autoSymbol
                ? "bg-bull/20 text-bull ring-1 ring-bull/50 hover:bg-bull/30"
                : "bg-ink-700 text-slate-300 hover:bg-ink-600",
            )}
          >
            <Radar size={13} className={autoSymbol ? "animate-spin" : ""} style={{ animationDuration: "5s" }} />
            <span>{autoSymbol ? "IA ESCOLHE A MOEDA (AUTO)" : "MOEDA FIXA (MANUAL)"}</span>
          </button>

          <div className="flex items-center gap-1">
            <select
              className="cursor-pointer rounded border border-ink-600 bg-ink-800 px-1.5 py-0.5 text-xs font-bold text-white outline-none hover:border-accent"
              value={snap?.symbol ?? meta?.symbol ?? ""}
              onChange={(e) => void run("symbol", () => send("set_symbol", { symbol: e.target.value }))}
              disabled={!connected || busy === "symbol"}
              title="Moeda atualmente em foco no gráfico (no modo AUTO a IA troca automaticamente para a melhor)"
            >
              {(meta?.symbols ?? []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
              {snap?.symbol && !(meta?.symbols ?? []).some((s) => s.name === snap.symbol) && (
                <option value={snap.symbol}>{snap.symbol}</option>
              )}
            </select>
            <button
              className="rounded p-0.5 text-slate-400 hover:bg-ink-700 hover:text-white"
              title="Atualizar lista de ativos do MT5"
              onClick={() => void run("refresh", () => send("refresh_symbols"))}
            >
              <RefreshCw size={11} className={busy === "refresh" ? "animate-spin" : ""} />
            </button>
          </div>

          <div className="num hidden border-l border-ink-700 pl-2 text-[10px] leading-tight sm:block">
            <div>
              <span className="text-slate-500">Venda: </span>
              <span className="font-semibold text-bear">{fmtPrice(snap?.tick.bid, digits)}</span>
            </div>
            <div>
              <span className="text-slate-500">Compra: </span>
              <span className="font-semibold text-bull">{fmtPrice(snap?.tick.ask, digits)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* PLACAR FINANCEIRO SIMPLES E DIRETO */}
      <div className="flex w-full items-center divide-x divide-ink-700 rounded border border-ink-700 bg-ink-850 py-1 sm:w-auto">
        <Stat label="Saldo Total" sub={`Livre: ${fmtMoney(acc.margin_free, ccy)}`} value={fmtMoney(acc.equity, ccy)} />
        <Stat
          label={hasOpen ? (floating >= 0 ? "🟢 Ganhando Agora" : "🔴 Perdendo Agora") : "Operação Atual"}
          sub={hasOpen ? "Ao vivo" : "Nenhuma aberta"}
          value={hasOpen ? fmtSigned(floating, ccy) : fmtSigned(0, ccy)}
          className={hasOpen ? pnlColor(floating) : "text-slate-400"}
        />
        <Stat
          label="Lucro Acumulado"
          sub={`${totalTrades} op. (${wins} ganha${wins === 1 ? "" : "s"})`}
          value={fmtSigned(totalWithFloating, ccy)}
          className={pnlColor(totalWithFloating)}
        />
      </div>

      {/* PASSO 4: BOTÕES DE AÇÃO PRINCIPAL */}
      <div className="flex w-full items-center gap-1.5 sm:w-auto">
        <button
          onClick={toggleAI}
          disabled={!connected || busy === "ai" || (lockActive && !ai?.enabled)}
          className={cx(
            "flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-extrabold tracking-wide transition disabled:cursor-not-allowed disabled:opacity-50 sm:flex-initial",
            ai?.enabled
              ? "animate-pulseRing bg-bull text-ink-950 hover:bg-bull/90"
              : "border-2 border-bull bg-bull/15 text-bull hover:bg-bull/25",
          )}
          title={lockActive ? `Trava diária ativa: ${ai?.lock.reason}` : "Clique para ligar ou pausar a IA autônoma"}
        >
          {ai?.enabled ? <Bot size={16} /> : <Power size={16} />}
          <div className="text-left leading-tight">
            <div className="text-[8.5px] uppercase opacity-80">Passo 4 · Piloto Automático</div>
            <div className="text-[11px]">{ai?.enabled ? "IA LIGADA (PAUSAR)" : "LIGAR IA AUTÔNOMA"}</div>
          </div>
          {ai?.enabled && <Zap size={12} />}
        </button>

        <button
          onClick={panic}
          disabled={!connected || busy === "panic"}
          className="flex items-center justify-center gap-1.5 rounded-md bg-bear px-2.5 py-1.5 text-xs font-extrabold tracking-wide text-white hover:bg-bear/85 disabled:opacity-50"
          title="Fecha imediatamente qualquer operação aberta e desliga a IA"
        >
          <OctagonX size={16} />
          <div className="text-left leading-tight">
            <div className="text-[8.5px] uppercase opacity-80">Emergência</div>
            <div className="text-[11px]">ZERAR AGORA</div>
          </div>
        </button>
      </div>
    </header>
  );
}

export const Header = memo(HeaderImpl);
