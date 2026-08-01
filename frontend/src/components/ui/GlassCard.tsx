import { type HTMLAttributes, forwardRef } from 'react';

import clsx from 'clsx';

interface GlassCardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: 'sm' | 'md' | 'lg';
  variant?: 'default' | 'hover' | 'active';
}

const paddingClasses = {
  sm: 'p-3',
  md: 'p-6',
  lg: 'p-8',
};

const variantClasses = {
  default: 'liquid-glass',
  hover: 'liquid-glass-hover',
  active: 'liquid-glass-active',
};

/**
 * Liquid Glass 材质卡片(v0.4-roadmap §3.2)
 *
 * 半透明 + blur(40px)+ 顶缘高光 + emerald 选中态
 * - default:静态玻璃面板
 * - hover:悬停提亮
 * - active:emerald 描边选中态(用于列表选中/当前视图)
 */
export const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(
  ({ padding = 'md', variant = 'default', className, children, ...rest }, ref) => {
    return (
      <div
        ref={ref}
        className={clsx(
          variantClasses[variant],
          paddingClasses[padding],
          'text-text-pri',
          className,
        )}
        {...rest}
      >
        {children}
      </div>
    );
  },
);
GlassCard.displayName = 'GlassCard';
