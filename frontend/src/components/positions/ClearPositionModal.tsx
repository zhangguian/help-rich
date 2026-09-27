'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { apiPost } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Position } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

/**
 * 一键清仓弹窗(v0.7 从 PositionsList 抽出)
 *
 * 独立成文件是为了让 PositionsList 能用 next/dynamic 懒加载它 ——
 * 该弹窗只有用户点「🛑 一键清仓」才需要,不该进首屏 bundle。
 */
export function ClearPositionModal({
  target,
  onClose,
  onCleared,
}: {
  target: Position | null;
  onClose: () => void;
  onCleared?: (p: Position) => void;
}) {
  const showToast = useUIStore((s) => s.showToast);
  // 初始卖出价 = 实时行情(优先),否则成本价
  const [price, setPrice] = useState(() =>
    target ? String(target.currentPrice ?? target.avgCost) : '',
  );
  const [clearing, setClearing] = useState(false);

  if (!target) return null;

  const pnlClass = (v: number) => (v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-text-ter');

  const submit = async () => {
    const priceNum = Number(price);
    if (!Number.isFinite(priceNum) || priceNum <= 0) {
      showToast({ type: 'error', message: '请输入有效卖出价' });
      return;
    }
    setClearing(true);
    try {
      await apiPost(`/positions/${target.stockCode}/clear`, {
        price: priceNum.toFixed(3),
        note: '一键清仓',
      });
      showToast({
        type: 'success',
        message: `${target.stockName ?? target.stockCode} 已清仓`,
      });
      onCleared?.(target);
      onClose();
    } catch {
      /* toast 已由拦截器处理 */
    } finally {
      setClearing(false);
    }
  };

  const estimatedPnl = (Number(price) - Number(target.avgCost)) * Number(target.shares);
  const priceValid = Number.isFinite(Number(price)) && Number(price) > 0;

  return (
    <Modal
      open
      onClose={() => !clearing && onClose()}
      title={`一键清仓 ${target.stockName ?? target.stockCode}`}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={clearing}>
            取消
          </Button>
          <Button variant="danger" onClick={submit} loading={clearing} disabled={clearing || !priceValid}>
            确认清仓
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-[13px]">
        <div className="flex justify-between">
          <span className="text-text-sec">持仓股数</span>
          <span className="font-mono">{target.shares}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-text-sec">加权成本</span>
          <span className="font-mono">¥{decimalFormat(target.avgCost)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-text-sec">当前价</span>
          <span className="font-mono">
            {target.currentPrice ? `¥${decimalFormat(target.currentPrice)}` : '--'}
          </span>
        </div>
        <div>
          <label className="block text-text-sec mb-1">卖出价</label>
          <input
            type="number"
            step="0.001"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="w-full px-2 py-1.5 text-[13px] border border-border-def rounded-sm bg-bg-surface focus:border-accent"
          />
        </div>
        <div className="flex justify-between pt-2 border-t border-border-def">
          <span className="text-text-sec">预估已实现盈亏</span>
          <span
            className={clsx('font-mono font-semibold', pnlClass(Number.isFinite(estimatedPnl) ? estimatedPnl : 0))}
          >
            {Number.isFinite(estimatedPnl)
              ? `${estimatedPnl >= 0 ? '+' : ''}¥${decimalFormat(String(estimatedPnl))}`
              : '--'}
          </span>
        </div>
        <p className="text-xs text-warn">
          ⚠ 清仓将卖出全部股数,触发一笔 sell 流水,并删除该持仓行(止损设置同步失效)。
        </p>
      </div>
    </Modal>
  );
}
