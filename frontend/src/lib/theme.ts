'use client';

/**
 * 主题切换(v0.8 交易台:深色终端 / 纸面终端)
 *
 * 为什么要有这个模块:src/styles/tokens.css 里定义了
 * `html[data-theme='light']` 的纸面终端配色,但此前**没有任何代码写这个属性** ——
 * 浅色主题等于一张永远打不开的底稿。
 *
 * 这里补上三件事:
 * 1. 读写 `document.documentElement.dataset.theme`(缺省 = 深色终端)
 * 2. 持久化到 localStorage
 * 3. 广播 `rich-theme-change` 事件 ——
 *    图表颜色是运行时从 CSS 变量读出来的(见 src/lib/chartTheme.ts),
 *    切主题后必须让图表重读,否则 UI 变浅色、图表还是深色的那套颜色。
 */

const THEME_KEY = 'rich-theme';
export const THEME_EVENT = 'rich-theme-change';

export type ThemeMode = 'dark' | 'light';

export function getTheme(): ThemeMode {
  if (typeof document === 'undefined') return 'dark';
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

export function setTheme(mode: ThemeMode) {
  if (typeof document === 'undefined') return;
  if (mode === 'light') document.documentElement.dataset.theme = 'light';
  else delete document.documentElement.dataset.theme;
  try {
    localStorage.setItem(THEME_KEY, mode);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

/** 首屏前同步一次,避免刷新时闪一下默认主题 */
export function applyStoredTheme() {
  if (typeof document === 'undefined') return;
  let mode: ThemeMode = 'dark';
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === 'light' || v === 'dark') mode = v;
  } catch {
    /* ignore */
  }
  if (mode === 'light') document.documentElement.dataset.theme = 'light';
}
