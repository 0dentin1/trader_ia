export type ModeKey = "LEVE" | "MEDIANO" | "ARRISCADO";
export type Side = "BUY" | "SELL";

export interface ModeConfig {
  key: ModeKey;
  label: string;
  subtitle: string;
  objective: string;
  timeframe: string;
  htf: string | null;
  min_score: number;
  risk_min: number;
  risk_max: number;
  risk_default: number;
  sl_atr: number;
  tp_atr: number;
  weights: number[];
  rvol_min: number;
  adx_min: number;
  min_green_pillars: number;
  be_mode: string;
  be_value: number;
  trail_mode: string;
  trail_value: number;
  rules: string[];
}

export interface Settings {
  mode: ModeKey;
  symbol: string | null;
  auto_select_symbol?: boolean;
  daily_loss_limit: number;
  daily_gain_target: number;
  max_spread_points: number;
  risk_pct: Record<ModeKey, number>;
  lot_multiplier: number;
  aggressive_rr: number;
  sync_chart_symbol: boolean;
  deviation_points: number;
  magic: number;
  risk_lock: { day: number; reason: string; at: string } | null;
}

export interface SymbolEntry {
  name: string;
  description: string;
  digits: number;
  path: string;
}

export interface MetaMsg {
  type: "meta";
  modes: ModeConfig[];
  settings: Settings;
  symbols: SymbolEntry[];
  symbol: string | null;
}

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number | null;
  vwap: number | null;
  vwap_up1: number | null;
  vwap_dn1: number | null;
  vwap_up2: number | null;
  vwap_dn2: number | null;
  ema9: number | null;
  ema21: number | null;
  ema200: number | null;
}

export interface SeriesMsg {
  type: "series";
  series_id: string;
  symbol: string;
  timeframe: string;
  digits: number;
  server_offset_s?: number;
  bars: Bar[];
}

export interface Account {
  login?: number;
  name?: string;
  server?: string;
  company?: string;
  currency?: string;
  leverage?: number;
  balance?: number;
  equity?: number;
  profit?: number;
  margin?: number;
  margin_free?: number;
  margin_level?: number;
  trade_mode?: "DEMO" | "CONTEST" | "REAL" | "?";
  trade_allowed?: boolean;
  trade_expert?: boolean;
}

export interface Terminal {
  name?: string;
  company?: string;
  connected?: boolean;
  trade_allowed?: boolean;
  ping_ms?: number;
  build?: number;
}

export interface Pillar {
  id: number;
  name: string;
  tag: string;
  weight: number;
  score: number;
  ok: boolean;
  value: string;
  checks: { label: string; ok: boolean }[];
}

export interface Gate {
  label: string;
  ok: boolean;
}

export interface FlowMetrics {
  buy: number;
  sell: number;
  delta: number;
  ticks: number;
  velocity: number;
  velocity_avg: number;
  acceleration: number;
  enough: boolean;
}

export interface CandleAnalysis {
  prob_up: number;
  prob_down: number;
  next_dir: Side;
  prev_desc: string;
  curr_desc: string;
  wick_desc: string;
  wick_pressure: number;
  best_strategy?: string;
  bull_strategies?: string[];
  bear_strategies?: string[];
  bull_reversal: boolean;
  bear_reversal: boolean;
  bull_impulse: boolean;
  bear_impulse: boolean;
  bull_hammer: boolean;
  bear_star: boolean;
  bull_engulf: boolean;
  bear_engulf: boolean;
  b0_bull_pin: boolean;
  b0_bear_pin: boolean;
  broke_prev_high: boolean;
  broke_prev_low: boolean;
  veto_buy: string[];
  veto_sell: string[];
}

export interface HorizonInfo {
  type: "SCALP_1VELA" | "IMPULSO_CURTO" | "ONDA_TENDENCIA";
  label: string;
  short_label: string;
  timeframe: string;
  duration_s: number;
  tp_atr: number;
  sl_atr: number;
  strategy?: string;
  reason: string;
}

export interface EvaluatedTF {
  tf: string;
  score: number;
  direction: Side | null;
  signal: Side | null;
  horizon: string;
  duration_s: number;
  strategy?: string;
}

export interface RadarEntry {
  symbol: string;
  direction: Side | null;
  score: number;
  min_score: number;
  next_prob: number;
  rank_score: number;
  regime: string;
  regime_code: string;
  spread_points: number;
  timeframe?: string;
  horizon_label?: string;
  duration_s?: number;
  strategy?: string;
  signal: Side | null;
  blocked: boolean;
  reason: string;
}

