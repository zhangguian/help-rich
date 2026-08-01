'use client';

import clsx from 'clsx';

import { StopLossButton } from '@/components/stop-loss/StopLossButton';
import { Card } from '@/components/ui/Card';
import { useStopLossChecker } from '@/hooks/useStopLossChecker';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Position } from '@/lib/types';

/**
 * 持仓列表(Client 包装,P5.3/P5.5 集成)
 *
 * - 每只持仓卡:右侧 [+ 设止损] / [🛡 ¥价格][⚡][🗑]
 * - 轮询检查:15s 拉最新行情,触达止损 → 弹 StopLossAlert
 */
export function PositionsList({ positions }: { positions: Position[] }) {
  const { alertEl } = useStopLossChecker(positions);

  const pnlClass = (v: number | null) =>
    v === null ? 'text-text-ter' : v >= 0 ? 'text-up' : 'text-down';

  return (
    <>
      <div className="space-y-3">
        {positions.map((p) => {
          const today = Number(p.todayPnl ?? 0);
          const floating = Number(p.floatingPnl ?? 0);
          return (
            <Card key={p.stockCode} padding="md">
              <div className="flex items-center justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="font-semibold truncate">
                    {p.stockName ?? p.stockCode}
                    <span className="text-text-ter text-sm ml-2 font-mono">
                      {p.stockCode}
                    </span>
                  </div>
                  <div className="text-sm text-text-sec mt-1">
                    持仓 <span className="font-mono">{p.shares}</span> 股 ·
                    加权成本 ¥
                    <span className="font-mono">
                      {decimalFormat(p.avgCost)}
                    </span>
                    {p.currentPrice !== null && (
                      <>
                        {' · 现价 '}
                        <span className="font-mono">
                          ¥{decimalFormat(p.currentPrice)}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                <div className="text-right space-y-1">
                  <div>
                    <span className="text-xs text-text-ter mr-2">
                      今日盈亏
                    </span>
                    <span
                      className={clsx(
                        'font-mono font-semibold',
                        pnlClass(p.todayPnl === null ? null : today),
                      )}
                    >
                      {p.todayPnl !== null
                        ? `¥${decimalFormat(p.todayPnl)}`
                        : '--'}
                    </span>
                  </div>
                  <div>
                    <span className="text-xs text-text-ter mr-2">
                      浮动盈亏
                    </span>
                    <span
                      className={clsx(
                        'font-mono font-semibold',
                        pnlClass(p.floatingPnl === null ? null : floating),
                      )}
                    >
                      {p.floatingPnl !== null
                        ? `¥${decimalFormat(p.floatingPnl)}`
                        : '--'}
                    </span>
                  </div>
                  <div>
                    <span className="text-xs text-text-ter mr-2">
                      已实现盈亏
                    </span>
                    <span
                      className={clsx(
                        'font-mono font-semibold',
                        pnlClass(Number(p.realizedPnl)),
                      )}
                    >
                      ¥{decimalFormat(p.realizedPnl)}
                    </span>
                  </div>
                  <div className="pt-1">
                    <StopLossButton position={p} />
                  </div>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
      {alertEl}
    </>
  );
}