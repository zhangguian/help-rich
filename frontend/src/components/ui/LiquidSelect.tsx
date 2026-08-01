'use client';

import { useEffect, useRef, useState } from 'react';

import { AnimatePresence, motion } from 'framer-motion';
import { createPortal } from 'react-dom';
import clsx from 'clsx';

export interface LiquidSelectOption {
  value: string;
  label: string;
}

/**
 * LiquidSelect(v0.4-roadmap §3.7)
 *
 * 液态玻璃下拉:portal 面板 + spring 弹出 + emerald 勾选态。
 * 禁用原生 <select>,全站统一使用本组件。
 */
export function LiquidSelect({
  value,
  options,
  onChange,
  placeholder = '请选择',
  className,
}: {
  value: string | null;
  options: LiquidSelectOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);

  const selected = options.find((o) => o.value === value);

  const updatePos = () => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos({ top: r.bottom + 8, left: r.left, width: r.width });
  };

  useEffect(() => {
    if (!open) return;
    updatePos();
    const onScroll = () => updatePos();
    const onResize = () => updatePos();
    const onClickOutside = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current && triggerRef.current.contains(t)) return;
      setOpen(false);
    };
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    document.addEventListener('mousedown', onClickOutside);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
      document.removeEventListener('mousedown', onClickOutside);
    };
  }, [open]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          'liquid-pill flex items-center justify-between gap-2 px-4 py-2 text-sm text-text-pri',
          'bg-white/5 border border-white/10 rounded-xl backdrop-blur-md',
          'hover:bg-white/10 transition-colors',
          className,
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={clsx(!selected && 'text-text-ter')}>{selected ? selected.label : placeholder}</span>
        <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
          ▾
        </motion.span>
      </button>

      {typeof document !== 'undefined' &&
        open &&
        pos &&
        createPortal(
          <AnimatePresence>
            <motion.div
              key="liquid-select"
              role="listbox"
              initial={{ opacity: 0, scale: 0.95, y: -6 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97, y: -4 }}
              transition={{ type: 'spring', stiffness: 380, damping: 30 }}
              className="liquid-glass fixed z-[60] overflow-hidden p-1.5"
              style={{ top: pos.top, left: pos.left, width: Math.max(pos.width, 160) }}
            >
              {options.map((o) => {
                const isActive = o.value === value;
                return (
                  <button
                    key={o.value}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    onClick={() => {
                      onChange(o.value);
                      setOpen(false);
                    }}
                    className={clsx(
                      'flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors',
                      isActive ? 'text-accent bg-accent-subtle' : 'text-text-sec hover:text-text-pri hover:bg-white/5',
                    )}
                  >
                    {o.label}
                    {isActive && <span className="text-accent">✓</span>}
                  </button>
                );
              })}
            </motion.div>
          </AnimatePresence>,
          document.body,
        )}
    </>
  );
}
