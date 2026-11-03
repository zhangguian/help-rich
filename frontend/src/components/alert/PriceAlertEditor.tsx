'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import {
  createPriceAlert,
  deletePriceAlert,
  fetchAlertMeta,
  fetchPriceAlerts,
  updatePriceAlert,
  type AlertConditions,
  type AlertGroup,
  type AlertLeaf,
  type AlertMeta,
  type PriceAlertRule,
} from '@/lib/api/advanced';

const DEFAULT_CONDITIONS: AlertConditions = {
  op: 'and',
  conditions: [{ metric: 'price', op: '<=', value: 0 }],
};

const GROUP_OP_LABELS: Record<string, string> = { and: '同时满足', or: '满足任一' };

const METRIC_LABELS: Record<string, string> = {
  price: '价格',
  change_pct: '涨跌幅(%)',
  volume_ratio: '量比',
  turnover: '换手率(%)',
};

const OP_LABELS: Record<string, string> = {
  '>=': '≥',
  '<=': '≤',
  '>': '>',
  '<': '<',
  '==': '=',
  cross_above: '上穿',
  cross_below: '下破',
};

/** 判断某个节点是叶子还是分组 */
function isGroup(node: AlertLeaf | AlertGroup): node is AlertGroup {
  return 'conditions' in node;
}

/**
 * 价格提醒编辑器(阶段1)
 *
 * 条件树的编辑策略:**只做两层**(一个分组 + 其下叶子)。
 * 后端支持任意嵌套,但 UI 上无限嵌套会让小白看不懂也点不动;
 * 两层已经能表达"价格跌破 X 且 量比放大"这类真实需求。
 * 已存在的更深结构会原样展示(conditionsText),编辑时降级为两层并提示。
 */
