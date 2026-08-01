'use client';

import Link from 'next/link';

import { useEffect, useState } from 'react';

import { useUIStore } from '@/stores/useUIStore';

import { Button } from '../ui/Button';
import { Card } from '../ui/Card';

/**
 * 今日反思卡(P7.5,ui-ux §4.1)
 *
 * 触发条件:当前时间 ≥ 22:00 + 当日已录入至少 1 笔交易
 * 内容:今日笔数 / 已实现盈亏 / 提示"回顾持仓是否理性"
 *
 * 持久化:localStorage 记录 dismiss 日期(每天只显示一次)
 */
const DISMISS_KEY = 'rich-reflection-dismiss-date';

function isAfterTenPM(): boolean {
  const now = new Date();
  return now.getHours() >= 22;
}

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

export function ReflectionCard() {
  const showToast = useUIStore((s) => s.showToast);
  const [show, setShow] = useState(false);
  const [tradeCount, setTradeCount] = useState(0);
  const [realizedPnl, setRealizedPnl] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!isAfterTenPM()) return;

    try {
      if (localStorage.getItem(DISMISS_KEY) === todayKey()) return;
    } catch {
      return;
    }

    // 拉今日交易统计
    import('@/lib/api').then(async ({ apiGet }) => {
      try {
        const r = await apiGet<{ items: Array<{ trade_date: string }> }>('/transactions?limit=100');
        const today = todayKey();
        const todayTrades = r.items.filter((t) => t.trade_date === today);
        if (todayTrades.length === 0) return;
        setTradeCount(todayTrades.length);
        // 已实现盈亏(从 positions 读)
        const pos = await apiGet<{ items: Array<{ realizedPnl: string }> }>('/positions');
        const total = pos.items.reduce((s, p) => s + Number(p.realizedPnl), 0);
        setRealizedPnl(total.toFixed(2));
        setShow(true);
      } catch {
        /* ignore */
      }
    });
  }, []);

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, todayKey());
    } catch {
      /* ignore */
    }
    setShow(false);
  };

  if (!show) return null;

  const pnlNum = realizedPnl ? Number(realizedPnl) : 0;
  const pnlClass = pnlNum > 0 ? 'text-up' : pnlNum < 0 ? 'text-down' : 'text-text-ter';

  return (
    <Card padding="md" className="border-warn/40 bg-warn-bg/30">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="font-semibold flex items-center gap-2">
            🌙 今日反思
            <span className="text-xs font-mono text-text-ter">
              {todayKey()}
            </span>
          </div>
          <p className="text-sm text-text-sec mt-2 leading-relaxed">
            今日共录入 <span className="font-mono font-semibold">{tradeCount}</span> 笔交易。
            <br />
            当前已实现盈亏:
            <span className={`font-mono font-semibold ml-1 ${pnlClass}`}>
              ¥{realizedPnl ?? '--'}
            </span>
            <br />
            <span className="text-text-ter text-xs">
              睡前 30 秒,看一眼持仓,问自己:今天是因为理性还是情绪做了决定?
            </span>
          </p>
          <div className="mt-3 flex gap-2">
            <Link href="/">
              <Button size="sm" variant="secondary">
                查看持仓
              </Button>
            </Link>
            <Link href="/transactions">
              <Button size="sm" variant="ghost">
                回顾流水
              </Button>
            </Link>
          </div>
        </div>
        <button
          onClick={dismiss}
          className="text-text-ter hover:text-text-pri text-xl leading-none"
          aria-label="关闭"
          title="今天不再提醒"
        >
          ×
        </button>
      </div>
    </Card>
  );
}