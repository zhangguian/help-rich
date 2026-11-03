'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import { fetchOnboarding, type OnboardingStatus } from '@/lib/api/advanced';

/**
 * 引导中心(阶段5)
 *
 * 进度由后端实时判定(数据库/行情/模型/持仓...),不用 localStorage。
 * 后端说完成才算完成 —— 否则用户会照着一个已经和真实状态脱节的清单操作。
 */
export function OnboardingPanel() {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [collapsed, setCollapsed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setStatus(await fetchOnboarding());
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <Card padding="lg">
        <div className="text-sm text-text-sec">检查系统状态中…</div>
      </Card>
    );
  }

  if (error || !status) {
    return (
      <Card padding="lg">
        <div className="text-sm text-danger">{error || '无法获取引导状态'}</div>
      </Card>
    );
  }

  // 全部必做项完成后自动收起,避免长期占用版面
  if (status.finished && collapsed) {
    return (
      <Card padding="md" className="flex items-center justify-between gap-2">
        <span className="text-xs text-text-sec">
          ✅ 基础配置已完成({status.requiredDone}/{status.requiredTotal})
        </span>
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="text-xs text-accent hover:underline"
        >
          查看
        </button>
      </Card>
    );
  }

  return (
    <Card padding="lg" className="space-y-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">
            {status.finished ? '✅ 基础配置已完成' : '开始使用'}
          </h2>
          <p className="mt-1 text-xs text-text-sec">
            必做项 {status.requiredDone}/{status.requiredTotal}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-28 overflow-hidden rounded-full bg-bg-elevated">
            <div
              className={clsx(
                'h-full rounded-full transition-all',
                status.finished ? 'bg-success' : 'bg-accent',
              )}
              style={{ width: `${status.progressPct}%` }}
            />
          </div>
          <span className="font-mono text-xs text-text-ter">{status.progressPct}%</span>
          {status.finished && (
            <button
              type="button"
              onClick={() => setCollapsed(true)}
              className="text-xs text-text-ter hover:text-text-sec"
            >
              收起
            </button>
          )}
        </div>
      </header>

      <ul className="space-y-1.5">
        {status.steps.map((s) => (
          <li
            key={s.key}
            className={clsx(
              'flex flex-wrap items-center gap-2 rounded-md border px-2.5 py-2',
              s.done
                ? 'border-success/30 bg-success/5'
                : 'border-border-def bg-surface-2/30',
            )}
          >
            <span className="text-xs">{s.done ? '✅' : '○'}</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span
                  className={clsx(
                    'text-xs font-medium',
                    s.done ? 'text-text-sec' : 'text-text-pri',
                  )}
                >
                  {s.title}
                </span>
                {s.optional && (
                  <span className="rounded bg-bg-elevated px-1 py-0.5 text-[10px] text-text-ter">
                    可选
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-[11px] text-text-ter">
                {s.done && s.detail ? s.detail : s.description}
              </p>
            </div>
            {!s.done && (
              <a
                href={s.actionHref}
                className="rounded border border-border-def px-2 py-1 text-[11px] text-text-sec transition hover:bg-bg-elevated"
              >
                {s.actionLabel}
              </a>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
