'use client';

/**
 * 自动刷新倒计时(阶段 10 · P7)
 *
 * **为什么单独一个 store**:这个数字只被顶栏那个「自动刷新 15s」按钮用到,
 * 但它原来住在 `Workbench` 的 state 里 → **每秒一次 `setState` → 整页重渲染**
 * (44 行自选 + 14 张图 + 三栏布局全走一遍 React diff + 样式重算)。
 *
 * LoAF 实测:开着自动刷新时,长帧时间几乎全花在 `styleAndLayout`,
 * 正是「每秒整页重渲染 → 整页样式重算/布局」造成的。
 *
 * 挪进独立 store 后,每秒只有**顶栏那个小按钮**重渲染,盯盘页主体完全不动。
 *
 * 写法沿用项目既有惯例(`useIntradayStore` 同样用 zustand)。
 */
import { create } from 'zustand';

interface RefreshState {
  /** 距下次刷新的秒数;0 = 不显示倒计时 */
  secondsLeft: number;
  setSecondsLeft: (n: number) => void;
  /** 倒计时走秒:由页面里的 1s 定时器驱动 */
  tick: () => void;
}

export const useRefreshStore = create<RefreshState>((set) => ({
  secondsLeft: 0,
  setSecondsLeft: (n) => set({ secondsLeft: n }),
  tick: () => set((s) => ({ secondsLeft: Math.max(0, s.secondsLeft - 1) })),
}));

export default useRefreshStore;
