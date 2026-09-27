/**
 * UI Store(Toast)
 *
 * 仅管理全局通知(成功/失败/警告/信息)。
 * v0.7 起为单主题深色终端,无主题切换(原注释提到的 next-themes 从未真正接入)。
 */
import { create } from 'zustand';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: number;
  type: ToastType;
  message: string;
  duration?: number; // ms,默认 3000
}

interface UIState {
  toasts: Toast[];
  showToast: (toast: Omit<Toast, 'id'>) => void;
  dismissToast: (id: number) => void;
}

let nextToastId = 1;

export const useUIStore = create<UIState>((set, get) => ({
  toasts: [],
  showToast: (toast) => {
    const id = nextToastId++;
    const t: Toast = { id, duration: 3000, ...toast };
    set((s) => ({ toasts: [...s.toasts, t] }));
    setTimeout(() => {
      get().dismissToast(id);
    }, t.duration);
  },
  dismissToast: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));