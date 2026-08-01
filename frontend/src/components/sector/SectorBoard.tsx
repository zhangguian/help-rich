'use client';

import { useEffect, useState } from 'react';

import { apiGet } from '@/lib/api';

import { GlassCard } from '@/components/ui/GlassCard';
import { SkeletonState } from '@/components/ui/States';

interface SectorItem {
  name: string;
  netamountYi: number;
  inamountYi: number;
  outamountYi: number;
  topStock?: { name: string; changePercent: number } | null;
}

/**
 * 板块资金排行(roadmap 功能7 收编中间区)
 *
 * 今日资金净流入排行:净额(亿)红涨绿跌 + 领涨股。
 */
export function SectorBoard() {
  const [items, setItems] = useState<SectorItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<{ items: SectorItem[] }>('/sector-fund-flow?fenlei=0&num=20&sort=netamount')
      .then((r) => setItems(r.items))
      .catch(() => setError('板块数据暂不可用'))
      .finally(() => setLoading(false));
  }, []);

  const netCls = (v: number) => (v >= 0 ? 'text-up' : 'text-down');

  return (
    <GlassCard padding="md" className="h-full flex flex-col overflow-hidden gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-text-pri">板块资金</span>
        <span className="text-xs text-text-ter">今日净流入排行</span>
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
