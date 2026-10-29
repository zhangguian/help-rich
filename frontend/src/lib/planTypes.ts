/* ============================================================
 * 每日作战计划(阶段9)类型
 *
 * ⚠️ 独立文件,不进 src/lib/types.ts ——
 *    那个文件会被 `npm run gen-types`(openapi-typescript -o src/lib/types.ts)整体覆盖。
 *    本文件的类型是手写的,后端没有 schema 化到 OpenAPI。
 *
 * ⚠️ 字段名一律**驼峰** —— axios 响应拦截器把后端的 snake_case
 *    递归转成了 camelCase(见 src/lib/api.ts 的 snakeToCamel),
 *    运行时拿到的是驼峰键。写成 snake_case 的话 TS 不报错(泛型只是断言),
 *    但页面读出来全是 undefined。
 * ============================================================ */

export type BattlePlanStance = 'bullish' | 'bearish' | 'neutral' | 'unknown';

export interface BattlePlanDim {
  key: string;
  label: string;
  score: number;
  state: 'bull' | 'bear' | 'flat' | 'missing';
  detail: string;
}

export interface BattlePlanKeyLevels {
  close: number | null;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  support: number[];
  resistance: number[];
}

export interface BattlePlanOutlook {
  stance: BattlePlanStance;
  stanceLabel: string;
  score: number;
  dimsTotal: number;
  dimsEffective: number;
  dims: BattlePlanDim[];
  keyLevels: BattlePlanKeyLevels;
  disclaimer: string;
  degraded: boolean;
  degradedReason: string[];
}

export interface BattlePlanItem {
  id?: number;
  /**
   * 后端 `_row_to_item` 返回的 `plan_id`(拦截器转成 `planId`)。
   * ⚠️ 只有**库里那一份** items 才有这三个字段(GET /api/battle-plan);
   * POST /generate 直接返回编排层算出的 items,没有它们 → 必须可选。
   */
  planId?: number;
  /** 后端 `_row_to_item` 返回的 `plan_date`(拦截器转成 `planDate`) */
  planDate?: string;
  stockCode: string;
  stockName: string | null;
  itemKind: string;
  direction: 'buy' | 'sell' | 'none';
  label: string;
  triggerPrice: number | null;
  triggerCondition: string;
  basis: string[];
  invalidIf: string;
  statusNow: 'now' | 'armed' | 'blocked';
  /** 溯源:decision.actions / decision.stop_loss / decision.t_plan / decision.do_not */
  source: string;
  /** `no_data` = 目标日无该票行情数据 → 未判定(不计入统计) */
  fulfillment: 'pending' | 'touched' | 'executed' | 'missed' | 'n_a' | 'no_data';
  fulfillmentNote: string;
}

export interface BattlePlanTodo {
  stockCode: string;
  stockName: string | null;
  label: string;
  condition: string;
  price: number | null;
  basis: string[];
}

export interface BattlePlanFulfillment {
  total: number;
  executed: number;
  touched: number;
  missed: number;
  na: number;
  /** 目标日无行情数据 → 未判定(不计入统计) */
  noData: number;
  discipline: number;
  verdictLabel: string;
  verdictLevel: 'ok' | 'warn' | 'danger' | 'flat';
  items?: Array<{
    stockCode: string;
    stockName: string | null;
    label: string;
    itemKind: string;
    fulfillment: string;
    note: string;
  }>;
}

/** 今日大盘实况(D 当天)—— 事实转述,不含任何指标推断 */
export interface BattlePlanMarket {
  indexClose: number | null;
  changePct: number | null;
  volumeNote: string | null;
}

export interface BattlePlanReview {
  market: BattlePlanMarket | null;
  fulfillment: BattlePlanFulfillment | null;
  /** 今日待办(now 动作)—— 早于该字段落库的日报可能没有它,故可选 */
  pendingTodos?: BattlePlanTodo[];
  note: string | null;
}

