'use client';

import { useEffect } from 'react';

import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';

import type { ReactNode } from 'react';

const staggerContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, delayChildren: 0.08 } },
};

const staggerItem = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.28, ease: 'easeOut' as const } },
};

/**
 * LiquidModal(v0.4-roadmap §3.7)
 *
 * 液态玻璃弹窗:遮罩 blur 淡入 + 面板 spring 缩放上浮 + 内容错落入场。
 * 与旧 Modal API 兼容(open/onClose/title/size/maskClosable/escToClose/footer)。
 */
export function LiquidModal({
  open,
  onClose,
  title,
  size = 'md',
  maskClosable = true,
  escToClose = true,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  maskClosable?: boolean;
  escToClose?: boolean;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open || !escToClose) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, escToClose, onClose]);

  const widths = { sm: 'max-w-sm', md: 'max-w-md', lg: 'max-w-2xl', xl: 'max-w-4xl' };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          key="liquid-modal"
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <motion.div
            className="absolute inset-0 bg-black/60 backdrop-blur-md"
            onClick={(e) => {
              if (maskClosable && e.target === e.currentTarget) onClose();
            }}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 28 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 16 }}
            transition={{ type: 'spring', stiffness: 340, damping: 28 }}
            className={clsx(
              'liquid-glass relative w-full mx-4 p-6 space-y-4 max-h-[90vh] overflow-y-auto',
              widths[size],
            )}
          >
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="show"
              className="space-y-4"
            >
              <motion.header variants={staggerItem} className="flex items-center justify-between">
                <h3 className="font-semibold text-lg text-text-pri">{title}</h3>
                {maskClosable && (
                  <button
                    className="text-text-ter hover:text-text-pri text-xl leading-none"
                    onClick={onClose}
                    aria-label="关闭"
                  >
                    ×
                  </button>
                )}
              </motion.header>
              <motion.div variants={staggerItem}>{children}</motion.div>
              {footer && (
                <motion.div variants={staggerItem} className="flex justify-end gap-2 pt-2">
                  {footer}
                </motion.div>
              )}
            </motion.div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
