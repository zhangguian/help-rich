'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { useEffect, useRef, useState } from 'react';

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
      { href: '/plan', label: '作战计划', icon: '🗓' },
      { href: '/market', label: '大盘', icon: '🌏' },
      { href: '/sector-fund-flow', label: '板块', icon: '🗂' },
      { href: '/news', label: '快讯', icon: '📰' },
    ],
  },
  {
    title: '决策',
    items: [
      { href: '/screener', label: '选股', icon: '🎯' },
      { href: '/backtest', label: '回测', icon: '📊' },
      { href: '/analysis', label: '深度分析', icon: '🤖' },
      { href: '/brief', label: '盘前简报', icon: '☀️' },
      { href: '/watchlist', label: '观察池', icon: '⭐' },
      { href: '/replay-history', label: '复盘', icon: '🕐' },
    ],
  },
  {
    title: '执行',
    items: [
      { href: '/price-alerts', label: '提醒', icon: '🔔' },
      { href: '/paper-trading', label: '模拟盘', icon: '🎮' },
    ],
  },
  {
    title: '账户',
    items: [
      { href: '/positions', label: '持仓', icon: '💼' },
      { href: '/accounts', label: '多账户', icon: '🏦' },
      { href: '/risk-report', label: '风险', icon: '⚠️' },
      { href: '/holdings-health', label: '体检', icon: '🩺' },
      { href: '/settings', label: '设置', icon: '⚙️' },
      { href: '/onboarding', label: '引导', icon: '🚀' },
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
  // 用户是否手动切换过 —— 手动切换后就不再被断点监听覆盖
  const manualRef = useRef(false);

  useEffect(() => {
    try {
      // v0.8 交易台:**默认收起**为图标轨(48px)—— 横向空间让给行情列表与图表。
      // 用户手动展开/收起后以 localStorage 为准(manualRef 标记,断点不再覆盖)。
      const stored = localStorage.getItem(COLLAPSE_KEY);
      setCollapsed(stored !== '0');
      if (stored === '0' || stored === '1') manualRef.current = true;
    } catch {
      /* ignore */
    }
  }, []);

  // 断点兜底:窄屏(<1024px)强制收起为图标条。
  // **只收不放** —— 宽屏也不自动展开,因为交易台默认就该是 48px 图标轨。
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1023px)');
    const apply = () => {
      if (manualRef.current) return;
      if (mq.matches) setCollapsed(true);
    };
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  const toggle = () => {
    manualRef.current = true;
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
        'shrink-0 h-screen sticky top-0 border-r border-border-def bg-bg-surface flex flex-col transition-[width] duration-15',
        collapsed ? 'w-12' : 'w-[200px]',
      )}
      aria-label="主导航"
    >
      {/* Logo */}
      <div
        className={clsx(
          'flex items-center gap-2 px-2 h-10 border-b border-border-def shrink-0',
          collapsed ? 'justify-center' : '',
        )}
      >
        <span className="w-7 h-7 rounded-md bg-accent-subtle text-accent flex items-center justify-center text-sm shrink-0">
          📈
        </span>
        {!collapsed && <span className="text-[13px] font-semibold text-text-pri whitespace-nowrap">买股工具室</span>}
      </div>

      {/* 导航项 */}
      <div className="flex-1 overflow-y-auto py-2">
        {GROUPS.map((g) => (
          <div key={g.title} className="mb-2">
            {!collapsed && (
              <div className="px-3 pb-1 text-[10px] font-semibold text-text-ter tracking-wider uppercase">
                {g.title}
              </div>
            )}
            {collapsed && (
              <div className="mx-auto mb-1.5 w-4 h-px bg-border-def" aria-hidden />
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
                    collapsed ? 'justify-center px-0' : '',
                    active
                      ? 'bg-accent-subtle text-accent font-semibold'
                      : 'text-text-ter hover:text-text-sec hover:bg-bg-subtle',
                  )}
                >
                  {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-accent" />}
                  {/* emoji 是彩色字形,不继承 text-color —— 用 grayscale 滤镜压成灰,
                      选中时才恢复彩色,避免在终端底色上显得花 */}
                  <span
                    className={clsx(
                      'w-4 text-center shrink-0 text-[14px] leading-none transition-all',
                      active ? 'grayscale-0 opacity-100' : 'grayscale opacity-60',
                    )}
                  >
                    {it.icon}
                  </span>
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
        className="h-9 border-t border-border-def text-text-ter hover:text-text-sec hover:bg-bg-subtle transition-colors text-xs shrink-0"
      >
        {collapsed ? '»' : '« 收起'}
      </button>
    </nav>
  );
}
