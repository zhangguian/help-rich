'use client';

import { useEffect, useState } from 'react';

import Link from 'next/link';

import { apiGet } from '@/lib/api';

import { Card } from '@/components/ui/Card';
import { LiquidSelect } from '@/components/ui/LiquidSelect';
import { SkeletonState } from '@/components/ui/States';

interface MonthlyItem {
  month: string;
  total: number;
  providers: Record<string, number>;
  statuses: Record<string, number>;
}

interface MonthlyResponse {
  year: number;
  items: MonthlyItem[];
}

interface SummaryProvider {
  provider: string;
  count: number;
  pct: number;
}

interface SummaryResponse {
  year: number;
  total: number;
  providers: SummaryProvider[];
}

const PROVIDER_COLOR: Record<string, string> = {
  deepseek: 'bg-accent',
  minimax: 'bg-warn',
  doubao: 'bg-down',
};

const PROVIDER_LABEL: Record<string, string> = {
  deepseek: 'DeepSeek',
  minimax: 'MiniMax',
  doubao: '豆包',
};

const MONTH_LABEL = [
  '一月', '二月', '三月', '四月', '五月', '六月',
  '七月', '八月', '九月', '十月', '十一月', '十二月',
];

export default function ProviderStatsPage() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [monthly, setMonthly] = useState<MonthlyResponse | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      apiGet<MonthlyResponse>(`/provider-stats/monthly?year=${year}`),
      apiGet<SummaryResponse>(`/provider-stats/summary?year=${year}`),
    ])
      .then(([m, s]) => {
        setMonthly(m);
        setSummary(s);
      })
      .catch((e) => setError(e?.response?.data?.detail?.message ?? '加载失败'))
      .finally(() => setLoading(false));
  }, [year]);

  return (
    <main className="min-h-screen p-8 max-w-5xl mx-auto space-y-6">
      <header>
        <Link href="/" className="text-sm text-text-sec hover:text-text-pri">
          ← 返回首页
        </Link>
        <h1 className="text-2xl font-bold mt-2">📊 多 Provider 占比</h1>
        <p className="text-text-sec text-sm mt-1">
          按月统计 LLM Provider 实际使用情况(基于 trade_scores.ai_provider)
        </p>
      </header>

      <div className="flex items-center gap-3">
        <label className="text-sm text-text-sec">年份</label>
        <LiquidSelect
          value={String(year)}
          options={[year + 1, year, year - 1]
            .filter((y) => y >= 2020)
            .map((y) => ({ value: String(y), label: String(y) }))}
          onChange={(v) => setYear(Number(v))}
        />
      </div>

      {loading && <SkeletonState rows={3} height="h-16" />}

      {error && (
        <Card padding="md">
          <p className="text-down">⚠ {error}</p>
        </Card>
      )}

      {summary && !loading && (
        <Card padding="md">
          <h3 className="font-semibold mb-3">{year} 年度汇总</h3>
          {summary.total === 0 ? (
            <p className="text-text-ter text-sm">
              本年暂无评分记录(录入流水后自动触发诊断评分,会出现在这里)
            </p>
          ) : (
            <div className="space-y-2">
              {summary.providers.map((p) => (
                <div key={p.provider}>
                  <div className="flex justify-between text-sm mb-1">
                    <span>{PROVIDER_LABEL[p.provider] ?? p.provider}</span>
                    <span className="font-mono">
                      {p.count} 次 · {p.pct}%
                    </span>
                  </div>
                  <div className="h-2 rounded-sm bg-bg-subtle overflow-hidden">
                    <div
                      className={`h-full ${PROVIDER_COLOR[p.provider] ?? 'bg-accent'}`}
                      style={{ width: `${p.pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {monthly && !loading && (
        <Card padding="md" className="overflow-x-auto">
          <h3 className="font-semibold mb-3">{year} 月度明细</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-text-sec border-b border-border-def">
                <th className="text-left py-2 pr-3">月份</th>
                <th className="text-right py-2 px-3">评分数</th>
                <th className="text-left py-2 pl-3">Provider 分布</th>
              </tr>
            </thead>
            <tbody>
              {monthly.items.map((m) => {
                const monthIdx = parseInt(m.month.split("-")[1] ?? "1", 10) - 1;
                return (
                  <tr
                    key={m.month}
                    className="border-b border-border-def last:border-0"
                  >
                    <td className="py-2.5 pr-3 font-medium">
                      {MONTH_LABEL[monthIdx]}
                      <span className="ml-2 text-text-ter text-xs font-mono">
                        {m.month}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono">
                      {m.total}
                    </td>
                    <td className="py-2.5 pl-3">
                      {m.total === 0 ? (
                        <span className="text-text-ter">--</span>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(m.providers).map(([p, n]) => (
                            <span
                              key={p}
                              className="text-xs px-1.5 py-0.5 rounded-sm bg-bg-subtle text-text-sec"
                            >
                              {PROVIDER_LABEL[p] ?? p}: {n}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </main>
  );
}