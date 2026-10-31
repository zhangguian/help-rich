'use client';

/**
 * 盘中信号 store(盘中持仓信号 · 桌面通知 ADR-0007)
 *
 * **为什么不塞进页面 useState**:信号流是**跨页面**的(工作台要在角标上提示,
 * 「信号流水」页要列历史),放 store 才能一份数据两处用。
 *
 * **桌面通知由后端弹**:前端**不再**调 `new Notification` ——
 * 浏览器一关就收不到,而盘中信号的价值恰恰在"关掉浏览器也能收到"。
 * 前端只负责:实时收到信号 → 记进流水 → 角标提示 + 流水页展示。
 */
import { create } from 'zustand';

import type { SignalRuntime, SignalTrigger } from '@/lib/api/advanced';

interface SignalState {
  /** 最近的信号(新到在前) */
  items: SignalTrigger[];
  /** 未读条数(用户点过"已读"才清零) */
  unread: number;
  /** SSE 是否已连接 */
  connected: boolean;
  /** 后端当前生效的触发价 + 不适合原因 */
  runtime: SignalRuntime | null;
  /** 追加一条新信号 */
  push: (item: SignalTrigger) => void;
  /** 用 REST 拉到的历史覆盖本地 */
  setItems: (items: SignalTrigger[]) => void;
  setRuntime: (runtime: SignalRuntime) => void;
  setConnected: (connected: boolean) => void;
  markRead: () => void;
}

/** 流水最多留多少条(避免长时间挂着把内存吃满) */
const MAX_ITEMS = 200;

export const useSignalStore = create<SignalState>((set) => ({
  items: [],
  unread: 0,
  connected: false,
  runtime: null,

  push: (item) =>
    set((state) => ({
      items: [item, ...state.items].slice(0, MAX_ITEMS),
      unread: state.unread + 1,
    })),

  setItems: (items) => set({ items, unread: 0 }),

  setRuntime: (runtime) => set({ runtime }),

  setConnected: (connected) =>
    set((state) => (state.connected === connected ? state : { ...state, connected })),

  markRead: () => set({ unread: 0 }),
}));
