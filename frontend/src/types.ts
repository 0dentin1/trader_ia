export type ModeKey = "LEVE" | "MEDIANO" | "ARRISCADO";
export type Side = "BUY" | "SELL";
export type DrawdownState = "NORMAL" | "CAUTION" | "REDUCED_EXPOSURE" | "TRADING_LOCKED" | "REVIEW_REQUIRED";
export type AdaptiveMode = "OBSERVATION" | "SHADOW" | "ACTIVE";
export type AccountProfile = "SMALL_ACCOUNT_PROTECTION" | "STANDARD";

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
  weekly_loss_limit?: number;
  account_profile?: AccountProfile;
  adaptive_mode?: AdaptiveMode;
  protect_whole_account?: boolean;
  session_loss_limit_pct?: number;
  weekly_drawdown_limit_pct?: number;
  broker_rollover_hour?: number;
  max_spread_points: number;
  risk_pct: Record<ModeKey, number>;
  lot_multiplier: number;
  aggressive_rr: number;
  sync_chart_symbol: boolean;
  deviation_points: number;
  magic: number;
  risk_lock: {
    active: boolean;
    lock_type?: string;
    reason: string | null;
    at?: string | null;
    scope?: string;
    day?: number;
    week?: number;
  } | null;
}

export interface SymbolEntry {
  name: string;
  description: string;
  digits: number;
  path: string;
}

export interface MetaMsg {
  type: "meta";
  algo_version?: string;
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

export interface StructuralRoom {
  status: "ADEQUATE" | "TIGHT" | "BLOCKED";
  room_points: number;
  room_atr: number;
  nearest_level: number;
  level_type: string;
  min_room_atr: number;
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
  calibrated_win_probability?: number | null;
  probability_category?: "HEURISTIC_CONFLUENCE" | "CALIBRATED_OOS";
  structural_room?: StructuralRoom;
  pillars: Pillar[];
  gates: Gate[];
  study_block: string | null;
  flow?: FlowMetrics;
  atr?: number;
  bar_time?: number;
  bar_remaining_s?: number;
  indicators: Record<string, number | null>;
  htf?: { available: boolean; trend: number; bias21: number; bar_dir?: number };
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
  sl_confirmed?: boolean;
  mfe_pts?: number;
  mae_pts?: number;
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
  | "WAITING_DATA_SYNC"
  | "STUDYING_MARKET"
  | "EVALUATING_CONFLUENCE"
  | "EXECUTING_TRADE"
  | "MANAGING_POSITION"
  | "COOLDOWN"
  | "RISK_LOCK"
  | "CRITICAL_EXECUTION_FAILURE";

export interface AIStatus {
  enabled: boolean;
  state: AIState;
  state_label: string;
  detail: string;
  cooldown_until: number;
  cooldown_reason: string;
  active_brains?: number;
  max_concurrent?: number;
  lock: {
    active: boolean;
    lock_type?: string;
    reason: string | null;
    at?: string | null;
    scope?: string;
  };
  adaptive_mode?: AdaptiveMode;
  account_profile?: AccountProfile;
  recovery?: { active: boolean; consecutive_losses: number; deficit: number; martingale_allowed?: boolean };
  managed: {
    ticket: number;
    symbol?: string;
    be_done: boolean;
    sl_confirmed?: boolean;
    initial_sl: number;
    atr: number;
    mode: ModeKey;
    horizon_type?: string;
    horizon_label?: string;
    max_duration_s?: number;
    mfe_pts?: number;
    mae_pts?: number;
    mfe_ccy?: number;
    mae_ccy?: number;
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

export interface SmallAccountGuardSummary {
  status: string;
  approved: boolean;
  reason: string;
  profile: AccountProfile;
  currency: string;
  reference_equity: number;
  drawdown_state: DrawdownState;
  drawdown_reason: string;
  risk_scale_factor: number;
  target_risk_pct: number;
  max_planned_risk_pct: number;
  planned_risk_money: number;
  effective_risk_pct: number;
  effective_risk_money: number;
  open_portfolio_risk_money: number;
  open_portfolio_risk_pct: number;
  max_aggregate_risk_pct: number;
  volume_min: number;
  min_lot_risk_money: number;
  min_lot_risk_pct: number;
  cost_to_risk_ratio: number;
  max_cost_to_risk_ratio: number;
  required_recovery_gain_pct: number;
  session_loss_limit_money: number;
  weekly_drawdown_limit_money: number;
}

export interface PerformanceReport {
  sample_size: number;
  wins: number;
  losses: number;
  win_rate: number;
  expectancy: number;
  profit_factor: number;
  avg_mfe_points: number;
  avg_mae_points: number;
  calibration?: {
    brier_score: number | null;
    log_loss: number | null;
    reliability_bins: { bin: string; predicted_avg: number; actual_win_rate: number; count: number }[];
  };
  by_strategy: Record<string, { sample_size: number; win_rate: number; expectancy: number; profit_factor: number }>;
  by_regime: Record<string, { sample_size: number; win_rate: number; expectancy: number; profit_factor: number }>;
}

export interface QuantSummary {
  algo_version: string;
  adaptive?: {
    rules?: any[];
    mode?: AdaptiveMode;
  };
  performance?: PerformanceReport;
  backtest?: any;
}

export interface DayFinancials {
  realized: number;
  floating: number;
  total: number;
  session_net?: number;
  weekly_net?: number;
  ai_realized_today?: number;
  ai_floating?: number;
  ai_day_total?: number;
  ai_weekly_net?: number;
  ai_realized_all_time?: number;
  account_realized_today?: number;
  account_floating?: number;
  account_day_total?: number;
  account_weekly_net?: number;
  account_realized_all_time?: number;
  reference_equity?: number;
  session_start_equity?: number;
  week_start_equity?: number;
  baseline_used?: number;
  protect_whole_account?: boolean;
  scope_label?: string;
  all_time?: number;
  net_closed?: number;
  trades_total?: number;
  trades_wins?: number;
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
  day: DayFinancials;
  risk_guard?: SmallAccountGuardSummary;
  quant?: QuantSummary;
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
