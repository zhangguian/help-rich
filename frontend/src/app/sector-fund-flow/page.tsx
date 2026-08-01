'use client';

import { useEffect, useRef, useState } from 'react';

import Link from 'next/link';

import { apiBaseUrl, apiGet } from '@/lib/api';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';
import { useUIStore } from '@/stores/useUIStore';

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

interface SectorAlert {
  fenlei: number;
  name: string;
  prevYi: number;
  currYi: number;
  deltaYi: number;
  reason: string;
  topStockCode: string | null;
}

interface AlertEvent {
  event: string;
  fenlei: number;
  fenleiLabel: string;
  alerts: SectorAlert[];
  ts: string;
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
  const [alerts, setAlerts] = useState<SectorAlert[]>([]);
  const [subscribing, setSubscribing] = useState(false);
  const showToast = useUIStore((s) => s.showToast);
  const esRef = useRef<EventSource | null>(null);

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

  useEffect(() => {
    return () => {
      esRef.current?.close();
      esRef.current = null;
    };
  }, []);

  const toggleSubscribe = () => {
    if (subscribing) {
      esRef.current?.close();
      esRef.current = null;
      setSubscribing(false);
      return;
    }
    const url = `${apiBaseUrl()}/sector-fund-flow/events`;
    let es: EventSource;
    try {
      es = new EventSource(url);
    } catch (e) {
      showToast({ type: 'error', message: '订阅失败:浏览器不支持 SSE' });
      return;
    }
    esRef.current = es;
    setSubscribing(true);
    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as AlertEvent | { event: string };
        if (msg.event !== 'sector_fund_flow_alert') return;
        const alertMsg = msg as AlertEvent;
        setAlerts((prev) => [...alertMsg.alerts, ...prev].slice(0, 30));
        if (alertMsg.alerts.length > 0 && alertMsg.alerts[0]) {
          const first = alertMsg.alerts[0];
          const sign = first.deltaYi >= 0 ? '+' : '';
          showToast({
            type: 'info',
            message: `板块异动 ${first.name}: ${sign}${(first.deltaYi / 1e8).toFixed(2)} 亿`,
          });
        }
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => {
      showToast({ type: 'error', message: '异动订阅连接断开,自动停止' });
      es.close();
      esRef.current = null;
      setSubscribing(false);
    };
  };

  const clearAlerts = () => setAlerts([]);

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
        <Button
          size="sm"
          variant={subscribing ? 'danger' : 'primary'}
          onClick={toggleSubscribe}
        >
          {subscribing ? '停止异动订阅' : '🔔 订阅异动'}
        </Button>
      </div>

      {loading && <SkeletonState rows={5} height="h-14" />}

      {error && (
        <Card padding="md">
          <p className="text-down">⚠ {error}</p>
        </Card>
      )}

      {alerts.length > 0 && (
        <Card padding="md">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-semibold">🔔 板块异动({alerts.length})</h3>
            <Button size="sm" variant="ghost" onClick={clearAlerts}>
              清空
            </Button>
          </div>
          <div className="space-y-1.5 text-sm">
            {alerts.map((a, i) => {
              const sign = a.deltaYi >= 0 ? '+' : '';
              return (
                <div
                  key={`${a.name}-${i}`}
                  className="flex items-center justify-between border-b border-border-def last:border-0 pb-1.5 last:pb-0"
                >
                  <div>
                    <span className="font-medium">{a.name}</span>
                    {a.topStockCode && (
                      <span className="ml-2 text-text-sec text-xs font-mono">
                        {a.topStockCode}
                      </span>
                    )}
                    <span className="ml-2 text-text-ter text-xs">
                      {a.reason === 'new'
                        ? '新进榜'
                        : a.reason.startsWith('top_stock_changed')
                          ? '领涨切换'
                          : '净额异动'}
                    </span>
                  </div>
                  <div
                    className={`font-mono ${
                      a.deltaYi >= 0 ? 'text-up' : 'text-down'
                    }`}
                  >
                    {sign}{(a.deltaYi / 1e8).toFixed(2)} 亿
                    <span className="text-text-ter text-xs ml-2">
                      ({a.prevYi >= 0 ? '+' : ''}
                      {(a.prevYi / 1e8).toFixed(2)} → {(a.currYi / 1e8).toFixed(2)})
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {data && !loading && (
        <Card padding="md" className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-text-sec border-b border-border-def">
                <th className="text-left py-2 pr-3">板块</th>
                <th className="text-right py-2 px-3">涨跌幅</th>
                <th className="text-right py-2 px-3">主力净流入</th>
                <th className="text-right py-2 px-3">成交额</th>
                <th className="text-left py-2 pl-3">领涨股</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((it, i) => (
                <tr key={i} className="border-b border-border-def last:border-0">
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
