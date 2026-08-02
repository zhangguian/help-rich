'use client';

import { useEffect, useRef, useState } from 'react';

import { AnimatePresence, motion } from 'framer-motion';
import { createPortal } from 'react-dom';

import { GLOSSARY } from '@/lib/glossary';

/**
 * TermHint — 通用术语"?"提示(v1 · 路线图 12.2)
 *
 * - 渲染一个小"?"圆点图标,点击后弹出 tooltip 显示术语解释。
 * - 实现方式参考 LiquidSelect:portal + fixed 定位 + 滚动/点击外部关闭,
 *   避免被 overflow-y-auto 容器裁切。
 * - 词典来自前端 GLOSSARY(`frontend/src/lib/glossary.ts`);键不存在时静默不渲染。
 */
export function TermHint({ term, className }: { term: string; className?: string }) {
  const entry = GLOSSARY[term];
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  if (!entry) return null;

  const updatePos = () => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    // 优先在右侧,空间不够则放左侧
    const spaceRight = window.innerWidth - r.right;
    const left = spaceRight > 280 ? r.right + 6 : r.left - 286;
    const top = Math.min(window.innerHeight - 120, Math.max(8, r.top));
    setPos({ top, left });
  };

  useEffect(() => {
    if (!open) return;
    updatePos();
    const onScroll = () => updatePos();
    const onResize = () => updatePos();
    const onClickOutside = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current && triggerRef.current.contains(t)) return;
      const portal = document.getElementById('term-hint-portal');
      if (portal && portal.contains(t)) return;
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
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-label={`术语解释:${term}`}
        className={
          'inline-flex items-center justify-center w-3.5 h-3.5 rounded-full ' +
          'text-[10px] text-text-ter border border-white/20 ' +
          'hover:text-text-pri hover:border-accent/50 hover:bg-white/5 ' +
          'transition-colors cursor-help leading-none align-middle ml-1 ' +
          (className ?? '')
        }
      >
        ?
      </button>

      {typeof document !== 'undefined' &&
        open &&
        pos &&
        createPortal(
          <AnimatePresence>
            <motion.div
              id="term-hint-portal"
              key="term-hint"
              role="tooltip"
              initial={{ opacity: 0, y: -4, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -4, scale: 0.97 }}
              transition={{ duration: 0.15 }}
              className="liquid-glass fixed z-[60] rounded-lg p-3 text-xs text-text-sec leading-relaxed shadow-lg"
              style={{ top: pos.top, left: pos.left, width: 280 }}
            >
              <div className="text-text-ter text-[10px] uppercase tracking-wide mb-1">
                术语 · {term}
              </div>
              <div className="text-text-pri">{entry.desc}</div>
            </motion.div>
          </AnimatePresence>,
          document.body,
        )}
    </>
  );
}