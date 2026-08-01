import { type HTMLAttributes } from 'react';

import clsx from 'clsx';

type BadgeVariant = 'good' | 'mid' | 'bad' | 'muted';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantClasses: Record<BadgeVariant, string> = {
  good: 'bg-down-bg text-down',
  mid: 'bg-warn-bg text-warn',
  bad: 'bg-up-bg text-up',
  muted: 'bg-bg-subtle text-text-ter',
};

export function Badge({ variant = 'muted', className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-block px-2 py-0.5 rounded-sm text-xs font-mono font-medium',
        variantClasses[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}