export interface Analysis {
  ready: boolean;
  mode: ModeKey;
  timeframe: string;
  htf_tf: string | null;
  spread_points: number;
  regime: {
    code: "TREND_UP" | "TREND_DOWN" | "REVERSAL_UP" | "REVERSAL_DOWN" | "RANGE" | "HIGH_VOL" | "UNKNOWN";
    label: string;
    adx?: number;
    plus_di?: number;
    minus_di?: number;
    atr?: number;
    atr_ratio?: number;
    ema200_slope?: number;
    spread_points?: number;
    spread_atr?: number;
  };
  candle?: CandleAnalysis | null;
  horizon?: HorizonInfo | null;
  evaluated_timeframes?: EvaluatedTF[];
  score: number;
  score_buy: number;
  score_sell: number;
  direction: Side | null;
  signal: Side | null;
  pillars: Pillar[];
  gates: Gate[];
  study_block: string | null;
  flow?: FlowMetrics;
  atr?: number;
  bar_time?: number;
  bar_remaining_s?: number;
  indicators: Record<string, number | null>;
  htf?: { available: boolean; trend: number; bias21: number };
}

export interface Position {
  ticket: number;
  symbol: string;
  type: Side;
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  swap: number;
  time: number;
  magic: number;
  comment: string;
  digits?: number;
  is_ai: boolean;
  open_time_local?: number;
  elapsed_s?: number;
  max_duration_s?: number;
  remaining_s?: number;
  horizon_label?: string;
  net_profit?: number;
  tp_profit?: number | null;
  sl_profit?: number | null;
  progress_pct?: number;
  be_protected?: boolean;
}

export interface Deal {
  ticket: number;
  order: number;
  time: number;
  time_msc?: number;
  type: string;
  entry: string;
  symbol: string;
  volume: number;
  price: number;
  profit: number;
  commission: number;
  swap: number;
  fee: number;
  magic: number;
  comment: string;
  position_id: number;
  reason: string;
}

export interface CompletedTrade {
  position_id: number;
  symbol: string;
  side: Side;
  volume: number;
  entry_price: number;
  exit_price: number;
  open_time: number;
  close_time: number;
  open_time_local: number;
  close_time_local: number;
  duration_s: number;
  gross_profit: number;
  commission: number;
  swap: number;
  net_profit: number;
  won: boolean;
  is_ai: boolean;
  mode: ModeKey | null;
  exit_reason: string;
  is_today: boolean;
}

export interface TradeSummary {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  net_total: number;
  net_today: number;
  avg_duration_s: number;
}

export type AIState =
  | "OFF"
  | "DISCONNECTED"
  | "STUDYING_MARKET"
  | "EVALUATING_CONFLUENCE"
  | "EXECUTING_TRADE"
  | "MANAGING_POSITION"
  | "COOLDOWN"
  | "RISK_LOCK";

export interface AIStatus {
  enabled: boolean;
  state: AIState;
  state_label: string;
  detail: string;
  cooldown_until: number;
  cooldown_reason: string;
  active_brains?: number;
  max_concurrent?: number;
  lock: { active: boolean; reason: string | null; at: string | null };
  recovery?: { active: boolean; consecutive_losses: number; deficit: number };
  managed: {
    ticket: number;
    symbol?: string;
    be_done: boolean;
    initial_sl: number;
    atr: number;
    mode: ModeKey;
    horizon_type?: string;
    horizon_label?: string;
    max_duration_s?: number;
  }[];
}

export interface SymbolInfo {
  name?: string;
  description?: string;
  digits?: number;
  point?: number;
  tick_size?: number;
  volume_min?: number;
  volume_max?: number;
  volume_step?: number;
  stops_level?: number;
  currency_profit?: string;
  trade_mode?: number;
}

export interface TimingInfo {
  tf: string;
  tf_seconds: number;
  bar_elapsed_s: number;
  bar_remaining_s: number;
  server_offset_s: number;
}

export interface SnapshotMsg {
  type: "snapshot";
  ts: number;
  conn: { mt5: boolean; error: { code: number; message: string } | null; terminal: Terminal };
  account: Account;
  symbol: string | null;
  symbol_info: SymbolInfo;
  tick: {
    bid?: number;
    ask?: number;
    last?: number;
    time?: number;
    time_msc?: number;
    spread_points?: number | null;
  };
  timing?: TimingInfo;
  series_id: string;
  bars: Bar[];
  analysis: Analysis | Record<string, never>;
  mode: ModeKey;
  ai: AIStatus;
  radar?: RadarEntry[];
  positions: Position[];
  day: {
    realized: number;
    floating: number;
    total: number;
    all_time?: number;
    net_closed?: number;
    trades_total?: number;
    trades_wins?: number;
  };
}

export interface LogEntry {
  id: number;
  ts: string;
  epoch: number;
  level: "info" | "warn" | "error" | "success" | "action" | "think" | "state";
  mode: ModeKey | null;
  msg: string;
}

export interface HistoryMsg {
  type: "history";
  deals: Deal[];
  trades?: CompletedTrade[];
  summary?: TradeSummary;
  realized: number;
}

export interface AckMsg {
  type: "ack";
  id: number | null;
  action: string;
  ok: boolean;
  message: string;
}

export type ServerMsg =
  | MetaMsg
  | SeriesMsg
  | SnapshotMsg
  | HistoryMsg
  | AckMsg
  | { type: "logs"; entries: LogEntry[]; backlog?: boolean };
