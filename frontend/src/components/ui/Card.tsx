import { type HTMLAttributes, forwardRef } from 'react';

import clsx from 'clsx';

type CardVariant = 'default' | 'raised' | 'interactive' | 'selected';
type CardPadding = 'sm' | 'md' | 'lg' | 'none';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: CardPadding;
  variant?: CardVariant;
}

const paddingClasses: Record<CardPadding, string> = {
  none: '',
  sm: 'p-2',
  md: 'p-3',
  lg: 'p-4',
};

const variantClasses: Record<CardVariant, string> = {
  default: 'panel',
  raised: 'panel shadow-pop',
  interactive: 'panel panel-hover cursor-default',
  selected: 'panel panel-active',
};

/**
 * 终端面板卡片(v0.7 Dark Terminal)
 *
 * 取代 v0.4 的 Liquid Glass(原名不副实:底色 94~97% 不透明白,blur 不可见)。
 * 深底上层次靠 1px 边框 + 顶缘内高光,不靠阴影。
 *
 * - default:静态面板
 * - raised:浮起(弹窗 / 抽屉)
 * - interactive:可交互(hover 提亮 + 边框增强)
 * - selected:选中态(强调色边框 + 淡强调底)
 */
export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ padding = 'md', variant = 'default', className, children, ...rest }, ref) => {
    return (
      <div
        ref={ref}
        className={clsx(variantClasses[variant], paddingClasses[padding], 'text-text-pri', className)}
        {...rest}
      >
        {children}
      </div>
    );
  },
);
Card.displayName = 'Card';
