import { memo, useEffect, useMemo, useRef } from "react";
import { Clock, LineChart } from "lucide-react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Bar, Position, SeriesMsg, TimingInfo } from "../types";
import { fmtDuration } from "../lib/format";

interface Props {
  series: SeriesMsg | null;
  liveBars: Bar[];
  liveSeriesId: string | undefined;
  positions: Position[];
  digits: number;
  serverOffsetSec?: number;
  timing?: TimingInfo;
}

type LineKey = "vwap" | "vwap_up1" | "vwap_dn1" | "vwap_up2" | "vwap_dn2" | "ema9" | "ema21" | "ema200";

const LINES: { key: LineKey; color: string; width: 1 | 2; style: LineStyle; title: string }[] = [
  { key: "vwap", color: "#e2b93b", width: 2, style: LineStyle.Solid, title: "VWAP" },
  { key: "vwap_up1", color: "rgba(226,185,59,0.45)", width: 1, style: LineStyle.Dashed, title: "+1σ" },
  { key: "vwap_dn1", color: "rgba(226,185,59,0.45)", width: 1, style: LineStyle.Dashed, title: "-1σ" },
  { key: "vwap_up2", color: "rgba(226,185,59,0.25)", width: 1, style: LineStyle.Dotted, title: "+2σ" },
  { key: "vwap_dn2", color: "rgba(226,185,59,0.25)", width: 1, style: LineStyle.Dotted, title: "-2σ" },
  { key: "ema9", color: "#22d3ee", width: 1, style: LineStyle.Solid, title: "EMA9" },
  { key: "ema21", color: "#a78bfa", width: 1, style: LineStyle.Solid, title: "EMA21" },
  { key: "ema200", color: "#f97316", width: 2, style: LineStyle.Solid, title: "EMA200" },
];

const BROWSER_TZ_OFFSET_S = new Date().getTimezoneOffset() * 60;
const toChartTime = (barTime: number, serverOffsetSec: number): UTCTimestamp =>
  (barTime - serverOffsetSec - BROWSER_TZ_OFFSET_S) as UTCTimestamp;

