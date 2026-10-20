'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import {
  fetchWeights,
  resetWeights,
  saveWeights,
  type FactorWeight,
} from '@/lib/api/advanced';

/**
 * 选股权重面板(阶段2)
 *
 * 交互取舍:
 * - 滑杆拖动只改本地 state,**松手才保存** —— 否则每拖动一格就打一次 API
 * - 停用的因子保留权重值,后端按 0 分处理;重新启用时不用重调
 * - 顶部显示后端返回的 `max_total`(不是前端自己加),避免和后端校验规则脱节
 */
export function WeightsPanel() {
  const [factors, setFactors] = useState<FactorWeight[]>([]);
  const [maxTotal, setMaxTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const apply = (view: { factors: FactorWeight[]; maxTotal: number }) => {
    setFactors(view.factors ?? []);
    setMaxTotal(view.maxTotal ?? 0);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      apply(await fetchWeights());
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const update = (key: string, patch: Partial<FactorWeight>) => {
    setFactors((prev) => prev.map((f) => (f.key === key ? { ...f, ...patch } : f)));
    setSavedAt(null);
  };

  const persist = useCallback(async () => {
    setSaving(true);
    setError('');
    try {
      apply(
        await saveWeights(factors.map((f) => ({ key: f.key, weight: f.weight, enabled: f.enabled }))),
      );
      setSavedAt(new Date().toLocaleTimeString('zh-CN'));
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }, [factors]);

  const doReset = async () => {
    setSaving(true);
    setError('');
    try {
      apply(await resetWeights());
      setSavedAt(new Date().toLocaleTimeString('zh-CN'));
    } catch (e) {
      setError(e instanceof Error ? e.message : '重置失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Card padding="lg">
        <div className="text-sm text-text-sec">加载权重中…</div>
      </Card>
    );
  }

  return (
    <Card padding="lg" className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">选股权重</h2>
          <p className="mt-1 text-xs text-text-sec">
            调整后建议用「权重对比回测」观察敏感度,再决定是否长期使用
          </p>
        </div>
        <span className="font-mono text-xs text-text-ter">满分 {maxTotal}</span>
      </header>

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}

      <ul className="space-y-4">
        {factors.map((f) => (
          <li key={f.key} className="space-y-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={f.enabled}
                  onChange={(e) => update(f.key, { enabled: e.target.checked })}
                  className="h-4 w-4 accent-accent"
                  aria-label={`启用 ${f.label}`}
                />
                <span className={clsx(!f.enabled && 'text-text-ter line-through')}>
                  {f.label}
                </span>
              </label>
              <span className="font-mono text-xs text-text-sec">{f.weight}</span>
            </div>

            <input
              type="range"
              min={f.min}
              max={f.max}
              step={1}
              value={f.weight}
              disabled={!f.enabled}
              onChange={(e) => update(f.key, { weight: Number(e.target.value) })}
              onMouseUp={() => void persist()}
              onTouchEnd={() => void persist()}
              onKeyUp={() => void persist()}
              className="w-full accent-accent disabled:opacity-40"
              aria-label={`${f.label} 权重`}
            />
            {f.description && (
              <p className="text-[11px] text-text-ter">{f.description}</p>
            )}
          </li>
        ))}
      </ul>

      <footer className="flex flex-wrap items-center gap-3 pt-1">
        <button
          type="button"
          onClick={() => void persist()}
          disabled={saving}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-bg-base transition hover:opacity-90 disabled:opacity-50"
        >
          {saving ? '保存中…' : '保存权重'}
        </button>
        <button
          type="button"
          onClick={() => void doReset()}
          disabled={saving}
          className="rounded-md border border-border-base px-3 py-1.5 text-sm text-text-sec transition hover:bg-bg-elev disabled:opacity-50"
        >
          恢复默认
        </button>
        {savedAt && <span className="text-xs text-text-ter">已于 {savedAt} 保存</span>}
      </footer>
    </Card>
  );
}
