'use client';

/**
 * 补T待接回 / 待卖出清单 store
 *
 * 左栏置顶清单与「补T提醒」页共用一份数据 —— 同一份口径,两处展示,
 * 不会出现「左栏说有 4 只、页面说 3 只」。
 *
 * 两组:待接回(反T,先卖后买)+ 待卖出(正T,先买后卖)。
 *
 * 刷新时机:挂载时拉一次;录完接回/卖出流水后由调用方 refresh();
 * 超过 60s 的旧数据在再次读取时自动重拉(避免开着页面看到隔夜数据)。
 */
import { create } from 'zustand';

import { fetchPendingTReminders, type TReminderItem } from '@/lib/api/tReminders';

const STALE_MS = 60_000;

/**
 * 补齐数组类字段(缺 → 空数组)。
 *
 * **为什么必须有这一层**:后端新增字段(如 `open_prices`)之前,
 * 页面里已经加载过的数据没有这些键 —— 组件直接 `.length` 就整页崩。
 * 一律在**进入 store 的那一刻**补齐,组件拿到的一定是完整结构。
 */
function normalizeItem(it: TReminderItem): TReminderItem {
  return {
    ...it,
    openTxIds: it.openTxIds ?? [],
    openPrices: it.openPrices ?? [],
  };
}

interface TReminderState {
  /** 待接回(反T) */
  items: TReminderItem[];
  /** 待卖出(正T) */
  forwardItems: TReminderItem[];
  totalCount: number;
  asOf: string | null;
  loading: boolean;
  error: string | null;
  lastLoadedAt: number;
  load: (force?: boolean) => Promise<void>;
  refresh: () => Promise<void>;
}

export const useTReminderStore = create<TReminderState>((set, get) => ({
  items: [],
  forwardItems: [],
  totalCount: 0,
  asOf: null,
  loading: false,
  error: null,
  lastLoadedAt: 0,
  load: async (force = false) => {
    const { loading, lastLoadedAt } = get();
    if (loading) return;
    if (!force && lastLoadedAt && Date.now() - lastLoadedAt < STALE_MS) return;
    set({ loading: true, error: null });
    try {
      const data = await fetchPendingTReminders();
      const rawItems = data.items ?? [];
      const rawForwardItems = data.forwardItems ?? [];
      // ⚠️ 唯一适配层:数组类字段一律补成空数组。
      // 后端加字段之前取到的旧数据(或老后端返回)里没有这些字段,
      // 组件里裸取 `.length` / `new Set(...)` 会直接把整页打崩。
      const items = rawItems.map(normalizeItem);
      const forwardItems = rawForwardItems.map(normalizeItem);
      set({
        items,
        forwardItems,
        totalCount: data.totalCount ?? items.length + forwardItems.length,
        asOf: data.asOf ?? null,
        loading: false,
        lastLoadedAt: Date.now(),
      });
    } catch (e) {
      set({
        loading: false,
        error: e instanceof Error ? e.message : '加载失败',
      });
    }
  },
  refresh: async () => {
    await get().load(true);
  },
}));
