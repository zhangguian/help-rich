/**
 * 做T操作历史 API client
 *
 * 口径见后端 `app/modules/portfolio/api_t_history.py`:
 * 做T有**两个方向**,腿的先后顺序不同:
 * - 反T reverse = 先卖出、后买回(高抛低吸)
 * - 正T forward = 先买入、后卖出(低吸高抛)
 * 按链全序双向 FIFO 配对;链尾还挂着的开腿 = 待接回(反T) / 待卖出(正T)。
 * 每条给两个盈亏口径:
 * - `tPnl`        做T差价盈亏 = (卖出价 − 买入价) × T股数(两方向都是低买高卖赚差价)
 * - `realizedPnl` 卖出确认的已实现盈亏 = (卖出价 − 卖出那一刻的摊薄成本) × 股数
 * 成本价取自成本链;基准吸收的早期流水没有逐笔成本 → 成本字段为 null。
 */
import { apiGet } from '@/lib/api';

export interface THistoryItem {
  /** closed = 两腿都齐了;pending = 还挂着一条腿(等另一条来闭合) */
  status: 'closed' | 'pending';
  /** reverse = 反T(先卖后买) / forward = 正T(先买后卖) */
  direction: 'reverse' | 'forward';
  /** 卖出那一笔(正T未闭合时为 null —— 还没卖) */
  sellTxId: number | null;
  sellDate: string | null;
  sellPrice: number | null;
  /** 买入那一笔(反T未闭合时为 null —— 还没买回) */
  buyTxId: number | null;
  buyDate: string | null;
  buyPrice: number | null;
  /** 做T股数 */
  shares: number;
  /** T 前成本价(开腿那一刻的持仓摊薄成本,券商口径) */
  costBefore: number | null;
  /** T 后成本价(收腿之后的持仓摊薄成本,券商口径) */
  costAfter: number | null;
  /** 做T差价盈亏 */
  tPnl: number | null;
  /** 卖出确认的已实现盈亏 */
  realizedPnl: number | null;
}

export interface THistory {
  stockCode: string;
  stockName: string | null;
  items: THistoryItem[];
  count: number;
  /** 基准吸收的流水 id 上界 —— <= 它的流水没有逐笔成本,成本字段为 null */
  baseTxId: number;
}

export async function fetchTHistory(stockCode: string): Promise<THistory> {
  return apiGet<THistory>(`/t-history/${encodeURIComponent(stockCode)}`);
}
