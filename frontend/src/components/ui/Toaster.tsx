'use client';

import { useUIStore } from '@/stores/useUIStore';

/**
 * 全局 Toast 渲染器(P7.x 收尾新增)
 *
 * - 监听 useUIStore.toasts,自动渲染所有 toast
 * - 4 种类型:success(绿)/ error(红)/ warning(黄)/ info(蓝)
 * - 右下角堆叠,3s 自动消失
 */
const variantClasses = {
  success: 'bg-down-bg text-down border-down/40',
  error: 'bg-up-bg text-up border-up/40',
  warning: 'bg-warn-bg text-warn border-warn/40',
  info: 'bg-accent-subtle text-accent border-accent/30',
};

const variantIcons = {
  success: '✓',
  error: '✕',
  warning: '!',
  info: 'i',
};

export function Toaster() {
  const toasts = useUIStore((s) => s.toasts);
  const dismiss = useUIStore((s) => s.dismissToast);

  return (
    <div
      aria-live="polite"
      className="fixed top-4 right-4 z-[60] flex flex-col gap-2 max-w-sm pointer-events-none"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={`pointer-events-auto flex items-start gap-2 px-4 py-3 rounded-sm border shadow-md text-sm animate-in fade-in slide-in-from-right ${variantClasses[t.type]}`}
        >
          <span className="font-bold flex-shrink-0">{variantIcons[t.type]}</span>
          <span className="flex-1 leading-snug">{t.message}</span>
          <button
            onClick={() => dismiss(t.id)}
            className="flex-shrink-0 opacity-60 hover:opacity-100 leading-none"
            aria-label="关闭"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}