export interface BattlePlanMeta {
  scopeCount: number;
  scope: Array<{
    stockCode: string;
    stockName: string | null;
    inPosition: boolean;
    isFavorite: boolean;
  }>;
  truncated: boolean;
  degraded: boolean;
  degradedReason: string[];
  generatedAt: string;
  targetDate: string | null;
  targetDateEstimated: boolean;
  /** 重新生成时保留了原有 items(已有兑现判定)—— 见 spec §4.6.3 */
  itemsPreserved?: boolean;
  /** 全市场滚动池(作战计划 v2)—— 缺省 = 该日报是 v2 之前生成的 */
  pool?: BattlePlanPoolMeta;
  /** 各票现价与涨跌幅 —— 左栏锚点栏用 */
  quotes?: Record<string, BattlePlanQuote>;
  /** 各阶段耗时(秒) */
  timings?: Record<string, number>;
}

/** 全市场选股口径统计 —— 空态要写明「全市场 → 主板 → 非 ST → 成交额达标」 */
export interface BattlePlanUniverse {
  /** 全市场只数 */
  total: number;
  /** 沪深主板 */
  mainBoard: number;
  /** 剔除 ST 之后 */
  nonSt: number;
  /** 过完全部闸门之后 */
  afterFilters: number;
  /** 成交额下限(亿元) */
  minAmountYi: number;
}

/** 池内一只 */
export interface BattlePlanPoolMember {
  stockCode: string;
  stockName: string | null;
  /** 4 因子总分 */
  score: number | null;
  /** 入选理由(给人看的白话) */
  reason: string;
  /** kept = 保留在池 | added = 新补位 */
  state: string;
  /** 连续未达预期天数 */
  missStreak: number;
  /** 昨日股票级兑现状态 */
  lastStatus: string | null;
  /** 「这只为什么还在池里」 */
  streakNote: string;
}

/** 被剔除出池的一只 */
export interface BattlePlanPoolDropped {
  stockCode: string;
  stockName: string | null;
  missStreak: number;
  reason: string;
}

export interface BattlePlanPoolMeta {
  /** 池上限 */
  limit: number;
  members: BattlePlanPoolMember[];
  /** 被剔除的票 —— 仍留在锚点栏里(标灰 + 原因),便于回看「这只为什么被换掉」 */
  dropped: BattlePlanPoolDropped[];
  /** 本次打分看过的候选数 */
  candidatesConsidered: number;
  universe?: BattlePlanUniverse | null;
}

/** 单只票的现价与涨跌幅 */
export interface BattlePlanQuote {
  price: number | null;
  changePct: number | null;
}

export interface BattlePlan {
  planDate: string;
  targetDate: string | null;
  /** 非 null —— 端点层保证:落库日报缺 outlook 时会填一个降级的空 outlook(spec §4.6.4) */
  outlook: BattlePlanOutlook;
  review: BattlePlanReview | null;
  items: BattlePlanItem[];
  /**
   * ⚠️ **没有顶层 `todos`** —— 待办统一在 `review.pendingTodos`。
   * 契约对称性:POST 与 GET 返回的字段集必须一致,否则前端切到 GET 时待办会凭空消失。
   */
  meta: BattlePlanMeta;
}

/** 目标股票池(持仓 ∪ ★关注) */
export interface BattlePlanScopeRow {
  stockCode: string;
  stockName: string | null;
  inPosition: boolean;
  isFavorite: boolean;
}

/**
 * `/battle-plan/scope` 的返回(**2026-10-25 破坏性变更**:list → 对象)
 *
 * - `watchlist`:持仓 ∪ ★关注
 * - `pool`:**当前**在池成员(读 `battle_plan_pool` 表,不是「今天会选出什么」)
 * - `universe`:全市场口径统计;快照不可用 → null
 */
export interface BattlePlanScopeResponse {
  watchlist: BattlePlanScopeRow[];
  pool: Array<{
    stockCode: string;
    stockName: string | null;
    missStreak: number;
    lastStatus: string | null;
    lastScore: number | null;
    joinedOn: string;
  }>;
  universe: BattlePlanUniverse | null;
}