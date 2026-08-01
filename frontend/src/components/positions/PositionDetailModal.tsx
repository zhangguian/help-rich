'use client';

import { useEffect, useState } from 'react';

import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';

import { KLineChart } from '../charts/KLineChart';

interface FundFlowItem {
  id?: number;
  timestamp: string;
  direction: 'in' | 'out';
  amount: string;
  category: string;
}

/**
 * 持仓详情 Modal(D+E)
 *
 * - K 线图(60 根日 K,TradingView Lightweight Charts)
 * - 资金流最近 30 条 + SSE 实时推送
 */
export function PositionDetailModal({
  open,
  onClose,
  stockCode,
  stockName,
}: {
  open: boolean;
  onClose: () => void;
  stockCode: string;
  stockName: string | null;
}) {
  const [flows, setFlows] = useState<FundFlowItem[]>([]);
  const [sseConnected, setSseConnected] = useState(false);

  // 初始列表 + SSE 订阅
  useEffect(() => {
    if (!open) return;

    let es: EventSource | null = null;
    let cancelled = false;

    const init = async () => {
      // 初始拉取
      try {
        const r = await fetch(`/api/fund-flow/${encodeURIComponent(stockCode)}`, {
          headers: { Accept: 'application/json' },
        });
        if (r.ok) {
          const data = await r.json();
          if (!cancelled) setFlows(data.items ?? []);
        }
      } catch {
        /* ignore */
      }

      // SSE 订阅(原生 EventSource,axios 不支持)
      const base = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      es = new EventSource(`${base}/api/fund-flow/${encodeURIComponent(stockCode)}/events`);
      es.onopen = () => {
        if (!cancelled) setSseConnected(true);
      };
      es.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as
            | { event: string; direction: string; amount: string; category: string; timestamp: string; replay?: boolean }
            | { event: 'subscribed' | 'ping' };
          if (msg.event === 'fund_flow') {
            const item: FundFlowItem = {
              timestamp: msg.timestamp,
              direction: msg.direction as 'in' | 'out',
              amount: msg.amount,
              category: msg.category,
            };
            setFlows((prev) => [item, ...prev].slice(0, 50));
          }
        } catch {
          /* ignore */
        }
      };
      es.onerror = () => {
        if (!cancelled) setSseConnected(false);
      };
    };

    init();

    return () => {
      cancelled = true;
      es?.close();
      setSseConnected(false);
    };
  }, [open, stockCode]);

  return (
    <Modal open={open} onClose={onClose} title={`${stockName ?? stockCode} ${stockCode}`} size="lg">
      <div className="space-y-4">
        {/* K 线图 */}
        <section>
          <h4 className="text-sm font-semibold mb-2">日 K 线(最近 60 个交易日)</h4>
          <KLineChart stockCode={stockCode} height={280} />
        </section>

        {/* 资金流 */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold">
              资金流
              <span
                className={`ml-2 text-xs ${
                  sseConnected ? 'text-down' : 'text-text-ter'
                }`}
              >
                {sseConnected ? '● 实时' : '○ 已断开'}
              </span>
            </h4>
          </div>
          <div className="border border-border-def rounded-sm max-h-48 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-bg-subtle text-text-sec sticky top-0">
                <tr>
                  <th className="text-left px-2 py-1">时间</th>
                  <th className="text-left px-2 py-1">方向</th>
                  <th className="text-left px-2 py-1">类型</th>
                  <th className="text-right px-2 py-1">金额(万)</th>
                </tr>
              </thead>
              <tbody>
                {flows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="text-text-ter text-center py-4">
                      暂无数据
                    </td>
                  </tr>
                )}
                {flows.map((f, i) => (
                  <tr key={i} className="border-t border-border-def">
                    <td className="px-2 py-1 font-mono text-text-sec">
                      {new Date(f.timestamp).toLocaleTimeString('zh-CN', {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>
                    <td className={`px-2 py-1 ${f.direction === 'in' ? 'text-up' : 'text-down'}`}>
                      {f.direction === 'in' ? '流入' : '流出'}
                    </td>
                    <td className="px-2 py-1 text-text-sec">{f.category}</td>
                    <td className="px-2 py-1 text-right font-mono">{f.amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="flex justify-end">
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
        </div>
      </div>
    </Modal>
  );
}