'use client';

import { useCallback, useEffect, useState } from 'react';

import clsx from 'clsx';

import { fetchTHistory, type THistory, type THistoryItem } from '@/lib/api/tHistory';

/**
 * 做T操作历史面板(持仓详情右侧)
 *
 * 口径(与后端 api_t_history.py 一致):
 * - 做T分两个方向,腿的先后顺序不同:
 *   · 反T = 先卖出、后买回(高抛低吸)
 *   · 正T = 先买入、后卖出(低吸高抛)
 * - 按链全序双向 FIFO 配对:后一笔流水闭合最早的开腿;
 *   链尾还挂着的开腿 = 待接回(反T) / 待卖出(正T)
 * - 做T盈亏 = (卖出价 − 买入价) × T股数 —— 两个方向都是低买高卖赚差价
 * - 已实现 = (卖出价 − 卖出那一刻的成本价) × 股数 —— 相对成本价这笔卖出赚没赚
 * - 基准吸收的早期导入流水没有逐笔成本 → 成本列显示「—」(不编数字)
 *
 * 颜色口径:涨红跌绿(text-up=红 / text-down=绿)。
 */
export function THistoryPanel({ stockCode }: { stockCode: string }) {
  const [data, setData] = useState<THistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchTHistory(stockCode));
    } catch {
      setError('做T历史加载失败,请重试');
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  useEffect(() => {
    void load();
  }, [load]);

  const pnlCls = (v: number | null) =>
    v == null ? 'text-text-ter' : v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-text-ter';

  const money = (v: number | null) =>
    v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}`;
  const price = (v: number | null) => (v == null ? '—' : v.toFixed(3));

  const items = data?.items ?? [];
  const closed = items.filter((it) => it.status === 'closed');
  const pendingReverse = items.filter(
    (it) => it.status === 'pending' && it.direction === 'reverse',
  );
  const pendingForward = items.filter(
    (it) => it.status === 'pending' && it.direction === 'forward',
  );
  const pendingCount = pendingReverse.length + pendingForward.length;
  // 累计做T盈亏只算已闭合(还挂着就没有价差);累计已实现只算有成本基准的记录
  const sumT = closed.reduce((a, it) => a + (it.tPnl ?? 0), 0);
  const sumRealized = items.reduce((a, it) => a + (it.realizedPnl ?? 0), 0);
  const realizedCount = items.filter((it) => it.realizedPnl != null).length;

  return (
    <section className="flex flex-col min-h-0">
      <div className="flex items-baseline gap-2 mb-1">
        <h4 className="text-sm font-semibold">做T操作历史</h4>
        {data && (
          <span className="text-[11px] text-text-ter font-mono">{data.count} 次</span>
        )}
      </div>

      {items.length > 0 && (
        <div className="grid grid-cols-3 gap-1.5 mb-2">
          <div className="rounded-sm border border-border-def bg-bg-subtle px-2 py-1.5">
            <div className="text-[10px] text-text-ter">已完成</div>
            <div className="font-mono text-[13px] text-text-pri">{closed.length} 次</div>
          </div>
          <div className="rounded-sm border border-border-def bg-bg-subtle px-2 py-1.5">
            <div className="text-[10px] text-text-ter">累计做T盈亏</div>
            <div className={clsx('font-mono text-[13px]', pnlCls(sumT))}>
              {money(sumT)}
            </div>
          </div>
          <div className="rounded-sm border border-border-def bg-bg-subtle px-2 py-1.5">
            <div className="text-[10px] text-text-ter">挂单中</div>
            <div
              className={clsx(
                'font-mono text-[13px]',
                pendingCount > 0 ? 'text-warn' : 'text-text-ter',
              )}
            >
              {pendingCount} 次
            </div>
            {pendingCount > 0 && (
              <div className="text-[10px] text-text-ter">
                待接回 {pendingReverse.length} · 待卖出 {pendingForward.length}
              </div>
            )}
          </div>
        </div>
      )}

      <p className="text-[10px] text-text-ter leading-relaxed mb-2">
        口径:<b className="text-text-sec">反T</b> = 先卖出后买回(高抛低吸),
        <b className="text-text-sec">正T</b> = 先买入后卖出(低吸高抛),按流水顺序自动配对
        (配对窗口 3 天 —— 隔更久就不是做T了,是加仓或割肉)。
        <br />
        做T盈亏 =(卖价 − 买价)×股数;已实现 =(卖价 − 卖出时成本)×股数
        {realizedCount > 0 && realizedCount < items.length && (
          <>;已实现只统计有成本基准的 {realizedCount}/{items.length} 条</>
        )}
        。成本为摊薄成本(券商口径);早期导入的流水没有逐笔成本,成本列显示「—」。
      </p>

      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-8 bg-bg-subtle rounded-sm animate-pulse" />
          ))}
        </div>
      ) : error ? (
        <div className="text-text-sec text-center py-6 space-y-2">
          <p className="text-xs">{error}</p>
          <button
            className="text-xs text-accent hover:underline"
            onClick={() => void load()}
          >
            重试
          </button>
        </div>
      ) : !data || items.length === 0 ? (
        <p className="text-text-ter text-xs text-center py-6">
          还没有做T记录 —— 先买后卖(正T)或先卖后买(反T)就会出现。
        </p>
      ) : (
        <div className="border border-border-def rounded-sm overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead className="bg-bg-subtle text-text-sec">
              <tr>
                <th className="text-left px-1.5 py-1 font-normal whitespace-nowrap">日期</th>
                <th className="text-right px-1.5 py-1 font-normal whitespace-nowrap">股数</th>
                <th className="text-right px-1.5 py-1 font-normal whitespace-nowrap">
                  卖出→买回
                </th>
                <th className="text-right px-1.5 py-1 font-normal whitespace-nowrap">
                  成本 前→后
                </th>
                <th className="text-right px-1.5 py-1 font-normal whitespace-nowrap">做T盈亏</th>
                <th className="text-right px-1.5 py-1 font-normal whitespace-nowrap">已实现</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((it) => (
                <tr
                  key={`${it.sellTxId ?? 'x'}-${it.buyTxId ?? 'x'}-${it.direction}`}
                  className="border-t border-border-def"
                >
                  <td className="px-1.5 py-1 font-mono text-text-sec whitespace-nowrap">
                    {(it.sellDate ?? it.buyDate ?? '').slice(5)}
                    <span
                      className={clsx(
                        'ml-1 px-1 rounded-sm text-[9px]',
                        it.direction === 'forward'
                          ? 'text-accent bg-accent-subtle'
                          : 'text-text-sec bg-bg-subtle',
                      )}
                    >
                      {it.direction === 'forward' ? '正T' : '反T'}
                    </span>
                    <span
                      className={clsx(
                        'ml-1 px-1 rounded-sm text-[9px]',
                        it.status === 'closed'
                          ? 'text-text-ter bg-bg-subtle'
                          : 'text-warn bg-warn/10',
                      )}
                    >
                      {it.status === 'closed'
                        ? '已完成'
                        : it.direction === 'forward'
                          ? '待卖出'
                          : '待接回'}
                    </span>
                  </td>
                  <td className="px-1.5 py-1 text-right font-mono text-text-pri">
                    {it.shares}
                  </td>
                  <td className="px-1.5 py-1 text-right font-mono whitespace-nowrap">
                    <LegCell it={it} price={price} />
                  </td>
                  <td className="px-1.5 py-1 text-right font-mono whitespace-nowrap">
                    <span className="text-text-sec">{price(it.costBefore)}</span>
                    <span className="text-text-ter"> → </span>
                    <span className="text-text-sec">{price(it.costAfter)}</span>
                  </td>
                  <td className={clsx('px-1.5 py-1 text-right font-mono', pnlCls(it.tPnl))}>
                    {money(it.tPnl)}
                  </td>
                  <td className={clsx('px-1.5 py-1 text-right font-mono', pnlCls(it.realizedPnl))}>
                    {money(it.realizedPnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * 「卖出→买回」单元格。
 *
 * 两个方向的腿顺序相反,列头写死「卖出→买回」但内容按方向排:
 * - 反T:卖出在前,买回在后(没买回就显示「待接回」)
 * - 正T:买回在前(其实是买入腿),卖出在后(没卖就显示「待卖出」)
 */
function LegCell({
  it,
  price,
}: {
  it: THistoryItem;
  price: (v: number | null) => string;
}) {
  const sell = it.sellPrice != null ? price(it.sellPrice) : null;
  const buy = it.buyPrice != null ? price(it.buyPrice) : null;

  if (it.direction === 'forward') {
    // 正T:买入腿 → 卖出腿
    return (
      <>
        <span className="text-text-sec">{buy ?? '—'}</span>
        <span className="text-text-ter"> → </span>
        {sell ? (
          <span className="text-text-sec">{sell}</span>
        ) : (
          <span className="text-warn">待卖出</span>
        )}
      </>
    );
  }

  // 反T:卖出腿 → 买回腿
  return (
    <>
      <span className="text-text-sec">{sell ?? '—'}</span>
      <span className="text-text-ter"> → </span>
      {buy ? (
        <span className="text-text-sec">{buy}</span>
      ) : (
        <span className="text-warn">待接回</span>
      )}
    </>
  );
}
