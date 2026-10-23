'use client';

/**
 * 盯盘页「盘中复盘」状态(阶段 10)
 *
 * **为什么单独一个 store**:顶栏胶囊与抽屉面板要显示**同一份**今日状态
 * (是否交易日 / 已产出哪几档 / 下一档倒计时)。
 * 放 store 而不是各自 fetch,是为了:
 * 1. 只打一次 `/intraday-review/schedule`(胶囊挂在顶栏,面板挂在页面里,各拉一次就重复了);
 * 2. 胶囊与面板的数据永远一致,不会出现「胶囊说已出、面板说还没」的错位;
 * 3. 面板开合状态也能被顶栏按钮直接控制。
 */
import { create } from 'zustand';

import {
  fetchIntradayReviewSchedule,
  type IntradayReviewSchedule,
} from '@/lib/api/advanced';

interface IntradayState {
  schedule: IntradayReviewSchedule | null;
  loading: boolean;
  error: string | null;
  /** 抽屉是否打开 */
  panelOpen: boolean;
  loadSchedule: () => Promise<void>;
  openPanel: () => void;
  closePanel: () => void;
}

export const useIntradayStore = create<IntradayState>((set, get) => ({
  schedule: null,
  loading: false,
  error: null,
  panelOpen: false,

  loadSchedule: async () => {
    // 已有数据且刚拉过 → 不重复打(顶栏与页面挂载都会调它)
    if (get().loading) return;
    set({ loading: true, error: null });
    try {
      const schedule = await fetchIntradayReviewSchedule();
      set({ schedule, loading: false });
    } catch (e) {
      // 交易日历/状态取不到不该让盯盘页报错 —— 胶囊显示「状态未知」即可
      set({
        loading: false,
        error: e instanceof Error ? e.message : '盘中复盘状态取不到',
      });
    }
  },

  openPanel: () => set({ panelOpen: true }),
  closePanel: () => set({ panelOpen: false }),
}));
