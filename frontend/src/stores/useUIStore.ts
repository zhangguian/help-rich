/**
 * UI Store(主题 + Toast)
 *
 * - 主题:light / dark / system(next-themes 持久化到 localStorage)
 * - Toast:全局通知(成功/失败/警告/信息)
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