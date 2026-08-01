'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { decimalFormat } from '@/lib/decimalFormat';
import type { Position, StopLoss } from '@/lib/types';

import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';

/**
 * 止损设置弹窗(P5.3,ui-ux §4.6)
 *
 * - 价格输入 + 实时预览"触发后亏损%"
 * - 4 个提醒 checkbox:启用 / 声音 / 桌面通知 / 震动
 * - 边界:价格 ≤ 当前价 → 禁用保存并提示
 */
export function StopLossModal({
  open,
  onClose,
  position,
  existing,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  position: Position;
  existing: StopLoss | null;
  onSave: (payload: {
    stopLossPrice: string;
    enabled: boolean;
    notifySound: boolean;
    notifyDesktop: boolean;
    notifyVibrate: boolean;
  }) => void;
}) {
  const initialPrice = existing?.stopLossPrice ?? position.avgCost;
  const [price, setPrice] = useState<string>(initialPrice);
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);
  const [sound, setSound] = useState(existing?.notifySound ?? true);
  const [desktop, setDesktop] = useState(existing?.notifyDesktop ?? true);
  const [vibrate, setVibrate] = useState(existing?.notifyVibrate ?? true);

  const currentPrice = Number(position.currentPrice ?? position.avgCost);
  const stopPrice = Number(price);
  const lossPct =
    currentPrice > 0 && stopPrice > 0
      ? ((stopPrice - currentPrice) / currentPrice) * 100
      : 0;
  const isLossAboveZero = lossPct < 0;
  const invalid = stopPrice <= 0 || (currentPrice > 0 && stopPrice > currentPrice);

  return (
    <Modal open={open} onClose={onClose} title="设置止损" size="sm">
      <div className="space-y-4">
        <div className="text-sm text-text-sec">
          <span className="font-semibold text-text-pri">
            {position.stockName ?? position.stockCode}
          </span>{' '}
          <span className="font-mono text-xs">{position.stockCode}</span>
          <span className="ml-2 text-text-ter">·</span>
          <span className="ml-2">
            持仓 {position.shares} 股 · 加权成本 ¥
            {decimalFormat(position.avgCost)}
            {position.currentPrice && (
              <> · 现价 ¥{decimalFormat(position.currentPrice)}</>
            )}
          </span>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            止损价格(元)
          </label>
          <input
            type="number"
            step="0.001"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="w-full px-3 py-2 border border-border-def rounded-sm font-mono text-sm bg-bg-surface"
          />
          <div
            className={clsx(
              'text-xs mt-1',
              invalid ? 'text-up' : 'text-text-ter',
            )}
          >
            {stopPrice > 0 && currentPrice > 0 ? (
              <>
                触发后亏损约{' '}
                <span className="font-mono font-semibold">
                  {lossPct.toFixed(2)}%
                </span>
                {invalid && (
                  <span className="ml-1">(止损价高于当前价,无效)</span>
                )}
              </>
            ) : (
              '请输入止损价'
            )}
          </div>
        </div>

        <div className="space-y-2">
          <div className="text-sm font-medium">触发时</div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <span>启用止损(关闭后价格触达也不会提醒)</span>
          </label>
          <div className="ml-6 space-y-1.5 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={sound}
                disabled={!enabled}
                onChange={(e) => setSound(e.target.checked)}
              />
              <span>声音提醒</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={desktop}
                disabled={!enabled}
                onChange={(e) => setDesktop(e.target.checked)}
              />
              <span>桌面通知(Web Notification)</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={vibrate}
                disabled={!enabled}
                onChange={(e) => setVibrate(e.target.checked)}
              />
              <span>手机震动(navigator.vibrate)</span>
            </label>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            disabled={invalid || stopPrice <= 0}
            onClick={() =>
              onSave({
                stopLossPrice: Number(price).toFixed(3),
                enabled,
                notifySound: sound,
                notifyDesktop: desktop,
                notifyVibrate: vibrate,
              })
            }
          >
            保存
          </Button>
        </div>
      </div>
    </Modal>
  );
}