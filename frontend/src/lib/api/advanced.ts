/**
 * 阶段1-5 新增能力的前端 API client。
 *
 * 类型严格对齐后端实际返回(已逐项核对 api/*.py 与对应 service 的 _to_dict),
 * 不按命名习惯臆测 —— 例如权重接口的 GET 返回 `factors` 而非 `weights`,
 * PUT 的请求体是 `{factors: [...]}` 而不是裸数组。
 */
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '@/lib/api';
import type { BattlePlan, BattlePlanScopeRow } from '@/lib/planTypes';

/* ============================================================
 * 阶段2 · 选股权重
 * ============================================================ */

export interface FactorWeight {
  key: string;
  label: string;
  description: string;
  weight: number;
  enabled: boolean;
  min: number;
  max: number;
}

export interface WeightsView {
  factors: FactorWeight[];
  maxTotal: number;
}

export interface WeightInput {
  key: string;
  weight: number;
  enabled: boolean;
}

export async function fetchWeights(): Promise<WeightsView> {
  return apiGet<WeightsView>('/screener/weights');
}

export async function saveWeights(factors: WeightInput[]): Promise<WeightsView> {
  // 后端 PUT body 是 {factors: [...]}
  return apiPut<WeightsView>('/screener/weights', { factors });
}

export async function resetWeights(): Promise<WeightsView> {
  return apiPost<WeightsView>('/screener/weights/reset');
}

/* ============================================================
 * 阶段2 · 回测
 * ============================================================ */

export interface BacktestMetrics {
  total_return_pct?: number;
  annual_return_pct?: number;
  max_drawdown_pct?: number;
  volatility_pct?: number;
  sharpe?: number | null;
  win_rate_pct?: number | null;
  profit_loss_ratio?: number | null;
  trade_count?: number;
  [k: string]: unknown;
}

export interface BacktestResult {
  metrics?: BacktestMetrics;
  equity_curve?: Array<{ date: string; equity: number }>;
  trades?: Array<Record<string, unknown>>;
  warnings?: string[];
  has_lookahead_bias?: boolean;
  [k: string]: unknown;
}

export interface BacktestRequest {
  days?: number;
  hold_days?: number;
  initial_capital?: number;
  max_positions?: number;
  slippage_bps?: number;
}

export interface WeightSet {
  label: string;
  /** {factor_name: weight} */
  weights: Record<string, number>;
}

export interface CompareWeightsRequest {
  weight_sets: WeightSet[];
  days?: number;
  hold_days?: number;
  initial_capital?: number;
  max_positions?: number;
}

export async function runSignalBacktest(payload: BacktestRequest): Promise<BacktestResult> {
  return apiPost<BacktestResult>('/backtest/signal', payload);
}

export interface CompareWeightsResult {
  ok: boolean;
  reason?: string;
  hasLookaheadBias?: boolean;
  note?: string;
  weightsSensitive?: boolean;
  results?: Record<
    string,
    {
      metrics: BacktestMetrics;
      maxTotalWeight: number;
      weights: Record<string, { value: number; enabled: boolean }>;
      selectedCount: number;
      tradedSymbols: number;
      selectedCodes: string[];
    }
  >;
}

export async function compareWeightsBacktest(
  payload: CompareWeightsRequest,
): Promise<CompareWeightsResult> {
  return apiPost<CompareWeightsResult>('/backtest/compare-weights', payload);
}

/* ============================================================
 * 阶段1 · 价格提醒
 * ============================================================ */

/** 叶子条件:{metric, op, value} */
export interface AlertLeaf {
  metric: string;
  op: string;
  value: number;
}

/** 条件组:{op:'and'|'or', conditions:[...]},可嵌套 */
export interface AlertGroup {
  op: 'and' | 'or';
  conditions: Array<AlertLeaf | AlertGroup>;
}

export type AlertConditions = AlertGroup;

export interface PriceAlertRule {
  id: number;
  stockCode: string;
  name: string | null;
  conditions: AlertConditions;
  conditionsText: string;
  cooldownSec: number;
  dailyLimit: number;
  expiresAt: string | null;
  enabled: boolean;
  channels: string[] | null;
  triggeredCount: number;
  lastTriggeredAt: string | null;
  createdAt: string | null;
}

export interface PriceAlertCreate {
  stock_code: string;
  conditions: AlertConditions;
  name?: string;
  cooldown_sec?: number;
  daily_limit?: number;
  channels?: string[] | null;
}

export interface AlertMeta {
  metrics: Array<{ value: string; label: string }>;
  ops: string[];
  groupOps: string[];
}

export async function fetchAlertMeta(): Promise<AlertMeta> {
  return apiGet<AlertMeta>('/price-alerts/meta/metrics');
}

export async function fetchPriceAlerts(
  stockCode?: string,
): Promise<{ items: PriceAlertRule[]; count: number }> {
  const q = stockCode ? `?stock_code=${encodeURIComponent(stockCode)}` : '';
  return apiGet<{ items: PriceAlertRule[]; count: number }>(`/price-alerts${q}`);
}

