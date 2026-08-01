'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { PositionDetailModal } from '@/components/positions/PositionDetailModal';
import { StopLossButton } from '@/components/stop-loss/StopLossButton';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { useStopLossChecker } from '@/hooks/useStopLossChecker';
import { apiPost } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Position } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

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
  const [clearPrice, setClearPrice] = useState('');
  const [clearing, setClearing] = useState(false);
  const showToast = useUIStore((s) => s.showToast);

  const pnlClass = (v: number | null) =>
    v === null ? 'text-text-ter' : v >= 0 ? 'text-up' : 'text-down';

  const openClear = (p: Position) => {
    setClearTarget(p);
    // 默认卖出价 = 实时行情(优先),否则成本价
    const defaultPrice = p.currentPrice ?? p.avgCost;
    setClearPrice(defaultPrice);
  };

  const submitClear = async () => {
    if (!clearTarget) return;
    const price = Number(clearPrice);
    if (!Number.isFinite(price) || price <= 0) {
      showToast({ type: 'error', message: '请输入有效卖出价' });
      return;
    }
    setClearing(true);
    try {
      await apiPost(`/positions/${clearTarget.stockCode}/clear`, {
        price: price.toFixed(3),
        note: '一键清仓',
      });
      showToast({ type: 'success', message: `${clearTarget.stockName ?? clearTarget.stockCode} 已清仓` });
      setClearTarget(null);
      onCleared?.(clearTarget);
    } catch {
      /* toast 已由拦截器处理 */
    } finally {
      setClearing(false);
    }
  };

  const clearCostPrice = clearTarget ? Number(clearTarget.avgCost) : 0;
  const clearSellPrice = Number(clearPrice) || 0;
  const clearShares = clearTarget?.shares ?? 0;
  const clearEstimatedPnl = (clearSellPrice - clearCostPrice) * clearShares;

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
                  <div className="pt-1 flex flex-wrap gap-1 justify-end">
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
        <Modal
          open={true}
          onClose={() => !clearing && setClearTarget(null)}
          title={`一键清仓 ${clearTarget.stockName ?? clearTarget.stockCode}`}
          size="sm"
          footer={
            <>
              <Button variant="ghost" onClick={() => setClearTarget(null)} disabled={clearing}>
                取消
              </Button>
              <Button
                variant="danger"
                onClick={submitClear}
                loading={clearing}
                disabled={clearing || !Number.isFinite(Number(clearPrice)) || Number(clearPrice) <= 0}
              >
                确认清仓
              </Button>
            </>
          }
        >
          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-text-sec">持仓股数</span>
              <span className="font-mono">{clearShares}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-sec">加权成本</span>
              <span className="font-mono">¥{decimalFormat(clearTarget.avgCost)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-sec">当前价</span>
              <span className="font-mono">
                {clearTarget.currentPrice ? `¥${decimalFormat(clearTarget.currentPrice)}` : '--'}
              </span>
            </div>
            <div>
              <label className="block text-text-sec mb-1">卖出价</label>
              <input
                type="number"
                step="0.001"
                value={clearPrice}
                onChange={(e) => setClearPrice(e.target.value)}
                className="w-full px-2 py-1.5 text-sm border border-border-def rounded-sm bg-bg-surface focus:border-accent"
              />
            </div>
            <div className="flex justify-between pt-2 border-t border-border-def">
              <span className="text-text-sec">预估已实现盈亏</span>
              <span
                className={clsx(
                  'font-mono font-semibold',
                  pnlClass(Number.isFinite(clearEstimatedPnl) ? clearEstimatedPnl : null),
                )}
              >
                {Number.isFinite(clearEstimatedPnl)
                  ? `${clearEstimatedPnl >= 0 ? '+' : ''}¥${decimalFormat(String(clearEstimatedPnl))}`
                  : '--'}
              </span>
            </div>
            <p className="text-xs text-warn">
              ⚠ 清仓将卖出全部股数,触发一笔 sell 流水,并删除该持仓行(止损设置同步失效)。
            </p>
          </div>
        </Modal>
      )}

      {detail && (
        <PositionDetailModal
          open={true}
          onClose={() => setDetail(null)}
          stockCode={detail.code}
          stockName={detail.name}
        />
      )}
      {alertEl}
    </>
  );
}