'use client';

import { useEffect, useState } from 'react';

import Link from 'next/link';

import { apiGet } from '@/lib/api';

import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';

interface SectorItem {
  category: string;
  name: string;
  avgPrice: number;
  changePct: number;
  turnoverYi: number;
  inamountYi: number;
  outamountYi: number;
  netamountYi: number;
  ratioamount: number;
  topStock: {
    code: string;
    name: string;
    price: number;
    changePct: number;
    ratioamount: number;
  } | null;
}

interface SectorResponse {
  fenlei: number;
  fenleiLabel: string;
  count: number;
  items: SectorItem[];
}

const FENLEI_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 0, label: '全部' },
  { value: 1, label: '行业' },
  { value: 2, label: '概念' },
  { value: 3, label: '地域' },
];

const SORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'netamount', label: '净流入' },
  { value: 'netbuy', label: '净买入' },
  { value: 'change', label: '涨幅' },
];

const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
const fmtYi = (v: number) => `${(v / 1e8).toFixed(2)}亿`;

export default function SectorFundFlowPage() {
  const [fenlei, setFenlei] = useState(0);
  const [sort, setSort] = useState('netamount');
  const [data, setData] = useState<SectorResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiGet<SectorResponse>(
      `/sector-fund-flow?fenlei=${fenlei}&num=20&sort=${sort}`,
    )
      .then(setData)
      .catch((e) => setError(e?.response?.data?.detail?.message ?? '加载失败'))
      .finally(() => setLoading(false));
  }, [fenlei, sort]);

  return (
    <main className="min-h-screen p-8 max-w-5xl mx-auto space-y-6">
      <header>
        <Link href="/" className="text-sm text-text-sec hover:text-text-pri">
          ← 返回首页
        </Link>
        <h1 className="text-2xl font-bold mt-2">板块资金流</h1>
        <p className="text-text-sec text-sm mt-1">
          新浪实时板块资金排行(guide §7,数据源 vip.stock.finance.sina.com.cn)
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex gap-2">
          {FENLEI_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => setFenlei(o.value)}
              className={`px-3 py-1.5 rounded-sm text-sm border ${
                fenlei === o.value
                  ? 'bg-up-bg text-up border-up'
                  : 'bg-bg-subtle text-text-sec border-transparent'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {SORT_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => setSort(o.value)}
              className={`px-3 py-1.5 rounded-sm text-sm border ${
                sort === o.value
                  ? 'bg-up-bg text-up border-up'
                  : 'bg-bg-subtle text-text-sec border-transparent'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <SkeletonState rows={5} height="h-14" />}

      {error && (
        <Card padding="md">
          <p className="text-up">⚠ {error}</p>
        </Card>
      )}

      {data && !loading && (
        <Card padding="md" className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-text-sec border-b border-bd-subtle">
                <th className="text-left py-2 pr-3">板块</th>
                <th className="text-right py-2 px-3">涨跌幅</th>
                <th className="text-right py-2 px-3">主力净流入</th>
                <th className="text-right py-2 px-3">成交额</th>
                <th className="text-left py-2 pl-3">领涨股</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((it, i) => (
                <tr key={i} className="border-b border-bd-subtle last:border-0">
                  <td className="py-2.5 pr-3 font-medium">{it.name}</td>
                  <td
                    className={`text-right py-2.5 px-3 font-mono ${
                      it.changePct >= 0 ? 'text-up' : 'text-down'
                    }`}
                  >
                    {pct(it.changePct)}
                  </td>
                  <td
                    className={`text-right py-2.5 px-3 font-mono ${
                      it.netamountYi >= 0 ? 'text-up' : 'text-down'
                    }`}
                  >
                    {fmtYi(it.netamountYi)}
                  </td>
                  <td className="text-right py-2.5 px-3 font-mono text-text-sec">
                    {fmtYi(it.turnoverYi)}
                  </td>
                  <td className="py-2.5 pl-3 text-text-sec">
                    {it.topStock
                      ? `${it.topStock.name} ${pct(it.topStock.changePct)}`
                      : '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </main>
  );
}
