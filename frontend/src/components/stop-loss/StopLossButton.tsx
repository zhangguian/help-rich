'use client';

import { useEffect, useState } from 'react';

import { apiDelete, apiGet, apiPost, apiPut } from '@/lib/api';
import type { Position, StopLoss } from '@/lib/types';
import { normalizeCode } from '@/lib/stockCode';
import { useUIStore } from '@/stores/useUIStore';

import { Button } from '../ui/Button';

import { StopLossModal } from './StopLossModal';

/**
 * 持仓卡 [+ 设止损] 入口(P5.3)
 *
 * - 加载现有止损(若有,显示 [改/删] 入口)
 * - 打开 StopLossModal 设置
 */
export function StopLossButton({ position }: { position: Position }) {
  const showToast = useUIStore((s) => s.showToast);
  const [existing, setExisting] = useState<StopLoss | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const list = await apiGet<StopLoss[]>('/stop-losses');
      const code = normalizeCode(position.stockCode);
      setExisting(list.find((s) => s.stockCode === code) ?? null);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [position.stockCode]);

  const handleSave = async (payload: {
    stopLossPrice: string;
    enabled: boolean;
    notifySound: boolean;
    notifyDesktop: boolean;
    notifyVibrate: boolean;
  }) => {
    try {
      await apiPut('/stop-losses', {
        stockCode: position.stockCode,
        stopLossPrice: payload.stopLossPrice,
        enabled: payload.enabled,
        notifySound: payload.notifySound,
        notifyDesktop: payload.notifyDesktop,
        notifyVibrate: payload.notifyVibrate,
      });
      showToast({
        type: 'success',
        message: existing ? '止损已更新' : '止损已设置',
      });
      setOpen(false);
      refresh();
    } catch (e) {
      showToast({ type: 'error', message: '设置失败,请重试' });
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`删除 ${position.stockCode} 的止损设置?`)) return;
    try {
      await apiDelete(`/stop-losses/${position.stockCode}`);
      showToast({ type: 'success', message: '止损已删除' });
      setExisting(null);
    } catch {
      showToast({ type: 'error', message: '删除失败' });
    }
  };

  const handleTriggered = async () => {
    try {
      const r = await apiPost<{ duplicate: boolean }>(
        `/stop-losses/${position.stockCode}/triggered`,
      );
      if (!r.duplicate) {
        showToast({
          type: 'warning',
          message: `已标记 ${position.stockCode} 触发(实际价触达)`,
        });
      }
    } catch {
      showToast({ type: 'error', message: '标记失败' });
    }
  };

  return (
    <>
      <div className="flex items-center gap-1">
        {existing ? (
          <>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setOpen(true)}
              title="修改止损"
              disabled={loading}
            >
              🛡 ¥{existing.stopLossPrice}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleTriggered}
              title="模拟价格触达"
            >
              ⚡
            </Button>
            <Button size="sm" variant="ghost" onClick={handleDelete} title="删除止损">
              🗑
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setOpen(true)}
            disabled={loading}
          >
            + 设止损
          </Button>
        )}
      </div>

      <StopLossModal
        open={open}
        onClose={() => setOpen(false)}
        position={position}
        existing={existing}
        onSave={handleSave}
      />
    </>
  );
}