'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { useEffect, useState } from 'react';

import clsx from 'clsx';

/**
 * 持久导航 rail(v0.7 Dark Terminal)
 *
 * 背景:此前 9 个 tab 只存在于首页内部(纯 useState,不改路由、不持久化),
 * 其余页面各自孤立、只有「← 返回首页」,页面间必须来回跳。
 * 本组件把导航提升为全局,延续原有 9 tab 的心智模型,分 3 组。
 *
 * 折叠态持久化到 localStorage;md 断点以下自动折叠为图标条。
 */

const COLLAPSE_KEY = 'rich-nav-collapsed';

interface NavItem {
  href: string;
  label: string;
  icon: string;
  /** 仅在该路径下高亮(用于 /stock/[code] 归入盯盘) */
  matchPrefix?: boolean;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  {
    title: '行情',
    items: [
      { href: '/', label: '盯盘', icon: '📈' },
      { href: '/market', label: '大盘', icon: '🌏' },
      { href: '/sector-fund-flow', label: '板块', icon: '🗂' },
      { href: '/news', label: '快讯', icon: '📰' },
    ],
  },
  {
    title: '决策',
    items: [
      { href: '/screener', label: '选股', icon: '🎯' },
      { href: '/watchlist', label: '观察池', icon: '⭐' },
      { href: '/replay-history', label: '复盘', icon: '🕐' },
      { href: '/stock/600519', label: '个股', icon: '🔍', matchPrefix: true },
    ],
  },
  {
    title: '账户',
    items: [
      { href: '/positions', label: '持仓', icon: '💼' },
      { href: '/risk-report', label: '风险', icon: '⚠️' },
      { href: '/holdings-health', label: '体检', icon: '🩺' },
      { href: '/settings', label: '设置', icon: '⚙️' },
    ],
  },
];

function isActive(pathname: string, item: NavItem): boolean {
  if (item.href === '/') return pathname === '/';
  if (item.matchPrefix) return pathname.startsWith('/stock/');
  return pathname === item.href;
}

export function NavRail() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSE_KEY) === '1');
    } catch {
      /* ignore */
    }
  }, []);

  // md 以下自动折叠为图标条
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1023px)');
    const apply = () => setCollapsed(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  const toggle = () => {
    setCollapsed((v) => {
      const next = !v;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0');
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  return (
    <nav
      className={clsx(
        'shrink-0 h-screen sticky top-0 border-r border-border-def bg-surface flex flex-col transition-[width] duration-15',
        collapsed ? 'w-14' : 'w-[200px]',
      )}
      aria-label="主导航"
    >
      {/* Logo */}
      <div className="flex items-center gap-2 px-3 h-12 border-b border-border-def shrink-0">
        <span className="w-6 h-6 rounded bg-accent-subtle text-accent flex items-center justify-center text-sm shrink-0">
          📈
        </span>
        {!collapsed && <span className="text-[13px] font-semibold text-text-pri">买股工具室</span>}
      </div>

      {/* 导航项 */}
      <div className="flex-1 overflow-y-auto py-2">
        {GROUPS.map((g) => (
          <div key={g.title} className="mb-3">
            {!collapsed && (
              <div className="px-3 pb-1 text-[10px] font-semibold text-text-ter tracking-wider uppercase">
                {g.title}
              </div>
            )}
            {g.items.map((it) => {
              const active = isActive(pathname, it);
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  title={it.label}
                  prefetch
                  className={clsx(
                    'relative flex items-center gap-2.5 mx-1.5 px-2 py-1.5 rounded text-[13px] transition-colors',
                    active
                      ? 'bg-accent-subtle text-accent font-semibold'
                      : 'text-text-sec hover:text-text-pri hover:bg-surface-2',
                  )}
                >
                  {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-accent" />}
                  <span className="w-4 text-center shrink-0">{it.icon}</span>
                  {!collapsed && <span className="truncate">{it.label}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </div>

      {/* 折叠开关 */}
      <button
        type="button"
        onClick={toggle}
        title={collapsed ? '展开导航' : '收起导航'}
        className="h-9 border-t border-border-def text-text-ter hover:text-text-pri hover:bg-surface-2 transition-colors text-xs shrink-0"
      >
        {collapsed ? '»' : '« 收起'}
      </button>
    </nav>
  );
}
