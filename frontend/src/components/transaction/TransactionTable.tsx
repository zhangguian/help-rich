'use client';

import { useEffect, useState } from 'react';

import Decimal from 'decimal.js-light';
import { useRouter } from 'next/navigation';

import { apiDelete, apiGet, apiPost } from '@/lib/api';
import { decimalFormat } from '@/lib/decimalFormat';
import { useSseSubscription } from '@/lib/eventSource';
import type { DiagnoseOut, Transaction, TransactionListResponse } from '@/lib/types';
import { useDiagnoseStore } from '@/stores/useDiagnoseStore';
import { useUIStore } from '@/stores/useUIStore';

import { ScoreBadge } from '../signal/ScoreBadge';
import { ScoreDetail } from '../signal/ScoreDetail';

import { TransactionEditModal } from './TransactionEditModal';

import { Button } from '../ui/Button';

/**
 * 「录入后持仓」快照(v0.5.0 事件溯源)
 *
 * 每笔流水带自己应用后的持仓(shares_after / total_cost_after)。
 * 没有快照 = 已被持仓基准吸收 或 历史数据 → 显示「—」。
 *
 * v0.17:total_cost_after = 摊薄总额(净投入)→ 除以股数得到**摊薄成本价**
 * (= 券商持仓页口径),与持仓页/决策台的成本列同源。
 */
function snapshotOf(tx: Transaction): { shares: number; avg: string } | null {
  if (tx.sharesAfter == null) return null;
  let avg = '—';
  if (tx.totalCostAfter != null && tx.sharesAfter > 0) {
    try {
      avg = new Decimal(tx.totalCostAfter).div(tx.sharesAfter).toFixed(3);
    } catch {
      avg = '—';
    }
  }
  return { shares: tx.sharesAfter, avg };
}

/**
 * 列表加载失败的原因文案(与 lib/api.ts 的拦截器口径一致)
 *
 * 区分「加载失败」与「没有数据」:两者在页面上必须显示不同的东西,
 * 否则一次超时会伪装成「流水丢了」。
 */
function loadErrorText(e: unknown): string {
  const err = e as {
    code?: string;
    response?: { status?: number };
  };
  if (err?.code === 'ECONNABORTED') return '请求超时,请重试';
  if (err?.code === 'ERR_NETWORK') return '网络错误:后端可能未启动';
  if (err?.response?.status) return `加载失败 (HTTP ${err.response.status})`;
  return '加载失败,请重试';
}

/**
 * 流水列表(frontend-arch §10.3,P4.7 升级)
 *
 * - 评分列:订阅 SSE,实时显示评分变化(滚动动效)
 * - [详情] 按钮:打开 ScoreDetail 弹窗(完整/加载/失败三态 + 反馈 + 脱敏)
 * - [诊断] 按钮:显式触发重新评分(异步)
 * - [删除] 按钮
 */
export function TransactionTable({
  refreshKey,
  stockCode,
  onChanged,
}: {
  refreshKey?: number;
  stockCode?: string;
  /** 流水被改动后通知外部(刷新持仓 / 补T清单) */
  onChanged?: () => void;
}) {
  const router = useRouter();
  const showToast = useUIStore((s) => s.showToast);
  useSseSubscription();

  const [data, setData] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  // 加载失败与「确实没有记录」必须区分:失败时不能显示空态,
  // 否则用户会误以为流水没录入(v0.8 实测踩过)。
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  // 内部重拉计数(编辑一笔后整表重拉 —— 后续笔的快照都变了)
  const [reloadKey, setReloadKey] = useState(0);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailData, setDetailData] = useState<DiagnoseOut | null>(null);
  const [regenerating, setRegenerating] = useState<number | null>(null);
  // 正在编辑的那一笔(null = 不显示编辑弹窗)
  const [editTx, setEditTx] = useState<Transaction | null>(null);

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
      setError(null);
      try {
        const url = stockCode
          ? `/transactions?stock_code=${encodeURIComponent(stockCode)}&limit=200`
          : '/transactions?limit=200';
        const resp = await apiGet<TransactionListResponse>(url);
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
      } catch (e) {
        if (!cancelled) setError(loadErrorText(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [refreshKey, retryKey, reloadKey, stockCode, reset, setComment, setScore]);

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

  if (error) {
    return (
      <div className="text-text-sec text-center py-12 space-y-3">
        <p>{error}</p>
        <p className="text-text-ter text-xs">流水可能仍在库里,重试或刷新页面确认</p>
        <Button onClick={() => setRetryKey((k) => k + 1)}>重试</Button>
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
              <th className="text-left py-2 px-2">时间</th>
              <th className="text-left py-2 px-2">代码</th>
              <th className="text-left py-2 px-2">名称</th>
              <th className="text-left py-2 px-2">操作</th>
              <th className="text-right py-2 px-2">股数</th>
              <th className="text-right py-2 px-2">价格</th>
              <th className="text-right py-2 px-2">交易额</th>
              <th className="text-center py-2 px-2">评分</th>
              <th className="text-right py-2 px-2 whitespace-nowrap">录入后持仓</th>
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
              const snap = snapshotOf(tx);

              return (
                <tr
                  key={tx.id}
                  className="border-b border-border-def hover:bg-bg-subtle"
                >
                  <td className="py-2 px-2 font-mono text-xs">{tx.tradeDate}</td>
                  <td className="py-2 px-2 font-mono text-xs whitespace-nowrap">
                    {tx.tradeTime ? (
                      tx.tradeTime.slice(0, 5)
                    ) : (
                      <span className="text-text-ter" title="时间未知(未录入 / 历史流水)">
                        —
                      </span>
                    )}
                  </td>
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
                  <td className="py-2 px-2 text-right font-mono whitespace-nowrap">
                    {snap ? (
                      <span className="text-text-pri">
                        {snap.shares.toLocaleString()} 股 @ {snap.avg}
                      </span>
                    ) : (
                      <span
                        className="text-text-ter"
                        title="没有快照:该笔已被持仓基准吸收,或属于历史数据"
                      >
                        —
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-2 text-right space-x-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setEditTx(tx)}
                      title="编辑这一笔(方向 / 股数 / 价格 / 时间 / 备注)"
                    >
                      编辑
                    </Button>
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

      <TransactionEditModal
        tx={editTx}
        onClose={() => setEditTx(null)}
        onSaved={(updated) => {
          // 就地替换这一笔,避免评分列闪一下
          setData((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
          showToast({ type: 'success', message: '流水已更新,持仓已同步' });
          // ⚠️ 改一笔会**重放整条成本链** → 后面每一笔的「录入后持仓」快照都变了,
          //    所以要整表重拉,不能只换当前行。
          setReloadKey((k) => k + 1);
          // 持仓 / 补T清单也跟着变了 → 通知外面刷新
          onChanged?.();
        }}
      />
    </>
  );
}