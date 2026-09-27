'use client';

import { AnimatePresence, motion } from 'framer-motion';

import { useUIStore } from '@/stores/useUIStore';

/**
 * 全局 Toast 渲染器
 *
 * - 监听 useUIStore.toasts,自动渲染所有 toast
 * - 4 种类型走**语义色**(success/error/warning/info),不借用行情红绿
 * - 右下角堆叠,3s 自动消失
 *
 * v0.7:原用 `animate-in fade-in slide-in-from-right`,但该类来自 tailwindcss-animate,
 * 而 tailwind.config plugins 为空 —— 一直静默不生效。改用项目已有的 framer-motion。
 */
const variantClasses = {
  success: 'bg-success-bg text-success border-success/40',
  error: 'bg-danger-bg text-danger border-danger/40',
  warning: 'bg-warn-bg text-warn border-warn/40',
  info: 'bg-info-bg text-info border-info/30',
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
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            role="alert"
            initial={{ opacity: 0, x: 24, scale: 0.98 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 24, scale: 0.98 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className={`pointer-events-auto flex items-start gap-2 px-3 py-2 rounded border shadow-pop text-[13px] ${variantClasses[t.type]}`}
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
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
