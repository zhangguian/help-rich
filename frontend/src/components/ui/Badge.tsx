import { type HTMLAttributes } from 'react';

import clsx from 'clsx';

/**
 * Badge 变体按**语义**命名,不按涨跌方向。
 *
 * 旧实现的 `good` 映射到绿色(`bg-down-bg`)、`bad` 映射到红色(`bg-up-bg`),
 * 借用的是行情色,与 A 股「红涨绿跌」直觉相反(绿的 good 读起来像跌)。
 * 新变体各归其位:状态类走语义色,行情类走 up/down。
 */
type BadgeVariant = 'positive' | 'negative' | 'caution' | 'neutral' | 'up' | 'down' | 'info' | 'pool';

/** 过渡期接受的旧变体名(映射见 LEGACY) */
type LegacyBadgeVariant = 'good' | 'mid' | 'bad' | 'muted';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant | LegacyBadgeVariant;
  /**
   * 描边样式(作战计划 v2 的锚点栏 / 票头徽章)
   *
   * 填色版是全站默认;描边版给「一排小徽章」用 —— 填色块挨在一起会糊成一片,
   * 描边能保住每个徽章的独立轮廓与可读性。
   */
  outline?: boolean;
}

/** 每个变体两套样式:填色(默认) / 描边(outline) */
const variantTone: Record<BadgeVariant, { fill: string; outline: string }> = {
  // 语义态
  positive: {
    fill: 'bg-success-bg text-success',
    outline: 'bg-success-bg text-success border border-success/40',
  },
  negative: {
    fill: 'bg-danger-bg text-danger',
    outline: 'bg-danger-bg text-danger border border-danger/40',
  },
  caution: {
    fill: 'bg-warn-bg text-warn',
    outline: 'bg-warn-bg text-warn border border-warn/40',
  },
  info: {
    fill: 'bg-info-bg text-info',
    outline: 'bg-info-bg text-info border border-info/40',
  },
  neutral: {
    fill: 'bg-bg-subtle text-text-ter',
    outline: 'bg-bg-subtle text-text-ter border border-border-str',
  },
  // 行情态(仅用于价格方向,数值须带 +/- 号作冗余编码)
  up: {
    fill: 'bg-up-bg text-up',
    outline: 'bg-up-bg text-up border border-up/40',
  },
  down: {
    fill: 'bg-down-bg text-down',
    outline: 'bg-down-bg text-down border border-down/40',
  },
  // 滚动池(作战计划 v2)—— 紫色只标识「来自全市场滚动池」
  pool: {
    fill: 'bg-pool-bg text-pool',
    outline: 'bg-pool-bg text-pool border border-pool/40',
  },
};

/** 旧变体名 -> 新语义名(过渡期保留,便于分批迁移调用方) */
const LEGACY: Record<string, BadgeVariant> = {
  good: 'positive',
  mid: 'caution',
  bad: 'negative',
  muted: 'neutral',
};

export function Badge({
  variant = 'neutral',
  outline = false,
  className,
  children,
  ...rest
}: BadgeProps) {
  const resolved: BadgeVariant =
    LEGACY[variant as LegacyBadgeVariant] ?? (variant as BadgeVariant);
  const tone = variantTone[resolved];
  return (
    <span
      className={clsx(
        'inline-block px-1.5 py-0.5 rounded text-[11px] font-mono font-medium',
        outline ? tone.outline : tone.fill,
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
