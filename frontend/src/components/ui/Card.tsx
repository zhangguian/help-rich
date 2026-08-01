import { type HTMLAttributes, forwardRef } from 'react';

import clsx from 'clsx';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: 'sm' | 'md' | 'lg';
}

const paddingClasses = {
  sm: 'p-3',
  md: 'p-6',
  lg: 'p-8',
};

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ padding = 'md', className, children, ...rest }, ref) => {
    return (
      <div
        ref={ref}
        className={clsx(
          'rounded-md border border-border-def bg-bg-surface shadow-sm',
          paddingClasses[padding],
          className,
        )}
        {...rest}
      >
        {children}
      </div>
    );
  },
);
Card.displayName = 'Card';