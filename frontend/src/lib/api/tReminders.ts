/**
 * 补T待接回 / 待卖出清单 API client
 *
 * 口径见后端 `app/modules/portfolio/api_t_reminders.py`:
 * 全链双向 FIFO 配对后**还没闭合的开腿**就是还挂着的做T单,分两组:
 * - 反T reverse = 先卖后买 → 待接回(不亏本接回线 = 净卖出加权均价,三档往下)
 * - 正T forward = 先买后卖 → 待卖出(买入加权均价,三档往上)
 *
 * 三档建议价(1% / 2% / 3%)每档都带「按这一档成交之后的摊薄成本线」。
 */
import { apiGet } from '@/lib/api';

/** 一档建议价 + 按这一档成交后的成本前→后 */
export interface TTier {
  /** 档位号(1/2/3) */
  tier: number;
  /** 档位名(一档/二档/三档) */
  label: string;
  /** 这一档的价格 */
  price: number;
  /** 相对基准线的幅度(0.01 = 1%) */
  offsetPct: number;
  /** 当前成本线(摊薄成本价,券商口径);没有持仓时为 null */
  costBefore: number | null;
  /** 按这一档成交之后的成本线;算不出来时为 null */
  costAfter: number | null;
  /** 这一档的取舍说明 */
  hint: string;
}

export interface TReminderItem {
  stockCode: string;
  stockName: string | null;
  /** reverse = 反T(先卖后买,待接回) / forward = 正T(先买后卖,待卖出) */
  direction: 'reverse' | 'forward';
  /** 待接回 / 待卖出的股数 */
  shares: number;
  /** 反T:不亏本接回线;正T:买入加权均价 */
  price: number;
  /** 一档建议价(兼容字段) —— 反T=建议接回价,正T=建议卖出价 */
  suggestedPrice: number | null;
  /** 三档建议价 + 每档成交后的成本前→后 */
  tiers: TTier[];
  /** 挂单起始日(该组最早未闭合开腿的日期) */
  openDate: string;
  /** 当前持仓股数 */
  positionShares: number | null;
  /** 现价(行情不可用时为 null) */
  currentPrice: number | null;
  /** 到价提醒 id */
  alertId: number | null;
  /** 该提醒的触发价 */
  alertPrice: number | null;
  /** 该提醒落在第几档 */
  alertTier: number | null;
  /** 该提醒是不是系统自动建的 */
  alertAuto: boolean;
  /** 用户自己建的到价提醒 id */
  manualAlertId: number | null;
  /** 用户自己建的到价提醒触发价 */
  manualAlertPrice: number | null;
  // ---- 预警(到价之前先给一次「准备」信号)----
  /** 预警提醒 id */
  preAlertId: number | null;
  /** 预警线价格(= 生效到价线朝基准线方向再退 1%) */
  preAlertPrice: number | null;
  /** 这条预警是不是已经响过了(一次性提醒命中后自动停用) */
  preAlertFired: boolean;
  /** 距到价线还差百分之几(绝对值);现价未知 → null */
  preAlertDistancePct: number | null;
  /** 现价是否已经越过到价线 */
  preAlertReached: boolean;
  /** 现价是否已经进入预警区(该准备了) */
  preAlertInZone: boolean;
  /** 当前成本线(持仓摊薄成本价,券商口径) */
  costBefore: number | null;
  /** 按一档建议价成交之后的成本线(摊薄成本) */
  costAfter: number | null;
}

export interface TReminderList {
  /** 待接回(反T:先卖后买) */
  items: TReminderItem[];
  count: number;
  /** 待卖出(正T:先买后卖) */
  forwardItems: TReminderItem[];
  forwardCount: number;
  /** 两组合计 */
  totalCount: number;
  /** 清单基准日 */
  asOf: string | null;
  /** 本次同步自动新建的到价提醒条数 */
  autoAlertsCreated: number;
  /** 本次同步自动停用的到价提醒条数 */
  autoAlertsDisabled: number;
  /** 本次同步把自动提醒的价格拉回一档的条数 */
  autoAlertsRealigned: number;
  /** 本次同步新建的预警提醒条数 */
  preAlertsCreated: number;
  /** 本次同步把已响过的预警提醒重新武装的条数(价格离开预警区了) */
  preAlertsRearmed: number;
  /** 本次同步停用的预警提醒条数(挂单已消失) */
  preAlertsDisabled: number;
  /** 本次同步把预警线就地改掉的条数 */
  preAlertsRealigned: number;
}

export async function fetchPendingTReminders(): Promise<TReminderList> {
  return apiGet<TReminderList>('/t-reminders/pending');
}
