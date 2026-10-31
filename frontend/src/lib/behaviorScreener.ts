/** 找股模块 API 封装(behavior-screener)
 *
 * ⚠️ 与 `lib/screener.ts` 的口径区别:
 * - 选股 `/screener`:按**因子打分**(主力净流入/量比/动能/板块强度/事件热度)排 Top 20
 * - 找股 `/behavior-screener`:按 **K 线行为信号命中**(主力异动/低吸/锁仓/高抛)分组
 *
 * 两者都在 NavRail「决策」组,页面须写清区别,避免用户以为数据应一致。
 */
import { apiGet } from '@/lib/api';

export interface BehaviorPick {
  stockCode: string;
  stockName: string | null;
  kind: 'main_force_move' | 'dip_buy' | 'lock_position' | 'distribute';
  kindLabel: string;
  signalDate: string | null;
  daysAgo: number;
  reason: string;
  metrics: Record<string, number | string | null>;
  score: number;
  changePct: number | null;
}

export interface BehaviorGroup {
  kind: BehaviorPick['kind'];
  kindLabel: string;
  count: number;
  picks: BehaviorPick[];
}

export interface BehaviorRun {
  id: number;
  runDate: string | null;
  generatedAt: string | null;
  poolSize: number;
  mainBoardCount: number;
  nonStCount: number;
  afterFiltersCount: number;
  candidatesConsidered: number;
  totalPicks: number;
  elapsedSec: number | null;
  note: string | null;
}

export interface BehaviorLatestResponse {
  run: BehaviorRun;
  groups: BehaviorGroup[];
  all: BehaviorPick[];
  kinds: { kind: BehaviorPick['kind']; label: string }[];
}

export interface BehaviorPoolResponse {
  /**
   * ⚠️ 必须是**驼峰**:axios 响应拦截器会递归把 snake_case 转成 camelCase
   * (`snakeToCamel`,见 lib/api.ts),运行期拿到的就是 `mainBoard`。
   * 类型写成 snake_case 的话 TS 不报错(泛型只是断言),但页面读出来全是
   * `undefined` —— 口径条会渲染成「主板 只 · 非 ST 只」这种**空数字**。
   */
  universe: {
    total: number;
    mainBoard: number;
    nonSt: number;
    afterFilters: number;
  } | null;
  candidatesConsidered: number;
  note: string | null;
}

/** 取最新一批找股结果(404 = 还没跑过) */
export function fetchBehaviorLatest() {
  return apiGet<BehaviorLatestResponse>('/behavior-screener/latest');
}

/** 取候选池口径统计 */
export function fetchBehaviorPool() {
  return apiGet<BehaviorPoolResponse>('/behavior-screener/pool');
}
