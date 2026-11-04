'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { TransactionForm } from '@/components/transaction/TransactionForm';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import type { TReminderItem, TTier } from '@/lib/api/tReminders';
import { intFormat, priceFormat } from '@/lib/decimalFormat';
import type { Transaction } from '@/lib/types';
import { useTReminderStore } from '@/stores/useTReminderStore';
import { useUIStore } from '@/stores/useUIStore';

import { TReminderEditModal } from './TReminderEditModal';

/**
 * 补T提醒面板(/t-reminders)
 *
 * 口径:全链双向 FIFO 配对后**还没闭合的开腿**就是还挂着的做T单,分两组:
 * - 待接回(反T,先卖后买):卖出了还没买回来。
 *   不亏本接回线 = 净卖出加权均价;三档建议价 = 线再低 1% / 2% / 3%。
 * - 待卖出(正T,先买后卖):买进了还没卖出去。
 *   买入加权均价;三档建议价 = 均价再高 1% / 2% / 3%。
 *
 * 两组的档位方向相反(反T 往下、正T 往上)—— 不能一味价高。
 * 每档都带「按这一档成交之后的摊薄成本线」,一眼看出做到哪一档最划算。
 *
 * 到价提醒由后端自动对齐:每条挂单保证有一条到价提醒(反T ≤ / 正T ≥),
 * 挂单接回/卖出后自动停用。
 *
 * 卖出腿和接回腿可以跨天(今天卖、明天接回是标准做T节奏),
 * 只要接回/卖出就自动消失,不用手动清理。
 */
