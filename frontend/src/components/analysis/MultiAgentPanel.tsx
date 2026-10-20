'use client';

import { useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import { fetchMultiAgentAnalysis, type DecisionReport } from '@/lib/api/advanced';

const ACTION_TONE: Record<string, string> = {
  strong_buy: 'border-danger/50 bg-danger/10 text-danger',
  buy: 'border-danger/35 bg-danger/5 text-danger',
  hold: 'border-border-base bg-bg-elev text-text-sec',
  reduce: 'border-success/35 bg-success/5 text-success',
  sell: 'border-success/50 bg-success/10 text-success',
};

const STANCE_TONE: Record<string, string> = {
  bullish: 'text-danger',
  bearish: 'text-success',
  neutral: 'text-text-sec',
};

/**
 * 多智能体决策书(阶段4)
 *
 * 刻意把「可能不靠谱」的信号显式展示出来:
 * - `degraded` 的 Agent 会被标灰并给出原因
 * - 底部固定免责声明
 * - 置信度低时不隐藏,让用户自己判断
 * 这类产品最容易犯的错是把 AI 结论包装得比实际更确定。
 */
export function MultiAgentPanel({ defaultCode = '' }: { defaultCode?: string }) {
  const [code, setCode] = useState(defaultCode);
  const [report, setReport] = useState<DecisionReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const run = async () => {
    const target = code.trim().toUpperCase();
    if (!target) {
      setError('请填写股票代码');
      return;
    }
    setLoading(true);
    setError('');
    setReport(null);
    try {
      setReport(await fetchMultiAgentAnalysis(target));
    } catch (e) {
      setError(e instanceof Error ? e.message : '分析失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card padding="lg" className="space-y-3">
        <header>
          <h2 className="text-base font-semibold">多智能体深度分析</h2>
          <p className="mt-1 text-xs text-text-sec">
            4 位分析师独立研判 → 多空辩论 → 风控审查 → 投资经理裁决。约需 10–40 秒。
          </p>
        </header>

        <div className="flex flex-wrap items-center gap-2">
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void run();
            }}
            placeholder="如 600519.SH"
            className="w-48 rounded-md border border-border-base bg-bg-elev px-3 py-2 text-sm text-text-pri outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={() => void run()}
            disabled={loading}
            className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-bg-base transition hover:opacity-90 disabled:opacity-50"
          >
            {loading ? '分析中…' : '开始分析'}
          </button>
          {loading && (
            <span className="text-xs text-text-ter">
              正在并发调用多个模型,请耐心等待
            </span>
          )}
        </div>

        {error && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}
      </Card>

      {report && (
        <>
          <Card padding="lg" className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold">
                  {report.stockName || report.stockCode}
                  <span className="ml-2 font-mono text-xs text-text-ter">
                    {report.stockCode}
                  </span>
                </h3>
                <p className="mt-0.5 text-[11px] text-text-ter">
                  模型 {report.model || '未知'} · 置信度{' '}
                  {(report.confidence * 100).toFixed(0)}%
                </p>
              </div>
              <span
                className={clsx(
                  'rounded-md border px-3 py-1.5 text-sm font-medium',
                  ACTION_TONE[report.action] ?? ACTION_TONE.hold,
                )}
              >
                {report.actionLabel}
              </span>
            </div>

            {report.degraded && (
              <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
                部分角色未能产出有效结论(见下方灰色标注),本次结果可信度下降。
              </div>
            )}

            {report.summary && (
              <p className="text-sm leading-relaxed text-text-pri">{report.summary}</p>
            )}

            {report.riskFlags.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-text-sec">风险提示</h4>
                <ul className="mt-1 space-y-0.5">
                  {report.riskFlags.map((f, i) => (
                    <li key={i} className="text-xs text-warning">
                      · {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          <div className="grid gap-3 sm:grid-cols-2">
            {report.opinions.map((op, i) => (
              <Card
                key={`${op.role}-${i}`}
                padding="md"
                className={clsx('space-y-1.5', op.degraded && 'opacity-60')}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium">{op.label}</span>
                  <span className={clsx('text-[11px]', STANCE_TONE[op.stance])}>
                    {op.stanceLabel} · {(op.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                {op.degraded ? (
                  <p className="text-[11px] text-text-ter">
                    数据不足:{op.degradedReason || '未返回可用结论'}
                  </p>
                ) : (
                  <>
                    <p className="text-xs leading-relaxed text-text-sec">{op.argument}</p>
                    {op.keyPoints.length > 0 && (
                      <ul className="space-y-0.5">
                        {op.keyPoints.map((k, j) => (
                          <li key={j} className="text-[11px] text-text-ter">
                            · {k}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </Card>
            ))}
          </div>

          {report.riskReview && (
            <Card padding="lg" className="space-y-1.5">
              <h4 className="text-sm font-semibold">风控意见</h4>
              <p className="text-xs leading-relaxed text-text-sec">{report.riskReview}</p>
            </Card>
          )}

          <p className="px-1 text-[11px] text-text-ter">{report.disclaimer}</p>
        </>
      )}
    </div>
  );
}
