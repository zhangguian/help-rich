'use client';

import clsx from 'clsx';

import { TermHint } from '@/components/ui/TermHint';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Position } from '@/lib/types';

/**
 * 持仓总览表格(持仓 tab 中间区,K线切换的另一种视图)
 *
 * - 9 列只读:代码/名称 | 现价 | 今日涨幅% | 持仓股数 | 加权成本 | 持仓资金 | 今日盈亏 | 浮动盈亏 | 已实现盈亏
 * - 行点击 → onSelect(stockCode):联动左右 aside(WatchList 高亮 / AnalysisPanel+ChatPanel 切股)
 * - 不持有选择 state,不显示选中行高亮(视觉反馈由左 aside 负责)
 * - 数据来自 page.tsx 已有 positions(已含 currentPrice/prevClose/todayPnl/floatingPnl/realizedPnl)
 * - 红涨绿跌(沿用全局 pctClass 约定)
 */
export function PositionSummaryTable({
  positions,
  onSelect,
}: {
  positions: Position[];
  onSelect?: (stockCode: string) => void;
}) {
  const pctClass = (v: number | null) =>
    v == null
      ? 'text-text-ter'
      : v > 0
        ? 'text-up'
        : v < 0
          ? 'text-down'
          : 'text-text-ter';

  const changePctOf = (p: Position): number | null => {
    const cur = p.currentPrice != null ? Number(p.currentPrice) : null;
    const prev = p.prevClose != null ? Number(p.prevClose) : null;
    if (cur == null || prev == null || prev <= 0) return null;
    return ((cur - prev) / prev) * 100;
  };

  return (
    <div className="flex-1 min-h-0 liquid-glass rounded-2xl p-4 overflow-y-auto">
      {positions.length === 0 ? (
        <div className="flex items-center justify-center h-full">
          <p className="text-text-ter text-sm">暂无持仓</p>
        </div>
      ) : (
        <table className="w-full text-sm font-mono">
          <thead className="sticky top-0 bg-bg-base/80 backdrop-blur-sm">
            <tr className="text-text-ter text-xs">
              <th className="text-left py-2 px-2 font-normal">股票</th>
              <th className="text-right py-2 px-2 font-normal">现价</th>
              <th className="text-right py-2 px-2 font-normal">今日%</th>
              <th className="text-right py-2 px-2 font-normal">持仓</th>
              <th className="text-right py-2 px-2 font-normal">加权成本</th>
              <th className="text-right py-2 px-2 font-normal">
                <span className="inline-flex items-center">
                  持仓资金<TermHint term="total_cost" />
                </span>
              </th>
              <th className="text-right py-2 px-2 font-normal">今日盈亏</th>
              <th className="text-right py-2 px-2 font-normal">浮动盈亏</th>
              <th className="text-right py-2 px-2 font-normal">已实现</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const cur =
                p.currentPrice != null ? Number(p.currentPrice) : null;
              const prev =
                p.prevClose != null ? Number(p.prevClose) : null;
              const changePct = changePctOf(p);
              const today =
                p.todayPnl != null ? Number(p.todayPnl) : null;
              const floating =
                p.floatingPnl != null ? Number(p.floatingPnl) : null;
              const realized = Number(p.realizedPnl);

              return (
                <tr
                  key={p.stockCode}
                  onClick={() => onSelect?.(p.stockCode)}
                  className="border-t border-white/5 hover:bg-white/3 cursor-pointer"
                >
                  <td className="py-2 px-2">
                    <div className="text-text-pri font-semibold font-sans truncate max-w-[10rem]">
                      {p.stockName ?? p.stockCode}
                    </div>
                    <div className="text-text-ter text-xs">{p.stockCode}</div>
                  </td>
                  <td
                    className={clsx(
                      'py-2 px-2 text-right',
                      pctClass(
                        cur != null && prev != null && cur !== prev
                          ? cur - prev
                          : null,
                      ),
                    )}
                  >
                    {cur != null ? `¥${decimalFormat(p.currentPrice!)}` : '--'}
                  </td>
                  <td className={clsx('py-2 px-2 text-right', pctClass(changePct))}>
                    {changePct != null
                      ? `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%`
                      : '--'}
                  </td>
                  <td className="py-2 px-2 text-right text-text-pri">
                    {p.shares.toLocaleString()}
                  </td>
                  <td className="py-2 px-2 text-right text-text-sec">
                    ¥{decimalFormat(p.avgCost)}
                  </td>
                  <td className="py-2 px-2 text-right text-text-pri">
                    ¥{decimalFormat(p.totalCost)}
                  </td>
                  <td className={clsx('py-2 px-2 text-right', pctClass(today))}>
                    {today != null
                      ? `${today >= 0 ? '+' : ''}¥${decimalFormat(String(today))}`
                      : '--'}
                  </td>
                  <td
                    className={clsx('py-2 px-2 text-right', pctClass(floating))}
                  >
                    {floating != null
                      ? `${floating >= 0 ? '+' : ''}¥${decimalFormat(String(floating))}`
                      : '--'}
                  </td>
                  <td className={clsx('py-2 px-2 text-right', pctClass(realized))}>
                    {`${realized >= 0 ? '+' : ''}¥${decimalFormat(String(realized))}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}