'use client';

/**
 * 实时行情 store(秒级盯盘 · 2026-10-29 ADR-0006)
 *
 * **为什么单独一个 store**:报价每 2 秒变一次。如果塞进 page.tsx 的 useState,
 * 每次报价变化都会让整个工作台重渲染(K 线、决策栏、复盘面板全跟着抖)。
 * 放进 store 后:
 * - `useQuote(code)` 订阅**单只**股票 → 只有价格变了的那一行重渲染;
 * - 组件间共享同一份报价 → 列表 / 持仓 / 止损检查不会出现"两处价格不一致"。
 *
 * **数据来源**:后端 `GET /api/quotes/stream`(SSE,3 秒快照档)。
 * 服务端是唯一真源 —— 前端只做展示,不再自己轮询 `/api/quotes`。
 *
 * **口径提醒**:这是 **3 秒快照(Level-1)**,不是逐笔 Tick。
 * 新浪/腾讯的 HTTP 接口本身就是这个精度,不要在 UI 上宣称"实时逐笔"。
 */
import { create } from 'zustand';

import type { Quote } from '@/lib/types';

interface QuoteState {
  /** code → 报价 */
  quotes: Record<string, Quote>;
  /** 数据是否已陈旧(后端行情源失败时为 true)—— UI 应显式提示,别装作新鲜 */
  stale: boolean;
  /** 最后一次收到数据的时间戳(ISO) */
  updatedAt: string | null;
  /** SSE 是否已连接 */
  connected: boolean;
  /** 合并一批报价(只覆盖变化了的项,保持引用稳定 → 下游 memo 生效) */
  merge: (quotes: Quote[], opts?: { stale?: boolean; updatedAt?: string | null }) => void;
  setConnected: (connected: boolean) => void;
  reset: () => void;
}

/** 报价是否真的变了(变了才更新引用,避免整表重渲染) */
function quoteChanged(a: Quote | undefined, b: Quote): boolean {
  if (!a) return true;
  return (
    a.currentPrice !== b.currentPrice ||
    a.changePct !== b.changePct ||
    a.volume !== b.volume ||
    a.timestamp !== b.timestamp
  );
}

export const useQuoteStore = create<QuoteState>((set) => ({
  quotes: {},
  stale: true,
  updatedAt: null,
  connected: false,

  merge: (incoming, opts) =>
    set((state) => {
      if (!incoming.length) {
        // 空批次只更新元信息(比如标 stale),不动报价本体
        return {
          stale: opts?.stale ?? state.stale,
          updatedAt: opts?.updatedAt ?? state.updatedAt,
        };
      }
      let changed = false;
      const next = { ...state.quotes };
      for (const q of incoming) {
        if (quoteChanged(next[q.code], q)) {
          next[q.code] = q;
          changed = true;
        }
      }
      if (!changed && opts?.stale === undefined && opts?.updatedAt === undefined) {
        return state;
      }
      return {
        quotes: changed ? next : state.quotes,
        stale: opts?.stale ?? state.stale,
        updatedAt: opts?.updatedAt ?? state.updatedAt,
      };
    }),

  setConnected: (connected) =>
    set((state) => (state.connected === connected ? state : { ...state, connected })),

  reset: () => set({ quotes: {}, stale: true, updatedAt: null, connected: false }),
}));

/** 订阅单只股票的报价(价格变了该组件才重渲染) */
export function useQuote(code: string | null | undefined): Quote | null {
  return useQuoteStore((s) => (code ? (s.quotes[code] ?? null) : null));
}

/** 订阅全量报价(列表级场景,如排序) */
export function useQuotes(): Record<string, Quote> {
  return useQuoteStore((s) => s.quotes);
}
