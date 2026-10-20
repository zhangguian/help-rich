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

/** 一键复盘聚合结果(v2.3) */
export type ReplayWindow = '1d' | '3d' | '5d' | '10d' | '20d' | '60d';

export interface ReplaySummary {
  stockCode: string;
  window: ReplayWindow;
  scoreAvg: string | null;
  dimensionAvg: Record<string, number>;
  topIssues: Array<{ dim: string; score: number; hint: string }>;
  aiComment: string | null;
  aiStatus: 'success' | 'failed' | 'no_key';
  aiProvider: string | null;
  aiModel: string | null;
  aiLatencyMs: number | null;
  summarySnapshot: {
    txCount: number;
    buyCount: number;
    sellCount: number;
    txLines: string[];
    concentrationPct: string;
    realizedPnl: string;
    isInWatchlist: boolean;
    startDate: string;
    endDate: string;
  };
  latestTxId: number;
  createdAt: string;
  updatedAt: string;
}

export interface ReplaySummaries {
  stockCode: string;
  windows: Partial<Record<ReplayWindow, ReplaySummary | null>>;
}

/** 每日 AI 分析持久化(v2.4)— 后端 GET /api/diagnose/stock/{code}/daily-analyses */
export interface DailyAnalysisItem {
  stockCode: string;
  analysisDate: string;  // YYYY-MM-DD(K 线最新交易日)
  scoreAvg: string | null;
  dimensionAvg: Record<string, number>;
  topIssues: Array<{ dim: string; score: number; hint: string }>;
  aiView: 'bullish' | 'bearish' | 'neutral' | null;
  aiSummary: string | null;  // LLM 评语
  currentPrice: string | null;  // 当时实时报价
  latestKlineDate: string | null;
  createdAt: string;
  updatedAt: string;
  // N 天后实际涨跌(由后端 lazy 计算)
  actualChangePct: string | null;  // e.g. "+5.32" / "-3.10" / null
  outcome: 'hit' | 'miss' | null;
}

export interface DailyAnalysisList {
  stockCode: string;
  days: number;
  horizonDays: number;
  total: number;
  items: DailyAnalysisItem[];
}

/** 方向胜率(view vs N 天后涨跌)— 后端 GET /winrate */
export interface WinrateDirection {
  total: number;
  hits: number;
  winrate: number | null;  // null:样本不足(WINRATE_MIN_SAMPLES)
}

