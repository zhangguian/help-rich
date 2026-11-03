'use client';

import { AnimatePresence, motion } from 'framer-motion';
import Link from 'next/link';

import clsx from 'clsx';

import type { PriceAlertPopupItem } from '@/lib/api/priceAlerts';

import { usePriceAlertStore } from '@/stores/usePriceAlertStore';

/**
 * 到价提醒 · 应用内弹窗
 *
 * **为什么必须做这个**:到价提醒原来只走「后端推系统通知」,
 * 而 Windows 托盘气泡在部分 Win11 机器上**根本不渲染**
 * (实测 `ShowBalloonTip` 返回成功,屏幕上什么都没有)。
 * 这条兜底不依赖任何系统能力 —— **只要页面开着,就一定弹得出来**。
 *
 * **不自动消失**:价格提醒错过就是错过,所以只能手动关(右上角 ×)。
 *
 * **两种提醒**:
 * - `kind === 'pre_alert'` → **预警**(到价之前先给一次「准备」信号)→ 琥珀色徽章;
 * - 其余 → **到价提醒** → 涨跌色徽章。
 *
 * **配色**:涨跌红绿。`跌到` 类提醒(条件含 `<=`)用绿,`涨到` 类(含 `>=`)用红,
 * 与项目「涨红跌绿」口径一致 —— 颜色说的是**行情方向**,不是好坏。
 */
const PRE_ALERT_KIND = 'pre_alert';

function directionOf(conditionsText: string): 'down' | 'up' {
  if (conditionsText.includes('>=')) return 'up';
  if (conditionsText.includes('<=')) return 'down';
  return 'up';
}

function AlertPopup({ item }: { item: PriceAlertPopupItem }) {
  const dismiss = usePriceAlertStore((s) => s.dismiss);
  const isPre = item.kind === PRE_ALERT_KIND;
  const dir = directionOf(item.alert.conditionsText);
  const priceTxt = item.alert.price != null ? item.alert.price.toFixed(3) : '—';

  return (
    <motion.div
      initial={{ opacity: 0, x: 32, scale: 0.96 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 32, scale: 0.96 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
      role="alert"
      data-testid="price-alert-popup"
      className="pointer-events-auto overflow-hidden rounded-lg border border-border-str bg-bg-elevated shadow-pop"
    >
      <div className={clsx('h-1 w-full', isPre ? 'bg-warn' : dir === 'up' ? 'bg-up' : 'bg-down')} />
      <div className="p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={clsx(
                  'rounded px-1.5 py-0.5 text-[10px] font-medium',
                  isPre
                    ? 'bg-warn-bg text-warn'
                    : dir === 'up'
                      ? 'bg-up-bg text-up'
                      : 'bg-down-bg text-down',
                )}
              >
                {isPre ? '准备' : dir === 'up' ? '涨到' : '跌到'}
              </span>
              <span className="truncate text-sm font-semibold text-text-pri">
                {item.alert.name}
              </span>
              <span className="font-mono text-[11px] text-text-ter">{item.alert.stockCode}</span>
            </div>
            <p className="mt-1.5 text-xs text-text-sec">{item.alert.conditionsText}</p>
            {isPre && (
              <p className="mt-0.5 text-[11px] text-warn">快到了 —— 先把单子准备好</p>
            )}
          </div>
          <button
            type="button"
            onClick={() => dismiss(item.localId)}
            aria-label="关闭提醒"
            className="flex-shrink-0 text-text-ter opacity-70 transition hover:opacity-100"
          >
            ×
          </button>
        </div>

        <div className="mt-2 flex items-end justify-between gap-3">
          <div>
            <div className="text-[10px] text-text-ter">当前价</div>
            <div className="font-mono text-lg leading-tight text-text-pri">{priceTxt}</div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/t-reminders"
              onClick={() => dismiss(item.localId)}
              className="rounded border border-border-str px-2 py-1 text-[11px] text-text-sec transition hover:bg-bg-surface"
            >
              看待办
            </Link>
            <button
              type="button"
              onClick={() => dismiss(item.localId)}
              className="rounded bg-accent px-2.5 py-1 text-[11px] text-bg-base transition hover:opacity-90"
            >
              知道了
            </button>
          </div>
        </div>

        {item.channels.length > 0 && (
          <p className="mt-2 text-[10px] text-text-ter">
            已推送:
            {item.channels.map((c) => c.channel).join(' / ')}
          </p>
        )}
      </div>
    </motion.div>
  );
}

/**
 * 弹窗容器。挂在 AppShell 上 —— **全站可见**,
 * 用户在盯盘页、在做T清单页,弹窗都冒得出来。
 */
export function PriceAlertPopup() {
  const items = usePriceAlertStore((s) => s.items);

  return (
    <div
      aria-live="assertive"
      className="pointer-events-none fixed bottom-24 right-6 z-[70] flex w-[340px] flex-col gap-2"
    >
      <AnimatePresence initial={false}>
        {items.map((item) => (
          <AlertPopup key={item.localId} item={item} />
        ))}
      </AnimatePresence>
    </div>
  );
}
