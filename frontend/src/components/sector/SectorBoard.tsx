'use client';

import { useEffect, useRef, useState } from 'react';

import { apiGet, apiBaseUrl } from '@/lib/api';
import { useUIStore } from '@/stores/useUIStore';

import { GlassCard } from '@/components/ui/GlassCard';
import { SkeletonState } from '@/components/ui/States';

interface SectorItem {
  name: string;
  netamountYi: number;
  inamountYi: number;
  outamountYi: number;
  topStock?: { name: string; changePercent: number } | null;
}

interface SectorAlert {
  fenlei: number;
  name: string;
  prevYi: number;
  currYi: number;
  deltaYi: number;
  reason: string;
  topStockCode?: string | null;
}

const REASON_TEXT: Record<string, string> = {
  delta: '净流入大幅变化',
  new: '新进榜',
};

function alertText(a: SectorAlert): string {
  const sign = a.deltaYi > 0 ? '+' : '';
  const reason =
    a.reason.startsWith('top_stock_changed')
      ? '领涨股切换'
      : REASON_TEXT[a.reason] ?? '异动';
  return `${a.name} ${reason}:净额 ${sign}${a.deltaYi.toFixed(2)} 亿`;
}

/**
 * 板块资金排行 + 异动订阅(roadmap 功能7/10)
 *
 * 今日资金净流入排行:净额(亿)红涨绿跌 + 领涨股。
 * 开启 [🔔 订阅异动] 后连接 SSE,异动(sector_fund_flow_alert)逐条 toast。
 */
export function SectorBoard() {
  const showToast = useUIStore((s) => s.showToast);
  const [items, setItems] = useState<SectorItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [subscribed, setSubscribed] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    apiGet<{ items: SectorItem[] }>('/sector-fund-flow?fenlei=0&num=20&sort=netamount')
      .then((r) => setItems(r.items))
      .catch(() => setError('板块数据暂不可用'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!subscribed) return;
    let closed = false;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${apiBaseUrl()}/sector-fund-flow/events?fenlei=0`);
      es.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as { event: string; alerts?: SectorAlert[] };
          if (msg.event !== 'sector_fund_flow_alert' || !msg.alerts?.length) return;
          msg.alerts.slice(0, 3).forEach((a) =>
            showToast({ type: 'info', message: alertText(a), duration: 5000 }),
          );
        } catch {
          /* ignore non-JSON */
        }
      };
      es.onerror = () => {
        if (closed) return;
        es?.close();
        es = null;
      };
      esRef.current = es;
    } catch {
      /* EventSource 不可用 */
    }
    return () => {
      closed = true;
      es?.close();
      esRef.current = null;
    };
  }, [subscribed, showToast]);

  const netCls = (v: number) => (v >= 0 ? 'text-up' : 'text-down');

  return (
    <GlassCard padding="md" className="h-full flex flex-col overflow-hidden gap-3">
      <div className="flex items-center justify-between shrink-0">
        <span className="text-sm font-semibold text-text-pri">板块资金</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-ter">今日净流入排行</span>
          <button
            onClick={() => setSubscribed((v) => !v)}
            className={`px-3 py-1 text-xs rounded-xl border transition-colors ${
              subscribed
                ? 'bg-accent-subtle text-accent border-accent/25'
                : 'bg-white/5 text-text-sec hover:text-text-pri border-white/10'
            }`}
          >
            {subscribed ? '🔔 订阅中' : '🔕 订阅异动'}
          </button>
        </div>
      </div>
      {loading && <SkeletonState rows={6} height="h-10" />}
      {error && <p className="text-sm text-down">⚠ {error}</p>}
      {!loading && !error && (
        <ul className="flex-1 overflow-y-auto space-y-1 min-h-0">
          {items.map((it, i) => (
            <li
              key={it.name}
              className="flex items-center justify-between rounded-xl px-3 py-2 hover:bg-white/5 transition-colors"
            >
              <div className="min-w-0 flex items-center gap-2">
                <span className="text-xs text-text-ter font-mono w-5">{i + 1}</span>
                <span className="text-sm text-text-pri truncate">{it.name}</span>
              </div>
              <div className="text-right shrink-0">
                <div className={`text-sm font-mono ${netCls(it.netamountYi)}`}>
                  {it.netamountYi > 0 ? '+' : ''}
                  {it.netamountYi.toFixed(2)} 亿
                </div>
                {it.topStock && (
                  <div className="text-xs text-text-ter truncate max-w-36">
                    领涨 {it.topStock.name}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}
