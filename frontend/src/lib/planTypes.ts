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