export function TReminderPanel() {
  const items = useTReminderStore((s) => s.items);
  const forwardItems = useTReminderStore((s) => s.forwardItems);
  const totalCount = useTReminderStore((s) => s.totalCount);
  const asOf = useTReminderStore((s) => s.asOf);
  const loading = useTReminderStore((s) => s.loading);
  const error = useTReminderStore((s) => s.error);
  const load = useTReminderStore((s) => s.load);
  const refresh = useTReminderStore((s) => s.refresh);
  const lastLoadedAt = useTReminderStore((s) => s.lastLoadedAt);
  const showToast = useUIStore((s) => s.showToast);

  const [editing, setEditing] = useState<TReminderItem | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  // 通用录入入口:录一笔**不是挂单**的流水(行内按钮只管挂单那几只)
  const [manualEntry, setManualEntry] = useState(false);
  // 编辑一条挂单对应的开腿流水
  const [editingLeg, setEditingLeg] = useState<TReminderItem | null>(null);

  useEffect(() => {
    void load();
  }, [load]);

  // 左栏点某条进来时高亮它(用 window 读,不引 useSearchParams —— 免得静态预渲染要 Suspense)
  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get('code');
    if (code) setHighlight(code);
  }, []);

  /**
   * 录完一笔流水后的即时反馈。
   *
   * 为什么按「这只票现在的挂单」判断,而不是接口里的 autoAlertsCreated:
   *   提醒是**录入那一刻**由后端建好的(POST /transactions 内同步),
   *   随后刷新补T清单时它们已经存在,`autoAlertsCreated` 必然是 0 ——
   *   拿它做提示会永远显示「没建任何提醒」。
   *   所以这里查这只票当前挂的提醒落在哪一档,直接告诉用户「跌到/涨到多少会响」。
   */
  const notifyRecorded = useCallback(
    async (tx: Transaction) => {
      await refresh();
      // refresh 后要读**最新**的 store(闭包里的 items 是刷新前的)
      const st = useTReminderStore.getState();
      const it = [...st.items, ...st.forwardItems].find(
        (x) => x.stockCode === tx.stockCode,
      );
      if (!it) {
        showToast({ type: 'success', message: '流水已录入' });
        return;
      }
      if (it.alertAuto && it.alertPrice !== null) {
        const when = it.direction === 'forward' ? '涨到' : '跌到';
        const what = it.direction === 'forward' ? '提醒卖出' : '提醒接回';
        showToast({
          type: 'success',
          message: `已生成二T提醒：${when} ${priceFormat(it.alertPrice)} ${what}`,
        });
        return;
      }
      showToast({ type: 'success', message: '流水已录入 · 补T清单已更新' });
    },
    [refresh, showToast],
  );

  const onRecorded = useCallback(
    async (tx: Transaction) => {
      setEditing(null);
      await notifyRecorded(tx);
    },
    [notifyRecorded],
  );

  const empty = items.length === 0 && forwardItems.length === 0;

  return (
    <div className="space-y-4">
      <Card padding="md" className="space-y-3">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold">
              做T挂单清单
              <span className="ml-2 text-xs font-normal text-text-sec">
                {totalCount} 只{asOf ? ` · 基准日 ${asOf}` : ''}
              </span>
            </h2>
            <p className="mt-1 text-xs text-text-ter leading-relaxed">
              口径:全链按流水顺序自动配对,做T分两个方向 ——
              <b className="text-text-sec">反T</b>(先卖后买,高抛低吸)与
              <b className="text-text-sec">正T</b>(先买后卖,低吸高抛);
              还没配上的那条腿就是挂单,接回/卖出后自动消失,跨天也记得住
              (配对窗口 3 天 —— 隔更久就不是做T了,是加仓或割肉)。
              <br />
              <b className="text-text-sec">待接回</b>的不亏本线 = 净卖出加权均价 ——
              接回价高于它,这次 T 就是做亏的;
              <b className="text-text-sec">待卖出</b>的基准线 = 买入加权均价。
              旁边的<b className="text-text-sec">当初卖出价 / 当初买入价</b>
              是<b className="text-text-sec">开腿那笔流水的真实成交价</b> ——
              同一只票做过两次T(两笔开腿)就会列两个价,而基准线是它们的加权均价。
              两组都分<b className="text-text-sec">一/二/三档</b>(1%、2%、3%),
              <b className="text-text-sec">方向相反</b>:反T 往下(越等越便宜),正T 往上(越等越贵)——
              一档贴线最容易成交,三档幅度最大但可能要等行情。
              每档后面跟的是<b className="text-text-sec">按这档成交后的成本前→后</b>(摊薄成本,券商口径)。
              <br />
              <b className="text-accent">到价提醒自动对齐</b>:每条挂单都保证有一条提醒 ——
              反T 跌到一档价提醒接回(≤),正T 涨到一档价提醒卖出(≥);
              挂单接回/卖出后,对应的自动提醒会停用。
              <br />
              <b className="text-warn">提前预警</b>:到价才响就没有操作空间了 ——
              每条挂单还有一条<b className="text-text-sec">预警线</b>
              (= 生效到价线朝基准线方向再退 1%,≈基准线),
              价格进了预警区就先提醒你<b className="text-text-sec">准备</b>,不用等真的到价。
              预警<b className="text-text-sec">只响一次</b>;价格离开预警区之后会自动重新武装。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => setManualEntry(true)}>
              + 录入流水
            </Button>
            <Button variant="ghost" onClick={() => void refresh()} loading={loading}>
              刷新
            </Button>
          </div>
        </header>

        {error && (
          <div className="rounded-sm border border-danger/40 bg-danger-bg px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}

        {loading && empty ? (
          <div className="py-8 text-center text-sm text-text-ter">加载中…</div>
        ) : empty && lastLoadedAt === 0 && !error ? (
          // 首次拉取还没回来 —— 别先闪一下「没有待接回的票」,那会让人以为真没有
          <div className="py-8 text-center text-sm text-text-ter">加载中…</div>
        ) : empty ? (
          <div className="py-10 text-center">
            <div className="text-2xl">✅</div>
            <p className="mt-2 text-sm text-text-sec">没有挂着的做T单</p>
            <p className="mt-1 text-xs text-text-ter">
              卖出的票都接回过了,买进的票也卖掉了。有一边没配上的话,这里会出现清单。
            </p>
          </div>
        ) : (
          <div className="space-y-5">
            <GroupTable
              title="待接回"
              subtitle="反T · 先卖出后买回"
              items={items}
              highlight={highlight}
              onEdit={setEditing}
              onEditLeg={setEditingLeg}
            />
            <GroupTable
              title="待卖出"
              subtitle="正T · 先买入后卖出"
              items={forwardItems}
              highlight={highlight}
              onEdit={setEditing}
              onEditLeg={setEditingLeg}
            />
          </div>
        )}
      </Card>

      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title={
          editing
            ? `${editing.direction === 'forward' ? '录入卖出' : '录入接回'} · ${editing.stockName ?? editing.stockCode}`
            : ''
        }
        size="lg"
      >
        {editing && (
          <>
            <div className="rounded-sm border border-border-def border-l-[3px] border-l-accent bg-bg-elevated px-3 py-2 text-xs text-text-sec">
              <div className="mb-1.5">
                {editing.direction === 'forward' ? '建议卖出价 ≥ ' : '建议接回价 ≤ '}
                <b className="font-mono text-accent">
                  {priceFormat(editing.suggestedPrice ?? editing.price)}
                </b>
                <span className="text-text-ter">
                  （一档;
                  {editing.direction === 'forward'
                    ? `买入均价 ${priceFormat(editing.price)}`
                    : `不亏本线 ${priceFormat(editing.price)}`}
                  {' · '}
                  {editing.direction === 'forward' ? '卖出' : '接回'} {intFormat(editing.shares)} 股）
                </span>
              </div>
              {editing.preAlertPrice !== null && (
                <div className="mb-1.5">
                  预警线{' '}
                  <b className="font-mono text-warn">
                    {editing.direction === 'forward' ? '≥ ' : '≤ '}
                    {priceFormat(editing.preAlertPrice)}
                  </b>
                  <span className="text-text-ter">
                    （到价前先提醒准备
                    {editing.preAlertDistancePct !== null
                      ? ` · 还差 ${editing.preAlertDistancePct.toFixed(2)}%`
                      : ''}
                    ）
                  </span>
                </div>
              )}
              {editing.tiers.length > 0 && (
                <div className="space-y-0.5">
                  {editing.tiers.map((t) => (
                    <div key={t.tier} className="flex items-baseline gap-2">
                      <span className="w-8 shrink-0 text-text-ter">{t.label}</span>
                      <span className="font-mono text-accent">{priceFormat(t.price)}</span>
                      <span className="font-mono text-text-ter">
                        成本 {t.costBefore !== null ? priceFormat(t.costBefore) : '—'} →{' '}
                        {t.costAfter !== null ? priceFormat(t.costAfter) : '—'}
                      </span>
                      <span className="text-text-ter">· {t.hint}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <TransactionForm
              initialStockCode={editing.stockCode}
              initialAction={editing.direction === 'forward' ? 'sell' : 'buy'}
              initialShares={editing.shares}
              initialPrice={priceFormat(editing.suggestedPrice ?? editing.price)}
              onSuccess={(tx) => void onRecorded(tx)}
              onCancel={() => setEditing(null)}
            />
          </>
        )}
      </Modal>

      <Modal
        open={manualEntry}
        onClose={() => setManualEntry(false)}
        title="录入流水"
        size="lg"
      >
        <TransactionForm
          onSuccess={(tx) => {
            setManualEntry(false);
            void notifyRecorded(tx);
          }}
          onCancel={() => setManualEntry(false)}
        />
      </Modal>

      <TReminderEditModal
        item={editingLeg}
        onClose={() => setEditingLeg(null)}
        onSaved={() => {
          // 改了开腿 → 挂单的股数/均价/提醒都变了 → 整表重拉
          void refresh();
          showToast({ type: 'success', message: '流水已更新,做T清单已同步' });
        }}
      />
    </div>
  );
}

/**
 * 一组挂单(全部同方向)的表格。
 *
 * 反T组:不亏本线 / 三档建议接回价 / 现价判断(可接回 · 刚回本 · 高于线)。
 * 正T组:买入均价 / 三档建议卖出价 / 现价判断(可卖出 · 刚回本 · 低于线)。
 */
function GroupTable({
  title,
  subtitle,
  items,
  highlight,
  onEdit,
  onEditLeg,
}: {
  title: string;
  subtitle: string;
  items: TReminderItem[];
  highlight: string | null;
  onEdit: (it: TReminderItem) => void;
  /** 编辑这条挂单对应的开腿流水(录错方向/价格时改,不用删了重录) */
  onEditLeg: (it: TReminderItem) => void;
}) {
  if (items.length === 0) return null;
  const isForward = items[0]?.direction === 'forward';
  const op = isForward ? '≥' : '≤';

  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-2">
        <h3 className="text-sm font-semibold text-text-pri">{title}</h3>
        <span className="text-[11px] text-text-ter">{subtitle}</span>
        <span className="text-[11px] font-mono text-text-ter">{items.length} 只</span>
      </div>
      <div className="overflow-x-auto">
        {/* ⚠️ 表格有 13 列,窄屏下会被挤扁(名称列竖着排一个字一行)。
            给一个最小宽度 → 横向滚动,而不是把每一列压扁。
            名称列再加 nowrap → 「平安新兴产业LOF」横着排,不折行。 */}
        <table className="w-full min-w-[1260px] text-xs">
          <thead>
            <tr className="border-b border-border-def text-left text-text-ter">
              <th className="py-2 pr-3 font-medium">标的</th>
              <th className="py-2 pr-3 font-medium whitespace-nowrap">名称</th>
              <th className="py-2 pr-3 text-right font-medium">
                {isForward ? '待卖出' : '待接回'}
              </th>
              <th className="py-2 pr-3 text-right font-medium whitespace-nowrap">
                {isForward ? '当初买入价' : '当初卖出价'}
              </th>
              <th className="py-2 pr-3 text-right font-medium">
                {isForward ? '买入均价' : '不亏本线'}
              </th>
              <th className="py-2 pr-3 font-medium">三档建议价 · 成本前→后</th>
              <th className="py-2 pr-3 text-right font-medium">现价</th>
              <th className="py-2 pr-3 font-medium">
                {isForward ? '卖出判断' : '接回判断'}
              </th>
              <th className="py-2 pr-3 text-right font-medium">持仓</th>
              <th className="py-2 pr-3 font-medium">挂单日</th>
              <th className="py-2 pr-3 font-medium">到价提醒</th>
              <th className="py-2 pr-3 font-medium">预警线 · 还差</th>
              <th className="py-2 font-medium whitespace-nowrap">操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => {
              const suggested = it.suggestedPrice ?? it.price;
              // 反T:现价 ≤ 建议价 = 可接回;高于不亏本线 = 接回来就亏
              // 正T:现价 ≥ 建议价 = 可卖出;低于买入均价 = 卖了就亏
              const reached = isForward
                ? it.currentPrice !== null && it.currentPrice >= suggested - 1e-9
                : it.currentPrice !== null && it.currentPrice <= suggested + 1e-9;
              const badSide =
                isForward
                  ? it.currentPrice !== null && it.currentPrice < it.price - 1e-9
                  : it.currentPrice !== null && it.currentPrice > it.price + 1e-9;
              const gap =
                it.currentPrice !== null && it.price > 0
                  ? ((it.currentPrice - it.price) / it.price) * 100
                  : null;
              return (
                <tr
                  key={it.stockCode}
                  className={clsx(
                    'border-b border-border-def/60 last:border-0',
                    highlight === it.stockCode && 'bg-accent-subtle',
                  )}
                >
                  <td className="py-2 pr-3 font-mono text-text-pri">{it.stockCode}</td>
                  <td className="py-2 pr-3 text-text-sec whitespace-nowrap">
                    {it.stockName ?? '—'}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-text-pri">
                    {intFormat(it.shares)}
                  </td>
                  {/* 当初那笔开腿流水的成交价(反T=卖出价,正T=买入价)。
                      与左边/右边的「不亏本线」不同:那是算出来的阈值,这是真成交价。
                      同一只票做过两次T → 两笔开腿 → 两个价,斜杠隔开。
                      `?? []`:store 已补齐,这里再兜一层 —— 旧数据/老后端缺字段时不崩。 */}
                  <td className="py-2 pr-3 text-right font-mono text-text-pri whitespace-nowrap">
                    {(it.openPrices ?? []).length > 0
                      ? (it.openPrices ?? []).map((p) => priceFormat(p)).join(' / ')
                      : '—'}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-text-sec">
                    {priceFormat(it.price)}
                  </td>
                  <td className="py-2 pr-3">
                    <TierColumn tiers={it.tiers} />
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-text-sec">
                    {it.currentPrice !== null ? priceFormat(it.currentPrice) : '—'}
                  </td>
                  <td className="py-2 pr-3">
                    {it.currentPrice === null ? (
                      <span className="text-text-ter">行情未知</span>
                    ) : reached ? (
                      <span className="text-accent">{isForward ? '可卖出' : '可接回'}</span>
                    ) : badSide ? (
                      <span className="text-warn">
                        {isForward ? '低于均价' : '高于线'}{' '}
                        {gap !== null ? `${Math.abs(gap).toFixed(2)}%` : ''}
                      </span>
                    ) : (
                      <span className="text-warn">刚回本</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-text-sec">
                    {it.positionShares !== null ? intFormat(it.positionShares) : '—'}
                  </td>
                  <td className="py-2 pr-3 font-mono text-text-ter">{it.openDate}</td>
                  <td className="py-2 pr-3">
                    {it.alertId !== null ? (
                      <div className="whitespace-nowrap">
                        <span className="text-accent">
                          {op}
                          {priceFormat(it.alertPrice ?? suggested)}
                          {it.alertTier !== null ? `(${it.alertTier}档)` : ''}
                        </span>
                        {!it.alertAuto && (
                          <span className="ml-1 text-text-ter">(手工)</span>
                        )}
                        {it.manualAlertId !== null && (
                          <span className="ml-1 text-text-ter">
                            另有手工 {op}
                            {priceFormat(it.manualAlertPrice ?? 0)}
                          </span>
                        )}
                      </div>
                    ) : it.manualAlertId !== null ? (
                      <span className="whitespace-nowrap text-text-sec">
                        手工 {op}
                        {priceFormat(it.manualAlertPrice ?? 0)}
                      </span>
                    ) : (
                      <span className="text-text-ter">—</span>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <PreAlertColumn it={it} op={op} />
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-1">
                      <Button size="sm" onClick={() => onEdit(it)}>
                        {isForward ? '录入卖出' : '录入接回'}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => onEditLeg(it)}
                        title="改这笔开腿流水的方向 / 股数 / 价格(录错了直接改,不用删了重录)"
                      >
                        编辑
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * 预警线 + 还差多少。
 *
 * **为什么要单列一栏**:到价才响 = 没有操作空间 —— 价格可能直接穿过去。
 * 预警线 = 生效到价线朝基准线方向再退 1%(≈基准线),价格进了这条线就先提醒「准备」。
 *
 * 三种状态:
 * - 还差 X%(还没进准备区);
 * - 已进入准备区(该准备了);
 * - 已越过到价线(该动手了)。
 * 现价拿不到 → 一律显示「—」,不编数字。
 */
function PreAlertColumn({ it, op }: { it: TReminderItem; op: string }) {
  if (it.preAlertId === null || it.preAlertPrice === null) {
    return <span className="text-text-ter">—</span>;
  }
  const dist =
    it.preAlertDistancePct !== null ? `${it.preAlertDistancePct.toFixed(2)}%` : '—';

  return (
    <div className="whitespace-nowrap">
      <div className="font-mono text-warn">
        {op}
        {priceFormat(it.preAlertPrice)}
      </div>
      <div className="text-[11px] text-text-ter">
        {it.currentPrice === null ? (
          '行情未知'
        ) : it.preAlertReached ? (
          <span className="text-accent">已越过 {dist}</span>
        ) : it.preAlertInZone ? (
          <span className="text-warn">已进入准备区 · 还差 {dist}</span>
        ) : (
          <>还差 {dist}</>
        )}
        {it.preAlertFired && <span className="ml-1 text-text-ter">(已预警)</span>}
      </div>
    </div>
  );
}

/**
 * 三档建议价 + 每档成交后的成本前→后。
 *
 * 一行一档:档位名 / 价格 / 成本前→后。
 * 成本拿不到时显示「—」,不编数字。
 */
function TierColumn({ tiers }: { tiers: TTier[] }) {
  if (!tiers || tiers.length === 0) {
    return <span className="text-text-ter">—</span>;
  }
  return (
    <div className="space-y-0.5">
      {tiers.map((t) => (
        <div key={t.tier} className="flex items-baseline gap-2 whitespace-nowrap">
          <span className="w-8 shrink-0 text-text-ter">{t.label}</span>
          <span className="font-mono text-accent">{priceFormat(t.price)}</span>
          <span className="font-mono text-text-sec">
            {t.costBefore !== null ? priceFormat(t.costBefore) : '—'}
            <span className="text-text-ter"> → </span>
            {t.costAfter !== null ? priceFormat(t.costAfter) : '—'}
          </span>
        </div>
      ))}
    </div>
  );
}