export function PriceAlertEditor() {
  const [rules, setRules] = useState<PriceAlertRule[]>([]);
  const [meta, setMeta] = useState<AlertMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const [stockCode, setStockCode] = useState('');
  const [name, setName] = useState('');
  const [groupOp, setGroupOp] = useState<'and' | 'or'>('and');
  const [leaves, setLeaves] = useState<AlertLeaf[]>([
    { metric: 'price', op: '<=', value: 0 },
  ]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [list, m] = await Promise.all([
        fetchPriceAlerts(),
        fetchAlertMeta().catch(() => null),
      ]);
      setRules(list.items ?? []);
      setMeta(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const addLeaf = () => {
    setLeaves((prev) => [...prev, { metric: 'change_pct', op: '>=', value: 0 }]);
  };

  const removeLeaf = (idx: number) => {
    setLeaves((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));
  };

  const patchLeaf = (idx: number, patch: Partial<AlertLeaf>) => {
    setLeaves((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  };

  const submit = async () => {
    if (!stockCode.trim()) {
      setError('请填写股票代码');
      return;
    }
    const valid = leaves.filter((l) => Number.isFinite(l.value) && l.value !== 0);
    if (valid.length === 0) {
      setError('至少需要一个有效条件(数值不能为 0)');
      return;
    }

    const conditions: AlertConditions =
      valid.length === 1 ? { op: 'and', conditions: valid } : { op: groupOp, conditions: valid };

    setBusy(true);
    setError('');
    try {
      await createPriceAlert({
        stock_code: stockCode.trim().toUpperCase(),
        conditions,
        name: name.trim(),
      });
      setStockCode('');
      setName('');
      setLeaves([{ metric: 'price', op: '<=', value: 0 }]);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败');
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (rule: PriceAlertRule) => {
    setBusy(true);
    try {
      await updatePriceAlert(rule.id, { enabled: !rule.enabled });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '更新失败');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (rule: PriceAlertRule) => {
    setBusy(true);
    try {
      await deletePriceAlert(rule.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败');
    } finally {
      setBusy(false);
    }
  };

  const metrics = meta?.metrics ?? Object.keys(METRIC_LABELS).map((v) => ({ value: v, label: METRIC_LABELS[v] }));
  const ops = meta?.ops ?? ['>=', '<=', '>', '<'];

  return (
    <div className="space-y-4">
      <Card padding="lg" className="space-y-3">
        <header>
          <h2 className="text-base font-semibold">新建价格提醒</h2>
          <p className="mt-1 text-xs text-text-sec">
            到价后推送到已配置的渠道(需先在「通知设置」里开启至少一个渠道)
          </p>
        </header>

        {error && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-xs">
            <span className="text-text-sec">股票代码</span>
            <input
              value={stockCode}
              onChange={(e) => setStockCode(e.target.value)}
              placeholder="如 600519.SH"
              className="w-full rounded-md border border-border-def bg-bg-elevated px-3 py-2 text-sm text-text-pri outline-none focus:border-accent"
            />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-text-sec">备注(可选)</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如 跌破成本价提醒"
              className="w-full rounded-md border border-border-def bg-bg-elevated px-3 py-2 text-sm text-text-pri outline-none focus:border-accent"
            />
          </label>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-sec">条件</span>
            {leaves.length > 1 && (
              <select
                value={groupOp}
                onChange={(e) => setGroupOp(e.target.value as 'and' | 'or')}
                className="rounded-md border border-border-def bg-bg-elevated px-2 py-1 text-xs text-text-pri"
                aria-label="条件组合方式"
              >
                <option value="and">{GROUP_OP_LABELS.and}</option>
                <option value="or">{GROUP_OP_LABELS.or}</option>
              </select>
            )}
          </div>

          {leaves.map((leaf, idx) => (
            <div key={idx} className="flex flex-wrap items-center gap-2">
              <select
                value={leaf.metric}
                onChange={(e) => patchLeaf(idx, { metric: e.target.value })}
                className="rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri"
                aria-label="指标"
              >
                {metrics.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <select
                value={leaf.op}
                onChange={(e) => patchLeaf(idx, { op: e.target.value })}
                className="rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri"
                aria-label="比较符"
              >
                {ops.map((o) => (
                  <option key={o} value={o}>
                    {OP_LABELS[o] ?? o}
                  </option>
                ))}
              </select>
              <input
                type="number"
                value={leaf.value}
                onChange={(e) => patchLeaf(idx, { value: Number(e.target.value) })}
                className="w-28 rounded-md border border-border-def bg-bg-elevated px-2 py-1.5 text-xs text-text-pri"
                aria-label="阈值"
              />
              {leaves.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeLeaf(idx)}
                  className="text-xs text-text-ter hover:text-danger"
                  aria-label="删除该条件"
                >
                  ✕
                </button>
              )}
            </div>
          ))}

          <button
            type="button"
            onClick={addLeaf}
            className="text-xs text-accent hover:underline"
          >
            + 添加条件
          </button>
        </div>

        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-bg-base transition hover:opacity-90 disabled:opacity-50"
        >
          {busy ? '提交中…' : '创建提醒'}
        </button>
      </Card>

      <Card padding="lg" className="space-y-3">
        <header className="flex items-baseline justify-between">
          <h2 className="text-base font-semibold">已有提醒</h2>
          <span className="text-xs text-text-ter">{rules.length} 条</span>
        </header>

        {loading ? (
          <div className="text-sm text-text-sec">加载中…</div>
        ) : rules.length === 0 ? (
          <div className="text-sm text-text-ter">还没有提醒规则</div>
        ) : (
          <ul className="divide-y divide-border-def">
            {rules.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm">{r.stockCode}</span>
                    {r.name && <span className="text-xs text-text-sec">{r.name}</span>}
                    <span
                      className={clsx(
                        'rounded px-1.5 py-0.5 text-[10px]',
                        r.enabled
                          ? 'bg-accent/15 text-accent'
                          : 'bg-bg-elevated text-text-ter',
                      )}
                    >
                      {r.enabled ? '启用' : '停用'}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-text-sec">{r.conditionsText}</p>
                  <p className="mt-0.5 text-[11px] text-text-ter">
                    已触发 {r.triggeredCount} 次
                    {r.lastTriggeredAt
                      ? ` · 最近 ${new Date(r.lastTriggeredAt).toLocaleString('zh-CN')}`
                      : ''}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void toggle(r)}
                    disabled={busy}
                    className="rounded border border-border-def px-2 py-1 text-xs text-text-sec hover:bg-bg-elevated disabled:opacity-50"
                  >
                    {r.enabled ? '停用' : '启用'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(r)}
                    disabled={busy}
                    className="rounded border border-border-def px-2 py-1 text-xs text-text-ter hover:text-danger disabled:opacity-50"
                  >
                    删除
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
