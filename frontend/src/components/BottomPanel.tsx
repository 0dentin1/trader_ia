import { memo, useEffect, useState } from "react";
import { Award, CheckCircle2, Clock, History, Layers, TrendingDown, TrendingUp, XCircle } from "lucide-react";
import type { CompletedTrade, HistoryMsg, Position } from "../types";
import {
  cx,
  fmtDuration,
  fmtLocalDateTime,
  fmtPrice,
  fmtSigned,
  pnlColor,
} from "../lib/format";

interface Props {
  positions: Position[];
  history: HistoryMsg | null;
  digits: number;
  currency: string;
}

const TH = "whitespace-nowrap px-2.5 py-1.5 text-left text-[10px] font-bold uppercase tracking-wider text-slate-400";
const TD = "px-2.5 py-2 text-[11px] align-middle";

function BottomPanelImpl({ positions, history, digits, currency }: Props) {
  const [tab, setTab] = useState<"hist" | "pos">("hist");
  const hasOpen = positions.length > 0;

  useEffect(() => {
    if (hasOpen) setTab("pos");
  }, [hasOpen]);

  const floating = positions.reduce((s, p) => s + (p.net_profit ?? p.profit + p.swap), 0);
  const trades: CompletedTrade[] = history?.trades ?? [];
  const summary = history?.summary ?? {
    total_trades: trades.length,
    wins: trades.filter((t) => t.won).length,
    losses: trades.filter((t) => !t.won).length,
    win_rate: trades.length ? (100 * trades.filter((t) => t.won).length) / trades.length : 0,
    net_total: history?.realized ?? 0,
    net_today: history?.realized ?? 0,
    avg_duration_s: 0,
  };

  return (
    <div className="panel flex w-full flex-col overflow-hidden">
      {/* CABEÇALHO DE ABAS + RESUMO FINANCEIRO */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-700 bg-ink-850 px-2.5 py-2 text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setTab("hist")}
            className={cx(
              "flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs font-extrabold transition",
              tab === "hist"
                ? "bg-accent text-white shadow"
                : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
            )}
          >
            <History size={13} />
            Histórico de Operações ({summary.total_trades})
          </button>

          <button
            onClick={() => setTab("pos")}
            className={cx(
              "flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs font-extrabold transition",
              tab === "pos"
                ? "bg-bull text-ink-950 shadow"
                : hasOpen
                  ? "border border-bull bg-bull/15 text-bull"
                  : "bg-ink-800 text-slate-300 hover:bg-ink-700 hover:text-white",
            )}
          >
            <Layers size={13} />
            Operação em Andamento ({positions.length})
            {hasOpen && <span className="num ml-1 font-extrabold">({fmtSigned(floating, currency)})</span>}
          </button>
        </div>

        {/* PLACAR RESUMO DAS OPERAÇÕES */}
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <div className="flex items-center gap-1 rounded bg-ink-900 px-2 py-1">
            <Award size={12} className="text-amber-400" />
            <span className="text-slate-400">Acertos:</span>
            <b className="num text-white">{summary.win_rate.toFixed(0)}%</b>
            <span className="text-slate-500">
              ({summary.wins}V / {summary.losses}D)
            </span>
          </div>

          {summary.avg_duration_s > 0 && (
            <div className="hidden items-center gap-1 rounded bg-ink-900 px-2 py-1 sm:flex">
              <Clock size={12} className="text-accent" />
              <span className="text-slate-400">Tempo Médio:</span>
              <b className="num text-slate-200">{fmtDuration(summary.avg_duration_s)}</b>
            </div>
          )}

          <div className="flex items-center gap-1.5 rounded border border-ink-700 bg-ink-900 px-2.5 py-1">
            <span className="text-slate-400">Lucro Fechado:</span>
            <b className={cx("num text-xs font-extrabold", pnlColor(summary.net_total))}>
              {fmtSigned(summary.net_total, currency)}
            </b>
          </div>
        </div>
      </div>

      {/* CONTEÚDO: ABA DE HISTÓRICO */}
      {tab === "hist" ? (
        <>
          {/* VISÃO NOTEBOOK / DESKTOP (4 COLUNAS ENCAIXADAS — 100% VISÍVEL SEM BARRA HORIZONTAL) */}
          <div className="hidden max-h-[290px] overflow-x-auto overflow-y-auto md:block">
            <table className="num w-full border-collapse">
              <thead className="sticky top-0 z-10 border-b border-ink-700 bg-ink-900">
                <tr>
                  <th className={TH}>Resultado Final</th>
                  <th className={TH}>Ativo, Direção & Quem Operou</th>
                  <th className={TH}>Horário (Início ➔ Fim) & Duração</th>
                  <th className={TH}>Preços (Entrada ➔ Saída) & Término</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-8 text-center font-sans text-xs text-slate-500">
                      Nenhuma operação concluída encontrada no histórico da conta.
                    </td>
                  </tr>
                )}
                {trades.map((t) => (
                  <tr
                    key={t.position_id}
                    className={cx(
                      "border-t border-ink-800 transition hover:bg-ink-850",
                      t.won ? "bg-bull/[0.03]" : "bg-bear/[0.03]",
                    )}
                  >
                    {/* 1. RESULTADO */}
                    <td className={TD}>
                      <div className="flex flex-col gap-0.5">
                        <span
                          className={cx(
                            "inline-flex w-fit items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-extrabold",
                            t.won ? "bg-bull/20 text-bull" : "bg-bear/20 text-bear",
                          )}
                        >
                          {t.won ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
                          {t.won ? "GANHOU" : "PERDEU"}
                        </span>
                        <span className={cx("text-xs font-extrabold", t.won ? "text-bull" : "text-bear")}>
                          {fmtSigned(t.net_profit, currency)}
                        </span>
                      </div>
                    </td>

                    {/* 2. ATIVO, DIREÇÃO E QUEM OPEROU */}
                    <td className={TD}>
                      <div className="flex items-center gap-1.5">
                        <span
                          className={cx(
                            "inline-flex items-center gap-0.5 font-bold",
                            t.side === "BUY" ? "text-bull" : "text-bear",
                          )}
                        >
                          {t.side === "BUY" ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                          {t.side === "BUY" ? "COMPRA" : "VENDA"}
                        </span>
                        <b className="text-white">{t.symbol}</b>
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-[10px]">
                        <span
                          className={cx(
                            "rounded px-1.5 py-0.5 font-sans font-bold",
                            t.is_ai ? "bg-accent/20 text-accent" : "bg-ink-700 text-slate-300",
                          )}
                        >
                          {t.is_ai ? `🤖 IA${t.mode ? ` (${t.mode})` : ""}` : "👤 Manual"}
                        </span>
                        <span className="text-slate-400">
                          · <b className="text-slate-200">{t.volume}</b> lote(s)
                        </span>
                      </div>
                    </td>

                    {/* 3. HORÁRIO E DURAÇÃO */}
                    <td className={TD}>
                      <div className="text-slate-200">
                        <span>{fmtLocalDateTime(t.open_time_local)}</span>
                        <span className="mx-1 text-slate-500">➔</span>
                        <span>{fmtLocalDateTime(t.close_time_local, false)}</span>
                      </div>
                      <div className="mt-0.5">
                        <span className="inline-flex items-center gap-1 rounded bg-ink-800 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                          <Clock size={10} /> Durou {fmtDuration(t.duration_s)}
                        </span>
                      </div>
                    </td>

                    {/* 4. PREÇOS E MOTIVO DE SAÍDA */}
                    <td className={TD}>
                      <div className="text-slate-300">
                        {fmtPrice(t.entry_price, digits)} <span className="text-slate-500">➔</span>{" "}
                        <b className="text-white">{fmtPrice(t.exit_price, digits)}</b>
                      </div>
                      <div className="mt-0.5 font-sans text-[10px] text-slate-400">{t.exit_reason}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* VISÃO CELULAR / TELAS PEQUENAS (CARDS COMPACTOS E FÁCEIS DE LER) */}
          <div className="divide-y divide-ink-800 md:hidden">
            {trades.length === 0 && (
              <div className="px-3 py-6 text-center text-xs text-slate-500">
                Nenhuma operação concluída encontrada no histórico da conta.
              </div>
            )}
            {trades.map((t) => (
              <div key={t.position_id} className={cx("p-3 text-xs", t.won ? "bg-bull/[0.03]" : "bg-bear/[0.03]")}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={cx(
                        "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10.5px] font-extrabold",
                        t.won ? "bg-bull/20 text-bull" : "bg-bear/20 text-bear",
                      )}
                    >
                      {t.won ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
                      {t.won ? "GANHOU" : "PERDEU"}
                    </span>
                    <span className={cx("font-bold", t.side === "BUY" ? "text-bull" : "text-bear")}>
                      {t.side === "BUY" ? "COMPRA" : "VENDA"}
                    </span>
                    <b className="text-white">{t.symbol}</b>
                  </div>
                  <span className={cx("num text-sm font-extrabold", t.won ? "text-bull" : "text-bear")}>
                    {fmtSigned(t.net_profit, currency)}
                  </span>
                </div>

                <div className="num mt-2 grid grid-cols-2 gap-1.5 text-[11px] text-slate-300">
                  <div>
                    <span className="text-slate-500">Horário: </span>
                    {fmtLocalDateTime(t.open_time_local)} ➔ {fmtLocalDateTime(t.close_time_local, false)}
                  </div>
                  <div>
                    <span className="text-slate-500">Duração: </span>
                    <b className="text-amber-300">{fmtDuration(t.duration_s)}</b>
                  </div>
                  <div>
                    <span className="text-slate-500">Preço: </span>
                    {fmtPrice(t.entry_price, digits)} ➔ <b className="text-white">{fmtPrice(t.exit_price, digits)}</b>
                  </div>
                  <div>
                    <span className="text-slate-500">Lotes: </span>
                    <b className="text-white">{t.volume}</b> ·{" "}
                    <span className="text-accent">{t.is_ai ? `🤖 IA` : "👤 Manual"}</span>
                  </div>
                </div>
                <div className="mt-1 text-[11px] text-slate-400">Saída: {t.exit_reason}</div>
              </div>
            ))}
          </div>
        </>
      ) : (
        /* CONTEÚDO: ABA DE OPERAÇÃO EM ANDAMENTO */
        <div className="max-h-[290px] overflow-x-auto overflow-y-auto">
          <table className="num w-full border-collapse">
            <thead className="sticky top-0 z-10 border-b border-ink-700 bg-ink-900">
              <tr>
                <th className={TH}>Status Agora</th>
                <th className={TH}>Direção & Ativo</th>
                <th className={TH}>Início & Tempo Aberta</th>
                <th className={TH}>Entrada ➔ Atual</th>
                <th className={TH}>Stop / Meta (TP)</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center font-sans text-xs text-slate-500">
                    Nenhuma operação aberta no momento. Clique na aba{" "}
                    <b className="text-accent">Histórico de Operações ({summary.total_trades})</b> acima para ver todas
                    as operações já concluídas e o lucro de cada uma.
                  </td>
                </tr>
              )}
              {positions.map((p) => {
                const net = p.net_profit ?? p.profit + p.swap;
                const winning = net >= 0;
                return (
                  <tr key={p.ticket} className="border-t border-ink-800 hover:bg-ink-850">
                    <td className={TD}>
                      <div className="flex flex-col gap-0.5">
                        <span
                          className={cx(
                            "w-fit rounded px-1.5 py-0.5 text-[10px] font-extrabold",
                            winning ? "bg-bull text-ink-950" : "bg-bear text-white",
                          )}
                        >
                          {winning ? "GANHANDO" : "PERDENDO"}
                        </span>
                        <span className={cx("text-xs font-extrabold", winning ? "text-bull" : "text-bear")}>
                          {fmtSigned(net, currency)}
                        </span>
                      </div>
                    </td>
                    <td className={TD}>
                      <div>
                        <span className={cx("font-bold", p.type === "BUY" ? "text-bull" : "text-bear")}>
                          {p.type === "BUY" ? "COMPRA" : "VENDA"}
                        </span>{" "}
                        · <b className="text-white">{p.symbol}</b>
                      </div>
                      <div className="text-[10px] text-slate-400">{p.volume} lote(s)</div>
                    </td>
                    <td className={TD}>
                      <div className="text-slate-200">{fmtLocalDateTime(p.open_time_local)}</div>
                      <div className="mt-0.5 text-[10px] font-semibold text-amber-300">
                        ⏱️ {fmtDuration(p.elapsed_s)} ({(p.progress_pct ?? 0).toFixed(0)}% da meta)
                      </div>
                    </td>
                    <td className={TD}>
                      {fmtPrice(p.price_open, digits)} ➔ <b className="text-white">{fmtPrice(p.price_current, digits)}</b>
                    </td>
                    <td className={TD}>
                      <div className={cx("text-[10.5px]", p.be_protected ? "font-bold text-bull" : "text-bear")}>
                        SL: {fmtPrice(p.sl, digits)}
                      </div>
                      <div className="text-[10.5px] font-bold text-bull">TP: {fmtPrice(p.tp, digits)}</div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export const BottomPanel = memo(BottomPanelImpl);
