'use client';

import { useCallback, useEffect, useState } from 'react';

import Link from 'next/link';

import { apiPost } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';
import {
  addToWatchlist,
  fetchScreenerLatest,
  fetchScreenerPool,
  removeFromWatchlist,
  triggerLlmPick,
  type LlmPicksResponse,
  type ScreenerLatestResponse,
  type ScreenerPoolResponse,
} from '@/lib/screener';

const ACTION_COLOR: Record<string, string> = {
  可关注: 'text-accent border-accent/30 bg-accent/10',
  轻仓: 'text-up border-up/30 bg-up/10',
  观望: 'text-text-ter border-border-def bg-bg-subtle',
};
const VIEW_COLOR: Record<string, string> = {
  偏多: 'text-up',
  中性: 'text-text-sec',
  偏空: 'text-down',
};

const fmtYi = (v: number | null) =>
  v == null ? '-' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}亿`;

/** 错误类型:区分 404(无数据) vs 其他错误 */
type LoadError =
  | { code: 'no_data'; message: string }
  | { code: 'error'; message: string }
  | null;

/** 选股面板 — 复用于主页 tab 内嵌 + /screener 独立路由
 *
  不带外层容器(<div className="p-8 max-w-5xl">),由调用方决定容器。
 *  - 主页 tab 嵌入:由 <section className="flex-1 min-w-0 min-h-0 flex flex-col gap-3"> 提供间距
 *  - /screener 路由:由 page.tsx 包一层居中容器
 */
export function ScreenerPanel() {
  const [data, setData] = useState<ScreenerLatestResponse | null>(null);
  const [pool, setPool] = useState<ScreenerPoolResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<LoadError>(null);
  const [llm, setLlm] = useState<LlmPicksResponse | null>(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);
  // 立即跑批(仅 404 状态用,需后端开启 SCREENER_ALLOW_TRIGGER)
  const [triggering, setTriggering] = useState(false);

  const loadLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [latest, poolInfo] = await Promise.all([
        fetchScreenerLatest(),
        fetchScreenerPool(),
      ]);
      setData(latest);
      setPool(poolInfo);
    } catch (e: any) {
      if (e?.response?.status === 404) {
        setError({
          code: 'no_data',
          message:
            '今日尚无选股数据。请运行 `python -m scripts.init_index_constituents --seed-only` 初始化候选池,然后在 15:30 工作日自动跑批,或点击下方按钮立即跑批(需后端开启 SCREENER_ALLOW_TRIGGER)。',
        });
      } else {
        setError({ code: 'error', message: e?.message || '加载失败' });
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLatest();
  }, [loadLatest]);

  const handleTriggerNow = useCallback(async () => {
    setTriggering(true);
    try {
      // 后端跑批可能耗时 30~60s,延长超时到 120s
      await apiPost('/screener/trigger-now', undefined, { timeout: 120000 });
      // 成功后自动重新加载,展示 Top 20
      await loadLatest();
    } catch (e: any) {
      if (e?.response?.status === 403) {
        setError({
          code: 'no_data',
          message:
            '立即跑批需要后端开启 `SCREENER_ALLOW_TRIGGER=1` 环境变量。请联系管理员启动后端时加上该变量,然后重试。',
        });
      } else {
        setError({
          code: 'error',
          message: `跑批失败:${e?.response?.data?.detail || e?.message || '未知错误'}`,
        });
      }
    } finally {
      setTriggering(false);
    }
  }, [loadLatest]);

  const handleLlmPick = useCallback(async () => {
    setLlmLoading(true);
    setLlmError(null);
    try {
      const result = await triggerLlmPick(false);
      setLlm(result);
    } catch (e: any) {
      setLlmError(e?.response?.data?.detail || e?.message || 'LLM 评选失败');
    } finally {
      setLlmLoading(false);
    }
  }, []);

  // 标选股:点击 ⭐ → add/remove + 本地 setState 立即更新 UI
  const [togglingCode, setTogglingCode] = useState<string | null>(null);
  const handleToggleWatch = useCallback(
    async (stockCode: string, stockName: string, isWatched: boolean) => {
      setTogglingCode(stockCode);
      try {
        if (isWatched) {
          await removeFromWatchlist(stockCode);
        } else {
          await addToWatchlist({ stockCode, stockName });
        }
        // 本地乐观更新 picks.is_watched
        setData((prev) =>
          prev
            ? {
                ...prev,
                picks: prev.picks.map((q) =>
                  q.stockCode === stockCode
                    ? { ...q, isWatched: !isWatched }
                    : q,
                ),
              }
            : prev,
        );
      } catch (e: any) {
        // 简单提示,不弹窗
        const msg = e?.response?.data?.detail || e?.message || '标选失败';
        // eslint-disable-next-line no-alert
        alert(`标选失败: ${msg}`);
      } finally {
        setTogglingCode(null);
      }
    },
    [],
  );

  if (loading) {
    return <SkeletonState rows={6} />;
  }

  if (error) {
    if (error.code === 'no_data') {
      return (
        <Card className="p-6">
          <p className="text-orange-500 font-medium">📊 尚无选股数据</p>
          <p className="text-text-sec mt-2 text-sm whitespace-pre-line">
            {error.message}
          </p>
          <div className="flex gap-2 mt-4">
            <Button
              variant="primary"
              size="sm"
              onClick={handleTriggerNow}
              loading={triggering}
              disabled={triggering}
            >
              ⚡ 立即跑批(约 30~60s)
            </Button>
            <Button variant="ghost" size="sm" onClick={loadLatest}>
              🔄 刷新
            </Button>
          </div>
        </Card>
      );
    }
    // 其他错误(网络/500):红字 + 重试
    return (
      <Card className="p-6">
        <p className="text-red-500 font-medium">⚠ 加载失败</p>
        <p className="text-text-sec mt-2 text-sm">{error.message}</p>
        <Button variant="ghost" size="sm" onClick={loadLatest} className="mt-4">
          🔄 重试
        </Button>
      </Card>
    );
  }

  if (!data || !data.run) {
    return (
      <Card className="p-6">
        <p className="text-text-sec">尚无选股数据</p>
      </Card>
    );
  }

  const { run, picks } = data;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">📈 盘后选股 · 资金驱动</h1>
          <p className="text-text-sec mt-1 text-sm">
            {run.runDate} 收盘 · 候选池:沪深 300 + 中证 500({pool?.count ?? '-'} 只)
            · 评分 {run.scoringVersion}
            {run.elapsedSec != null && ` · 跑批耗时 ${run.elapsedSec.toFixed(1)}s`}
          </p>
          {run.note && (
            <p className="text-text-ter mt-1 text-xs">⚠ {run.note}</p>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={handleLlmPick}
            disabled={llmLoading || picks.length === 0}
            loading={llmLoading}
          >
            🤖 LLM 评选 Top 5
          </Button>
          <Button variant="ghost" size="sm" onClick={loadLatest}>
            🔄 刷新
          </Button>
        </div>
      </div>

      {/* LLM 评选结果区(展开) */}
      {llmError && (
        <Card className="p-4 border-red-500/30 bg-red-500/10">
          <p className="text-red-500 text-sm">⚠ LLM 评选失败:{llmError}</p>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleLlmPick}
            className="mt-2"
            disabled={llmLoading}
          >
            重试
          </Button>
        </Card>
      )}
      {llm && llm.status === 'success' && (
        <Card className="p-5 border-accent/30 bg-accent/5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold">
              🌟 LLM 评选结果
              {llm.cached && <span className="ml-2 text-xs text-text-ter">(已评过)</span>}
            </h2>
            <span className="text-xs text-text-ter font-mono">{llm.model}</span>
          </div>
          {llm.summary && (
            <p className="text-text-sec text-sm italic mb-4">"{llm.summary}"</p>
          )}
          <div className="space-y-3">
            {llm.picks.map((p) => (
              <div
                key={`${p.rank}-${p.stockCode}`}
                className="flex gap-3 p-3 rounded border border-border-def bg-bg-surface"
              >
                <div className="text-2xl font-bold text-accent shrink-0 w-8">
                  {p.rank}
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Link
                      href={`/stock/${encodeURIComponent(p.stockCode)}`}
                      className="font-mono text-text-pri hover:text-accent"
                    >
                      {p.stockCode}
                    </Link>
                    <span className={VIEW_COLOR[p.view] ?? 'text-text-sec'}>
                      {p.view}
                    </span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded border ${ACTION_COLOR[p.action] ?? ''}`}
                    >
                      {p.action}
                    </span>
                  </div>
                  <p className="text-sm text-text-sec">💡 {p.highlights}</p>
                  <p className="text-sm text-text-ter">⚠ {p.risks}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Top N 候选股列表 */}
      <div className="space-y-3">
        {picks.length === 0 && (
          <Card className="p-6">
            <p className="text-text-sec">本次跑批无候选通过过滤(行情或 K 线全失败?)</p>
          </Card>
        )}
        {picks.map((p) => (
          <Card key={p.stockCode} className="p-4">
            <div className="flex items-start gap-4">
              {/* rank + score */}
              <div className="flex flex-col items-center shrink-0 w-14">
                <div className="text-2xl font-bold text-accent">{p.rank}</div>
                <div className="text-xs text-text-ter mt-1">{p.score.toFixed(0)} 分</div>
              </div>
              {/* ⭐ 观察池按钮(右上) */}
              <div className="ml-auto shrink-0">
                <button
                  type="button"
                  onClick={() => handleToggleWatch(p.stockCode, p.stockName, p.isWatched)}
                  disabled={togglingCode === p.stockCode}
                  title={p.isWatched ? '已在观察池,点击取消标记' : '加入观察池(主页 ⭐ 观察池查看胜率)'}
                  className={`text-xl transition-colors disabled:opacity-50 ${
                    p.isWatched
                      ? 'text-accent hover:text-accent-hover'
                      : 'text-text-ter hover:text-accent'
                  }`}
                >
                  {p.isWatched ? '🌟' : '⭐'}
                </button>
              </div>
              {/* 内容 */}
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 mb-2">
                  <Link
                    href={`/stock/${encodeURIComponent(p.stockCode)}`}
                    className="font-mono text-text-pri hover:text-accent"
                  >
                    {p.stockCode}
                  </Link>
                  <span className="font-medium">{p.stockName}</span>
                  {p.sector && (
                    <span className="text-xs px-2 py-0.5 rounded border border-border-def bg-bg-subtle text-text-sec">
                      {p.sector}
                      {p.sectorInflowRank != null && ` · Top${p.sectorInflowRank}`}
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm mb-2">
                  <span className="text-text-sec">
                    主力{' '}
                    <span className="text-text-pri font-mono">
                      {fmtYi(p.mainNetInflowYi)}
                    </span>
                  </span>
                  <span className="text-text-sec">
                    量比{' '}
                    <span className="text-text-pri font-mono">
                      {p.volumeRatio?.toFixed(2) ?? '-'}
                    </span>
                  </span>
                  <span
                    className={
                      (p.changePct ?? 0) >= 0 ? 'text-up' : 'text-down'
                    }
                  >
                    {(p.changePct ?? 0) >= 0 ? '+' : ''}
                    {p.changePct?.toFixed(2) ?? '-'}%
                  </span>
                  <span className="text-text-sec">
                    连涨{' '}
                    <span className="text-text-pri font-mono">
                      {p.consecutiveUpDays}
                    </span>{' '}
                    天
                  </span>
                </div>
                {p.reason && (
                  <p className="text-sm text-text-sec mt-2 leading-relaxed">
                    💡 入选理由:{p.reason}
                  </p>
                )}
                {p.triggeredRules.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {p.triggeredRules.map((r) => (
                      <span
                        key={r}
                        className="text-xs px-2 py-0.5 rounded border border-accent/30 bg-accent/10 text-accent"
                      >
                        {r}
                      </span>
                    ))}
                  </div>
                )}
                {p.fundamental_filter_status && (
                  <div className="text-xs mt-1">
                    {p.fundamental_filter_status === 'passed' ? (
                      <span className="text-up">✓ 基本面通过</span>
                    ) : (
                      <span className="text-down">⚠️ 基本面被过滤</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}