'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';

import { apiGet } from '@/lib/api';
import { getAnalysisCache, setAnalysisCache } from '@/lib/analysisCache';
import type { AnalysisResult, Position, Quote, WatchlistItem } from '@/lib/types';

import { AnalysisPanel } from '@/components/advice/AnalysisPanel';
import { CalculatorPanel } from '@/components/calculator/CalculatorPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { CompareChart } from '@/components/charts/CompareChart';
import { KLineChart, type KlinePeriod } from '@/components/charts/KLineChart';
import { HoldingsHealthPanel } from '@/components/holdings-health/HoldingsHealthPanel';
import { IntradayChart } from '@/components/charts/IntradayChart';
import { MarketOverviewPage } from '@/components/market/MarketOverviewPage';
import { NewsFeed } from '@/components/news/NewsFeed';
import { PositionStatsCards } from '@/components/positions/PositionStatsCards';
import { PositionSummaryTable } from '@/components/positions/PositionSummaryTable';
import { SectorBoard } from '@/components/sector/SectorBoard';
import { SettingsPanel } from '@/components/settings/SettingsPanel';
import { Button } from '@/components/ui/Button';
import { GlassCard } from '@/components/ui/GlassCard';
import { LiquidModal } from '@/components/ui/LiquidModal';
import { WatchList, type WatchItem } from '@/components/watch/WatchList';

type TabKey = 'watch' | 'position' | 'market' | 'sector' | 'news' | 'settings';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'watch', label: '自选' },
  { key: 'position', label: '持仓' },
  { key: 'market', label: '大盘' },
  { key: 'sector', label: '板块资金' },
  { key: 'news', label: '快讯' },
  { key: 'settings', label: '设置' },
];

const PERIODS: { key: KlinePeriod; label: string }[] = [
  { key: 'intraday', label: '分时' },
  { key: 'daily', label: '日K' },
  { key: 'weekly', label: '周K' },
  { key: 'monthly', label: '月K' },
  { key: '60min', label: '60分' },
];

/**
 * 四区盯盘工作台(v0.4-roadmap §4.0)
 *
 * 左 aside 盯盘列表 | 中间 K线区(顶 tab 可切板块/快讯) | 右侧上操作提示 + 下 AI 对话。
 * 点击列表行 → 中间 + 右侧联动切换(不跳路由)。
 */
