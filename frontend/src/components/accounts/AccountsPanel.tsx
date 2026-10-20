'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { Card } from '@/components/ui/Card';
import {
  createAccount,
  deleteAccount,
  fetchAccountDetail,
  fetchAccounts,
  renameAccount,
  type AccountDetail,
  type AccountSummaryItem,
} from '@/lib/api/advanced';

/**
 * 多账户管理(阶段5)
 *
 * 默认账户不可删不可改名 —— 后端的 `positions/transactions.account_id`
 * 外键默认指向它,删掉会让存量数据的归属悬空。
 */
export function AccountsPanel() {
  const [accounts, setAccounts] = useState<AccountSummaryItem[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AccountDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [newName, setNewName] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchAccounts();
      const list = data.items ?? [];
      setAccounts(list);
      setActiveId((prev) => prev ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (activeId == null) {
      setDetail(null);
      return;
    }
    void (async () => {
      try {
        setDetail(await fetchAccountDetail(activeId));
      } catch (e) {
        setError(e instanceof Error ? e.message : '加载账户明细失败');
      }
    })();
  }, [activeId]);

  const add = async () => {
    if (!newName.trim()) return;
    setBusy(true);
    setError('');
    try {
      await createAccount({ name: newName.trim() });
      setNewName('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败');
    } finally {
      setBusy(false);
    }
  };

  const rename = async (acc: AccountSummaryItem) => {
    const next = window.prompt('新的账户名称', acc.name);
    if (!next || !next.trim() || next === acc.name) return;
    setBusy(true);
    try {
      await renameAccount(acc.id, next.trim());
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '重命名失败');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (acc: AccountSummaryItem) => {
    if (!window.confirm(`确定删除账户「${acc.name}」?`)) return;
    setBusy(true);
    try {
      await deleteAccount(acc.id);
      if (activeId === acc.id) setActiveId(null);
      await load();
    } catch (e) {
      // 后端会明确拒绝(默认账户/仍有持仓),把原因透给用户
      setError(e instanceof Error ? e.message : '删除失败');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Card padding="lg">
        <div className="text-sm text-text-sec">加载账户中…</div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}

      <Card padding="lg" className="space-y-3">
        <header>
          <h2 className="text-base font-semibold">投资账户</h2>
          <p className="mt-1 text-xs text-text-sec">
            多个券商账户分开统计,盈亏才不会算混。默认账户承载存量数据,不可删除。
          </p>
        </header>

        <ul className="divide-y divide-border-base">
          {accounts.map((a) => (
            <li
              key={a.id}
              className={clsx(
                'flex flex-wrap items-center gap-3 py-2.5',
                activeId === a.id && 'bg-bg-elev/40',
              )}
            >
              <button
                type="button"
                onClick={() => setActiveId(a.id)}
                className="min-w-0 flex-1 text-left"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{a.name}</span>
                  {a.isDefault && (
                    <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent">
                      默认
                    </span>
                  )}
                  {a.broker && (
                    <span className="text-[11px] text-text-ter">{a.broker}</span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] text-text-ter">
                  {a.positionCount} 只持仓 · 成本 {a.totalCost.toFixed(2)} · 已实现{' '}
                  {a.realizedPnl.toFixed(2)}
                </p>
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void rename(a)}
                  disabled={busy || a.isDefault}
                  className="rounded border border-border-base px-2 py-1 text-xs text-text-sec hover:bg-bg-elev disabled:opacity-40"
                >
                  改名
                </button>
                <button
                  type="button"
                  onClick={() => void remove(a)}
                  disabled={busy || a.isDefault}
                  className="rounded border border-border-base px-2 py-1 text-xs text-text-ter hover:text-danger disabled:opacity-40"
                >
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="新账户名称"
            className="w-48 rounded-md border border-border-base bg-bg-elev px-2 py-1.5 text-xs text-text-pri outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={() => void add()}
            disabled={busy || !newName.trim()}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-bg-base transition hover:opacity-90 disabled:opacity-50"
          >
            新建账户
          </button>
        </div>
      </Card>

      {detail && (
        <Card padding="lg" className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">{detail.name} · 持仓</h3>
            <span className="text-[11px] text-text-ter">
              市值 {detail.marketValue.toFixed(2)} · 浮动{' '}
              <span
                className={clsx(
                  detail.unrealizedPnl >= 0 ? 'text-danger' : 'text-success',
                )}
              >
                {detail.unrealizedPnl >= 0 ? '+' : ''}
                {detail.unrealizedPnl.toFixed(2)}
              </span>
            </span>
          </div>

          {detail.positions.length === 0 ? (
            <div className="text-xs text-text-ter">该账户暂无持仓</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-text-ter">
                  <tr>
                    <th className="py-1">代码</th>
                    <th className="py-1">名称</th>
                    <th className="py-1">股数</th>
                    <th className="py-1">成本</th>
                    <th className="py-1">现价</th>
                    <th className="py-1 text-right">浮动盈亏</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.positions.map((p) => (
                    <tr key={p.stockCode} className="border-t border-border-base">
                      <td className="py-1.5 font-mono">{p.stockCode}</td>
                      <td className="py-1.5">{p.stockName ?? '—'}</td>
                      <td className="py-1.5">{p.shares}</td>
                      <td className="py-1.5 font-mono">{p.totalCost.toFixed(2)}</td>
                      <td className="py-1.5 font-mono">{p.currentPrice || '—'}</td>
                      <td
                        className={clsx(
                          'py-1.5 text-right font-mono',
                          p.unrealizedPnl >= 0 ? 'text-danger' : 'text-success',
                        )}
                      >
                        {p.unrealizedPnl >= 0 ? '+' : ''}
                        {p.unrealizedPnl.toFixed(2)}({p.unrealizedPct.toFixed(2)}%)
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
