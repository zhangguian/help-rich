'use client';

import { useEffect, useState } from 'react';

import { apiErrorCode, apiErrorMessage, apiPatch } from '@/lib/api';
import type { Transaction } from '@/lib/types';

import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';

/**
 * 流水编辑弹窗(改一笔已录入的流水)
 *
 * 为什么要有这个:
 *  「买录成了卖」是最常见的录错。以前只能**删掉重录** —— 代价是:
 *  ① 要重新输一遍所有字段;② 评分快照与 AI 评语(history)一并丢掉;
 *  ③ 补T清单里那条挂单要等重新录完才重新出现。
 *  改方向的风险比改价格大(股数会**反向**变化),所以后端在写入前
 *  会**先验算整条成本链是否仍然自洽** —— 卖不出那么多股 → 422,拒绝写入。
 *
 * 可改:方向(买↔卖) / 股数 / 价格 / 时间点 / 备注。
 * 不可改:股票代码 / 交易日 —— 改标的等于把一笔流水搬到别的股票上,
 * 改日期会改变它在成本链里的落位,两者都只能「删了重录」。
 */
export function TransactionEditModal({
  tx,
  onClose,
  onSaved,
}: {
  tx: Transaction | null;
  onClose: () => void;
  /** 保存成功回调(带后端返回的最新流水) */
  onSaved?: (tx: Transaction) => void;
}) {
  const [action, setAction] = useState<'buy' | 'sell'>('buy');
  const [shares, setShares] = useState('');
  const [price, setPrice] = useState('');
  const [tradeTime, setTradeTime] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  // 每次打开不同的流水 → 重置表单
  useEffect(() => {
    if (!tx) return;
    setAction(tx.action);
    setShares(String(tx.shares));
    setPrice(tx.price);
    setTradeTime(tx.tradeTime ? tx.tradeTime.slice(0, 5) : '');
    setNote(tx.note ?? '');
    setError(null);
    setErrorCode(null);
  }, [tx]);

  if (!tx) return null;

  const submit = async () => {
    const n = Number(shares);
    if (!Number.isFinite(n) || n <= 0) {
      setError('股数必须 > 0');
      return;
    }
    if (!/^\d+(\.\d{1,3})?$/.test(price.trim())) {
      setError('价格格式:数字,最多 3 位小数');
      return;
    }
    setSubmitting(true);
    setError(null);
    setErrorCode(null);
    try {
      const updated = await apiPatch<Transaction>(`/transactions/${tx.id}`, {
        action,
        shares: n,
        price: price.trim(),
        ...(tradeTime ? { tradeTime } : {}),
        ...(note ? { note } : {}),
      });
      onSaved?.(updated);
      onClose();
    } catch (e) {
      setErrorCode(apiErrorCode(e));
      setError(apiErrorMessage(e, '保存失败'));
    } finally {
      setSubmitting(false);
    }
  };

  const label = tx.stockName ? `${tx.stockName} ${tx.stockCode}` : tx.stockCode;

  return (
    <Modal
      open
      onClose={() => !submitting && onClose()}
      title={`编辑流水 · ${label}`}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button onClick={() => void submit()} disabled={submitting}>
            {submitting ? '保存中…' : '保存'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="text-xs text-text-ter">
          {tx.tradeDate} · #{tx.id}
          {tx.score !== null && ` · 原评分 ${tx.score}`}
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">方向</label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setAction('buy')}
              className={
                action === 'buy'
                  ? 'flex-1 rounded border border-accent bg-accent/10 text-accent text-sm py-1.5'
                  : 'flex-1 rounded border border-border-def text-text-sec text-sm py-1.5 hover:bg-bg-subtle'
              }
            >
              买入
            </button>
            <button
              type="button"
              onClick={() => setAction('sell')}
              className={
                action === 'sell'
                  ? 'flex-1 rounded border border-accent bg-accent/10 text-accent text-sm py-1.5'
                  : 'flex-1 rounded border border-border-def text-text-sec text-sm py-1.5 hover:bg-bg-subtle'
              }
            >
              卖出
            </button>
          </div>
          {tx.action !== action && (
            <p className="mt-1 text-xs text-warn">
              改了方向 → 持仓股数会反向变化;保存前系统会校验卖出的股数是否够。
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium mb-1">股数</label>
            <input
              type="number"
              min={1}
              value={shares}
              onChange={(e) => setShares(e.target.value)}
              className="w-full rounded border border-border-def bg-bg-subtle px-2 py-1.5 text-sm text-text-pri outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">价格</label>
            <input
              type="text"
              inputMode="decimal"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              className="w-full rounded border border-border-def bg-bg-subtle px-2 py-1.5 text-sm text-text-pri outline-none focus:border-accent"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            时间点
            <span className="ml-1 text-xs font-normal text-text-ter">
              留空 = 未知(不编造)
            </span>
          </label>
          <input
            type="time"
            value={tradeTime}
            onChange={(e) => setTradeTime(e.target.value)}
            className="w-full rounded border border-border-def bg-bg-subtle px-2 py-1.5 text-sm text-text-pri outline-none focus:border-accent"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">备注</label>
          <input
            type="text"
            maxLength={200}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="可选"
            className="w-full rounded border border-border-def bg-bg-subtle px-2 py-1.5 text-sm text-text-pri outline-none focus:border-accent"
          />
        </div>

        {error && (
          <div className="rounded border border-down/40 bg-down/10 px-3 py-2 text-xs text-down">
            {error}
            {errorCode && (
              <span className="ml-2 font-mono opacity-70">{errorCode}</span>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
