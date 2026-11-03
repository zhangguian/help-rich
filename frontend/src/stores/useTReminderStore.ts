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
      const items = data.items ?? [];
      const forwardItems = data.forwardItems ?? [];
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
