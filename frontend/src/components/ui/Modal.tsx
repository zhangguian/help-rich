'use client';

import clsx from 'clsx';

import type { ReactNode } from 'react';

/**
 * 通用 Modal(ui-ux §11.5)
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
  if (!open) return null;

  const widths = { sm: 'max-w-sm', md: 'max-w-md', lg: 'max-w-2xl' };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (maskClosable && e.target === e.currentTarget) onClose();
      }}
      onKeyDown={(e) => {
        if (escToClose && e.key === 'Escape') onClose();
      }}
    >
      <div
        className={clsx(
          'bg-bg-surface rounded-md shadow-lg w-full mx-4 p-6 space-y-4 max-h-[90vh] overflow-y-auto',
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
      </div>
    </div>
  );
}