'use client';

/**
 * 盘中信号 SSE 订阅(盘中持仓信号 · 桌面通知 ADR-0007)
 *
 * **为什么单独一条流**:行情流(`/api/quotes/stream`)推的是报价,信号流
 * (`/api/signals/stream`)推的是"命中了哪条信号"。两条流的节奏、生命周期、
 * 降级动作都不一样,混在一个 store 里会让两边都变复杂。
 *
 * **桌面通知由后端弹**:这里**不调** `new Notification` —— 浏览器关着就收不到,
 * 而这正是本功能存在的理由。前端只做展示(角标 + 流水)。
 *
 * **降级**:SSE 连不上 → 退回 REST 拉流水(`GET /api/signals`);
 * 降级是**可逆**的(不 close 掉 EventSource,浏览器自己会重连)。
 */
import { useEffect } from 'react';

import { apiBaseUrl, apiGet, snakeToCamel } from '@/lib/api';
import type { SignalRuntime, SignalTrigger } from '@/lib/api/advanced';

import { useSignalStore } from '@/stores/useSignalStore';

/**
 * ⚠️ URL 拼接坑:`NEXT_PUBLIC_API_URL` 的值**已经含 `/api`**
 * → 再拼 `/api/...` 会得到 `/api/api/signals/stream` → 404。
 * 与 `hooks/useQuoteStream.ts` 同一套路。
 */
const SSE_URL = `${apiBaseUrl().replace(/\/api\/?$/, '')}/api/signals/stream`;

/** 连续失败多少次后降级到 REST 拉流水 */
const FAIL_THRESHOLD = 3;
/** 降级后的拉取间隔(ms) */
const DEGRADE_POLL_INTERVAL = 5000;

type StreamPayload = {
  event?: string;
  signal?: unknown;
  levels_updated_at?: string | null;
  codes?: string[];
  levels?: Record<string, unknown[]>;
  notes?: Record<string, string[]>;
};

function toSignal(raw: unknown): SignalTrigger | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = snakeToCamel(raw) as SignalTrigger;
  if (!item || !item.kind || !item.stockCode) return null;
  return item;
}

/**
 * 订阅信号流。组件挂载即开始,卸载即断开。
 */
export function useSignalStream(): void {
  const push = useSignalStore((s) => s.push);
  const setItems = useSignalStore((s) => s.setItems);
  const setRuntime = useSignalStore((s) => s.setRuntime);
  const setConnected = useSignalStore((s) => s.setConnected);

  useEffect(() => {
    let closed = false;
    let failCount = 0;
    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const stop = () => {
      closed = true;
      if (es) {
        es.close();
        es = null;
      }
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      setConnected(false);
    };

    /** 降级:REST 拉流水 */
    const startPolling = () => {
      if (pollTimer) return;
      pollTimer = setInterval(async () => {
        if (closed) return;
        try {
          const data = await apiGet<{ items: SignalTrigger[] }>('/signals?limit=50');
          if (closed) return;
          setItems(data.items ?? []);
        } catch {
          /* 保留上一份;下一轮再试 */
        }
      }, DEGRADE_POLL_INTERVAL);
    };

    const start = () => {
      if (closed) return;
      try {
        es = new EventSource(SSE_URL);
      } catch {
        failCount += 1;
        if (failCount >= FAIL_THRESHOLD) startPolling();
        return;
      }
      es.onopen = () => {
        failCount = 0;
        setConnected(true);
      };
      es.onmessage = (ev) => {
        let payload: StreamPayload;
        try {
          payload = JSON.parse(ev.data) as StreamPayload;
        } catch {
          return; // 非 JSON(心跳等)→ 忽略
        }
        failCount = 0;
        // 收到帧 = SSE 正常 → 停掉降级轮询
        if (pollTimer) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
        if (payload.event === 'signal_snapshot') {
          const runtime = snakeToCamel({
            levels_updated_at: payload.levels_updated_at,
            codes: payload.codes,
            levels: payload.levels,
            notes: payload.notes,
          }) as SignalRuntime;
          setRuntime(runtime);
          return;
        }
        if (payload.event === 'signal_fired') {
          const item = toSignal(payload.signal);
          if (item) push(item);
        }
      };
      es.onerror = () => {
        failCount += 1;
        if (failCount >= FAIL_THRESHOLD) {
          setConnected(false);
          startPolling();
          // ⚠️ 不要 close() 掉 es:EventSource 自己会重连,后端恢复后自动回切 SSE
        }
      };
    };

    start();

    return () => {
      stop();
    };
  }, [push, setItems, setRuntime, setConnected]);
}
