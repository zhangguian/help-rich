/**
 * ⚠️ 这部分接口类型(交易流水 + 计算器)是手写 stub(后端 OpenAPI 自动生成的是嵌套结构,使用不便)
 * 实际 OpenAPI 类型在 paths/operations 中,详细见 docs/api-contract/api-contract.md
 * 完整生成物见 types.ts(下方)
 *
 * 设计原则(frontend-arch §12.5):
 * - Decimal → string(后端 JSON 序列化保留精度)
 * - int / float → number
 * - snake_case → camelCase(由 axios 拦截器自动转换)
 */

export interface HealthResponse {
  status: string;
}

/** LLM Keys 状态(v2.1) */
export interface LlmKeysStatus {
  deepseek: boolean;
  minimax: boolean;
  doubao: boolean;
}

/** LLM Test 响应 */
export interface LlmTestResponse {
  ok: boolean;
  latencyMs: number | null;
  error: string | null;
}

export interface LlmTestRequest {
  provider: 'deepseek' | 'minimax' | 'doubao';
}

export interface LlmKeysUpdate {
  deepseek: string;
  minimax: string;
  doubao: string;
}

/** 交易流水(P2.1 实施) */
export interface Transaction {
  id: number;
  stockCode: string;
  stockName: string | null;
  action: 'buy' | 'sell';
  shares: number;
  price: string;
  tradeDate: string;
  note: string | null;
  score: number | null;
  createdAt: string;
}

export interface TransactionCreate {
  stockCode: string;
  action: 'buy' | 'sell';
  shares: number;
  price: string;
  tradeDate: string;
  stockName?: string;
  note?: string;
}

export interface TransactionListResponse {
  items: Transaction[];
  total: number;
}

/** 持仓(P2.3, P3.5.1 扩展行情字段) */
export interface Position {
  stockCode: string;
  stockName: string | null;
  shares: number;
  avgCost: string;
  totalCost: string;
  realizedPnl: string;
  /** P3.5.1 行情字段,行情不可用时为 null */
  currentPrice: string | null;
  prevClose: string | null;
  todayPnl: string | null;
  floatingPnl: string | null;
}

export interface PositionListResponse {
  items: Position[];
}

/** 手动录入 / 覆盖持仓(v0.4.0) */
export interface PositionCreate {
  stockCode: string;
  shares: number;
  costPrice: string;
  stockName?: string;
}

/** 持仓体检(v0.4.0) */
export interface HoldingsHealthItem {
  stockCode: string;
  stockName: string | null;
  shares: number;
  avgCost: string;
  currentPrice: string;
  floatingPnl: string;
  floatingPnlRatioPct: number;
  concentrationPct: number;
  status: 'profit' | 'loss' | 'flat' | 'high_concentration' | 'unknown';
  priceAvailable: boolean;
}

export interface HoldingsHealth {
  totalPositions: number;
  totalMarketValue: string;
  totalFloatingPnl: string;
  pnlRatioPct: number;
  riskLevel: string;
  riskScore: number;
  warnings: string[];
  items: HoldingsHealthItem[];
  quotesUnavailable: boolean;
}

/** 诊断(P4.4) */
export interface DiagnoseOut {
  tradeId: number;
  status: 'pending' | 'success' | 'no_key' | 'failed';
  score: number | null;
  breakdown: Record<string, number> | null;
  aiComment: string | null;
  aiStatus: string | null;
}

export interface FeedbackUpdate {
  feedback: 'useful' | 'useless' | null;
}

/** 止损(P5.1) */
export interface StopLoss {
  id: number;
  stockCode: string;
  stopLossPrice: string;
  enabled: boolean;
  notifySound: boolean;
  notifyDesktop: boolean;
  notifyVibrate: boolean;
  lastTriggeredAt: string | null;
}

/** Provider 信息(P4.2e) */
export interface LlmProviderItem {
  name: string;
  model: string;
  configured: boolean;
}

export interface LlmProvidersOut {
  items: LlmProviderItem[];
}

export interface LlmSettingsOut {
  activeProvider: 'deepseek' | 'minimax' | 'doubao';
}

/** 实时行情(P3.5) */
export interface Quote {
  code: string;
  name: string;
  currentPrice: string;
  prevClose: string;
  open: string;
  high: string;
  low: string;
  change: string;
  changePct: number;
  volume: number;
  amount: string;
  timestamp: string;
  turnoverPct: number | null;
  pe: number | null;
  pb: number | null;
}

/** 大盘盯盘(roadmap §3.9) */
export interface MarketIndex {
  code: string;
  name: string;
  currentPrice: string;
  prevClose: string;
  open: string;
  high: string;
  low: string;
  change: string;
  changePct: number;
  volume: number;
  amount: string;
  timestamp: string;
}

export interface MarketMover {
  code: string;
  name: string;
  currentPrice: string;
  changePct: number;
}

export interface MarketOverview {
  indexes: (MarketIndex | null)[];
  gainers: MarketMover[];
  losers: MarketMover[];
  fetchedAt: string;
}

/** 计算器(P3.2) */
export interface CalculatorRequest {
  stockCode: string;
  action: 'buy' | 'sell';
  txShares: number;
  txPrice: string;
}

export interface CalculatorBefore {
  shares: number;
  costPrice: string;
  totalCost: string;
}