function PriceChartImpl({
  series,
  liveBars,
  liveSeriesId,
  positions,
  digits,
  serverOffsetSec = 0,
  timing,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lineRefs = useRef<Partial<Record<LineKey, ISeriesApi<"Line">>>>({});
  const priceLines = useRef<IPriceLine[]>([]);
  const loadedId = useRef<string>("");
  const lastTime = useRef<number>(0);

  const offset = series?.server_offset_s ?? serverOffsetSec;

  // Criação do gráfico (uma vez)
  useEffect(() => {
    if (!boxRef.current) return;
    const chart = createChart(boxRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0a0e15" },
        textColor: "#8b98ad",
        fontSize: 11,
      },
      grid: { vertLines: { color: "#121924" }, horzLines: { color: "#121924" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#1a2331" },
      timeScale: { borderColor: "#1a2331", timeVisible: true, secondsVisible: false, rightOffset: 6 },
    });
    const candle = chart.addCandlestickSeries({
      upColor: "#16c784",
      downColor: "#ea3943",
      borderUpColor: "#16c784",
      borderDownColor: "#ea3943",
      wickUpColor: "#16c784",
      wickDownColor: "#ea3943",
    });
    const vol = chart.addHistogramSeries({
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const lines: Partial<Record<LineKey, ISeriesApi<"Line">>> = {};
    for (const l of LINES) {
      lines[l.key] = chart.addLineSeries({
        color: l.color,
        lineWidth: l.width,
        lineStyle: l.style,
        priceLineVisible: false,
        lastValueVisible: l.key === "vwap" || l.key.startsWith("ema"),
        crosshairMarkerVisible: false,
        title: l.key.startsWith("vwap_") ? "" : l.title,
      });
    }
    chartRef.current = chart;
    candleRef.current = candle;
    volRef.current = vol;
    lineRefs.current = lines;
    return () => {
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volRef.current = null;
      lineRefs.current = {};
      priceLines.current = [];
      loadedId.current = "";
    };
  }, []);

  // Precisão de preço do ativo
  useEffect(() => {
    const fmt = { type: "price" as const, precision: digits, minMove: 1 / 10 ** digits };
    candleRef.current?.applyOptions({ priceFormat: fmt });
    Object.values(lineRefs.current).forEach((s) => s?.applyOptions({ priceFormat: fmt }));
  }, [digits]);

  // Série completa (troca de ativo/timeframe ou reconexão)
  useEffect(() => {
    const candle = candleRef.current;
    const vol = volRef.current;
    if (!series || !candle || !vol) return;
    const bars = series.bars;
    candle.setData(
      bars.map((b) => ({
        time: toChartTime(b.time, offset),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    vol.setData(
      bars.map((b) => ({
        time: toChartTime(b.time, offset),
        value: b.vol ?? 0,
        color: b.close >= b.open ? "rgba(22,199,132,0.35)" : "rgba(234,57,67,0.35)",
      })),
    );
    for (const l of LINES) {
      const s = lineRefs.current[l.key];
      if (!s) continue;
      s.setData(
        bars
          .filter((b) => b[l.key] !== null)
          .map((b) => ({ time: toChartTime(b.time, offset), value: b[l.key] as number })),
      );
    }
    loadedId.current = series.series_id;
    lastTime.current = bars.length ? bars[bars.length - 1].time : 0;
    chartRef.current?.timeScale().scrollToRealTime();
  }, [series, offset]);

  // Atualização ao vivo (últimas 2 velas a cada snapshot)
  useEffect(() => {
    const candle = candleRef.current;
    const vol = volRef.current;
    if (!candle || !vol || !liveSeriesId || liveSeriesId !== loadedId.current) return;
    for (const b of liveBars) {
      if (b.time < lastTime.current) continue;
      const ct = toChartTime(b.time, offset);
      candle.update({ time: ct, open: b.open, high: b.high, low: b.low, close: b.close });
      vol.update({
        time: ct,
        value: b.vol ?? 0,
        color: b.close >= b.open ? "rgba(22,199,132,0.35)" : "rgba(234,57,67,0.35)",
      });
      for (const l of LINES) {
        const v = b[l.key];
        if (v !== null) lineRefs.current[l.key]?.update({ time: ct, value: v });
      }
      lastTime.current = b.time;
    }
  }, [liveBars, liveSeriesId, offset]);

  // Linhas horizontais: Entrada / Stop Loss / Take Profit das posições abertas
  const posKey = useMemo(
    () => positions.map((p) => `${p.ticket}:${p.type}:${p.price_open}:${p.sl}:${p.tp}:${p.is_ai}`).join("|"),
    [positions],
  );
  useEffect(() => {
    const candle = candleRef.current;
    if (!candle) return;
    priceLines.current.forEach((pl) => candle.removePriceLine(pl));
    priceLines.current = [];
    for (const p of positions) {
      const tag = p.is_ai ? "IA" : "MAN";
      priceLines.current.push(
        candle.createPriceLine({
          price: p.price_open,
          color: "#3b82f6",
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: `${tag} ${p.type === "BUY" ? "COMPRA" : "VENDA"} ${p.volume}`,
        }),
      );
      if (p.sl) {
        priceLines.current.push(
          candle.createPriceLine({
            price: p.sl,
            color: "#ea3943",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: "STOP LOSS",
          }),
        );
      }
      if (p.tp) {
        priceLines.current.push(
          candle.createPriceLine({
            price: p.tp,
            color: "#16c784",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: "TAKE PROFIT",
          }),
        );
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [posKey]);

  return (
    <div className="panel flex w-full flex-col overflow-hidden">
      {/* BARRA DE TOPO DO GRÁFICO (SEPARADA DO CANVAS PARA NUNCA SOBREPOR VELAS) */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-700 bg-ink-850 px-3 py-1.5 text-[11px]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 font-extrabold text-white">
            <LineChart size={14} className="text-accent" />
            Gráfico ao Vivo · {series?.symbol ?? "—"} ({series?.timeframe ?? "—"})
          </span>
          <div className="hidden flex-wrap items-center gap-2 sm:flex">
            {LINES.filter((l) => !l.key.startsWith("vwap_")).map((l) => (
              <span key={l.key} className="flex items-center gap-1 text-[10px] text-slate-400">
                <span className="inline-block h-0.5 w-2.5" style={{ background: l.color }} />
                {l.title}
              </span>
            ))}
            <span className="flex items-center gap-1 text-[10px] text-slate-400">
              <span className="inline-block h-0.5 w-2.5 border-t border-dashed" style={{ borderColor: "#e2b93b" }} />
              ±1σ/±2σ
            </span>
          </div>
        </div>

        {timing && (
          <div className="num flex items-center gap-1 rounded bg-ink-900 px-2 py-0.5 text-[10px] text-slate-300">
            <Clock size={11} className="text-accent" />
            <span>
              Vela <b>{timing.tf}</b>: <b className="text-white">{fmtDuration(timing.bar_remaining_s)}</b>
            </span>
          </div>
        )}
      </div>

      {/* ÁREA ISOLADA DO GRÁFICO (ALTURA CONTROLADA E OVERFLOW-HIDDEN) */}
      <div className="relative h-[260px] w-full overflow-hidden sm:h-[310px] xl:h-[350px]">
        <div ref={boxRef} className="h-full w-full" />
      </div>
    </div>
  );
}

export const PriceChart = memo(PriceChartImpl);