export async function createPriceAlert(payload: PriceAlertCreate): Promise<{ id: number }> {
  return apiPost<{ id: number }>('/price-alerts', payload);
}

export async function updatePriceAlert(
  id: number,
  payload: Partial<PriceAlertCreate> & { enabled?: boolean },
): Promise<{ ok: boolean }> {
  // 后端是 PATCH
  return apiPatch<{ ok: boolean }>(`/price-alerts/${id}`, payload);
}

export async function deletePriceAlert(id: number): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`/price-alerts/${id}`);
}

export async function testPriceAlert(
  id: number,
  payload: { price: number; change_pct?: number; volume_ratio?: number; turnover?: number },
): Promise<{ matched: boolean; conditions_text: string }> {
  return apiPost(`/price-alerts/${id}/test`, payload);
}

/* ============================================================
 * 阶段1 · 通知渠道
 * ============================================================ */

export interface NotifyChannelConfig {
  channel: string;
  label: string;
  enabled: boolean;
  configured: boolean;
  hint: string | null;
  lastOkAt: string | null;
  lastError: string | null;
}

export async function fetchNotifyChannels(): Promise<{ items: NotifyChannelConfig[] }> {
  return apiGet<{ items: NotifyChannelConfig[] }>('/notify/channels');
}

export async function saveNotifyChannel(
  channel: string,
  payload: { enabled: boolean; config: Record<string, string> },
): Promise<Record<string, unknown>> {
  return apiPut(`/notify/channels/${channel}`, payload);
}

export async function testNotifyChannel(
  channel: string,
): Promise<{ ok: boolean; detail?: string }> {
  return apiPost<{ ok: boolean; detail?: string }>(`/notify/channels/${channel}/test`);
}

/* ============================================================
 * 阶段3 · 模拟盘
 * ============================================================ */

export interface PaperAccount {
  id: number;
  name: string;
  initialCapital: string;
  cash: string;
  realizedPnl: string;
  autoFollow: boolean;
}

export interface PaperPosition {
  stockCode: string;
  stockName: string | null;
  shares: number;
  avgCost: string;
  currentPrice: number;
  marketValue: number;
  unrealizedPnl: number;
  unrealizedPct: number;
}

export interface PaperSummary {
  accountId: number;
  name: string;
  initialCapital: string;
  cash: string;
  marketValue: number;
  totalEquity: number;
  totalReturnPct: number;
  realizedPnl: string;
  positionCount: number;
  positions: PaperPosition[];
}

export interface PaperOrderRow {
  id: number;
  stockCode: string;
  stockName: string | null;
  action: 'buy' | 'sell';
  shares: number;
  price: string;
  fee: string;
  tradeDate: string;
  origin: string;
  note: string | null;
}

export async function fetchPaperAccounts(): Promise<{ items: PaperAccount[] }> {
  return apiGet<{ items: PaperAccount[] }>('/paper-trading/accounts');
}

export async function fetchPaperSummary(accountId: number): Promise<PaperSummary> {
  return apiGet<PaperSummary>(`/paper-trading/${accountId}/summary`);
}

export async function fetchPaperOrders(
  accountId: number,
  limit = 50,
): Promise<{ items: PaperOrderRow[] }> {
  return apiGet<{ items: PaperOrderRow[] }>(`/paper-trading/${accountId}/orders?limit=${limit}`);
}

export async function fetchPaperEquityCurve(accountId: number): Promise<{
  dates: string[];
  equity: number[];
  metrics: BacktestMetrics;
}> {
  return apiGet(`/paper-trading/${accountId}/equity-curve`);
}

export async function paperBuy(
  accountId: number,
  stockCode: string,
  shares: number,
): Promise<{ ok: boolean; fee: string }> {
  return apiPost(`/paper-trading/${accountId}/buy`, { stock_code: stockCode, shares });
}

export async function paperSell(
  accountId: number,
  stockCode: string,
  shares: number,
): Promise<{ ok: boolean; fee: string; realized_pnl: string }> {
  return apiPost(`/paper-trading/${accountId}/sell`, { stock_code: stockCode, shares });
}

/* ============================================================
 * 阶段4 · 多智能体 / 三段式
 * ============================================================ */

export interface AgentOpinion {
  role: string;
  label: string;
  stance: string;
  stanceLabel: string;
  confidence: number;
  argument: string;
  keyPoints: string[];
  degraded: boolean;
  degradedReason: string;
  latencyMs: number;
}

export interface DecisionReport {
  stockCode: string;
  stockName: string;
  opinions: AgentOpinion[];
  debateSummary: string;
  riskReview: string;
  riskFlags: string[];
  action: string;
  actionLabel: string;
  confidence: number;
  summary: string;
  keyLevels: Record<string, unknown>;
  disclaimer: string;
  degraded: boolean;
  model: string;
}

export async function fetchMultiAgentAnalysis(stockCode: string): Promise<DecisionReport> {
  return apiGet<DecisionReport>(`/multi-agent/${encodeURIComponent(stockCode)}`);
}

export interface WorkflowBrief {
  kind: string;
  title: string;
  summary: string;
  lines: string[];
  stockCodes: string[];
}

