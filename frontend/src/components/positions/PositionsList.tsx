'use client';

import { useState } from 'react';

import dynamic from 'next/dynamic';

import clsx from 'clsx';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EtfBadge } from '@/components/ui/EtfBadge';
import { decimalFormat } from '@/lib/decimalFormat';
import { useStopLossChecker } from '@/hooks/useStopLossChecker';
import type { Position } from '@/lib/types';

/**
 * v0.7:止损轮询检查器 / 持仓明细弹窗 / 一键清仓弹窗改为动态加载。
 * 三者都不是首屏必需(止损轮询要 15s 后才可能触发,弹窗要用户点开),
 * 静态引入会让本页首屏多背约 100kB。
 */
const PositionDetailModal = dynamic(
  () => import('@/components/positions/PositionDetailModal').then((m) => m.PositionDetailModal),
  { ssr: false },
);
const StopLossButton = dynamic(
  () => import('@/components/stop-loss/StopLossButton').then((m) => m.StopLossButton),
  { ssr: false },
);
const ClearPositionModal = dynamic(
  () => import('./ClearPositionModal').then((m) => m.ClearPositionModal),
  { ssr: false },
);
const PositionTransactionModal = dynamic(
  () =>
    import('./PositionTransactionModal').then((m) => m.PositionTransactionModal),
  { ssr: false },
);

/**
 * 持仓列表(Client 包装,P5.3/P5.5 集成)
 *
 * - 每只持仓卡:右侧 [+ 设止损] / [🛡 ¥价格][⚡][🗑][🛑 一键清仓]
 * - 轮询检查:15s 拉最新行情,触达止损 → 弹 StopLossAlert
 */
export function PositionsList({
  positions,
  onDelete,
  onCleared,
}: {
  positions: Position[];
  onDelete?: (p: Position) => void;
  onCleared?: (p: Position) => void;
}) {
  const { alertEl } = useStopLossChecker(positions);
  const [detail, setDetail] = useState<{ code: string; name: string | null } | null>(null);
  const [clearTarget, setClearTarget] = useState<Position | null>(null);
  const [txTarget, setTxTarget] = useState<{ code: string; name: string | null } | null>(null);

  const pnlClass = (v: number | null) =>
    v === null ? 'text-text-ter' : v >= 0 ? 'text-up' : 'text-down';

  const openClear = (p: Position) => setClearTarget(p);

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
                    {/* 场内 ETF 品种徽章(跨境/商品类带 T+0) */}
                    <EtfBadge code={p.stockCode} className="ml-2 align-middle" />
                    <span className="text-text-ter text-sm ml-2 font-mono">
                      {p.stockCode}
                    </span>
                  </div>
                  <div className="text-sm text-text-sec mt-1">
                    持仓 <span className="font-mono">{p.shares}</span> 股 ·
                    摊薄成本 ¥
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
                  <div className="pt-1 flex flex-wrap gap-1 justify-end">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setTxTarget({ code: p.stockCode, name: p.stockName })
                      }
                      title="录入这只股票的交易流水(每笔自动打分)"
                    >
                      📝 录入流水
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setDetail({ code: p.stockCode, name: p.stockName })
                      }
                    >
                      📊 K 线
                    </Button>
                    <StopLossButton position={p} />
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-up"
                      onClick={() => openClear(p)}
                    >
                      🛑 一键清仓
                    </Button>
                    {onDelete && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-down"
                        onClick={() => onDelete(p)}
                      >
                        🗑 删除
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {clearTarget && (
        <ClearPositionModal
          target={clearTarget}
          onClose={() => setClearTarget(null)}
          {...(onCleared ? { onCleared } : {})}
        />
      )}

      {detail && (
        <PositionDetailModal
          open={true}
          onClose={() => setDetail(null)}
          stockCode={detail.code}
          stockName={detail.name}
        />
      )}
      {txTarget && (
        <PositionTransactionModal
          open={true}
          onClose={() => setTxTarget(null)}
          stockCode={txTarget.code}
          stockName={txTarget.name}
        />
      )}
      {alertEl}
    </>
  );
}
