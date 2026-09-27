import { type ReactNode } from 'react';

import Link from 'next/link';

/**
 * 页面外壳(v0.7 Dark Terminal)
 *
 * 收敛此前 5 份逐行雷同的页面模板(sector-fund-flow / risk-report / rebalance /
 * annual-report / provider-stats),它们只有 h1 文案不同。
 */
export function PageShell({
  title,
  subtitle,
  icon,
  backHref = '/',
  backLabel = '返回首页',
  children,
}: {
  title: string;
  subtitle?: string;
  icon?: string;
  backHref?: string;
  backLabel?: string;
  children: ReactNode;
}) {
  return (
    <main className="p-5 max-w-6xl mx-auto space-y-4">
      <header className="space-y-1.5">
        <Link href={backHref} className="text-xs text-text-ter hover:text-accent">
          ← {backLabel}
        </Link>
        <h1 className="text-xl font-semibold text-text-pri">
          {icon && <span className="mr-1.5">{icon}</span>}
          {title}
        </h1>
        {subtitle && <p className="text-sm text-text-sec">{subtitle}</p>}
      </header>
      {children}
    </main>
  );
}