export interface WinrateResponse {
  stockCode: string;
  days: number;
  horizonDays: number;
  samples: number;
  skipped: number;
  bullish: WinrateDirection;
  bearish: WinrateDirection;
  overallAccuracy: number | null;
  insufficient: boolean;
  // 同向模拟累计简单收益率(%):bullish 做多 / bearish 做空,等权 1 单位/次
  simulateReturnPct: number | null;
  generatedAt: string;
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

/** 指数 sparkline(roadmap §3.9 大盘 Tab) */
export interface MarketIndexSparklinePoint {
  date: string;
  close: number;
}
export interface MarketIndexSparks {
  count: number;
  sparks: Record<string, MarketIndexSparklinePoint[]>;
}

/** 沪深 A 股涨跌家数 + 区间分布(roadmap §3.9 大盘 Tab) */
export interface MarketSentiment {
  sampleSize: number;
  upTotal: number;
  downTotal: number;
  flatTotal: number;
  buckets: {
    limitUp: number;
    up5_10: number;
    up1_5: number;
    up0_1: number;
    flat: number;
    down0_1: number;
    down1_5: number;
    down5_10: number;
    limitDown: number;
  };
amountYi: number;
  /** M2.5:涨停/跌停家数单列 */
  limitUp?: number;
  limitDown?: number;
  /** 数据口径:sina_full=全市场统计 / sina_partial=首页采样(不可信) */
  source?: string;
  /** true 表示样本不完整(首页采样),前端必须显式提示,不得当作全市场 */
  partial?: boolean;
}

/** M2.5 两市量能 N 日趋势(/api/market/amount-trend) */
export interface AmountTrendItem {
  date: string;
  volumeYi: number;
}
export interface AmountTrendResponse {
  days: number;
  items: AmountTrendItem[];
}

/** A 股个股主力净流入榜(roadmap §3.9 大盘 Tab,降级估算) */
export interface MainFundFlowItem {
  code: string;
  name: string;
  currentPrice: string;
  changePct: number;
  netamountYi: number;
}
export interface MainFundFlowResponse {
  limit: number;
  items: MainFundFlowItem[];
  estimated?: boolean; // GB-001 IR-6:估算值标记
  method?: string;
  source?: string;
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
  realizedPnlGross: string; // GB-001 IR-4:不含费用
  realizedPnlNet: string;   // GB-001 IR-4:扣除费用
  feePaid: string;          // GB-001 IR-4:本笔费用
}

/** 交易费用设置(GB-001 IR-4) */
export interface CostSettings {
  enabled: boolean;
  commissionRate: string;
  minCommission: string;
  stampTaxRate: string;
  transferFeeRate: string;
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
  squeeze: boolean;
  position: 'touching_upper' | 'touching_lower' | 'mid' | null;
}

/** K 线图图例指标 v2(roadmap §3.9 v3):RSI / CCI / STOCH / MOM / WMSR / SKT / FASK */
export type IndicatorState =
  | 'overbought'
  | 'oversold'
  | 'bullish'
  | 'bearish'
  | 'strong_up'
  | 'strong_down'
  | 'golden_cross'
  | 'dead_cross'
  | 'rising'
  | 'falling'
  | 'zero_cross_up'
  | 'zero_cross_down'
  | 'neutral'
  | null;

export interface RsiIndicator {
  rsi: number | null;
  rsiSeries: number[];
  state: IndicatorState;
}
export interface CciIndicator {
  cci: number | null;
  cciSeries: number[];
  state: IndicatorState;
}
export interface StochIndicator {
  fastk: number | null;
  fastd: number | null;
  slowk: number | null;
  slowd: number | null;
  fastkSeries: number[];
  fastdSeries: number[];
  slowkSeries: number[];
  slowdSeries: number[];
  state: IndicatorState;
}
export interface MomIndicator {
  mom: number | null;
  momSeries: number[];
  state: IndicatorState;
}
export interface WmsrIndicator {
  wmsr: number | null;
  wmsrSeries: number[];
  state: IndicatorState;
}
export interface SktIndicator {
  slowk: number | null;
  slowd: number | null;
  slowkSeries: number[];
  slowdSeries: number[];
  state: IndicatorState;
}
export interface FaskIndicator {
  fastk: number | null;
  fastkSeries: number[];
  state: IndicatorState;
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
  /** v0.5 M1.2:近120日 P20/P80 分位风险带 */
  riskBand?: 'high' | 'mid' | 'low';
  p20?: number | null;
  p80?: number | null;
  /** 参考支撑 = 近20日最低收盘 × 0.98 */
  supportPrice?: number | null;
  /** 建议止损 = 参考支撑 × 0.97 */
  stopLossPrice?: number | null;
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

/** M1.3 信号历史胜率回检(/api/stock/{code}/analysis 顶层 signalWinrate) */
export interface SignalWinrate {
  signal: 'bullish' | 'bearish' | 'neutral';
  signalLabel: string;
  count: number;
  up5: number;
  up20: number;
  sample5: number;
  sample20: number;
  insufficient: boolean;
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
  rsi: RsiIndicator;
  cci: CciIndicator;
  stoch: StochIndicator;
  mom: MomIndicator;
  wmsr: WmsrIndicator;
  skt: SktIndicator;
  fask: FaskIndicator;
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

/** v2.5:LLM 输出的操作参考结构化字段(替代旧版单字符串 advice) */
export interface AdviceTStrategy {
  suitable: boolean;
  tRange: string;
  basePositionPct: string;
  sellTrigger: string;
  buybackTrigger: string;
  stopLoss: string;
  unsuitableSignals: string;
}

export interface AdviceStructured {
  rationale: string;
  price: {
    entryOrExitRange: string;
    stopLoss: string;
  };
  positionPct: string;
  trigger: string;
  holdingWindow: string;
  notAction: string;
  /** v2.5:做 T 策略;仅 profit/loss 角色下由 LLM 决定是否输出 */
  tStrategy?: AdviceTStrategy | null;
}

/** 单只股票 AI 分析结果(/api/stock/{code}/analysis) */
export interface AnalysisResult {
  stockCode: string;
  indicators: TechnicalIndicators;
  signalWinrate?: SignalWinrate;
  /** 后端 LLM 解读;null 时 ai_error 描述降级原因 */
  ai: {
    view: 'bullish' | 'bearish' | 'neutral';
    viewReason: string;
    trend: string;
    volumeNote: string;
    keyLevels: { type: string; price: number; note: string }[];
    /** v2.5:用户持仓状态,决定 advice 角色段 */
    positionStatus: 'empty' | 'profit' | 'loss';
    /** v2.5:advice 角色名(建仓参考 / 止盈参考 / 解套参考) */
    adviceRole: string;
    /** v2.5:结构化操作参考(6 字段 + 可选 tStrategy) */
    advice: AdviceStructured;
    riskWarning: string;
  } | null;
  /** ai=null 时的原因:'unconfigured' | 'timeout' | 'failed' | null(ai 成功) */
  aiError?: 'unconfigured' | 'timeout' | 'failed' | null;
  /** v2.5.4:AI 来源 — 'live' 本次成功 / null 完全不可用(取消 stale_cache 兜底) */
  aiSource?: 'live' | null;
  /** v2.5.3:K 线缓存最新一根的 trade_date(YYYY-MM-DD),前端用作缓存失效键 */
  latestKlineDate?: string | null;
  /** v2.3:实时盘中报价(盘中为实时价,盘后/停牌 = latest_close) */
  currentPrice?: string | null;
  quoteChangePct?: number | null;
  /** v2.5:后端判定的用户持仓角色(empty/profit/loss) */
  positionStatus?: 'empty' | 'profit' | 'loss';
  /** v2.5:基于持仓成本的盈亏百分比(0.05=+5%);空仓或成本缺失时 null */
  costBasisPct?: number | null;
}

/** 自选股(P2.2) */
export interface WatchlistItem {
  stockCode: string;
  stockName: string | null;
  source: string;
  note: string | null;
  addedAt: string;
  isFavorite: boolean;  // v0.5 特别关注
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