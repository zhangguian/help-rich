'use client';

import { useEffect } from 'react';

import { Modal } from '../ui/Modal';
import { Button } from '../ui/Button';

/**
 * 止损全屏提醒(P5.4,ui-ux §4.7)
 *
 * - maskClosable=false + escToClose=false:必须做出选择
 * - 个性化文案:"再扛一下" / "止损离场"
 * - 触发后:Web Notification + navigator.vibrate + audio
 */
export function StopLossAlert({
  open,
  stockCode,
  stockName,
  triggerPrice,
  stopLossPrice,
  onHold, // 再扛一下(推迟 30 分钟)
  onExit, // 立即止损离场
  onMute, // 静音
}: {
  open: boolean;
  stockCode: string;
  stockName: string | null;
  triggerPrice: string | null;
  stopLossPrice: string;
  onHold: () => void;
  onExit: () => void;
  onMute: () => void;
}) {
  // 触发提醒:震动 + 通知 + 蜂鸣音
  useEffect(() => {
    if (!open) return;
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
      navigator.vibrate?.([300, 100, 300, 100, 600]);
    }
    if (typeof window !== 'undefined' && 'Notification' in window) {
      if (Notification.permission === 'granted') {
        try {
          new Notification('止损触达', {
            body: `${stockName ?? stockCode} 价格触达止损 ¥${stopLossPrice}`,
            tag: `stoploss-${stockCode}`,
            requireInteraction: true,
          });
        } catch {
          /* ignore */
        }
      }
    }
    // 蜂鸣(Web Audio)
    if (typeof window !== 'undefined' && 'AudioContext' in window) {
      try {
        const ctx = new AudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = 880;
        gain.gain.value = 0.2;
        osc.start();
        setTimeout(() => {
          osc.stop();
          ctx.close();
        }, 500);
      } catch {
        /* ignore */
      }
    }
  }, [open, stockCode, stockName, stopLossPrice]);

  if (!open) return null;

  const lossPct =
    triggerPrice && Number(triggerPrice) > 0
      ? ((Number(stopLossPrice) - Number(triggerPrice)) / Number(triggerPrice)) * 100
      : null;

  return (
    <Modal
      open={open}
      onClose={() => undefined}
      title="⚠ 止损触达"
      size="md"
      maskClosable={false}
      escToClose={false}
    >
      <div className="space-y-4">
        <div className="bg-up-bg text-up rounded-sm p-3 text-sm">
          <div className="font-semibold text-base mb-1">
            {stockName ?? stockCode}
            <span className="text-xs font-mono ml-2">{stockCode}</span>
          </div>
          <div>
            当前价 ¥{triggerPrice ?? '--'} 已跌破止损价{' '}
            <span className="font-mono font-semibold">¥{stopLossPrice}</span>
            {lossPct !== null && (
              <span className="ml-1">
                ({lossPct.toFixed(2)}%)
              </span>
            )}
          </div>
        </div>

        <p className="text-sm text-text-sec leading-relaxed">
          每一次"再扛一下"都可能是深渊的开始。
          止损位的存在是因为你曾在冷静时做了决定 ——
          现在情绪上来了吗?
        </p>

        <div className="flex flex-col gap-2">
          <Button
            variant="primary"
            onClick={onExit}
            fullWidth
          >
            ✅ 止损离场(执行纪律)
          </Button>
          <Button
            variant="secondary"
            onClick={onHold}
            fullWidth
          >
            😐 再扛一下(推迟 30 分钟)
          </Button>
          <Button variant="ghost" onClick={onMute} fullWidth>
            🔕 静音(本次不再提醒)
          </Button>
        </div>
      </div>
    </Modal>
  );
}