export async function fetchWorkflowSchedule(): Promise<{
  windows: Array<{ kind: string; at: string; hour: number; minute: number }>;
}> {
  return apiGet('/workflow/schedule');
}

export async function generatePremarketBrief(): Promise<WorkflowBrief> {
  return apiPost<WorkflowBrief>('/workflow/premarket');
}

export interface WorkflowDelivery {
  channel: string;
  ok: boolean;
  detail: string | null;
}

export interface WorkflowDispatchResult {
  kind: string;
  summary: string;
  delivered: WorkflowDelivery[];
}

/** 生成盘前简报并推送到已启用渠道(推送是副作用,调一次就真发出去了)。 */
export async function dispatchPremarketBrief(): Promise<WorkflowDispatchResult> {
  return apiPost<WorkflowDispatchResult>('/workflow/premarket/dispatch');
}

/** 盘中速览。slot 只能是 '11:30' 或 '14:50'(后端据此取不同的对比基准)。 */
export async function generateIntradayBrief(
  slot: '11:30' | '14:50',
  dispatch = false,
): Promise<WorkflowBrief & { delivered: WorkflowDelivery[] }> {
  return apiPost('/workflow/intraday', { slot, dispatch });
}

/* ============================================================
 * 阶段5 · 多账户
 * ============================================================ */

export interface AccountSummaryItem {
  id: number;
  name: string;
  kind: string;
  broker: string | null;
  note: string | null;
  isDefault: boolean;
  positionCount: number;
  totalCost: number;
  realizedPnl: number;
}

export interface AccountDetail extends AccountSummaryItem {
  marketValue: number;
  unrealizedPnl: number;
  positions: Array<{
    stockCode: string;
    stockName: string | null;
    shares: number;
    totalCost: number;
    realizedPnl: string;
    currentPrice: number;
    marketValue: number;
    unrealizedPnl: number;
    unrealizedPct: number;
  }>;
}

export async function fetchAccounts(): Promise<{ items: AccountSummaryItem[] }> {
  return apiGet<{ items: AccountSummaryItem[] }>('/accounts');
}

export async function fetchAccountDetail(id: number): Promise<AccountDetail> {
  return apiGet<AccountDetail>(`/accounts/${id}/summary`);
}

export async function createAccount(payload: {
  name: string;
  kind?: string;
  broker?: string | null;
  note?: string | null;
}): Promise<{ id: number }> {
  return apiPost<{ id: number }>('/accounts', payload);
}

export async function renameAccount(id: number, name: string): Promise<{ ok: boolean }> {
  // 后端是 PATCH
  return apiPatch<{ ok: boolean }>(`/accounts/${id}`, { name });
}

export async function deleteAccount(id: number): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`/accounts/${id}`);
}

/* ============================================================
 * 阶段5 · 引导中心
 * ============================================================ */

export interface GuideStep {
  key: string;
  title: string;
  description: string;
  actionLabel: string;
  actionHref: string;
  done: boolean;
  optional: boolean;
  detail: string;
}

export interface OnboardingStatus {
  steps: GuideStep[];
  progressPct: number;
  completed: number;
  requiredDone: number;
  requiredTotal: number;
  finished: boolean;
}

export async function fetchOnboarding(): Promise<OnboardingStatus> {
  return apiGet<OnboardingStatus>('/onboarding');
}

/* ============================================================
 * 阶段9 每日作战计划
 * ============================================================ */

/** 作战计划生成要拉 11 只票的行情,默认 10s 超时不够 */
const PLAN_TIMEOUT = { timeout: 60000 };

export async function fetchBattlePlan(date?: string): Promise<BattlePlan> {
  const q = date ? `?date=${encodeURIComponent(date)}` : '';
  // ⚠️ expectedNotFound:本次请求的 404 = 「今天的作战计划还没生成」,是**正常业务语义**
  // (后端 API 契约如此,见 backend/app/api/battle_plan.py),由 PlanPanel 走空态分支。
  // 关掉 404 的错误 toast,避免把正常状态渲染成错误。
  // 只影响 404:500/422/网络错误照常弹 toast;错误仍然 reject,PlanPanel 的
  // `e.response.status === 404` 判定不受影响。
  return apiGet<BattlePlan>(`/battle-plan${q}`, { expectedNotFound: true });
}

export async function generateBattlePlan(date?: string): Promise<BattlePlan> {
  return apiPost<BattlePlan>('/battle-plan/generate', { date: date ?? null }, PLAN_TIMEOUT);
}

export async function fetchBattlePlanScope(): Promise<BattlePlanScopeRow[]> {
  // ⚠️ 响应经 axios 拦截器做过 snake→camel(见 lib/api.ts),
  // 所以运行时拿到的是 stockCode / stockName / inPosition / isFavorite —— 类型必须按驼峰写,
  // 写成 snake_case 的话 TS 不报错(泛型是断言),但页面读出来全是 undefined。
  // ⚠️ 必须写显式泛型,否则返回 any,ScopeRow 的字段拼错也没人拦。
  return apiGet<BattlePlanScopeRow[]>('/battle-plan/scope');
}
