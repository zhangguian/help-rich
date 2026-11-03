import { type HTMLAttributes } from 'react';

import clsx from 'clsx';

export interface SegmentedOption<T extends string | number> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}

interface SegmentedControlProps<T extends string | number>
  extends Omit<HTMLAttributes<HTMLDivElement>, 'onChange'> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
}

/**
 * 段控(v0.7 Dark Terminal)
 *
 * 收敛此前 6 处段控实现(WinrateCard / ReplayCard / sector-fund-flow ×2 /
 * SectorBoard / page.tsx ×2),此前 5 套不同圆角与配色变体。
 */
export function SegmentedControl<T extends string | number>({
  options,
  value,
  onChange,
  size = 'sm',
  className,
  ...rest
}: SegmentedControlProps<T>) {
  return (
    <div
      role="tablist"
      className={clsx('inline-flex items-center gap-0.5 p-0.5 rounded bg-bg-surface border border-border-def', className)}
      {...rest}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={o.disabled}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={clsx(
              'rounded transition-colors font-medium whitespace-nowrap disabled:opacity-40 disabled:cursor-not-allowed',
              size === 'sm' ? 'px-2.5 py-0.5 text-xs' : 'px-3 py-1 text-[13px]',
              active
                ? 'bg-accent-subtle text-accent border border-accent/40'
                : 'text-text-sec border border-transparent hover:text-text-pri hover:bg-surface-2',
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