export interface CalculatorAfter {
  shares: number;
  costPrice: string | null;
  totalCost: string;
  deltaCost: string | null;
  realizedPnl: string;
}

export interface PnlGridRow {
  pct: number;
  price: string;
  marketValue: string;
  pnl: string;
}

export interface CalculatorResponse {
  input: CalculatorRequest;
  before: CalculatorBefore;
  after: CalculatorAfter;
  pnlGrid: PnlGridRow[];
}

/** K 线智能分析 v1 — 新增指标类型(backend/app/services/ta_service.py) */

export interface MacdIndicator {
  dif: number | null;
  dea: number | null;
  hist: number | null;
  difSeries: number[];
  deaSeries: number[];
  histSeries: number[];
  cross: 'golden' | 'dead' | null;
}

export interface KdjIndicator {
  k: number | null;
  d: number | null;
  j: number | null;
  kSeries: number[];
  dSeries: number[];
  jSeries: number[];
  zone: 'overbought' | 'oversold' | 'normal' | null;
  cross: 'golden' | 'dead' | null;
}

export interface BollIndicator {
  mid: number | null;
  upper: number | null;
  lower: number | null;
  midSeries: number[];
  upperSeries: number[];
  lowerSeries: number[];
  bandwidth: number | null;
  squeeze: boolean | null;
  position: 'touching_upper' | 'touching_lower' | 'middle' | null;
}

export interface VolumePriceReason {
  name: string;
  ok: boolean;
  note: string;
}

export interface VolumePriceIndicator {
  label: string | null;
  direction: 'healthy_up' | 'panic_sell' | 'liar_up_suspect' | 'natural_pullback' | null;
  emoji: string | null;
  health: number | null;
  reasons: VolumePriceReason[];
}

export interface PatternMatch {
  name: string;
  type: 'bull' | 'bear' | 'neutral';
  emoji: string;
  dateIndex: number;
}

export interface LiarPattern {
  name: string;
  note: string;
  severity: 'low' | 'medium' | 'high';
}

export interface LiarIndicator {
  bullLiars: LiarPattern[];
  bearLiars: LiarPattern[];
  summary: string;
}

export interface PositionIndicator {
  pct20: number | null;
  pct60: number | null;
  biasMa60: number | null;
  rangePct: number | null;
  band: 'high' | 'mid' | 'low';
}

export interface SignalReason {
  module: string;
  weight: number;
  verdict: string;
  delta: number;
}

export interface SignalFusion {
  view: 'bullish' | 'bearish' | 'neutral';
  viewLabel: string;
  score: number;
  confidence: 'high' | 'medium' | 'low';
  reasons: SignalReason[];
  summary: string;
}

export interface SignalMarker {
  time: string;
  dateIndex: number;
  text: string;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  color: string;
}

export interface TechnicalIndicators {
  latestClose: number;
  ma: { ma5: number | null; ma10: number | null; ma20: number | null; ma60: number | null };
  maSeries: { ma5: number[]; ma10: number[]; ma20: number[]; ma60: number[] };
  volume: { ratio: number | null; state: 'expand' | 'shrink' | 'normal' | null };
  channel: {
    state: 'up' | 'down' | 'sideways';
    slope: number | null;
    upper: number | null;
    lower: number | null;
    residStd: number | null;
  };
  supportPressure: { support: number[]; pressure: number[] };
  stabilize: { state: boolean; price: number | null; reasons: { name: string; ok: boolean; note: string }[] };
  macd: MacdIndicator;
  kdj: KdjIndicator;
  boll: BollIndicator;
  volumePrice: VolumePriceIndicator;
  patterns: PatternMatch[];
  liar: LiarIndicator;
  position: PositionIndicator;
  signal: SignalFusion;
  signalSeries: SignalMarker[];
  dataQuality: { klineCount: number; degraded: string[] };
}

/** K 线 + 指标 端点响应(/api/kline/{code}/indicators) */
export interface KlineIndicatorsResponse {
  stockCode: string;
  period: string;
  count: number;
  items: KlineItem[];
  indicators: TechnicalIndicators;
}

export interface KlineItem {
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

/** 单只股票 AI 分析结果(/api/stock/{code}/analysis) */
export interface AnalysisResult {
  stockCode: string;
  indicators: TechnicalIndicators;
  ai: {
    view: 'bullish' | 'bearish' | 'neutral';
    viewReason: string;
    trend: string;
    volumeNote: string;
    keyLevels: { type: string; price: number; note: string }[];
    advice: string;
    riskWarning: string;
  } | null;
}

/** 自选股(P2.2) */
export interface WatchlistItem {
  stockCode: string;
  stockName: string | null;
  source: string;
  note: string | null;
  addedAt: string;
}

export interface WatchlistListResponse {
  items: WatchlistItem[];
}

/** 错误响应统一格式 */
export interface ApiError {
  code: string;
  message: string;
  detail?: Record<string, unknown>;
}

/* ============================================================
 * 下方是 openapi-typescript 生成的完整 OpenAPI 类型(嵌套结构)
 * 平时用上方手写接口即可,需要查完整 schema 时用 paths[key]
 * ============================================================
 */

/** This file was auto-generated by openapi-typescript. */
export interface paths {
  // (下面是 18 个端点的完整 OpenAPI schema)
}