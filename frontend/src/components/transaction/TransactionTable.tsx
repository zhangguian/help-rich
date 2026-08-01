import { useEffect, useState } from 'react';

import { apiDelete, apiGet } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import type { Transaction, TransactionListResponse } from '@/lib/types';

import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

/**
 * 流水列表(frontend-arch §10.3)
 *
 * GET /api/transactions + 行内 [删除] 按钮
 */
export function TransactionTable({ refreshKey }: { refreshKey?: number }) {
  const [data, setData] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      setLoading(true);
      try {
        const resp = await apiGet<TransactionListResponse>('/transactions');
        if (!cancelled) setData(resp.items);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const handleDelete = async (id: number) => {
    if (!confirm(`确认删除交易 #${id}?`)) return;
    setDeleting(id);
    try {
      await apiDelete(`/transactions/${id}`);
      setData((prev) => prev.filter((t) => t.id !== id));
    } finally {
      setDeleting(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-12 bg-bg-subtle rounded-sm animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="text-text-ter text-center py-12">
        还没有交易记录,开始录入第一笔
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-border-def text-text-sec">
          <tr>
            <th className="text-left py-2 px-2">日期</th>
            <th className="text-left py-2 px-2">代码</th>
            <th className="text-left py-2 px-2">名称</th>
            <th className="text-left py-2 px-2">操作</th>
            <th className="text-right py-2 px-2">股数</th>
            <th className="text-right py-2 px-2">价格</th>
            <th className="text-right py-2 px-2">交易额</th>
            <th className="text-center py-2 px-2">评分</th>
            <th className="text-right py-2 px-2">操作</th>
          </tr>
        </thead>
        <tbody>
          {data.map((tx) => (
            <tr key={tx.id} className="border-b border-border-def hover:bg-bg-subtle">
              <td className="py-2 px-2 font-mono text-xs">{tx.tradeDate}</td>
              <td className="py-2 px-2 font-mono">{tx.stockCode}</td>
              <td className="py-2 px-2">{tx.stockName ?? '—'}</td>
              <td className="py-2 px-2">
                {tx.action === 'buy' ? (
                  <span className="text-down">买</span>
                ) : (
                  <span className="text-up">卖</span>
                )}
              </td>
              <td className="py-2 px-2 text-right font-mono">{tx.shares}</td>
              <td className="py-2 px-2 text-right font-mono">{tx.price}</td>
              <td className="py-2 px-2 text-right font-mono">
                {decimalFormat((tx.shares * Number(tx.price)).toFixed(2))}
              </td>
              <td className="py-2 px-2 text-center">
                {tx.score === null ? (
                  <Badge variant="muted">--</Badge>
                ) : (
                  <Badge variant={tx.score >= 80 ? 'good' : tx.score >= 60 ? 'mid' : 'bad'}>
                    {tx.score}
                  </Badge>
                )}
              </td>
              <td className="py-2 px-2 text-right">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => handleDelete(tx.id)}
                  loading={deleting === tx.id}
                >
                  删除
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}