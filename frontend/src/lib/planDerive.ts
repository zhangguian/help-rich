/* ============================================================
 * 作战计划 v2 · 派生层(纯函数,零 IO)
 *
 * 为什么单独抽一层:
 * 左栏「股票锚点栏」与中栏「票头」要显示**同一份**「最新操作要求」
 * 与**同一套**兑现徽章。两处各算一遍 → 必然漂移(一处显示「减仓」,
 * 另一处显示「止损」),而用户会以为页面自相矛盾。
 * 所以:算一次,两处渲染。
 *
 * ⚠️ 字段名一律驼峰(axios 拦截器已把 snake_case 转好,见 lib/api.ts)。
 * ============================================================ */

import type {
  BattlePlanItem,
  BattlePlanPoolMeta,
  BattlePlanQuote,
  BattlePlanScopeRow,
} from './planTypes';

/** 股票级兑现状态 —— 与后端 `aggregate_stock_status` 同一套优先级 */
export type StockFulfillment = 'executed' | 'touched' | 'missed' | 'no_data' | 'n_a';

/**
 * 优先级:executed > touched > missed > no_data > n_a
 *
 * 「达到预期」= 触及 或 执行(用户口径);只有 missed 计入连续未达天数。
 * no_data / n_a **不参与**判定,只作为兜底状态展示。
 */
const FULFILLMENT_PRIORITY: Record<string, number> = {
  executed: 5,
  touched: 4,
  missed: 3,
  no_data: 2,
  n_a: 1,
};

/**
 * 昨日逐条兑现 → 股票级兑现(code → 状态)
 *
 * 一只票可能有多条预案;池与锚点栏关心的是「这只票昨天有没有达到预期」。
 * `pending` 不进 map —— 它是「还没到判定的时候」,不是一种判定结果。
 */
export function aggregateStockFulfillment(
  items: Array<{ stockCode: string; fulfillment: string }> | undefined | null,
): Map<string, StockFulfillment> {
  const out = new Map<string, StockFulfillment>();
  for (const it of items ?? []) {
    const code = it.stockCode;
    if (!code) continue;
    const st = it.fulfillment as StockFulfillment;
    const prio = FULFILLMENT_PRIORITY[st];
    if (prio === undefined) continue;
    const cur = out.get(code);
    if (!cur || prio > (FULFILLMENT_PRIORITY[cur] ?? 0)) out.set(code, st);
  }
  return out;
}

/** 取条件首句 —— 「最新操作要求」要的是一句话摘要,不是整段条件 */
function firstClause(text: string | null | undefined): string {
  if (!text) return '';
  const head = text.split(/[，,。;；]/)[0] ?? '';
  return head.trim();
}

/**
 * 「最新操作要求」—— 唯一事实源
 *
 * 取值顺序:
 * 1. `status_now === 'now'` 的第一条(条件已满足、待执行)
 * 2. `status_now === 'armed'` 的第一条(待触发)
 * 3. 第一条预案(拿不到状态就按列表顺序)
 * 4. 都没有 → 「暂无待执行动作,仅观察」
 *
 * ⚠️ 条件为空时退回 `label + 触发价` —— 不能显示成空白,
 * 空白会让人以为这条票没有预案。
 */
export function requirementOf(items: BattlePlanItem[] | undefined | null): string {
  const list = items ?? [];
  if (list.length === 0) return '暂无待执行动作,仅观察';
  const pick =
    list.find((i) => i.statusNow === 'now') ??
    list.find((i) => i.statusNow === 'armed') ??
    list[0];
  if (!pick) return '暂无待执行动作,仅观察';
  const clause = firstClause(pick.triggerCondition);
  if (clause) return clause;
  const price = pick.triggerPrice != null ? ` ${pick.triggerPrice.toFixed(2)}` : '';
  return `${pick.label}${price}`;
}

/** 锚点栏里的一只票 */
export interface RailStock {
  code: string;
  name: string;
  price: number | null;
  changePct: number | null;
  inPosition: boolean;
  isFavorite: boolean;
  /** 来自全市场滚动池 */
  isPool: boolean;
  /** kept = 保留在池 | added = 新补位 */
  poolState: string | null;
  /** 4 因子总分 */
  poolScore: number | null;
  /** 入选理由 */
  poolReason: string;
  /** 连续未达预期天数 */
  missStreak: number;
  /** 「这只为什么还在池里」 */
  streakNote: string;
  /** 昨日股票级兑现状态 */
  fulfillment: StockFulfillment | null;
  /** 最新操作要求 */
  requirement: string;
  /** 已被剔除出池 */
  dropped: boolean;
  /** 剔除原因 */
  dropReason: string;
}

