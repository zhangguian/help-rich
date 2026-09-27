import { type HTMLAttributes } from 'react';

import clsx from 'clsx';

/**
 * Badge 变体按**语义**命名,不按涨跌方向。
 *
 * 旧实现的 `good` 映射到绿色(`bg-down-bg`)、`bad` 映射到红色(`bg-up-bg`),
 * 借用的是行情色,与 A 股「红涨绿跌」直觉相反(绿的 good 读起来像跌)。
 * 新变体各归其位:状态类走语义色,行情类走 up/down。
 */
type BadgeVariant = 'positive' | 'negative' | 'caution' | 'neutral' | 'up' | 'down' | 'info';

/** 过渡期接受的旧变体名(映射见 LEGACY) */
type LegacyBadgeVariant = 'good' | 'mid' | 'bad' | 'muted';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant | LegacyBadgeVariant;
}

const variantClasses: Record<BadgeVariant, string> = {
  // 语义态
  positive: 'bg-success-bg text-success',
  negative: 'bg-danger-bg text-danger',
  caution: 'bg-warn-bg text-warn',
  info: 'bg-info-bg text-info',
  neutral: 'bg-bg-subtle text-text-ter',
  // 行情态(仅用于价格方向,数值须带 +/- 号作冗余编码)
  up: 'bg-up-bg text-up',
  down: 'bg-down-bg text-down',
};

/** 旧变体名 -> 新语义名(过渡期保留,便于分批迁移调用方) */
const LEGACY: Record<string, BadgeVariant> = {
  good: 'positive',
  mid: 'caution',
  bad: 'negative',
  muted: 'neutral',
};

export function Badge({ variant = 'neutral', className, children, ...rest }: BadgeProps) {
  const resolved: BadgeVariant =
    LEGACY[variant as LegacyBadgeVariant] ?? (variant as BadgeVariant);
  return (
    <span
      className={clsx(
        'inline-block px-1.5 py-0.5 rounded text-[11px] font-mono font-medium',
        variantClasses[resolved],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
