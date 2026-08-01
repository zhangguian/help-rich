'use client';

import { useEffect, useState } from 'react';

import Link from 'next/link';

import { apiGet } from '@/lib/api';

import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';

interface RebalanceAction {
  type: 'reduce' | 'add' | 'diversify' | 'alert';
  priority: 'high' | 'medium' | 'low';
  stock_code: string | null;
  stock_name: string | null;
  title: string;
  reason: string;
  suggested_pct: number;
}

interface RebalanceSuggestion {
  total_market_value: number;
  actions: RebalanceAction[];
  summary: string;
}

const TYPE_META: Record<RebalanceAction['type'], { icon: string; color: string; label: string }> = {
  reduce: { icon: '📉', color: 'text-up', label: '减仓' },
  add: { icon: '📈', color: 'text-down', label: '加仓' },
  diversify: { icon: '🌐', color: 'text-warn', label: '分散' },
  alert: { icon: '⚠️', color: 'text-warn', label: '提示' },
};

const PRIORITY_META: Record<RebalanceAction['priority'], { label: string; bg: string }> = {
  high: { label: '高', bg: 'bg-up-bg text-up' },
  medium: { label: '中', bg: 'bg-warn-bg text-warn' },
  low: { label: '低', bg: 'bg-down-bg text-down' },
};

export default function RebalancePage() {
  const [data, setData] = useState<RebalanceSuggestion | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<RebalanceSuggestion>('/rebalance-suggestion')
      .then(setData)
      .catch((e) => setError(e?.response?.data?.detail?.message ?? '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen p-8 max-w-4xl mx-auto space-y-6">
      <header>
        <Link href="/" className="text-sm text-text-sec hover:text-text-pri">
          ← 返回首页
        </Link>
        <h1 className="text-2xl font-bold mt-2">智能调仓建议</h1>
        <p className="text-text-sec text-sm mt-1">
          基于当前持仓 + 风险报告生成减仓 / 加仓 / 分散建议(MVP 暂不接真实交易 API)
        </p>
      </header>

      {loading && <SkeletonState rows={3} height="h-20" />}

      {error && (
        <Card padding="md">
          <p className="text-up">⚠ {error}</p>
        </Card>
      )}

      {data && !loading && (
        <>
          <Card padding="md">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-text-sec">总市值</div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  ¥{data.total_market_value.toFixed(2)}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm text-text-sec">建议数</div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  {data.actions.length}
                </div>
              </div>
            </div>
            <p className="mt-3 text-sm text-text-sec">{data.summary}</p>
          </Card>

          {data.actions.length === 0 ? (
            <Card padding="lg">
              <p className="text-center text-down font-semibold py-6">
                ✅ 持仓结构合理,无需调仓
              </p>
            </Card>
          ) : (
            <div className="space-y-3">
              {data.actions.map((a, i) => {
                const tm = TYPE_META[a.type];
                const pm = PRIORITY_META[a.priority];
                return (
                  <Card key={i} padding="md">
                    <div className="flex items-start gap-3">
                      <div className={`text-2xl ${tm.color}`}>{tm.icon}</div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs px-2 py-0.5 rounded-sm bg-bg-subtle text-text-sec">
                            {tm.label}
                          </span>
                          <span className={`text-xs px-2 py-0.5 rounded-sm ${pm.bg}`}>
                            {pm.label}优先级
                          </span>
                          {a.suggested_pct > 0 && (
                            <span className="text-xs text-text-sec">
                              建议: {a.suggested_pct.toFixed(0)}%
                            </span>
                          )}
                        </div>
                        <h3 className="font-semibold mt-2">{a.title}</h3>
                        <p className="text-sm text-text-sec mt-1.5 leading-relaxed">
                          {a.reason}
                        </p>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </>
      )}
    </main>
  );
}