/** 锚点栏分组 */
export interface RailGroups {
  positions: RailStock[];
  favorites: RailStock[];
  pool: RailStock[];
  /** 被剔除的票 —— 仍留在锚点栏(标灰 + 原因),便于回看「这只为什么被换掉」 */
  dropped: RailStock[];
}

/**
 * 组装锚点栏数据
 *
 * 分组口径(与视觉稿一致):
 * - 持仓组:持仓票(**同时是 ★关注的也在这里**,行内再挂一个 ★ 徽章)
 * - ★关注组:只关注、没持仓的
 * - 池组:全市场滚动池成员(与自选去重,不会重复出现在前两组)
 * - 已剔除:被踢出池的票,标灰留在池组末尾
 */
export function buildRailGroups(
  scope: BattlePlanScopeRow[] | undefined | null,
  pool: BattlePlanPoolMeta | null | undefined,
  quotes: Record<string, BattlePlanQuote> | undefined | null,
  items: BattlePlanItem[] | undefined | null,
  fulfillment: Map<string, StockFulfillment>,
): RailGroups {
  const quoteOf = (code: string): BattlePlanQuote => ({
    price: quotes?.[code]?.price ?? null,
    changePct: quotes?.[code]?.changePct ?? null,
  });

  // 逐票预案 → code → 该票的预案列表(算「最新操作要求」用)
  const itemsByCode = new Map<string, BattlePlanItem[]>();
  for (const it of items ?? []) {
    const arr = itemsByCode.get(it.stockCode) ?? [];
    arr.push(it);
    itemsByCode.set(it.stockCode, arr);
  }

  const positions: RailStock[] = [];
  const favorites: RailStock[] = [];

  for (const s of scope ?? []) {
    const q = quoteOf(s.stockCode);
    const row: RailStock = {
      code: s.stockCode,
      name: s.stockName ?? s.stockCode,
      price: q.price,
      changePct: q.changePct,
      inPosition: s.inPosition,
      isFavorite: s.isFavorite,
      isPool: false,
      poolState: null,
      poolScore: null,
      poolReason: '',
      missStreak: 0,
      streakNote: '',
      fulfillment: fulfillment.get(s.stockCode) ?? null,
      requirement: requirementOf(itemsByCode.get(s.stockCode)),
      dropped: false,
      dropReason: '',
    };
    if (s.inPosition) positions.push(row);
    else if (s.isFavorite) favorites.push(row);
  }

  const poolRows: RailStock[] = (pool?.members ?? []).map((m) => {
    const q = quoteOf(m.stockCode);
    return {
      code: m.stockCode,
      name: m.stockName ?? m.stockCode,
      price: q.price,
      changePct: q.changePct,
      inPosition: false,
      isFavorite: false,
      isPool: true,
      poolState: m.state,
      poolScore: m.score,
      poolReason: m.reason,
      missStreak: m.missStreak,
      streakNote: m.streakNote,
      fulfillment: fulfillment.get(m.stockCode) ?? null,
      requirement: requirementOf(itemsByCode.get(m.stockCode)),
      dropped: false,
      dropReason: '',
    };
  });

  const droppedRows: RailStock[] = (pool?.dropped ?? []).map((d) => {
    const q = quoteOf(d.stockCode);
    return {
      code: d.stockCode,
      name: d.stockName ?? d.stockCode,
      price: q.price,
      changePct: q.changePct,
      inPosition: false,
      isFavorite: false,
      isPool: true,
      poolState: 'dropped',
      poolScore: null,
      poolReason: '',
      missStreak: d.missStreak,
      streakNote: '',
      fulfillment: fulfillment.get(d.stockCode) ?? null,
      requirement: '今日不再跟踪',
      dropped: true,
      dropReason: d.reason,
    };
  });

  return { positions, favorites, pool: poolRows, dropped: droppedRows };
}

/**
 * 兑现状态 → 徽章文案
 *
 * 「已触及 / 已执行」= 达到了预期 → 绿色(与视觉稿一致);
 * 「未达预期」= 红色;「未判定」= 灰(缺数据,不惩罚股票)。
 */
export type FulfillmentTone = 'positive' | 'negative' | 'neutral';

export const FULFILLMENT_BADGE: Record<StockFulfillment, { label: string; tone: FulfillmentTone }> = {
  executed: { label: '昨日已执行', tone: 'positive' },
  touched: { label: '昨日已触及', tone: 'positive' },
  missed: { label: '昨日未达预期', tone: 'negative' },
  no_data: { label: '昨日未判定', tone: 'neutral' },
  n_a: { label: '昨日不适用', tone: 'neutral' },
};
