'use client';

import { Card } from '@/components/ui/Card';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Position } from '@/lib/types';

/**
 * 持仓表视图下的顶部统计卡片(替换选中股行情条)
 * 一行 3 项:总市值 · 总浮盈(带占比%)· 今日盈亏
 *
 * 数据纯来自 positions(与表格数据一致;现价缺失 → 该项计入 0,顶部显示 `--`)
 */
export function PositionStatsCards({ positions }: { positions: Position[] }) {
  const hasQuotes = positions.some((p) => p.currentPrice != null);

  const totalMarketValue = positions.reduce(
    (sum, p) =>
      p.currentPrice != null ? sum + p.shares * Number(p.currentPrice) : sum,
    0,
  );
  const totalCost = positions.reduce((sum, p) => sum + Number(p.totalCost), 0);
  const totalFloatingPnl = positions.reduce(
    (sum, p) => sum + Number(p.floatingPnl ?? 0),
    0,
  );
  const totalTodayPnl = positions.reduce(
    (sum, p) => sum + Number(p.todayPnl ?? 0),
    0,
  );
  const ratioPct =
    totalCost > 0 ? (totalFloatingPnl / totalCost) * 100 : null;

  const pctClass = (v: number) =>
    v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-text-pri';

  return (
    <Card padding="md" className="shrink-0 min-h-[80px]">
      <div className="grid grid-cols-3 gap-3">
        {/* 总市值 */}
        <div>
          <div className="text-text-sec text-xs mb-1">总市值</div>
          <div className="text-xl font-mono font-semibold">
            {hasQuotes ? `¥${decimalFormat(totalMarketValue.toFixed(2))}` : '--'}
          </div>
          <div className="text-xs text-text-ter mt-1">
            {hasQuotes ? 'Σ 股数 × 现价' : '行情暂不可用'}
          </div>
        </div>
        {/* 总浮盈(占比%) */}
        <div>
          <div className="text-text-sec text-xs mb-1">总浮盈</div>
          <div
            className={`text-xl font-mono font-semibold ${pctClass(totalFloatingPnl)}`}
          >
            {hasQuotes
              ? `${totalFloatingPnl >= 0 ? '+' : ''}¥${decimalFormat(totalFloatingPnl.toFixed(2))}`
              : '--'}
          </div>
          <div className="text-xs text-text-ter mt-1">
            {hasQuotes && ratioPct != null
              ? `占比 ${ratioPct >= 0 ? '+' : ''}${ratioPct.toFixed(2)}%`
              : '行情暂不可用'}
          </div>
        </div>
        {/* 今日盈亏 */}
        <div>
          <div className="text-text-sec text-xs mb-1">今日盈亏</div>
          <div
            className={`text-xl font-mono font-semibold ${pctClass(totalTodayPnl)}`}
          >
            {hasQuotes
              ? `${totalTodayPnl >= 0 ? '+' : ''}¥${decimalFormat(totalTodayPnl.toFixed(2))}`
              : '--'}
          </div>
          <div className="text-xs text-text-ter mt-1">
            {hasQuotes ? 'Σ 现价 − 昨收' : '行情暂不可用'}
          </div>
        </div>
      </div>
    </Card>
  );
}