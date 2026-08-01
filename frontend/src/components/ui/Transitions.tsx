'use client';

import { motion } from 'framer-motion';

import type { ReactNode } from 'react';

/**
 * ViewTransition(v0.4-roadmap §3.7)
 *
 * tab / 周期 / 视图切换:横向滑动 + blur,带方向感知。
 * 使用时父级需包 <AnimatePresence mode="wait">,并传唯一 key。
 */
export function ViewTransition({
  direction = 1,
  className,
  children,
}: {
  direction?: 1 | -1;
  className?: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 28 * direction, filter: 'blur(6px)' }}
      animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
      exit={{ opacity: 0, x: -28 * direction, filter: 'blur(6px)' }}
      transition={{ duration: 0.28, ease: 'easeOut' }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

/**
 * TitleTransition:顶部标题交叉淡入。
 */
export function TitleTransition({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.24, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  );
}

/**
 * RouteTransition:页面级切换(设置页等独立路由),左右滑入 + blur + 轻微缩放。
 */
export function RouteTransition({
  direction = 1,
  className,
  children,
}: {
  direction?: 1 | -1;
  className?: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 48 * direction, scale: 0.98, filter: 'blur(8px)' }}
      animate={{ opacity: 1, x: 0, scale: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, x: -48 * direction, scale: 0.99, filter: 'blur(8px)' }}
      transition={{ duration: 0.32, ease: 'easeOut' }}
      className={className}
    >
      {children}
    </motion.div>
  );
}
