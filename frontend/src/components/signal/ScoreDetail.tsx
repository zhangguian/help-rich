'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { apiPost, apiPut } from '@/lib/api';
import type { DiagnoseOut, FeedbackUpdate } from '@/lib/types';
import { useUIStore } from '@/stores/useUIStore';

import { Button } from '../ui/Button';

import { ScoreBadge } from './ScoreBadge';
import { ScoreBreakdown } from './ScoreBreakdown';

/**
 * 评分详情弹窗(P4.5 + P4.9 + P4.10)
 *
 * 三态:
 * - loading:骨架屏
 * - success:完整评分 + breakdown + AI 评语 + 反馈按钮 + 脱敏 tooltip
 * - failed:重试按钮 + 错误说明
 *
 * P4.9 反馈按钮:有用 / 没用
 * P4.10 脱敏 tooltip:列出实际传给 LLM 的 5 项字段(代码/方向/股数区间/日期/占比)
 */
export function ScoreDetail({
  open,
  onClose,
  tradeId,
  stockCode,
  stockName,
  action,
  shares,
  tradeDate,
  concentrationPct,
  initial,
  onRegenerate,
}: {
  open: boolean;
  onClose: () => void;
  tradeId: number;
  stockCode?: string;
  stockName?: string | null;
  action?: 'buy' | 'sell';
  shares?: number;
  tradeDate?: string;
  concentrationPct?: number | null;
  initial: DiagnoseOut | null;
  onRegenerate?: () => void;
}) {
  const showToast = useUIStore((s) => s.showToast);
  const [data, setData] = useState<DiagnoseOut | null>(initial);
  const [regenerating, setRegenerating] = useState(false);
  const [feedback, setFeedback] = useState<'useful' | 'useless' | null>(null);
  const [showPrivacy, setShowPrivacy] = useState(false);

  if (!open) return null;

  const status = data?.status ?? 'pending';

  const submitFeedback = async (v: 'useful' | 'useless') => {
    const body: FeedbackUpdate = { feedback: v };
    try {
      await apiPut(`/diagnose/${tradeId}/feedback`, body);
      setFeedback(v);
      showToast({ type: 'success', message: '已记录反馈' });
    } catch {
      showToast({ type: 'error', message: '反馈失败,请重试' });
    }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      await apiPost(`/diagnose/${tradeId}`);
      showToast({ type: 'info', message: '已触发重新评分' });
      onRegenerate?.();
      onClose();
    } catch {
      showToast({ type: 'error', message: '触发失败,请重试' });
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-bg-surface rounded-md shadow-lg max-w-md w-full mx-4 p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <header className="flex items-center justify-between">
          <h3 className="font-semibold text-lg">
            评分详情
            <span className="text-text-ter text-sm ml-2 font-mono">
              #{tradeId}
            </span>
          </h3>
          <button
            className="text-text-ter hover:text-text-pri text-xl leading-none"
            onClick={onClose}
            aria-label="关闭"
          >
            ×
          </button>
        </header>

        {status === 'pending' && (
          <div className="space-y-3 animate-pulse">
            <div className="h-12 bg-bg-subtle rounded-sm" />
            <div className="h-24 bg-bg-subtle rounded-sm" />
          </div>
        )}

        {status === 'success' && data && (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <ScoreBadge score={data.score} />
              <span className="text-sm text-text-sec">
                {data.score} / 100 分
                {data.aiStatus === 'success' && data.aiStatus && (
                  <span className="ml-2 text-xs text-text-ter">
                    {data.aiStatus === 'success' ? 'AI 评语已生成' : ''}
                  </span>
                )}
              </span>
            </div>
            <ScoreBreakdown breakdown={data.breakdown} />
            {data.aiComment && (
              <div className="bg-bg-subtle rounded-sm p-3 text-sm leading-relaxed whitespace-pre-wrap">
                {data.aiComment}
                <div className="text-xs text-text-ter mt-2">
                  以上不构成投资建议
                </div>
              </div>
            )}

            {/* P4.9 反馈按钮 */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-sec">这条评语对你有用吗?</span>
              <Button
                size="sm"
                variant={feedback === 'useful' ? 'primary' : 'secondary'}
                onClick={() => submitFeedback('useful')}
              >
                👍 有用
              </Button>
              <Button
                size="sm"
                variant={feedback === 'useless' ? 'primary' : 'secondary'}
                onClick={() => submitFeedback('useless')}
              >
                👎 没用
              </Button>
              {feedback && (
                <span className="text-xs text-text-ter">已记录</span>
              )}
            </div>
          </div>
        )}

        {(status === 'no_key' || status === 'failed') && (
          <div className="space-y-3">
            <div className="bg-warn-bg text-warn text-sm rounded-sm p-3">
              {status === 'no_key'
                ? '未配置 LLM Key,无法生成评语。设置页 → 填写后重试。'
                : '评语生成失败,可点击重试。'}
            </div>
            <Button
              variant="primary"
              loading={regenerating}
              onClick={handleRegenerate}
            >
              🔄 重新评分
            </Button>
          </div>
        )}

        {/* P4.10 脱敏可核验 tooltip */}
        {stockCode && action && shares !== undefined && tradeDate && (
          <div className="border-t border-border-def pt-3">
            <button
              className="text-xs text-text-sec hover:text-text-pri"
              onClick={() => setShowPrivacy((v) => !v)}
            >
              🔒 实际传给 LLM 的字段 {showPrivacy ? '▾' : '▸'}
            </button>
            {showPrivacy && (
              <div className="mt-2 text-xs font-mono bg-bg-subtle rounded-sm p-2 space-y-0.5 text-text-sec">
                <div>stock_code: {stockCode}</div>
                <div>action: {action === 'buy' ? 'buy(买入)' : 'sell(卖出)'}</div>
                <div>shares_bucket: {bucketOf(shares)}</div>
                <div>trade_date: {tradeDate}</div>
                <div>
                  concentration_pct:{' '}
                  {concentrationPct === null || concentrationPct === undefined
                    ? '未知'
                    : `${concentrationPct.toFixed(1)}%`}
                </div>
                <div className="text-text-ter mt-1">
                  不含价格 / 金额 / 成本
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** 股数分桶(与后端 sanitizer 一致) */
function bucketOf(shares: number): string {
  if (shares < 100) return '<100';
  if (shares < 500) return '100-500';
  if (shares < 1000) return '500-1000';
  if (shares < 5000) return '1000-5000';
  return '5000+';
}