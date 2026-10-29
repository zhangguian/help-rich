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
  wide = false,
  children,
}: {
  title: string;
  subtitle?: string;
  icon?: string;
  backHref?: string;
  backLabel?: string;
  /**
   * 宽版内容区(作战计划 v2 的三栏工作台用)
   *
   * 默认 `max-w-6xl`(1152px)对两栏够用,但三栏(左锚点 + 中预案 + 右预期)
   * 在 1152 里中栏只剩 500 出头,票头与条件行会挤成两行。
   * 宽版放到 1560 —— 实际宽度仍由视口与左侧导航决定。
   */
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <main
      className={
        wide
          ? 'p-4 max-w-[1560px] mx-auto space-y-3'
          : 'p-5 max-w-6xl mx-auto space-y-4'
      }
    >
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
