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
  /** 时间节点(HH:MM:SS);null = 未知(存量流水 / 用户留空) */
  tradeTime: string | null;
  note: string | null;
  score: number | null;
  createdAt: string;
  /** v0.5.0 事件溯源快照:该笔应用后的持仓状态(NULL = 已被基准吸收 / 旧数据) */
  sharesAfter: number | null;
  totalCostAfter: string | null;
  realizedAfter: string | null;
}

export interface TransactionCreate {
  stockCode: string;
  action: 'buy' | 'sell';
  shares: number;
  price: string;
  tradeDate: string;
  /** 时间节点(HH:MM);留空 = 未知 */
  tradeTime?: string;
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
  /** v0.5.0:累计已实现盈亏(可为负)。留空 = 沿用当前累计值 */
  realizedPnl?: string;
  /** v0.5.0:这份持仓快照是哪一天(YYYY-MM-DD)。只吸收该日期前的流水 */
  baseDate?: string;
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
  status: 'pending' | 'success' | 'no_key' | 'failed' | 'scored';
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

/* ============================================================
 * 拟交易复核(v0.6 · POST /api/calculator/review)
 * 三档判定 + 做 T 评估 —— 纯算法、零 LLM
 * ============================================================ */

/** ok=符合条件 / conditional=有条件可做 / not_recommended=不建议 / unknown=数据不足 */
export type ReviewVerdict = 'ok' | 'conditional' | 'not_recommended' | 'unknown';

export interface ReviewPriceCheck {
  /** 引擎给出的建议价(NULL = 没有可参考的建议价位) */
  suggested: number | null;
  yourPrice: number;
  verdict: ReviewVerdict;
  note: string;
}

export interface ReviewSizeCheck {
  /** 建议股数(sell = 持仓的 1/3;buy = null) */
  suggestedShares: number | null;
  yourShares: number;
  note: string;
}

export interface ReviewTAssessment {
  suitable: boolean;
  tHigh: number | null;
  tLow: number | null;
  sellTrigger: string;
  buybackTrigger: string;
  yourPriceInRange: boolean | null;
  /** 可动 T 仓上限(底仓之外的部分) */
  maxTShares: number | null;
  note: string;
}

export interface ReviewPositionAfter {
  shares: number;
  avgCost: string | null;
  totalCost: string;
  realizedPnl: string;
}

/**
 * 做 T 的一个方向(正T / 反T)
 *
 * 术语(后端写死,前后端一致):
 * - 反T(reverse)= 先卖后买(高抛低吸),持股数不变
 * - 正T(forward)= 先买后卖(低吸高抛),要占用买入资金
 */
export interface ReviewTDirection {
  key: 'reverse' | 'forward';
  label: string;
  applicable: boolean;
  /**
   * 不可用的原因码 —— 前端据此区分「缺资金 → 引导去填」与「真不适用 → 只灰显」。
   * ok | no_cash | cash_too_little | no_position | not_suitable
   * | no_t_range | base_too_large | no_base_ratio | unknown
   */
  reasonCode: string;
  prerequisite: string;
  /** 股数上限(null = 算不出来,如未填写资金) */
  maxShares: number | null;
  /** 对应金额(元,字符串保精度) */
  maxAmount: string | null;
  steps: ReviewTStep[];
  statusText: string;
}

export interface ReviewTStep {
  /** sell / buyback(反T)· buy / sell(正T) */
  role: string;
  text: string;
}

export interface ReviewTDirections {
  reverse: ReviewTDirection;
  forward: ReviewTDirection;
  /** 推荐的方向(null = 都不推荐) */
  recommended: 'reverse' | 'forward' | null;
  recommendReason: string;
  /**
   * 用户拟的这笔落在推荐方向的具体哪条腿:
   * reverse.sell / reverse.buyback / forward.buy / forward.sell / null
   */
  yourLeg: string | null;
  /** A 股 T+1 提示 */
  tPlusOneNote: string;
}

export interface TradeReviewResponse {
  verdict: ReviewVerdict;
  headline: string;
  /** 支持本次操作的依据 */
  reasons: string[];
  /** 反对本次操作的依据 */
  blockers: string[];
  priceCheck: ReviewPriceCheck;
  sizeCheck: ReviewSizeCheck;
  tAssessment: ReviewTAssessment;
  positionAfter: ReviewPositionAfter;
  riskFlags: string[];
  /** 数据降级说明(缺数据 → 降级,不编数字) */
  degraded: string[];
  /** 正T / 反T 两行对照 */
  tDirections: ReviewTDirections;
}

/** 账户可用资金(GET/PUT /accounts/{id}/cash) */
export interface AccountCash {
  accountId: number;
  /** null = 未填写(不是 0) */
  cashAvailable: number | null;
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
  /**
   * 参考支撑 = **当前这根 K 线之前** 20 日最低收盘 × 0.98
   *
   * 为什么排除当前根:若把当前根也算进支撑窗口,支撑 ≤ 当前收盘 × 0.98,
   * 止损位就 ≤ 当前收盘 × 0.9506,止损触发条件 `现价 < 止损位`
   * 在收盘价口径下**永不可能成立**(实测 15900 个信号日命中 0 次)。
   * 后端 `ta_service._position` 已按此口径实现(2026-10-21)。
   */
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
  /**
   * 信号发生**当日**的数值依据(仅四类异动行为标注有)。
   *
   * ⚠️ 与「当前这只票的真实数据」是**两回事**:
   * 现在线是末根 K 线的当前值,依据是信号当天的事实 ——
   * 不能混用,否则会把 10-28 的信号配上 10-30 的现价。
   */
  reason?: string;
}

/**
 * K 线异动行为标注点(四信号:主力异动 / 低吸 / 锁仓 / 高抛)
 *
 * 与 `SignalMarker` 的区别:
 * - `SignalMarker` 是**末日**语义(金叉/死叉/形态/诱多诱空),全部落在最后一根 K 线
 * - `BehaviorMarker` 是**历史回溯**语义,标注「某一天出现了什么可观测事实」
 *
 * `reason` 是信号发生**当日**的数值依据 —— 不能与「当前这只票的真实数据」混用。
 */
export interface BehaviorMarker {
  kind: 'main_force_move' | 'dip_buy' | 'lock_position' | 'distribute';
  /** 对应 K 线日期(YYYY-MM-DD) */
  date: string;
  /** 在 K 线序列中的下标 */
  dateIndex: number;
  /** 显示文案(含 emoji) */
  text: string;
  position: 'aboveBar' | 'belowBar';
  color: string;
  /** 依据文字(带实测数值) */
  reason: string;
  /**
   * 机器可读依据数值。
   *
   * ⚠️ 不全是数字:`strength_level` 是字符串枚举(`强` / `一般`)、
   * `strength_note` 是说明文字 —— 等级要能当枚举用,不能塞进 number。
   */
  metrics: Record<string, number | string | null>;
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
  /** 四类异动行为标注点(历史回溯语义) */
  behaviorMarkers?: BehaviorMarker[];
  /** 资金流不可用 → true(此时 behaviorMarkers 为空) */
  behaviorMarkersUnavailable?: boolean;
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
  /** 行业标签:股票 = 行业名(如「白酒」);ETF = 「跟踪{指数}」;未覆盖 = null */
  industry?: string | null;
  /** 行业标签来源:baostock / etf_index / sina / null */
  industrySource?: string | null;
  /** 行业标签的补充说明(如「场内 ETF · 宽基」) */
  industryNote?: string | null;
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

/* ============================================================
 * 盯盘决策引擎(v0.9)—— 确定性算法结果,不是 LLM 解读
 *
 * 对应后端 `GET /api/stock/{code}/decision` → `{ decision: StockDecision }`
 * 字段名是 camelCase —— 后端返回 snake_case,由 `api.ts` 的 `snakeToCamel`
 * 拦截器递归转换(对象和数组都处理)。
 * ============================================================
 */

/** 行动清单条目(设计文档 §5.2 Action) */
export interface DecisionAction {
  kind: 'entry' | 'add' | 'exit' | 'stop' | 't_sell' | 't_buyback' | 'watch';
  /** 短标签,如「支撑企稳建仓」 */
  label: string;
  /** 触发条件,必须含具体数字 */
  condition: string;
  /** 该动作对应的价位;无对应价位时为 null */
  price: number | null;
  /** 依据列表,每条引用一个输入里的具体数字 */
  basis: string[];
  /** now=此刻条件已满足 / armed=条件待触发 / blocked=已否决 */
  status: 'now' | 'armed' | 'blocked';
}

/** 做 T 计划(设计文档 §5.2 TPlan) */
export interface DecisionTPlan {
  suitable: boolean;
  tHigh: number | null;
  tLow: number | null;
  amplitudePct: number | null;
  sellTrigger: string;
  buybackTrigger: string;
  basePositionPct: string;
  /** suitable=false 时写明原因;suitable=true 时为空字符串 */
  unsuitableSignals: string;
  /** 空仓时为 true:做 T 需先有底仓 */
  needsPosition: boolean;
}

/** 市场环境(设计文档 §5.3 MarketContext) */
export interface DecisionMarketEnv {
  market: {
    state: string | null;
    upTotal: number | null;
    downTotal: number | null;
    flatTotal: number | null;
    limitUp: number | null;
    limitDown: number | null;
    sampleSize: number | null;
    changePct: number | null;
    summary: string;
  };
  sector: {
    industry: string | null;
    changePct: number | null;
    vsMarketPct: number | null;
    fundNetYi: number | null;
    fundDirection: 'in' | 'out' | null;
    state: string | null;
    summary: string;
    leading: { name: string; netYi: number }[];
  };
  stockFlow: {
    direction: string | null;
    amountWan: number | null;
    category: string | null;
    summary: string;
  };
  relative: {
    vsSectorPct: number | null;
    vsMarketPct: number | null;
    summary: string;
  };
  /** 本层降级说明(不编数字,只说明缺什么) */
  degraded: string[];
}

/** 决策输出(设计文档 §5.2 Decision) */
export interface StockDecision {
  stockCode: string;
  stockName: string | null;
  verdict: 'buy' | 'add' | 'hold' | 'reduce' | 'sell' | 'wait';
  /** 一句话结论(中文白话,含具体数字) */
  headline: string;
  confidence: 'high' | 'medium' | 'low';
  /** 建仓参考 / 止盈参考 / 解套参考 */
  role: string;
  positionStatus: 'empty' | 'profit' | 'loss';
  actions: DecisionAction[];
  stopLoss: { price: number; basis: string } | null;
  positionPct: string;
  doNot: string[];
  tPlan: DecisionTPlan | null;
  trendState: { phase: string; note: string };
  marketEnv: DecisionMarketEnv;
  dataQuality: { degraded: string[] };
  /* ---------- v0.10 操作建议区(设计文档 §6.8~§6.10) ---------- */
  /** 操作建议六格;单格为 null = 该维度数据不足(前端置灰占位,不编数字) */
  suggestions: DecisionSuggestions | null;
  /** 规则白话兜底(零 LLM,source 恒为 'rule');AI 不可用时的兜底文案 */
  advice: DecisionAdviceText | null;
  /** 网格交易配置建议;不适用时配置类字段全为 null(不给半截配置) */
  gridPlan: DecisionGridPlan | null;
  /** 成本锚点:浮盈亏 / 回本所需 / 距止损 / 到 P80 空间 / 风险收益比 */
  costAnchor: DecisionCostAnchor | null;
  /** 时间窗口:持有天数 / 起点来源 / 是否超期 / 超期文案 */
  timeWindow: DecisionTimeWindow | null;
  /** 费用影响:往返费率 / 费用档 / 做 T 差价是否划算 */
  costEffect: DecisionCostEffect | null;
  /** 品种规则:涨跌停 / 印花税 / T+0 */
  instrumentRule: DecisionInstrumentRule | null;
  /** 集中度:该票持仓成本占比 */
  concentration: DecisionConcentration | null;
}

/** 操作建议六格的一格(设计文档 §6.10) */
export interface DecisionSuggestionCell {
  label: string;
  value: string;
}

/** 操作建议六格:价位 / 止损 / 仓位 / 触发 / 时间 / 不动 */
export interface DecisionSuggestions {
  price: DecisionSuggestionCell | null;
  stopLoss: DecisionSuggestionCell | null;
  position: DecisionSuggestionCell | null;
  trigger: DecisionSuggestionCell | null;
  timing: DecisionSuggestionCell | null;
  avoid: DecisionSuggestionCell | null;
}

/** 网格交易配置建议(设计文档 §6.9);`mode`: add = 加仓网格 / base = 底仓高抛低吸 */
export interface DecisionGridPlan {
  suitable: boolean;
  mode: 'add' | 'base' | null;
  reason: string;
  rangeLow: number | null;
  rangeHigh: number | null;
  spanPct: number | null;
  grids: number | null;
  stepPct: number | null;
  stepPrice: number | null;
  sharesPerGrid: number | null;
  capitalPerGrid: number | null;
  cashNeeded: number | null;
  cashAvailable: number | null;
  netStepPct: number | null;
  roundtripFeePct: number | null;
  feeBasis: 'configured' | 'default_estimate' | null;
  netProfitPerGrid: number | null;
  /** 与做 T 互斥:两者都可行时为 true(择一,勿同时执行) */
  replaceTPlan: boolean;
  risk: string;
  unsuitableSignals: string;
}

/** 白话(规则兜底或 LLM 现场生成) */
export interface DecisionAdviceText {
  headline: string;
  bullets: string[];
  source: 'rule' | 'llm';
  generatedAt?: string;
}

/** `GET /api/stock/{code}/decision-advice` 响应 */
export interface DecisionAdviceResponse {
  advice: DecisionAdviceText;
  degraded: string[];
}

/** 成本锚点(设计文档 §6.8.1) */
export interface DecisionCostAnchor {
  costBasis: number | null;
  currentPrice: number | null;
  pnlPct: number | null;
  breakEvenGapPct: number | null;
  distanceToStopPct: number | null;
  distanceToTargetPct: number | null;
  riskReward: number | null;
}

/** 时间窗口(设计文档 §6.8.2) */
export interface DecisionTimeWindow {
  holdingDays: number | null;
  /** 'transactions' = 最早一笔流水(真实起点) / 'snapshot' = 快照导入日(建仓日未知) */
  source: 'transactions' | 'snapshot' | null;
  overdue: boolean | null;
  overdueText: string | null;
  note: string;
}

/** 费用影响(设计文档 §6.8.3) */
export interface DecisionCostEffect {
  roundtripFeePct: number | null;
  feeBasis: 'configured' | 'default_estimate' | null;
  spreadPct: number | null;
  worthIt: boolean | null;
  note: string;
}

/** 品种规则(设计文档 §6.8.4) */
export interface DecisionInstrumentRule {
  kind: string;
  t0: boolean;
  notes: string[];
}

/** 集中度(设计文档 §6.8.5) */
export interface DecisionConcentration {
  costSharePct: number | null;
  level: string;
  note: string;
}