import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { useMemo } from "react";
import { BottomPanel } from "./components/BottomPanel";
import { BrainPanel } from "./components/BrainPanel";
import { ConnectionOverlay } from "./components/ConnectionOverlay";
import { Header } from "./components/Header";
import { LiveTradeBanner } from "./components/LiveTradeBanner";
import { ModeSelector } from "./components/ModeSelector";
import { PriceChart } from "./components/PriceChart";
import { RiskPanel } from "./components/RiskPanel";
import { useTerminal } from "./hooks/useTerminal";
import { cx } from "./lib/format";
import type { Analysis, Bar, Position } from "./types";

const EMPTY_BARS: Bar[] = [];
const EMPTY_POS: Position[] = [];

export default function App() {
  const { wsStatus, wsUrl, meta, snap, series, history, logs, toasts, send } = useTerminal();

  const modeKey = snap?.mode ?? meta?.settings.mode;
  const mode = meta?.modes.find((m) => m.key === modeKey);
  const digits = snap?.symbol_info.digits ?? series?.digits ?? 5;
  const currency = snap?.account.currency ?? "USD";
  const positions = snap?.positions ?? EMPTY_POS;
  const aiHasPosition = positions.some((p) => p.is_ai);
  const analysis = useMemo<Analysis | null>(
    () => (snap?.analysis && "regime" in snap.analysis ? (snap.analysis as Analysis) : null),
    [snap?.analysis],
  );
  const softError = snap?.conn.mt5 && snap.conn.error ? snap.conn.error.message : null;
  const serverOffsetSec = snap?.timing?.server_offset_s ?? series?.server_offset_s ?? 0;

  return (
    <div className="flex min-h-screen w-full flex-col overflow-x-hidden bg-ink-950">
      <Header snap={snap} meta={meta} history={history} send={send} />

      {softError && (
        <div className="flex items-center gap-2 border-b border-warn/40 bg-warn/10 px-3 py-1 text-xs text-warn">
          <AlertTriangle size={14} /> {softError}
        </div>
      )}

      <main className="mx-auto flex w-full max-w-[1920px] flex-1 flex-col gap-2.5 p-2 sm:p-3">
        {/* LINHA 1: SELETOR DE MODO (PASSO 2) + LIMITES DE PROTEÇÃO DIÁRIA (PASSO 3) */}
        <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-12">
          <div className="lg:col-span-7 xl:col-span-8">
            <ModeSelector
              meta={meta}
              active={modeKey}
              send={send}
              locked={aiHasPosition}
              ai={snap?.ai}
              analysis={analysis}
              radar={snap?.radar}
            />
          </div>
          <div className="lg:col-span-5 xl:col-span-4">
            <RiskPanel
              meta={meta}
              mode={modeKey}
              currency={currency}
              spreadNow={snap?.tick.spread_points}
              lock={snap?.ai.lock}
              guard={snap?.risk_guard}
              day={snap?.day}
              send={send}
            />
          </div>
        </div>

        {/* LINHA 2: PAINEL DE DESTAQUE DA OPERAÇÃO EM ANDAMENTO (OU STATUS DA IA) */}
        <LiveTradeBanner
          positions={positions}
          ai={snap?.ai}
          analysis={analysis}
          mode={mode}
          timing={snap?.timing}
          symbol={snap?.symbol ?? null}
          digits={digits}
          currency={currency}
          send={send}
        />

        {/* LINHA 3: WORKSPACE PRINCIPAL (GRÁFICO + HISTÓRICO À ESQUERDA | VISÃO DA IA À DIREITA) */}
        <div className="grid grid-cols-1 items-start gap-2.5 lg:grid-cols-12">
          <div className="flex min-w-0 flex-col gap-2.5 lg:col-span-7 xl:col-span-8">
            <PriceChart
              series={series}
              liveBars={snap?.bars ?? EMPTY_BARS}
              liveSeriesId={snap?.series_id}
              positions={positions}
              digits={digits}
              serverOffsetSec={serverOffsetSec}
              timing={snap?.timing}
            />

            <BottomPanel
              positions={positions}
              history={history}
              digits={digits}
              currency={currency}
              day={snap?.day}
            />
          </div>

          <div className="min-w-0 lg:col-span-5 xl:col-span-4">
            <BrainPanel
              ai={snap?.ai}
              analysis={analysis}
              mode={mode}
              logs={logs}
              radar={snap?.radar}
              activeSymbol={snap?.symbol ?? null}
              autoSymbol={meta?.settings.auto_select_symbol ?? true}
              quant={snap?.quant}
              send={send}
            />
          </div>
        </div>
      </main>

      <div className="pointer-events-none fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "flex items-center gap-2 rounded border px-3 py-2 text-xs shadow-lg",
              t.ok ? "border-bull/50 bg-ink-900 text-bull" : "border-bear/50 bg-ink-900 text-bear",
            )}
          >
            {t.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />} {t.message}
          </div>
        ))}
      </div>

      <ConnectionOverlay wsStatus={wsStatus} wsUrl={wsUrl} snap={snap} />
    </div>
  );
}