export default function Workbench() {
  const [tab, setTab] = useState<TabKey>('watch');
  const [activeCode, setActiveCode] = useState<string | null>(null);
  const [watchAll, setWatchAll] = useState<WatchItem[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [quotesMap, setQuotesMap] = useState<Record<string, Quote>>({});
  const [period, setPeriod] = useState<KlinePeriod>('daily');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysisStarted, setAnalysisStarted] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [selectedQuote, setSelectedQuote] = useState<Quote | null>(null);
  // 当前选中股票(异步回调防串:分析/缓存返回时比对,避免贴到别的股票面板)
  const activeCodeRef = useRef<string | null>(null);
  const [showCalc, setShowCalc] = useState(false);
  const [showHealth, setShowHealth] = useState(false);
  const [positionView, setPositionView] = useState<'kline' | 'table'>('kline');
  // 自动刷新开关(默认关):开启后 15s 周期 fetchBase;同步到 localStorage
  // 初始一律 false;挂载后 useEffect 读 localStorage 修正 — 避免 SSR/CSR className 不匹配
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  // 倒计时显示(秒):开启时从 15 开始倒数,1s 一刷;关闭时为 0
  const [secondsLeft, setSecondsLeft] = useState<number>(0);
  useEffect(() => {
    setAutoRefresh(localStorage.getItem('auto-refresh-enabled') === '1');
  }, []);
  useEffect(() => {
    if (autoRefresh) localStorage.setItem('auto-refresh-enabled', '1');
    else localStorage.removeItem('auto-refresh-enabled');
  }, [autoRefresh]);
  // ChatPanel 高度(用户拖拽条控制);null = 用 flex 默认;持久化到 localStorage
  const [chatHeight, setChatHeight] = useState<number | null>(null);
  useEffect(() => {
    const v = localStorage.getItem('chat-panel-height');
    if (v) setChatHeight(parseInt(v, 10));
  }, []);
  useEffect(() => {
    if (chatHeight != null) {
      localStorage.setItem('chat-panel-height', String(chatHeight));
    } else {
      localStorage.removeItem('chat-panel-height');
    }
  }, [chatHeight]);

  const fetchBase = useCallback(async () => {
    try {
      const [w, p] = await Promise.all([
        apiGet<{ items: WatchlistItem[] }>('/watchlist'),
        apiGet<{ items: Position[] }>('/positions'),
      ]);
      setPositions(p.items);
      const posName = new Map(p.items.map((x) => [x.stockCode, x.stockName]));
      // 自选 = 自选表 ∪ 持仓(持仓未加自选的自动并入,避免漏看)
      const merged = new Map<string, WatchItem>();
      for (const it of w.items) {
        merged.set(it.stockCode, {
          code: it.stockCode,
          name: it.stockName ?? posName.get(it.stockCode) ?? null,
          inPosition: posName.has(it.stockCode),
          quote: null,
        });
      }
      for (const pos of p.items) {
        if (!merged.has(pos.stockCode)) {
          merged.set(pos.stockCode, {
            code: pos.stockCode,
            name: pos.stockName,
            inPosition: true,
            quote: null,
          });
        }
      }
      setWatchAll(Array.from(merged.values()));
      const codes = Array.from(merged.keys());
      if (codes.length > 0) {
        apiGet<Quote[]>(`/quotes?codes=${codes.join(',')}`)
          .then((qs) => {
            const map = Object.fromEntries(qs.map((q) => [q.code, q]));
            setQuotesMap(map);
            setWatchAll((prev) =>
              prev.map((it) => ({ ...it, quote: map[it.code] ?? null })),
            );
          })
          .catch(() => {});
      }
    } catch {
      /* toast 已由拦截器处理 */
    }
  }, []);

  useEffect(() => {
    fetchBase();
  }, [fetchBase]);

  useEffect(() => {
    if (!autoRefresh) {
      setSecondsLeft(0);
      return;
    }
    fetchBase();
    setSecondsLeft(15);
    const refresh = setInterval(() => {
      fetchBase().finally(() => setSecondsLeft(15));
    }, 15000);
    const tick = setInterval(
      () => setSecondsLeft((s) => Math.max(0, s - 1)),
      1000,
    );
    return () => {
      clearInterval(refresh);
      clearInterval(tick);
    };
  }, [autoRefresh, fetchBase]);

  const selectStock = useCallback((code: string) => {
    setActiveCode(code);
    activeCodeRef.current = code;
    setAnalysis(null);
    setAnalysisStarted(false);
    setSelectedQuote(null);
    apiGet<Quote>(`/quotes/${encodeURIComponent(code)}`)
      .then(setSelectedQuote)
      .catch(() => {});
    // 恢复 IndexedDB 缓存(24h 内分析过的不再重新烧 token)
    getAnalysisCache(code).then((cached) => {
      if (activeCodeRef.current !== code) return;
      setAnalysis(cached);
      setAnalysisStarted(cached != null);
    });
  }, []);

  const refreshAnalysis = useCallback(() => {
    const code = activeCode;
    if (!code) return;
    setAnalysisStarted(true);
    setAnalysisLoading(true);
    apiGet<AnalysisResult>(`/stock/${encodeURIComponent(code)}/analysis`, {
      timeout: 60000,
    })
      .then((r) => {
        setAnalysisCache(code, r);
        if (activeCodeRef.current === code) setAnalysis(r);
      })
      .catch(() => {
        if (activeCodeRef.current === code) setAnalysis(null);
      })
      .finally(() => setAnalysisLoading(false));
  }, [activeCode]);

  const visibleItems = useMemo(() => {
    if (tab === 'position') {
      return positions.map((p) => ({
        code: p.stockCode,
        name: p.stockName,
        inPosition: true,
        quote: quotesMap[p.stockCode] ?? null,
      }));
    }
    return watchAll;
  }, [tab, positions, watchAll, quotesMap]);

  const pctClass = (v: number | undefined) =>
    v == null ? 'text-text-ter' : v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-text-ter';

  const activePosition = positions.find((p) => p.stockCode === activeCode) ?? null;

  const positionPnl = useMemo(() => {
    if (!activePosition) return null;
    const floatingPnl =
      activePosition.floatingPnl != null ? Number(activePosition.floatingPnl) : null;
    const totalCost = Number(activePosition.totalCost);
    return {
      todayPnl: activePosition.todayPnl != null ? Number(activePosition.todayPnl) : null,
      floatingPnl,
      ratioPct:
        totalCost > 0 && floatingPnl != null ? (floatingPnl / totalCost) * 100 : null,
    };
  }, [activePosition]);

  return (
    <main className="h-screen flex flex-col bg-bg-base text-text-pri p-5 gap-4 overflow-hidden">
      {/* 顶部 tab */}
      <header className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-bold mr-3">买股工具室</h1>
          <nav className="flex items-center gap-1 rounded-2xl bg-white/5 p-1">
            {TABS.map((t) => {
              const isActive = tab === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={clsx(
                    'relative px-4 py-1.5 text-sm rounded-xl transition-colors',
                    isActive ? 'text-text-pri' : 'text-text-sec hover:text-text-pri',
                  )}
                >
                  {isActive && (
                    <motion.span
                      layoutId="tab-pill"
                      className="liquid-glass absolute inset-0 rounded-xl bg-accent-subtle border border-accent/25"
                      transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                    />
                  )}
                  <span className="relative">{t.label}</span>
                </button>
              );
            })}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setAutoRefresh((v) => !v)}
            title={autoRefresh ? '点击关闭自动刷新' : '点击开启自动刷新(15s 一次)'}
            className={clsx(
              'flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium border transition-colors',
              autoRefresh
                ? 'border-up/40 bg-up-bg text-up'
                : 'border-white/10 bg-white/5 text-text-sec hover:bg-white/10',
            )}
          >
            <span
              className={clsx(
                'w-2 h-2 rounded-full',
                autoRefresh ? 'bg-up animate-pulse' : 'bg-text-ter/50',
              )}
            />
            自动刷新{' '}
            {autoRefresh ? (secondsLeft > 0 ? `${secondsLeft}s` : '刷新中…') : 'OFF'}
          </button>
          <span className="text-xs text-text-ter">数据源:新浪 · AI 本地配置</span>
        </div>
      </header>

      {/* 三区主体 */}
      <div className="flex flex-1 gap-4 min-h-0">
        {/* 左 aside:大盘 / 设置 Tab 时收起,中间区占满宽度 */}
        {tab !== 'market' && tab !== 'settings' && (
          <aside className="w-72 shrink-0 min-h-0">
            <WatchList
              items={visibleItems}
              activeCode={activeCode}
              onSelect={selectStock}
              onChanged={fetchBase}
            />
          </aside>
        )}

        {/* 中间 K线区 */}
        <section className="flex-1 min-w-0 min-h-0 flex flex-col gap-3">
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              initial={{ opacity: 0, x: 24, filter: 'blur(6px)' }}
              animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, x: -24, filter: 'blur(6px)' }}
              transition={{ duration: 0.26, ease: 'easeOut' }}
              className="flex-1 min-h-0 flex flex-col gap-3"
            >
              {tab === 'sector' ? (
                <SectorBoard />
              ) : tab === 'news' ? (
                <NewsFeed />
              ) : tab === 'market' ? (
                <MarketOverviewPage />
              ) : tab === 'settings' ? (
                <SettingsPanel />
              ) : (
                <>
                  {tab === 'position' && positionView === 'table' ? (
                    <PositionStatsCards positions={positions} />
                  ) : activeCode ? (
                    <GlassCard padding="sm" className="flex items-center justify-between shrink-0 min-h-[80px]">
                      <div className="min-w-0">
                        <div className="flex items-center gap-3 min-w-0">
                          <span className="font-semibold text-text-pri truncate">
                            {selectedQuote?.name ?? activeCode}
                          </span>
                          <span className="text-xs text-text-ter font-mono">{activeCode}</span>
                          {activePosition && (
                            <span className="text-[10px] px-1.5 py-px rounded bg-accent-subtle text-accent border border-accent/25">
                              已持仓
                            </span>
                          )}
                        </div>
                        {positionPnl && (
                          <div className="flex items-center gap-3 mt-0.5 text-xs font-mono">
                            <span className={pctClass(positionPnl.todayPnl ?? undefined)}>
                              {positionPnl.todayPnl != null
                                ? `今日 ${positionPnl.todayPnl >= 0 ? '+' : ''}¥${positionPnl.todayPnl.toFixed(2)}`
                                : '今日 --'}
                            </span>
                            <span
                              className={pctClass(positionPnl.floatingPnl ?? undefined)}
                            >
                              {positionPnl.floatingPnl != null
                                ? `浮盈 ${positionPnl.floatingPnl >= 0 ? '+' : ''}¥${positionPnl.floatingPnl.toFixed(2)} (${
                                    positionPnl.ratioPct != null
                                      ? `${positionPnl.ratioPct >= 0 ? '+' : ''}${positionPnl.ratioPct.toFixed(2)}%`
                                      : '--'
                                  })`
                                : '浮盈 --'}
                            </span>
                          </div>
                        )}
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-xl font-mono font-semibold text-text-pri">
                          {selectedQuote
                            ? Number(selectedQuote.currentPrice) === 0
                              ? '停牌'
                              : selectedQuote.currentPrice
                            : '--'}
                        </div>
                        <div className={`text-sm font-mono ${pctClass(selectedQuote?.changePct)}`}>
                          {selectedQuote
                            ? Number(selectedQuote.currentPrice) === 0
                              ? '停牌'
                              : `${selectedQuote.changePct > 0 ? '+' : ''}${selectedQuote.changePct.toFixed(2)}%`
                            : '行情加载中'}
                        </div>
                        <div className="flex justify-end gap-2 mt-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setShowCalc(true)}
                          >
                            🧮 成本计算器
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setShowHealth(true)}
                          >
                            🩺 持仓分析
                          </Button>
                        </div>
                      </div>
                    </GlassCard>
                  ) : (
                    <GlassCard padding="lg" className="shrink-0 text-center">
                      <p className="text-text-ter text-sm">← 从左侧选择一只自选 / 持仓股票</p>
                    </GlassCard>
                  )}

                  <div className="flex items-center justify-between gap-2 shrink-0">
                    {/* 左侧:持仓 tab 视图切换 */}
                    {tab === 'position' && (
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => setPositionView('kline')}
                          className={clsx(
                            'px-3 py-1.5 text-sm rounded-xl transition-colors ',
                            positionView === 'kline'
                              ? 'bg-accent-subtle text-accent border border-accent/25 liquid-glass'
                              : 'bg-white/5 text-text-sec hover:text-text-pri border border-white/5',
                          )}
                        >
                          📈 K 线
                        </button>
                        <button
                          onClick={() => setPositionView('table')}
                          className={clsx(
                            'px-3 py-1.5 text-sm rounded-xl transition-colors ',
                            positionView === 'table'
                              ? 'bg-accent-subtle text-accent border border-accent/25 liquid-glass'
                              : 'bg-white/5 text-text-sec hover:text-text-pri border border-white/5',
                          )}
                        >
                          📋 持仓表
                        </button>
                      </div>
                    )}
                    {/* 右侧:周期切换(持仓表视图下隐藏,切回 K 线再显示) */}
                    {!(tab === 'position' && positionView === 'table') && (
                      <div className="flex items-center gap-1.5">
                        {PERIODS.map((p) => (
                          <button
                            key={p.key}
                            onClick={() => setPeriod(p.key)}
                            className={clsx(
                              'px-3 py-1.5 text-sm rounded-xl transition-colors',
                              period === p.key
                                ? 'bg-accent-subtle text-accent border border-accent/25 liquid-glass'
                                : 'bg-white/5 text-text-sec hover:text-text-pri border border-white/5',
                            )}
                          >
                            {p.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {tab === 'position' && positionView === 'table' ? (
                    <PositionSummaryTable positions={positions} onSelect={selectStock} />
                  ) : activeCode ? (
                    <div className="flex-1 min-h-0 overflow-y-auto">
                      {period === 'intraday' ? (
                        <IntradayChart stockCode={activeCode} height={420} />
                      ) : (
                        <>
                          {period === 'daily' && (
                            <div className="mb-2">
                              <CompareChart stockCode={activeCode} />
                            </div>
                          )}
                          <KLineChart stockCode={activeCode} period={period} showVolume height={420} />
                        </>
                      )}
                    </div>
                  ) : (
                    <div className="flex-1 min-h-0 liquid-glass rounded-2xl flex items-center justify-center">
                      <p className="text-text-ter text-sm">选择股票后显示 K 线图</p>
                    </div>
                  )}
                </>
              )}
            </motion.div>
          </AnimatePresence>
        </section>

        {/* 右侧:上操作提示 / 下 AI 对话 — 大盘 / 设置 Tab 时收起 */}
        {tab !== 'market' && tab !== 'settings' && (
          <aside className="w-[22rem] shrink-0 flex flex-col gap-3 min-h-0">
            <div className="flex-1 min-h-0 overflow-y-auto pr-1">
              <AnalysisPanel
                analysis={analysis}
                started={analysisStarted}
                loading={analysisLoading}
                onRefresh={refreshAnalysis}
              />
            </div>
            <div className="flex-none min-h-0">
              <ChatPanel
                stockCode={activeCode}
                stockName={selectedQuote?.name ?? null}
                avgCost={activePosition ? Number(activePosition.avgCost) : null}
                currentPrice={selectedQuote ? Number(selectedQuote.currentPrice) : null}
                changePct={selectedQuote?.changePct != null ? Number(selectedQuote.changePct) : null}
                height={chatHeight}
                onHeightChange={setChatHeight}
              />
            </div>
          </aside>
        )}
      </div>

      <LiquidModal
        open={showCalc}
        onClose={() => setShowCalc(false)}
        title="🧮 成本计算器"
        size="xl"
      >
        <CalculatorPanel initialCode={activeCode} />
      </LiquidModal>

      <LiquidModal
        open={showHealth}
        onClose={() => setShowHealth(false)}
        title="🩺 持仓分析"
        size="xl"
      >
        <HoldingsHealthPanel />
      </LiquidModal>
    </main>
  );
}
