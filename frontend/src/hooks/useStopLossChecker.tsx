'use client';

import { useEffect, useRef, useState } from 'react';

import { apiGet, apiPost } from '@/lib/api';
import { normalizeCode } from '@/lib/stockCode';
import type { Position, StopLoss } from '@/lib/types';

import { StopLossAlert } from '../components/stop-loss/StopLossAlert';

/**
 * 止损轮询检查(P5.5)
 *
 * - 15s 轮询当前价(positions 端点含 currentPrice)
 * - 触达 → 触发后端 markTriggered(同日幂等)+ 弹 StopLossAlert
 * - 每天最多触发 1 次(后端 last_triggered_at 强制幂等)
 * - 网络恢复检测:online 事件立即补一次
 */
const POLL_INTERVAL = 15000;
const HOLD_DURATION_MS = 30 * 60 * 1000; // "再扛一下" 推迟 30 分钟

interface AlertInfo {
  stockCode: string;
  stockName: string | null;
  triggerPrice: string | null;
  stopLossPrice: string;
}

export function useStopLossChecker(positions: Position[]) {
  const [alert, setAlert] = useState<AlertInfo | null>(null);
  const [mutedCodes, setMutedCodes] = useState<Set<string>>(new Set());
  const holdUntilRef = useRef<Map<string, number>>(new Map());
  const stopLossMapRef = useRef<Map<string, StopLoss>>(new Map());

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const refreshStopLosses = async () => {
      try {
        const list = await apiGet<StopLoss[]>('/stop-losses');
        const map = new Map<string, StopLoss>();
        for (const s of list) {
          if (s.enabled) map.set(s.stockCode, s);
        }
        stopLossMapRef.current = map;
      } catch {
        /* ignore */
      }
    };

    const checkOnce = async () => {
      if (cancelled) return;
      const map = stopLossMapRef.current;
      if (map.size === 0) return;
      // 拉最新持仓(行情)
      try {
        const r = await apiGet<{ items: Position[] }>('/positions');
        for (const p of r.items) {
          const code = normalizeCode(p.stockCode);
          if (!code) continue;
          const sl = map.get(code);
          if (!sl) continue;
          if (mutedCodes.has(code)) continue;
          const holdUntil = holdUntilRef.current.get(code) ?? 0;
          if (Date.now() < holdUntil) continue;
          const triggerPrice = p.currentPrice;
          if (triggerPrice === null || triggerPrice === undefined) continue;
          if (Number(triggerPrice) <= Number(sl.stopLossPrice)) {
            // 触达
            setAlert({
              stockCode: code,
              stockName: p.stockName,
              triggerPrice,
              stopLossPrice: sl.stopLossPrice,
            });
            // 标记后端(幂等)
            try {
              await apiPost(`/stop-losses/${code}/triggered`);
            } catch {
              /* ignore */
            }
            return; // 一次只弹一个
          }
        }
      } catch {
        /* ignore */
      }
    };

    const start = async () => {
      await refreshStopLosses();
      checkOnce();
      timer = setInterval(checkOnce, POLL_INTERVAL);
    };

    start();

    const onlineHandler = () => {
      if (timer) clearInterval(timer);
      start();
    };
    window.addEventListener('online', onlineHandler);

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      window.removeEventListener('online', onlineHandler);
    };
  }, [positions.length, mutedCodes]);

  const dismiss = () => setAlert(null);
  const onHold = () => {
    if (alert) {
      holdUntilRef.current.set(alert.stockCode, Date.now() + HOLD_DURATION_MS);
    }
    dismiss();
  };
  const onExit = () => {
    // TODO v0.2:调用交易 API 一键止损离场;MVP 先仅关闭弹窗
    dismiss();
  };
  const onMute = () => {
    if (alert) {
      setMutedCodes((prev) => new Set(prev).add(alert.stockCode));
    }
    dismiss();
  };

  const alertEl = alert ? (
    <StopLossAlert
      open
      stockCode={alert.stockCode}
      stockName={alert.stockName}
      triggerPrice={alert.triggerPrice}
      stopLossPrice={alert.stopLossPrice}
      onHold={onHold}
      onExit={onExit}
      onMute={onMute}
    />
  ) : null;

  return { alertEl, dismiss };
}