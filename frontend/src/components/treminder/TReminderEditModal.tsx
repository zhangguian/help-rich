'use client';

import { useEffect, useState } from 'react';

import { apiGet } from '@/lib/api';
import type { TReminderItem } from '@/lib/api/tReminders';
import type { Transaction } from '@/lib/types';

import { TransactionEditModal } from '@/components/transaction/TransactionEditModal';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';

/**
 * 做T挂单「编辑」弹窗 —— 挑出这条挂单对应的开腿流水,再编辑其中一笔。
 *
 * 为什么不是直接编辑:
 *   清单里**一行 = 一只票 = 可能合并了多笔开腿流水**(同一只票做了两次T)。
 *   一行直接给编辑框 → 用户不知道在改哪一笔,容易改错。
 *   所以先列出这条挂单的所有开腿流水(带日期/时间/方向/价格),挑一笔再编辑。
 *
 * 一行只有一笔时 → 直接进编辑框(不绕这一层)。
 */
export function TReminderEditModal({
  item,
  onClose,
  onSaved,
}: {
  item: TReminderItem | null;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [legs, setLegs] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Transaction | null>(null);

  useEffect(() => {
    if (!item) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      setEditing(null);
      try {
        const resp = await apiGet<{ items: Transaction[] }>(
          `/transactions?stock_code=${encodeURIComponent(item.stockCode)}&limit=200`,
        );
        if (cancelled) return;
        // `?? []`:老数据/老后端可能没有开腿 id 字段 —— 缺了就不过滤(全列出来)
        const ids = new Set(item.openTxIds ?? []);
        const picked = resp.items
          .filter((t) => (ids.size ? ids.has(t.id) : true))
          .sort((a, b) => a.id - b.id);
        setLegs(picked);
        // 只有一笔 → 直接进编辑(不让人多点一次)
        if (picked.length === 1) setEditing(picked[0] ?? null);
      } catch {
        if (!cancelled) setError('流水加载失败,请重试');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [item]);

  if (!item) return null;

  const label = item.stockName ? `${item.stockName} ${item.stockCode}` : item.stockCode;

  return (
    <>
      <Modal
        open={!editing}
        onClose={onClose}
        title={`编辑做T流水 · ${label}`}
        size="lg"
        footer={
          <Button variant="secondary" onClick={onClose}>
            关闭
          </Button>
        }
      >
        <div className="space-y-3">
          <p className="text-xs text-text-ter">
            这条挂单由下面这些开腿流水组成(方向 / 股数 / 价格录错了就改哪一笔):
          </p>
          {loading && <div className="py-4 text-center text-sm text-text-ter">加载中…</div>}
          {error && (
            <div className="rounded-sm border border-danger/40 bg-danger-bg px-3 py-2 text-xs text-danger">
              {error}
            </div>
          )}
          {!loading && !error && legs.length === 0 && (
            <div className="py-4 text-center text-sm text-text-ter">
              找不到对应的流水(可能已被删除)
            </div>
          )}
          {legs.length > 0 && (
            <div className="space-y-2">
              {legs.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between gap-3 rounded-sm border border-border-def px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="text-sm text-text-pri">
                      <span className={t.action === 'buy' ? 'text-down' : 'text-up'}>
                        {t.action === 'buy' ? '买入' : '卖出'}
                      </span>
                      <span className="ml-2 font-mono">
                        {t.shares} 股 @ {t.price}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-text-ter">
                      {t.tradeDate}
                      {t.tradeTime ? ` ${t.tradeTime.slice(0, 5)}` : ' 时间未知'}
                      {t.note ? ` · ${t.note}` : ''}
                    </div>
                  </div>
                  <Button size="sm" onClick={() => setEditing(t)}>
                    编辑
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>

      <TransactionEditModal
        tx={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          onSaved?.();
        }}
      />
    </>
  );
}
