'use client';

/**
 * 止损检查(P5.5)—— 2026-10-29 改为「实时价驱动 + 轮询兜底」
 *
 * **改造前**:15s 轮询 `/positions`,拿后端返回的 `currentPrice` 判定。
 * 但 `/positions` 的价格走的是 **5 分钟缓存**(`QuoteService.get_quotes`),
 * 所以止损实际是「5 分钟前的价 + 15s 轮询」—— 盘中价格已经跌破止损线时,
 * 弹窗可能晚好几分钟才出现。
 *
 * **改造后**:
 * - **主路径**:订阅 `useQuoteStore` 的实时价(SSE 推送,3 秒快照档)。
 *   价格一变就重新判定 → 触达延迟从"分钟级"降到"秒级"。
 * - **兜底**:仍保留 15s 轮询 `/positions`,覆盖 SSE 没覆盖的情况
 *   (非交易时段后端轮询器不跑、SSE 断线降级、持仓票不在 watchlist 里)。
 *
 * 两条路径**共用同一份判定逻辑**(`checkOnce`),不重复实现。
 * 触发仍是后端 `markTriggered` 幂等 + 每天最多一次。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { apiGet, apiPost } from '@/lib/api';
import { normalizeCode } from '@/lib/stockCode';
import type { Position, StopLoss } from '@/lib/types';

import { useQuoteStore } from '@/stores/useQuoteStore';

import { StopLossAlert } from '../components/stop-loss/StopLossAlert';

/** 兜底轮询间隔(ms)—— SSE 正常时这条路径几乎不会产生判定 */
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
  const positionsRef = useRef<Position[]>(positions);
  positionsRef.current = positions;

  /** 实时价表(SSE 推送);订阅它 → 价格一变就重新判定 */
  const liveQuotes = useQuoteStore((s) => s.quotes);

  const refreshStopLosses = useCallback(async () => {
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
  }, []);

  /**
   * 判定一轮。`liveOnly=true` 时只看实时价(主路径),
   * 否则回落到持仓接口的价格(兜底路径)。
   */
  const checkOnce = useCallback(
    async (liveOnly: boolean) => {
      const map = stopLossMapRef.current;
      if (map.size === 0) return;

      for (const [code, sl] of Array.from(map.entries())) {
        if (mutedCodes.has(code)) continue;
        const holdUntil = holdUntilRef.current.get(code) ?? 0;
        if (Date.now() < holdUntil) continue;

        // 主路径:实时价(秒级)。没有实时价就跳过这一轮,交给兜底路径。
        const live = liveQuotes[code]?.currentPrice;
        let triggerPrice: string | null | undefined = live;
        if (triggerPrice == null) {
          if (liveOnly) continue;
          // 兜底:持仓接口的价格(可能来自 5 分钟缓存)
          const pos = positionsRef.current.find((p) => normalizeCode(p.stockCode) === code);
          triggerPrice = pos?.currentPrice;
        }
        if (triggerPrice == null || triggerPrice === undefined) continue;

        if (Number(triggerPrice) <= Number(sl.stopLossPrice)) {
          const pos = positionsRef.current.find((p) => normalizeCode(p.stockCode) === code);
          setAlert({
            stockCode: code,
            stockName: pos?.stockName ?? null,
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
    },
    [liveQuotes, mutedCodes],
  );

  // 主路径:实时价一变就判定一次(SSE 推送 → 秒级)
  useEffect(() => {
    void checkOnce(true);
  }, [checkOnce, liveQuotes]);

  // 兜底:15s 轮询持仓接口(覆盖实时价缺失的情况)
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const poll = async () => {
      if (cancelled) return;
      try {
        const r = await apiGet<{ items: Position[] }>('/positions');
        if (cancelled) return;
        positionsRef.current = r.items;
        await checkOnce(false);
      } catch {
        /* ignore */
      }
    };

    const start = async () => {
      await refreshStopLosses();
      await poll();
      timer = setInterval(poll, POLL_INTERVAL);
    };

    void start();

    const onlineHandler = () => {
      if (timer) clearInterval(timer);
      void start();
    };
    window.addEventListener('online', onlineHandler);

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      window.removeEventListener('online', onlineHandler);
    };
  }, [checkOnce, refreshStopLosses]);

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
