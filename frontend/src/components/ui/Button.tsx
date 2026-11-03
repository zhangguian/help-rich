import { type ButtonHTMLAttributes, forwardRef } from 'react';

import clsx from 'clsx';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle';
type ButtonSize = 'xs' | 'sm' | 'md';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  fullWidth?: boolean;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-hover active:bg-accent-hover',
  secondary:
    'bg-bg-surface text-text-pri border border-border-def hover:bg-surface-2 hover:border-border-str',
  ghost: 'text-text-sec hover:text-text-pri hover:bg-surface-2',
  danger: 'bg-danger text-white hover:opacity-90',
  subtle: 'bg-bg-subtle text-text-sec border border-border-def hover:bg-surface-2 hover:text-text-pri',
};

const sizeClasses: Record<ButtonSize, string> = {
  xs: 'px-2 py-0.5 text-[11px]',
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-3 py-1.5 text-[13px]',
};

/**
 * 按钮(v0.7 Dark Terminal)
 *
 * variant 语义:
 * - primary   强调主操作(强调色实底)
 * - secondary 次级操作(面板底 + 边框)
 * - ghost     弱操作(无底,hover 才出底)
 * - subtle    标签式操作(浅底)
 * - danger    危险/破坏性操作(语义红,非行情红)
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      fullWidth,
      className,
      children,
      disabled,
      ...rest
    },
    ref,
  ) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={clsx(
          'inline-flex items-center justify-center rounded font-medium transition-colors whitespace-nowrap',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-canvas',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          variantClasses[variant],
          sizeClasses[size],
          fullWidth && 'w-full',
          className,
        )}
        {...rest}
      >
        {loading ? '...' : children}
      </button>
    );
  },
);
Button.displayName = 'Button';
