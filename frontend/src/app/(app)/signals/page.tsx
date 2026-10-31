'use client';

/**
 * /signals — 盘中信号流水(盘中持仓信号 · 桌面通知 ADR-0007)
 *
 * 展示后端推送/记录的全部信号:命中了什么、触发价多少、**有没有真的推出去**。
 * 被冷却/限流或发送失败的行也会出现在这里(后端落库),并标出原因 ——
 * 避免"我没收到通知 → 是不是坏了"这种猜。
 */
import { useCallback, useEffect, useState } from 'react';

import { PageShell } from '@/components/shell/PageShell';
import { Card } from '@/components/ui/Card';
import { fetchSignalTriggers, type SignalTrigger } from '@/lib/api/advanced';
import { useSignalStream } from '@/hooks/useSignalStream';
import { useSignalStore } from '@/stores/useSignalStore';

/** 信号类型 → 中文名(与后端 `modules/signal/engine.py` 的 kind 对齐) */
const KIND_LABELS: Record<string, string> = {
  velocity_up: '急速拉升',
  velocity_down: '急速下跌',
  breakout_up: '涨幅突破',
  breakout_down: '跌幅突破',
  t_sell_point: '已到 T 卖出点',
  t_buyback_point: '已到 T 买回点',
  grid_sell_point: '已到网格卖点',
  buy_point: '已到买点',
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

export default function SignalsPage() {
  useSignalStream();
  const live = useSignalStore((s) => s.items);
  const connected = useSignalStore((s) => s.connected);
  const runtime = useSignalStore((s) => s.runtime);
  const [history, setHistory] = useState<SignalTrigger[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchSignalTriggers(undefined, 100);
      setHistory(data.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 实时推来的信号排在最前,历史在后(去重:同 id 只留一条)
  const seen = new Set<number>();
  const items = [...live, ...history].filter((it) => {
    if (seen.has(it.id)) return false;
    seen.add(it.id);
    return true;
  });

  const notes = Object.entries(runtime?.notes ?? {}).filter(([, v]) => v.length > 0);

  return (
    <PageShell
      title="盘中信号"
      subtitle="持仓股的急速涨跌、突破、做T点与买点 —— 后端直接弹桌面通知"
      icon="📡"
    >
      <div className="max-w-3xl space-y-4">
        <Card padding="lg" className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold">信号流水</span>
            <span className="text-[11px] text-text-ter">
              {connected ? '实时流已连接' : '实时流未连接(显示历史记录)'}
            </span>
          </div>
          {error && (
            <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
              {error}
            </div>
          )}
          {loading && items.length === 0 ? (
            <div className="text-sm text-text-sec">加载中…</div>
          ) : items.length === 0 ? (
            <div className="text-sm text-text-sec">
              还没有信号记录。盘中命中阈值后会实时出现在这里。
            </div>
          ) : (
            <ul className="space-y-2">
              {items.map((it) => (
                <li key={it.id} className="rounded-md border border-border-base p-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-medium text-text-pri">
                      {kindLabel(it.kind)} · {it.stockName || it.stockCode}
                    </span>
                    <span
                      className={
                        it.notified
                          ? 'rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent'
                          : 'rounded bg-bg-elev px-1.5 py-0.5 text-[10px] text-text-ter'
                      }
                    >
                      {it.notified ? '已推送' : '未推送'}
                    </span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-[11px] text-text-sec">{it.body}</p>
                  <p className="mt-1 text-[10px] text-text-ter">
                    {it.createdAt ? new Date(it.createdAt).toLocaleString('zh-CN') : ''}
                    {it.level != null ? ` · 触发价 ${it.level.toFixed(2)}` : ''}
                    {it.value != null && it.level == null
                      ? ` · 幅度 ${it.value.toFixed(2)}%`
                      : ''}
                  </p>
                  {it.error && <p className="mt-1 text-[10px] text-danger">{it.error}</p>}
                </li>
              ))}
            </ul>
          )}
        </Card>

        {notes.length > 0 && (
          <Card padding="lg" className="space-y-2">
            <span className="text-sm font-semibold">今日不适合做T / 做网格</span>
            <ul className="space-y-1">
              {notes.map(([code, list]) => (
                <li key={code} className="text-[11px] text-text-sec">
                  <span className="font-medium text-text-pri">{code}</span>:{list.join(';')}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </PageShell>
  );
}
