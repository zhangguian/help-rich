'use client';

import { useEffect, useState } from 'react';

import { useRouter } from 'next/navigation';

import { apiDelete, apiGet, apiPost } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import { useSseSubscription } from '@/lib/eventSource';
import type { DiagnoseOut, Transaction, TransactionListResponse } from '@/lib/types';
import { useDiagnoseStore } from '@/stores/useDiagnoseStore';
import { useUIStore } from '@/stores/useUIStore';

import { ScoreBadge } from '../signal/ScoreBadge';
import { ScoreDetail } from '../signal/ScoreDetail';

import { Button } from '../ui/Button';

/**
 * 流水列表(frontend-arch §10.3,P4.7 升级)
 *
 * - 评分列:订阅 SSE,实时显示评分变化(滚动动效)
 * - [详情] 按钮:打开 ScoreDetail 弹窗(完整/加载/失败三态 + 反馈 + 脱敏)
 * - [诊断] 按钮:显式触发重新评分(异步)
 * - [删除] 按钮
 */
export function TransactionTable({ refreshKey }: { refreshKey?: number }) {
  const router = useRouter();
  const showToast = useUIStore((s) => s.showToast);
  useSseSubscription();

  const [data, setData] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailData, setDetailData] = useState<DiagnoseOut | null>(null);
  const [regenerating, setRegenerating] = useState<number | null>(null);

  const scores = useDiagnoseStore((s) => s.scores);
  const comments = useDiagnoseStore((s) => s.comments);
  const aiStatus = useDiagnoseStore((s) => s.aiStatus);
  const setScore = useDiagnoseStore((s) => s.setScore);
  const setComment = useDiagnoseStore((s) => s.setComment);
  const setFailed = useDiagnoseStore((s) => s.setFailed);
  const addPending = useDiagnoseStore((s) => s.addPending);
  const reset = useDiagnoseStore((s) => s.reset);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      setLoading(true);
      try {
        const resp = await apiGet<TransactionListResponse>('/transactions');
        if (!cancelled) {
          setData(resp.items);
          reset();
          // 用后端初始 score 填充 store(避免空白闪烁)
          for (const tx of resp.items) {
            if (tx.score !== null) {
              setScore(tx.id, tx.score, null);
              setComment(tx.id, null);
            }
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [refreshKey, reset, setComment, setScore]);

  const handleDelete = async (id: number) => {
    if (!window.confirm(`确认删除交易 #${id}?`)) return;
    setDeleting(id);
    try {
      await apiDelete(`/transactions/${id}`);
      setData((prev) => prev.filter((t) => t.id !== id));
    } finally {
      setDeleting(null);
    }
  };

  const openDetail = async (id: number) => {
    setDetailId(id);
    setDetailData(null);
    try {
      const d = await apiGet<DiagnoseOut>(`/diagnose/${id}`);
      setDetailData(d);
    } catch {
      showToast({ type: 'error', message: '获取评分失败' });
    }
  };

  const closeDetail = () => {
    setDetailId(null);
    setDetailData(null);
  };

  const handleRegenerate = async (id: number) => {
    setRegenerating(id);
    addPending(id);
    try {
      await apiPost(`/diagnose/${id}`);
      showToast({ type: 'info', message: `已触发 #${id} 重新评分` });
      // 重新打开 detail 等待新数据
      setDetailId(id);
      setDetailData(null);
      setTimeout(() => openDetail(id), 300);
    } catch {
      setFailed(id, '触发失败');
      showToast({ type: 'error', message: '触发失败' });
    } finally {
      setRegenerating(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 bg-bg-subtle rounded-sm animate-pulse" />
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

  const detailTx = detailId ? data.find((t) => t.id === detailId) : null;

  return (
    <>
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
            {data.map((tx) => {
              const liveScore = scores[tx.id];
              const liveComment = comments[tx.id];
              const status = aiStatus[tx.id];
              const hasScore =
                liveScore !== undefined && liveScore !== null;
              const isPending =
                status === 'pending' || (liveScore === undefined && tx.score === null);

              return (
                <tr
                  key={tx.id}
                  className="border-b border-border-def hover:bg-bg-subtle"
                >
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
                    {isPending && !hasScore ? (
                      <ScoreBadge score={null} loading />
                    ) : (
                      <ScoreBadge score={liveScore ?? tx.score} />
                    )}
                  </td>
                  <td className="py-2 px-2 text-right space-x-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => openDetail(tx.id)}
                      title={liveComment ? '查看评分详情' : '暂无评语,点击触发'}
                    >
                      {liveComment ? '📊 详情' : '🔄 诊断'}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleRegenerate(tx.id)}
                      loading={regenerating === tx.id}
                      title="重新评分(A/B 对比)"
                    >
                      ♻
                    </Button>
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
              );
            })}
          </tbody>
        </table>
      </div>

      {detailTx && (
        <ScoreDetail
          open={detailId !== null}
          onClose={closeDetail}
          tradeId={detailTx.id}
          stockCode={detailTx.stockCode}
          stockName={detailTx.stockName}
          action={detailTx.action}
          shares={detailTx.shares}
          tradeDate={detailTx.tradeDate}
          concentrationPct={null}
          initial={detailData}
        />
      )}
    </>
  );
}