'use client';

/**
 * 实时行情 SSE 订阅(秒级盯盘 · 2026-10-29 ADR-0006)
 *
 * **为什么不用现成的 `lib/eventSource.ts`**:那个封装是**诊断事件**专用
 * (固定连 `/api/events/sse`,降级后轮询 `/api/diagnose/{id}`),
 * 行情流是**另一条端点 + 另一套降级动作**,硬塞进去会把两个业务搅在一起。
 * 这里沿用它的**设计**(心跳过滤 / 连续失败降级 / online 事件回切 / localStorage 标记),
 * 但独立成一个流。
 *
 * **降级路径**:SSE 连不上 → 退回 REST 轮询 `GET /api/quotes?codes=...&fresh=true`
 * (`fresh=true` = 后端跳过 5 分钟缓存直取数据源,否则降级后拿到的还是 5 分钟前的旧价)。
 *
 * **降级是可逆的**:降级时**不关掉 EventSource** —— 浏览器自己会按 ~3s 重连,
 * 后端一恢复就重新收到帧 → 停掉 REST 轮询 + 清掉降级标记 → 自动回切 SSE。
 * (否则降级会变成闩锁:一次后端重启,整个会话都回不到 SSE。)
 * 同理,**刷新页面后即使带着降级标记也照样建 SSE** —— 标记只决定"要不要同时开轮询兜底",
 * 不决定"要不要连流",否则标记一落就再也回不来了。
 *
 * **口径**:3 秒快照(Level-1),不是逐笔 Tick。见 ADR-0006。
 */
import { useEffect, useRef } from 'react';

import { apiBaseUrl, apiGet, snakeToCamel } from '@/lib/api';
import type { Quote } from '@/lib/types';

import { useQuoteStore } from '@/stores/useQuoteStore';

/**
 * SSE 端点(需与后端 `GET /api/quotes/stream` 对齐)
 *
 * ⚠️ URL 拼接坑:`NEXT_PUBLIC_API_URL` 的值**已经含 `/api`**
 * (默认 `http://127.0.0.1:8000/api`)—— 再拼 `/api/...` 会得到
 * `/api/api/quotes/stream` → 404。
 * 所以这里用 `apiBaseUrl()` 去掉尾部 `/api` 后再拼路径,
 * 与 `lib/api.ts` 的 `sseUrl()` 同一套路。
 */
const SSE_URL = `${apiBaseUrl().replace(/\/api\/?$/, '')}/api/quotes/stream`;

/** 连续失败多少次后降级到 REST 轮询 */
const FAIL_THRESHOLD = 3;
/** 降级后的轮询间隔(ms)—— 与服务端 2s 节奏同量级 */
const DEGRADE_POLL_INTERVAL = 3000;
/** 降级标记持久化 key(避免 SSE 短闪断就来回切换) */
const DEGRADE_KEY = 'rich-quote-sse-degraded';

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

type StreamPayload = {
  event?: string;
  quotes?: unknown[];
  updated_at?: string | null;
  stale?: boolean;
};

/**
 * SSE 帧 → 前端 Quote[]
 *
 * ⚠️ **必须做 snake→camel 转换**:REST 走 axios,响应拦截器会自动转;
 * 而 EventSource 拿到的是**裸 JSON**,后端推的是 snake_case
 * (`current_price` / `change_pct`),前端 `Quote` 类型是 camelCase。
 * 不转的话 `quote.currentPrice` 全是 undefined → 价格列显示空。
 */
function toQuotes(raw: unknown[] | undefined): Quote[] {
  if (!raw?.length) return [];
  return snakeToCamel(raw) as Quote[];
}

/**
 * 订阅行情流。组件挂载即开始,卸载即断开。
 *
 * @param codes 需要关注的代码(自选 ∪ 持仓)。空数组 = 不订阅(还没加载出列表)。
 */
export function useQuoteStream(codes: string[]): void {
  const merge = useQuoteStore((s) => s.merge);
  const setConnected = useQuoteStore((s) => s.setConnected);

  // codes 每次渲染都是新数组 → 用 ref 存一份"非空且有变化"的签名,避免重连
  const codesKey = codes.length ? [...codes].sort().join(',') : '';
  const codesRef = useRef<string[]>(codes);
  codesRef.current = codes;

  useEffect(() => {
    if (!codesKey) return; // 列表还没加载出来 → 不连

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

    /** 降级:REST 轮询(fresh=1 跳过缓存) */
    const startPolling = () => {
      if (pollTimer) return;
      setDegraded(true);
      pollTimer = setInterval(async () => {
        if (closed) return;
        const list = codesRef.current;
        if (!list.length) return;
        try {
          const quotes = await apiGet<Quote[]>(`/quotes?codes=${list.join(',')}&fresh=true`);
          if (closed) return;
          merge(quotes, { stale: false, updatedAt: new Date().toISOString() });
          failCount = 0;
        } catch {
          /* 保留上一份报价;下一轮再试 */
        }
      }, DEGRADE_POLL_INTERVAL);
    };

    const start = () => {
      if (closed) return;
      // 上次会话是降级态(后端当时挂了)→ **先把 REST 兜底拉起来,但仍然要建 SSE**:
      // EventSource 自己会按 ~3s 重连,后端一恢复就收到帧 → 停轮询 + 清降级标记 → 自动回切。
      // ⚠️ 早先这里直接 return(只轮询不建流)→ 降级成了**不可逆闩锁**:
      // 刷新页面后连 SSE 都不再尝试,只能靠清站点数据才能回到 SSE 模式。
      if (isDegraded()) {
        startPolling();
      }
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
        setDegraded(false);
        // 收到帧 = SSE 已恢复 → **停掉降级轮询,自动回切**
        // (轮询与 SSE 同时跑会重复取价;这里以"收到帧"为准切换)
        if (pollTimer) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
        const quotes = toQuotes(payload.quotes);
        if (!quotes.length) {
          // 首帧可能还没有数据 → 只更新元信息
          merge([], { stale: payload.stale ?? false, updatedAt: payload.updated_at ?? null });
          return;
        }
        merge(quotes, {
          stale: payload.stale ?? false,
          updatedAt: payload.updated_at ?? null,
        });
      };
      es.onerror = () => {
        failCount += 1;
        if (failCount >= FAIL_THRESHOLD) {
          setConnected(false);
          startPolling();
          // ⚠️ **不要 close() 掉 es**:EventSource 断线后浏览器会自己按 ~3s 自动重连,
          // 留着它才能在后端恢复后**自动回切 SSE**(收到帧 → 停轮询 → 清降级标记)。
          // 直接 close 会把降级变成"不可逆闩锁"—— 一次后端重启,整个会话就再也回不到 SSE,
          // 只能靠刷新页面(且 localStorage 标记还在 → 连刷新都是降级态)。
        }
      };
    };

    start();

    // 网络恢复 → 立刻回切 SSE
    const onlineHandler = () => {
      if (closed) return;
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      setDegraded(false);
      failCount = 0;
      if (es) es.close();
      start();
    };
    window.addEventListener('online', onlineHandler);

    return () => {
      window.removeEventListener('online', onlineHandler);
      stop();
    };
  }, [codesKey, merge, setConnected]);
}
