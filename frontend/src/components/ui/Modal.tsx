'use client';

import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';

import type { ReactNode } from 'react';

/**
 * 通用 Modal(v0.4 Liquid Glass 版,ui-ux §11.5)
 *
 * 遮罩 blur 淡入 + 面板 spring 缩放上浮(动效铁律:所有二级弹窗 LiquidModal 风格)。
 * API 与旧版完全兼容。
 *
 * - maskClosable 控制点击遮罩是否关闭(止损 Alert 用 false 强制决策)
 * - escToClose 控制 ESC 键关闭
 */
export function Modal({
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
  size?: 'sm' | 'md' | 'lg';
  maskClosable?: boolean;
  escToClose?: boolean;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const widths = { sm: 'max-w-sm', md: 'max-w-md', lg: 'max-w-2xl' };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          key="modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={(e) => {
            if (maskClosable && e.target === e.currentTarget) onClose();
          }}
          onKeyDown={(e) => {
            if (escToClose && e.key === 'Escape') onClose();
          }}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 28 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 16 }}
            transition={{ type: 'spring', stiffness: 340, damping: 28 }}
            className={clsx(
              'liquid-glass w-full mx-4 p-6 space-y-4 max-h-[90vh] overflow-y-auto',
              widths[size],
            )}
          >
            <header className="flex items-center justify-between">
              <h3 className="font-semibold text-lg">{title}</h3>
              {maskClosable && (
                <button
                  className="text-text-ter hover:text-text-pri text-xl leading-none"
                  onClick={onClose}
                  aria-label="关闭"
                >
                  ×
                </button>
              )}
            </header>
            {children}
            {footer && <div className="flex justify-end gap-2 pt-2">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
