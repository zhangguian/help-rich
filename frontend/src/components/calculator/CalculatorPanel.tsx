'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { PnlHeatmap } from '@/components/charts/PnlHeatmap';
import { TermHint } from '@/components/ui/TermHint';
import { decimalFormat, intFormat, priceFormat } from '@/lib/decimalFormat';
import { api, apiGet, apiPost, apiPut } from '@/lib/api';
import { normalizeCode } from '@/lib/stockCode';
import clsx from 'clsx';
import type {
  AccountCash,
  CalculatorResponse,
  Position,
  PositionListResponse,
  TradeReviewResponse,
} from '@/lib/types';
import { ReviewChecks, TAssessmentCard, VerdictBar, WhyPanel } from './TradeReviewCard';

/**
 * 账户 id —— 系统恒有且仅有一个默认账户(id=1,见 account_repository.DEFAULT_ACCOUNT_ID)。
 * 可用资金挂在账户上,不做多账户切换(计算器本身也按默认账户取持仓)。
 */
const DEFAULT_ACCOUNT_ID = 1;

/**
 * 计算器主面板(ui-ux §4.2 + frontend-arch §10.2,v0.6 布局优化)
 *
 * 布局:五段式,自上而下
 * - ① 结论条(全宽):打开弹窗第一眼就看到「这笔对不对」
 * - ② 预交易输入条 + 成交后摘要行
 * - ③ 双栏:左=当前持仓列表 / 右=做 T 判断 + 判定依据
 * - ④ 检查条:价位 / 数量
 * - ⑤ ±10% 盈亏热力图(复用 PnlHeatmap)
 *
 * 两条请求链路互不阻塞:
 * - POST /calculator         (300ms debounce) → 摘要行 + 热力图
 * - POST /calculator/review  (800ms debounce) → 结论条 + T 卡 + 依据 + 检查条
 *
 * initialCode:从工作台传入的默认股票代码,弹窗打开时自动选中
 */
