'use client';

/**
 * 到价提醒 · 弹窗 store
 *
 * **为什么是 store 不是页面 useState**:提醒是**跨页面**的 —— 用户可能在盯盘页、
 * 可能在做T清单页,不管在哪,弹窗都得冒出来。放 store 才能全站一份。
 *
 * **去重**:断线重连时后端会补发一次快照(SSE 建连的第一帧),
 * 快照里那条和实时推送那条是**同一次提醒** —— 靠 `triggerId` 去重,
 * 不然用户会看到同一条弹两遍,反而觉得系统在乱弹。
 */
import { create } from 'zustand';

import type { PriceAlertFiredEvent, PriceAlertPopupItem } from '@/lib/api/priceAlerts';

interface PriceAlertState {
  /** 待用户确认的弹窗(新的在前) */
  items: PriceAlertPopupItem[];
  /** SSE 是否已连接 */
  connected: boolean;
  /** 收到一次提醒 */
  push: (event: PriceAlertFiredEvent) => void;
  /** 关闭一条弹窗 */
  dismiss: (localId: string) => void;
  setConnected: (connected: boolean) => void;
}

/** 同时最多堆几条弹窗(再多就把最旧的挤掉,别糊屏) */
const MAX_POPUPS = 4;

let seq = 1;

export const usePriceAlertStore = create<PriceAlertState>((set) => ({
  items: [],
  connected: false,

  push: (event) =>
    set((state) => {
      // 同一次提醒(triggerId 相同)只弹一次
      if (
        event.triggerId != null &&
        state.items.some((i) => i.triggerId === event.triggerId)
      ) {
        return state;
      }
      const item: PriceAlertPopupItem = { ...event, localId: `pa-${seq++}` };
      return { items: [item, ...state.items].slice(0, MAX_POPUPS) };
    }),

  dismiss: (localId) =>
    set((state) => ({ items: state.items.filter((i) => i.localId !== localId) })),

  setConnected: (connected) =>
    set((state) => (state.connected === connected ? state : { ...state, connected })),
}));
