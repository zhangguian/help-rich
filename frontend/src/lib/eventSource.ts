'use client';

/**
 * SSE 客户端封装(frontend-arch §8.1,backend-arch §8.3 心跳)
 *
 * - 心跳过滤(`event: ping` 丢弃,只转发业务事件)
 * - 失败降级:连续 3 次连接失败 → 切 5s 轮询 /api/diagnose/{id}
 * - localStorage 持久化降级标志(避免 SSE 短闪断反复切换)
 * - online 事件自动回切 SSE
 */
import { useEffect, useRef } from 'react';

import { apiGet, sseUrl } from '@/lib/api';
import type { DiagnoseOut } from '@/lib/types';
import { useDiagnoseStore } from '@/stores/useDiagnoseStore';

const FAIL_THRESHOLD = 3;
const DEGRADE_KEY = 'rich-sse-degraded';
const DEGRADE_POLL_INTERVAL = 5000;

function isDegraded(): boolean {
  try {
    return localStorage.getItem(DEGRADE_KEY) === '1';
  } catch {
    return false;
  }
}

function setDegraded(v: boolean) {
  try {
    if (v) localStorage.setItem(DEGRADE_KEY, '1');
    else localStorage.removeItem(DEGRADE_KEY);
  } catch {
    /* localStorage 不可用 */
  }
}

export type SseMessage = {
  event: string;
  trade_id?: number;
  score?: number;
  breakdown?: Record<string, number>;
  comment?: string;
  reason?: string;
  provider?: string;
  model?: string;
  latency_ms?: number;
  ts?: number;
};

/**
 * 打开 SSE 流;onMessage 收到非心跳业务事件;
 * 失败/降级由内部管理。
 */
export function openSse(
  onMessage: (msg: SseMessage) => void,
  onError?: () => void,
): () => void {
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
  };

  const startPolling = () => {
    if (pollTimer) return;
    setDegraded(true);
    pollTimer = setInterval(async () => {
      if (closed) return;
      const pending = useDiagnoseStore.getState().pendingIds();
      for (const id of pending) {
        try {
          const d = await apiGet<DiagnoseOut>(`/diagnose/${id}`);
if (d.status !== 'pending') {
              const msg: SseMessage = {
                event:
                  d.status === 'success' ? 'trade.commented' : 'trade.failed',
                trade_id: id,
              };
              if (d.score !== null && d.score !== undefined) msg.score = d.score;
              if (d.breakdown) msg.breakdown = d.breakdown;
              if (d.aiComment) msg.comment = d.aiComment;
              onMessage(msg);
              useDiagnoseStore.getState().markDone(id);
            }
        } catch {
          /* keep polling */
        }
      }
    }, DEGRADE_POLL_INTERVAL);
  };

  const start = () => {
    if (closed || isDegraded()) {
      startPolling();
      return;
    }
    try {
      es = new EventSource(sseUrl());
    } catch {
      failCount += 1;
      if (failCount >= FAIL_THRESHOLD) startPolling();
      return;
    }
    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as SseMessage;
        if (msg.event === 'ping') return; // 心跳过滤
        failCount = 0;
        setDegraded(false);
        onMessage(msg);
      } catch {
        /* ignore non-JSON */
      }
    };
    es.onerror = () => {
      failCount += 1;
      if (failCount >= FAIL_THRESHOLD) {
        es?.close();
        es = null;
        startPolling();
        onError?.();
      }
    };
  };

  start();

  const onlineHandler = () => {
    if (closed) return;
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
      setDegraded(false);
    }
    failCount = 0;
    if (es) es.close();
    start();
  };
  window.addEventListener('online', onlineHandler);

  return () => {
    window.removeEventListener('online', onlineHandler);
    stop();
  };
}

/** React hook:订阅全局 diagnose 事件,自动更新 store */
export function useSseSubscription() {
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const cleanup = openSse((msg) => {
      const store = useDiagnoseStore.getState();
      if (!msg.trade_id) return;
      if (msg.event === 'trade.scored') {
        store.setScore(msg.trade_id, msg.score ?? null, msg.breakdown ?? null);
      } else if (msg.event === 'trade.commented') {
        store.setComment(msg.trade_id, msg.comment ?? null);
        store.markDone(msg.trade_id);
      } else if (msg.event === 'trade.failed') {
        store.setFailed(msg.trade_id, msg.reason ?? '生成失败');
        store.markDone(msg.trade_id);
      }
    });
    return cleanup;
  }, []);
}