export function CalculatorPanel({
  initialCode = null,
}: {
  initialCode?: string | null;
}) {
  const [positions, setPositions] = useState<Position[]>([]);
  const [positionsError, setPositionsError] = useState<string | null>(null);
  const [positionsLoading, setPositionsLoading] = useState(true);
  const [stockCode, setStockCode] = useState(() => {
    const c = initialCode ? normalizeCode(initialCode) : null;
    return c ?? '000001.SZ';
  });
  const [action, setAction] = useState<'buy' | 'sell'>('buy');
  const [txShares, setTxShares] = useState(200);
  const [txPrice, setTxPrice] = useState('11.000');
  const [result, setResult] = useState<CalculatorResponse | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 拟交易复核(v0.6):与 /calculator 分开一条链路 —— /calculator 是纯算术(300ms),
  // /calculator/review 要拉 K 线 + 指标 + 大盘(debounce 800ms,超时 30s)
  const [review, setReview] = useState<TradeReviewResponse | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  // 账户可用资金(正T 的股数上限由它决定)。
  // null = 未填写(不是 0)—— 两者对用户是不同结论,不能混。
  const [cash, setCash] = useState<string>('');
  const [cashSaving, setCashSaving] = useState(false);
  const [cashSaved, setCashSaved] = useState(false);

  const loadPositions = useCallback(async () => {
    setPositionsLoading(true);
    setPositionsError(null);
    try {
      const r = await apiGet<PositionListResponse>('/positions');
      setPositions(r.items);
    } catch (e) {
      const msg =
        e instanceof Error && e.message
          ? e.message
          : '持仓加载失败';
      setPositionsError(msg);
      setPositions([]);
    } finally {
      setPositionsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPositions();
  }, [loadPositions]);

  // 读账户可用资金(未填写 = 空字符串,不是 0)
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await apiGet<AccountCash>(`/accounts/${DEFAULT_ACCOUNT_ID}/cash`);
        if (!alive) return;
        setCash(r.cashAvailable == null ? '' : String(r.cashAvailable));
      } catch {
        // 读不到就当"未填写" —— 不阻断判定(判定层会给 None + degraded)
        if (alive) setCash('');
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // 用户改过资金后才自动保存(避免打开弹窗就把刚读到的值又写回去)
  const cashDirty = useRef(false);

  const onCashChange = useCallback((v: string) => {
    cashDirty.current = true;
    setCash(v);
  }, []);

  // 写账户可用资金:输入停顿 600ms 后自动保存
  useEffect(() => {
    if (!cashDirty.current) return;
    const handle = setTimeout(async () => {
      const trimmed = cash.trim();
      setCashSaving(true);
      try {
        if (trimmed === '') {
          // 空 = 清空(= 未填写),不是 0
          await apiPut<AccountCash>(`/accounts/${DEFAULT_ACCOUNT_ID}/cash`, {
            cashAvailable: null,
          });
        } else {
          const n = Number(trimmed);
          if (!Number.isFinite(n) || n < 0) return;
          await apiPut<AccountCash>(`/accounts/${DEFAULT_ACCOUNT_ID}/cash`, {
            cashAvailable: n,
          });
        }
        setCashSaved(true);
        setTimeout(() => setCashSaved(false), 2000);
      } catch {
        /* 静默:保存失败不影响本地试算,下次输入会再试 */
      } finally {
        setCashSaving(false);
      }
    }, 600);
    return () => clearTimeout(handle);
  }, [cash]);

  useEffect(() => {
    if (!initialCode) return;
    const c = normalizeCode(initialCode);
    if (c) setStockCode(c);
  }, [initialCode]);

  useEffect(() => {
    const norm = normalizeCode(stockCode);
    if (!norm) return;
    const pos = positions.find((p) => p.stockCode === norm);
    if (pos?.currentPrice != null) {
      setTxPrice(pos.currentPrice);
    }
  }, [stockCode, positions]);

  const currentPosition = positions.find(
    (p) => p.stockCode === normalizeCode(stockCode),
  );

  const currentPricePct =
    result?.after.costPrice != null && currentPosition?.currentPrice != null
      ? (Number(currentPosition.currentPrice) / Number(result.after.costPrice) - 1) * 100
      : undefined;

  // 实时计算(输入即算,300ms debounce)
  useEffect(() => {
    if (!txPrice || !stockCode || txShares <= 0) {
      setResult(null);
      return;
    }
    if (!/^\d+(\.\d{1,3})?$/.test(txPrice)) {
      setResult(null);
      return;
    }
    const handle = setTimeout(() => {
      doCalculate();
    }, 300);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stockCode, action, txShares, txPrice]);

  const doCalculate = async () => {
    setCalculating(true);
    setError(null);
    try {
      const resp = await apiPost<CalculatorResponse>('/calculator', {
        stockCode: normalizeCode(stockCode) ?? stockCode,
        action,
        txShares,
        txPrice,
      });
      setResult(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : '计算失败');
      setResult(null);
    } finally {
      setCalculating(false);
    }
  };

  // 拟交易复核:输入停 800ms 后拉一次深度判定
  //
  // 为什么用 validateStatus 而不是靠 axios 抛错:
  // 复核是「边输入边看结论」的高频调用,422(卖出超额)/502(K 线不可用)都会被
  // 全局拦截器弹 toast —— 打字过程中反复弹窗是噪音。业务文案就地展示即可。
  useEffect(() => {
    if (!txPrice || !stockCode || txShares <= 0) {
      setReview(null);
      setReviewError(null);
      return;
    }
    if (!/^\d+(\.\d{1,3})?$/.test(txPrice)) {
      setReview(null);
      return;
    }
    const handle = setTimeout(() => {
      doReview();
    }, 800);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stockCode, action, txShares, txPrice, cash]);

  const doReview = async () => {
    setReviewing(true);
    try {
      const body: Record<string, unknown> = {
        stockCode: normalizeCode(stockCode) ?? stockCode,
        action,
        txShares,
        txPrice,
      };
      // 可用资金:空字符串 = 明确"没有可用资金"(传 null),
      // 否则传当前输入值(覆盖账户已保存的值,即时反映用户刚填的数)
      const trimmed = cash.trim();
      if (trimmed !== '') {
        const n = Number(trimmed);
        if (Number.isFinite(n) && n >= 0) body.cashAvailable = n;
      } else {
        body.cashAvailable = null;
      }
      const resp = await api.post<TradeReviewResponse>('/calculator/review', body, {
        timeout: 30000,
        validateStatus: () => true,
      });
      if (resp.status !== 200) {
        const detail = (resp.data as { detail?: { message?: string } })?.detail;
        setReviewError(detail?.message ?? `判定失败 (HTTP ${resp.status})`);
        setReview(null);
        return;
      }
      setReview(resp.data);
      setReviewError(null);
    } catch (e) {
      setReviewError(e instanceof Error ? e.message : '判定失败');
      setReview(null);
    } finally {
      setReviewing(false);
    }
  };

  const code = normalizeCode(stockCode) ?? stockCode;
  const tradeAmount = decimalFormat(
    (txShares * Number(txPrice || 0)).toFixed(2),
  );

  return (
    <div className="flex flex-col gap-3" data-testid="calculator-panel">
      {/* ① 结论条 —— 打开即读 */}
      {(review || reviewError || reviewing) && (
        <section data-testid="review-verdict">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-text-sec inline-flex items-center">
              这笔操作是否合适
            </h3>
            {reviewing && <span className="text-xs text-text-ter">判定中...</span>}
          </div>
          {reviewError ? (
            <div
              className="px-3.5 py-2.5 rounded-lg bg-warn-bg border border-warn/40 text-warn text-xs"
              data-testid="review-error"
            >
              ⚠ {reviewError}
            </div>
          ) : review ? (
            <div className={clsx('transition-opacity', reviewing && 'opacity-60')}>
              <VerdictBar
                review={review}
                action={action}
                shares={txShares}
                price={txPrice}
                code={code}
                name={currentPosition?.stockName}
              />
            </div>
          ) : null}
        </section>
      )}

      {/* ② 预交易输入条 + 成交后摘要行 */}
      <section className="bg-bg-elevated border border-border-def rounded-lg px-3.5 py-3">
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <div className="text-[11px] text-text-ter mb-1.5 inline-flex items-center">
              预交易<TermHint term="pre_trade" />
            </div>
            <div className="flex gap-1.5">
              <ActionButton
                on="buy"
                active={action === 'buy'}
                onClick={() => setAction('buy')}
              >
                买入<TermHint term="action_buy" />
              </ActionButton>
              <ActionButton
                on="sell"
                active={action === 'sell'}
                onClick={() => setAction('sell')}
              >
                卖出<TermHint term="action_sell" />
              </ActionButton>
            </div>
          </div>

          <div>
            <label className="block text-[11px] text-text-ter mb-1.5 inline-flex items-center">
              股数<TermHint term="shares" />
            </label>
            <input
              type="number"
              value={txShares}
              onChange={(e) => {
                const v = Number(e.target.value);
                setTxShares(v >= 1 ? v : 1);
              }}
              min={0}
              step={100}
              className="w-28 px-2.5 py-1.5 border border-border-def rounded-md font-mono bg-bg-surface text-text-pri focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 transition-colors"
            />
          </div>

          <div>
            <label className="block text-[11px] text-text-ter mb-1.5 inline-flex items-center">
              成本价<TermHint term="cost_price" />
            </label>
            <input
              type="text"
              value={txPrice}
              onChange={(e) => setTxPrice(e.target.value)}
              placeholder="11.000"
              className="w-36 px-2.5 py-1.5 border border-border-def rounded-md font-mono bg-bg-surface text-text-pri focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 transition-colors placeholder:text-text-ter/60"
            />
          </div>

          <div className="text-xs text-text-ter pb-2 inline-flex items-center">
            交易额<TermHint term="trade_amount" /> ¥{tradeAmount}
          </div>
        </div>

        {/* 成交后摘要:输入一改就能看到结果,不用往下滚 */}
        {result && (
          <div
            className="mt-2.5 pt-2.5 border-t border-dashed border-border-str flex flex-wrap gap-x-5 gap-y-1 text-xs text-text-sec"
            data-testid="trade-summary"
          >
            <span>
              当前{' '}
              <b className="font-mono text-[13.5px] text-text-pri font-semibold">
                {intFormat(result.before.shares)} 股 @ {priceFormat(result.before.costPrice)}
              </b>
            </span>
            <span>
              成交后股数{' '}
              <b className="font-mono text-[13.5px] text-text-pri font-semibold">
                {intFormat(result.after.shares)}
              </b>
            </span>
            <span>
              新均价{' '}
              <b className="font-mono text-[13.5px] text-text-pri font-semibold">
                {result.after.costPrice ? priceFormat(result.after.costPrice) : '—'}
              </b>
            </span>
            <span>
              持仓资金{' '}
              <b className="font-mono text-[13.5px] text-text-pri font-semibold">
                ¥{decimalFormat(result.after.totalCost)}
              </b>
            </span>
            <span>
              已实现{' '}
              <b
                className={clsx(
                  'font-mono text-[13.5px] font-semibold',
                  Number(result.after.realizedPnlNet) > 0
                    ? 'text-up'
                    : Number(result.after.realizedPnlNet) < 0
                      ? 'text-down'
                      : 'text-text-pri',
                )}
              >
                ¥{decimalFormat(result.after.realizedPnlNet)}
              </b>
            </span>
            <span>
              费用{' '}
              <b className="font-mono text-[13.5px] text-text-pri font-semibold">
                ¥{decimalFormat(result.after.feePaid)}
              </b>
            </span>
          </div>
        )}

        {error && (
          <div className="mt-2.5 p-2 bg-warn-bg text-warn rounded-sm text-xs">
            ⚠ {error}
          </div>
        )}
      </section>

      {/* ③ 双栏:持仓列表 + 做 T 判断 / 判定依据 */}
      <section className="grid grid-cols-1 lg:grid-cols-[296px_1fr] gap-3 items-start">
        <div className="bg-bg-elevated border border-border-def rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border-def text-xs text-text-ter">
            <span>当前持仓</span>
            <span>{positions.length} 只</span>
          </div>
          {positionsLoading ? (
            <p className="text-text-ter text-sm px-3 py-3">加载中...</p>
          ) : positionsError ? (
            <div className="space-y-2 px-3 py-3">
              <p className="text-danger text-sm">⚠ {positionsError}</p>
              <button
                onClick={loadPositions}
                className="text-xs px-3 py-1 rounded-sm bg-bg-subtle hover:bg-bg-subtle border border-border-def"
              >
                重试
              </button>
            </div>
          ) : positions.length === 0 ? (
            <p className="text-text-ter text-sm px-3 py-3">暂无持仓(空仓建仓)</p>
          ) : (
            <ul
              className="max-h-[302px] overflow-y-auto p-1 flex flex-col gap-0.5"
              data-testid="position-list"
            >
              {positions.map((p) => {
                const selected = p.stockCode === normalizeCode(stockCode);
                const floating = p.floatingPnl != null ? Number(p.floatingPnl) : null;
                const floatingCls =
                  floating == null
                    ? 'text-text-ter'
                    : floating > 0
                      ? 'text-up'
                      : floating < 0
                        ? 'text-down'
                        : 'text-text-ter';
                const cur = p.currentPrice != null ? Number(p.currentPrice) : null;
                const prev = p.prevClose != null ? Number(p.prevClose) : null;
                const priceCls =
                  cur != null && prev != null && cur !== prev
                    ? cur > prev
                      ? 'text-up'
                      : 'text-down'
                    : 'text-text-sec';
                return (
                  <li key={p.stockCode}>
                    <button
                      type="button"
                      onClick={() => setStockCode(p.stockCode)}
                      className={clsx(
                        'w-full grid grid-cols-[1fr_auto] gap-x-2 gap-y-0.5 px-2.5 py-2 rounded-md transition-colors border text-left',
                        selected
                          ? 'bg-accent-subtle border-accent/25'
                          : 'border-transparent hover:bg-bg-subtle',
                      )}
                    >
                      <div className="flex items-baseline gap-1.5 min-w-0">
                        <span className="text-[13px] truncate">
                          {p.stockName ?? p.stockCode}
                        </span>
                        <span className="font-mono text-[11px] text-text-ter shrink-0">
                          {p.stockCode}
                        </span>
                      </div>
                      <span className={clsx('font-mono text-[12.5px] text-right', priceCls)}>
                        {p.currentPrice ?? '—'}
                      </span>
                      <span className="text-[11.5px] text-text-sec">
                        {intFormat(p.shares)} 股 · 成本 {p.avgCost}
                      </span>
                      <span
                        className={clsx(
                          'font-mono text-[12.5px] text-right',
                          floatingCls,
                        )}
                      >
                        {floating != null
                          ? `${floating >= 0 ? '+' : ''}¥${floating.toFixed(2)}`
                          : '—'}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="min-w-0">
          {review && (
            <>
              <TAssessmentCard
                review={review}
                action={action}
                shares={txShares}
                price={txPrice}
                code={code}
                name={currentPosition?.stockName}
                cash={cash}
                onCashChange={onCashChange}
                cashSaving={cashSaving}
                cashSaved={cashSaved}
              />
              <WhyPanel review={review} />
            </>
          )}
        </div>
      </section>

      {/* ④ 检查条 */}
      {review && (
        <section data-testid="review-checks">
          <ReviewChecks review={review} />
        </section>
      )}

      {/* ⑤ ±10% 盈亏热力图 */}
      {result && (
        <section>
          <PnlHeatmap grid={result.pnlGrid} currentPricePct={currentPricePct} />
        </section>
      )}
    </div>
  );
}

/**
 * 方向按钮(买入=绿 / 卖出=红,沿用 App 既有行情色口径)
 *
 * 为什么用按钮而不是 radio:分段控件点一下就切换,不用对准小圆点。
 */
function ActionButton({
  on,
  active,
  onClick,
  children,
}: {
  on: 'buy' | 'sell';
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'px-3 py-1.5 rounded-md border text-[13px] transition-colors inline-flex items-center',
        active && on === 'buy'
          ? 'bg-down-bg text-down border-down/30 font-semibold'
          : active && on === 'sell'
            ? 'bg-up-bg text-up border-up/30 font-semibold'
            : 'bg-bg-surface text-text-sec border-border-def hover:border-border-str',
      )}
    >
      {children}
    </button>
  );
}
