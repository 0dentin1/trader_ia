import { memo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Bot,
  Clock,
  Lock,
  OctagonX,
  PlayCircle,
  ShieldCheck,
  Target,
  Timer,
  Zap,
} from "lucide-react";
import type { AIStatus, Analysis, ModeConfig, Position, TimingInfo } from "../types";
import type { TerminalApi } from "../hooks/useTerminal";
import { cx, fmtDuration, fmtLocalDateTime, fmtPrice, fmtSigned } from "../lib/format";

interface Props {
  positions: Position[];
  ai: AIStatus | undefined;
  analysis: Analysis | null;
  mode: ModeConfig | undefined;
  timing: TimingInfo | undefined;
  symbol: string | null;
  digits: number;
  currency: string;
  send: TerminalApi["send"];
}

function LiveTradeBannerImpl({
  positions,
  ai,
  analysis,
  mode,
  timing,
  symbol,
  digits,
  currency,
  send,
}: Props) {
  const [closingTicket, setClosingTicket] = useState<number | "ALL" | null>(null);

  const closePosition = async (ticket?: number) => {
    setClosingTicket(ticket ?? "ALL");
    try {
      await send("panic_close", ticket ? { ticket } : {});
    } finally {
      setClosingTicket(null);
    }
  };

  if (positions.length > 0) {
    return (
      <div className="flex flex-col gap-2">
        {positions.map((p) => {
          const net = p.net_profit ?? p.profit + p.swap;
          const winning = net >= 0;
          const isBuy = p.type === "BUY";
          const progress = Math.max(0, Math.min(100, p.progress_pct ?? 0));
          const pDigits = p.digits ?? (p.symbol === symbol ? digits : 5);
          const maxDur = p.max_duration_s ?? 75;
          const remS = p.remaining_s ?? Math.max(0, maxDur - (p.elapsed_s ?? 0));
          const hzLabel = p.horizon_label ?? "⚡ Tiro de 1 Vela (60s)";

          return (
            <div
              key={p.ticket}
              className={cx(
                "rounded-md border-2 p-3 shadow-lg transition",
                winning
                  ? "border-bull/80 bg-gradient-to-r from-bull/15 via-ink-900 to-ink-900"
                  : "border-bear/80 bg-gradient-to-r from-bear/15 via-ink-900 to-ink-900",
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                {/* 1. GANHANDO OU PERDENDO AGORA */}
                <div className="flex items-center gap-3">
                  <div
                    className={cx(
                      "flex h-12 w-12 items-center justify-center rounded-lg font-bold text-ink-950",
                      winning ? "bg-bull" : "bg-bear text-white",
                    )}
                  >
                    {isBuy ? <ArrowUpRight size={28} /> : <ArrowDownRight size={28} />}
                  </div>
                  <div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={cx(
                          "rounded px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-wider",
                          winning ? "bg-bull text-ink-950" : "bg-bear text-white",
                        )}
                      >
                        {winning ? "🟢 GANHANDO AGORA" : "🔴 OPERAÇÃO EM OSCILAÇÃO"}
                      </span>
                      <span className="rounded bg-amber-400/20 px-2 py-0.5 text-[11px] font-bold text-amber-300">
                        {hzLabel}
                      </span>
                      <span className="rounded bg-ink-800 px-2 py-0.5 text-[11px] font-semibold text-slate-300">
                        {p.is_ai ? `🧠 Cérebro ${p.symbol}` : "👤 Manual"}
                      </span>
                    </div>
                    <div className={cx("num mt-0.5 text-2xl font-extrabold", winning ? "text-bull" : "text-bear")}>
                      {fmtSigned(net, currency)}
                    </div>
                  </div>
                </div>

                {/* 2. DADOS DA ENTRADA */}
                <div className="rounded border border-ink-700 bg-ink-950/80 px-3 py-2 text-xs">
                  <div className="font-bold text-white">
                    {isBuy ? "COMPRA (Alta)" : "VENDA (Queda)"} · <b className="text-accent">{p.symbol}</b> ·{" "}
                    <span className="num text-slate-200">{p.volume} lote(s)</span>
                  </div>
                  <div className="num mt-1 flex flex-wrap items-center gap-3 text-[11px] text-slate-300">
                    <span>
                      Início: <b className="text-white">{fmtLocalDateTime(p.open_time_local, false)}</b>
                    </span>
                    <span>
                      Entrada: <b className="text-white">{fmtPrice(p.price_open, pDigits)}</b>
                    </span>
                    <span>
                      Agora:{" "}
                      <b className={winning ? "text-bull" : "text-bear"}>{fmtPrice(p.price_current, pDigits)}</b>
                    </span>
                  </div>
                </div>

                {/* 3. RELÓGIO DE VALIDADE DA PREVISÃO (ATÉ QUANDO O SINAL VALE) */}
                <div className="rounded border border-ink-700 bg-ink-950/80 px-3 py-2 text-xs">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="flex items-center gap-1 font-semibold text-amber-300">
                      <Timer size={14} /> Tempo aberta:{" "}
                      <b className="num text-sm text-white">{fmtDuration(p.elapsed_s)}</b>
                    </span>
                    <span
                      className={cx(
                        "flex items-center gap-1 rounded px-2 py-0.5 font-extrabold",
                        remS > 15 ? "bg-accent/15 text-accent" : "bg-amber-400/20 text-amber-300",
                      )}
                    >
                      <Zap size={12} />
                      {remS > 0
                        ? `Validade da vela: ${fmtDuration(remS)} restantes`
                        : "Janela concluída · colhendo na melhor saída"}
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] text-slate-400">
                    Horizonte previsto pela IA: <b className="text-slate-200">{fmtDuration(maxDur)}</b> (fecha sozinha no lucro ao fim da janela ou na meta)
                  </div>
                </div>

                {/* 4. BOTÃO PARA ENCERRAR */}
                <button
                  onClick={() => void closePosition(p.ticket)}
                  disabled={closingTicket !== null}
                  className="flex items-center gap-2 rounded-md bg-bear px-4 py-3 text-xs font-extrabold uppercase tracking-wide text-white shadow hover:bg-bear/85 disabled:opacity-50"
                >
                  <OctagonX size={18} />
                  <div className="text-left leading-tight">
                    <div>Encerrar {p.symbol} Agora</div>
                    <div className="text-[10px] font-normal opacity-90">
                      {winning ? "Guardar lucro imediatamente" : "Fechar a mercado agora"}
                    </div>
                  </div>
                </button>
              </div>

              {/* BARRA DE CAMINHO ATÉ TERMINAR (STOP LOSS <-> PREÇO ATUAL <-> META DE LUCRO) */}
              <div className="mt-2.5 rounded border border-ink-700 bg-ink-950/90 px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                  <div className="flex items-center gap-1.5">
                    {p.be_protected ? (
                      <span className="flex items-center gap-1 rounded bg-bull/20 px-2 py-0.5 font-bold text-bull">
                        <ShieldCheck size={13} /> Stop no Lucro / Zero a Zero ({fmtPrice(p.sl, pDigits)}) ·{" "}
                        {p.sl_profit !== null && p.sl_profit !== undefined ? fmtSigned(p.sl_profit, currency) : ""}
                      </span>
                    ) : (
                      <span className="text-bear">
                        🛑 Limite de Proteção (Stop): <b className="num">{fmtPrice(p.sl, pDigits)}</b>{" "}
                        {p.sl_profit !== null && p.sl_profit !== undefined
                          ? `(${fmtSigned(p.sl_profit, currency)})`
                          : ""}
                      </span>
                    )}
                  </div>

                  <div className="font-semibold text-slate-300">
                    Caminho até a Meta da Vela: <b className="num text-white">{progress.toFixed(0)}%</b> concluído
                  </div>

                  <div className="flex items-center gap-1 text-bull">
                    <Target size={13} /> 🎯 Alvo Rápido (Take Profit): <b className="num">{fmtPrice(p.tp, pDigits)}</b>{" "}
                    {p.tp_profit !== null && p.tp_profit !== undefined
                      ? `(ganha ${fmtSigned(p.tp_profit, currency)})`
                      : ""}
                  </div>
                </div>

                <div className="relative mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-ink-800">
                  <div
                    className={cx("h-full transition-all duration-300", winning ? "bg-bull" : "bg-warn")}
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  // SEM OPERAÇÃO ABERTA NO MOMENTO
  const score = analysis?.score ?? 0;
  const minScore = mode?.min_score ?? 85;
  const hz = analysis?.horizon;
  const dirLabel =
    analysis?.direction === "BUY" ? "COMPRA (Alta)" : analysis?.direction === "SELL" ? "VENDA (Baixa)" : "Aguardando";

  return (
    <div
      className={cx(
        "flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2.5 text-xs",
        ai?.enabled
          ? "border-accent/60 bg-gradient-to-r from-accent/15 via-ink-900 to-ink-900"
          : "border-ink-700 bg-ink-900",
      )}
    >
      <div className="flex items-center gap-2.5">
        {ai?.enabled ? (
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-bull/20 text-bull">
            <Bot size={20} />
          </div>
        ) : ai?.lock.active ? (
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-bear/20 text-bear">
            <Lock size={20} />
          </div>
        ) : (
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-ink-800 text-slate-400">
            <PlayCircle size={20} />
          </div>
        )}
        <div>
          <div className="font-bold text-white">
            {ai?.enabled
              ? `🧠 MEGA BRAIN ATIVO — ${ai.active_brains ?? 8} Cérebros escaneando todas as moedas e tempos (M1/M2/M5)`
              : ai?.lock.active
                ? `🔒 Trava Diária Acionada — ${ai.lock.reason}`
                : "⏸️ Mega Brain em Modo Leitura (IA Desligada)"}
          </div>
          <div className="mt-0.5 text-[11px] text-slate-400">
            {ai?.enabled ? (
              analysis?.study_block ? (
                <span>
                  Em <b>{symbol}</b>: {analysis.study_block} · Os outros cérebros seguem vigiando as demais moedas em paralelo!
                </span>
              ) : (
                <span>
                  Em <b>{symbol}</b>: <b className="text-slate-200">{dirLabel}</b> ({score.toFixed(0)}%) · Horizonte:{" "}
                  <b className="text-amber-300">{hz?.label ?? "⚡ 1 Vela (60s)"}</b> · Próx. vela:{" "}
                  <b className="num text-bull">
                    {analysis?.candle
                      ? `${Math.max(analysis.candle.prob_up, analysis.candle.prob_down).toFixed(0)}%`
                      : "--"}
                  </b>{" "}
                  (dispara apenas em oportunidade Imperdível ≥ <b className="num text-bull">{minScore}%</b>).
                </span>
              )
            ) : (
              <span>
                O <b>Mega Brain V3</b> analisa sozinho <b>qual moeda</b>, <b>qual direção</b> e <b>por quanto tempo</b> (30s, 1 min ou 5 min) operar. Confira seu Limite Diário e clique em{" "}
                <b className="text-bull">LIGAR IA AUTÔNOMA</b>.
              </span>
            )}
          </div>
        </div>
      </div>

      {timing && (
        <div className="num flex items-center gap-2 rounded border border-ink-700 bg-ink-950 px-3 py-1.5 text-[11px] text-slate-300">
          <Clock size={13} className="text-accent" />
          <span>
            Vela <b>{timing.tf}</b> fecha em:{" "}
            <b className="text-white">{fmtDuration(timing.bar_remaining_s)}</b>
          </span>
        </div>
      )}
    </div>
  );
}

export const LiveTradeBanner = memo(LiveTradeBannerImpl);
