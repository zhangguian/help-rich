'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';

import { apiGet, snakeToCamel } from '@/lib/api';
import { consumeAnalysisStream } from '@/lib/analysisStream';
import { pctClass, chipColor } from '@/lib/format';
import type {
  AmountTrendResponse,
  AnalysisResult,
  MarketIndex,
  MarketMover,
  MarketOverview,
  MarketSentiment,
  Position,
  Quote,
  WatchlistItem,
} from '@/lib/types';

import { AnalysisPanel } from '@/components/advice/AnalysisPanel';
import { CalculatorPanel } from '@/components/calculator/CalculatorPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { CompareChart } from '@/components/charts/CompareChart';
import { KLineChart, type KlinePeriod } from '@/components/charts/KLineChart';
import { BreadthBar } from '@/components/desk/BreadthBar';
import { DecisionColumn } from '@/components/desk/DecisionColumn';
import { DeskTopBar } from '@/components/desk/DeskTopBar';
import { KeyLevels } from '@/components/desk/KeyLevels';
import { HoldingsHealthPanel } from '@/components/holdings-health/HoldingsHealthPanel';
import { IntradayChart } from '@/components/charts/IntradayChart';
import { MarketOverviewPage } from '@/components/market/MarketOverviewPage';
import { NewsFeed } from '@/components/news/NewsFeed';
import { PositionStatsCards } from '@/components/positions/PositionStatsCards';
import { PositionSummaryTable } from '@/components/positions/PositionSummaryTable';
import { StockFlowTab } from '@/components/positions/StockFlowTab';
import { ScreenerPanel } from '@/components/screener/ScreenerPanel';
import { WatchlistPanel } from '@/components/screener/WatchlistPanel';
import { ReflectionCard } from '@/components/reflection/ReflectionCard';
import { SectorBoard } from '@/components/sector/SectorBoard';
import { SettingsPanel } from '@/components/settings/SettingsPanel';
import { Button } from '@/components/ui/Button';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { GlassCard } from '@/components/ui/GlassCard';
import { LiquidModal } from '@/components/ui/LiquidModal';
import { WatchList, type WatchItem } from '@/components/watch/WatchList';
import type { HoldingsHealth } from '@/lib/types';

/**
 * 首页筛选器(自选 / 关注)
 *
 * 此前此处是 9 个 tab,其中 6 个(大盘/板块/快讯/选股/观察池/设置)已由
 * 持久 NavRail 提升为独立路由,故不再需要本地 tab 切换;持仓明细见 /positions。
 */
type TabKey = 'watch' | 'favorite';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'watch', label: '自选' },
  { key: 'favorite', label: '⭐ 关注' },
];

const PERIODS: { value: KlinePeriod; label: string }[] = [
  { value: 'intraday', label: '分时' },
  { value: 'daily', label: '日K' },
  { value: 'weekly', label: '周K' },
  { value: 'monthly', label: '月K' },
  { value: '60min', label: '60分' },
];

/**
 * 上次选中的股票 —— 刷新后恢复盯盘上下文
 *
 * v0.8 的核心命题是「用满屏工作台消灭虚空」,而首屏若没有选中标的,
 * 中栏就是一大块「选择股票后显示 K 线图」的空态 —— 正是 v0.7 被否掉的形态。
 * 所以刷新后必须回到上次盯的那只票。
 */
const LAST_SELECTED_KEY = 'rich-last-selected';

/** 自选列表排序偏好(与 WatchList 组件共用同一 key,决定「列表首行」是谁) */
const WATCHLIST_SORT_KEY = 'watchlist-sort';

type WatchSortDir = 'default' | 'desc' | 'asc';

function readLastSelected(): string | null {
  try {
    return localStorage.getItem(LAST_SELECTED_KEY);
  } catch {
    return null;
  }
}

function readWatchlistSort(): WatchSortDir {
  try {
    const v = localStorage.getItem(WATCHLIST_SORT_KEY);
    return v === 'desc' || v === 'asc' ? v : 'default';
  } catch {
    return 'default';
  }
}

/**
 * 列表首行 —— 排序规则必须与 WatchList 完全一致,
 * 否则「自动选中的票」和「用户看到的第一个票」会对不上。
 */
function pickFirstVisible(items: WatchItem[], sortDir: WatchSortDir): WatchItem | null {
  if (items.length === 0) return null;
  if (sortDir === 'default') return items[0] ?? null;
  const arr = [...items].sort((a, b) => {
    const ac = a.quote?.changePct ?? null;
    const bc = b.quote?.changePct ?? null;
    if (ac == null && bc == null) return 0;
    if (ac == null) return 1;
    if (bc == null) return -1;
    return sortDir === 'desc' ? bc - ac : ac - bc;
  });
  return arr[0] ?? null;
}

/** 顶栏 / 宽度条 / 决策栏共用的大盘速览数据 */
interface MarketHeader {
  indexes: MarketIndex[];
  /** 领涨(右栏「领涨 / 领跌」区块用) */
  gainers: MarketMover[];
  /** 领跌 */
  losers: MarketMover[];
  upTotal: number | null;
  downTotal: number | null;
  flatTotal: number | null;
  amountYi: number | null;
  buckets: MarketSentiment['buckets'] | null;
  /** 样本量(全市场约 5500+ 只) */
  sampleSize: number | null;
  /** true = 仅首页采样,数据不可作决策依据 */
  partial: boolean;
}

/** 成交额(亿元)格式化:保留 1 位小数 + 千分位 */
function decimal(v: number): string {
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
}
/**
 * 盯盘台(v0.8 Trading Desk)
 *
 * 满屏三栏工作台:**顶栏(指数 ticker) → 市场宽度条 → 行情列表 / 图表舞台 / 决策栏**。
 *
 * 为什么推翻旧版:旧首页是「卡片墙 + 上下堆叠」,页面高 3194px,
 * 选股票在页面最底部而 K 线在中部 —— 选完要滚 2000px 才看到图(动作链断裂),
 * 且首屏被总市值大卡占据(盯盘时第一眼要的是「看哪只票」)。
 *
 * v0.7 曾做过深色投研终端却因「下半屏纯黑虚空」被否 —— 失败原因是**布局**不是配色。
 * v0.8 用满屏工作台消灭虚空:每一栏都有明确职责,内容铺满视口。
 *
 * 数据流(轮询 / SSE / LLM 流)与旧版完全一致,本次只重排视图层。
 */
export default function Workbench() {
  const [tab, setTab] = useState<TabKey>('watch');
  const router = useRouter();
  const [activeCode, setActiveCode] = useState<string | null>(null);
  const [watchAll, setWatchAll] = useState<WatchItem[]>([]);
  // 自选/持仓是否已拉完 —— 用来区分「还在加载」和「确实一张自选都没有」,
  // 否则首屏加载的那一瞬会误报「自选列表为空」
  const [baseLoaded, setBaseLoaded] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);
  const [quotesMap, setQuotesMap] = useState<Record<string, Quote>>({});
  const [period, setPeriod] = useState<KlinePeriod>('daily');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysisStarted, setAnalysisStarted] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  // 流式进度:LLM 启动 30s 后开始推,这里存最新的 elapsed_s(供 AnalysisPanel 显示「思考中…Ns」)
  const [analysisProgress, setAnalysisProgress] = useState<number | null>(null);
  const [selectedQuote, setSelectedQuote] = useState<Quote | null>(null);
  // 当前选中股票(异步回调防串:分析/缓存返回时比对,避免贴到别的股票面板)
  const activeCodeRef = useRef<string | null>(null);
  const [showCalc, setShowCalc] = useState(false);
  const [showHealth, setShowHealth] = useState(false);
  const [positionView, setPositionView] = useState<'kline' | 'flow' | 'table'>('kline');
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
  // ChatPanel 高度(用户拖拽条控制);null = 用组件默认;持久化到 localStorage
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

  // 欢迎横幅(挂载后计算,避免 SSR/CSR 时间不一致)
  const [greeting, setGreeting] = useState<string>('--');
  const [dateStr, setDateStr] = useState<string>('');
  useEffect(() => {
    const now = new Date();
    const h = now.getHours();
    setGreeting(h < 5 ? '夜深了' : h < 9 ? '早上好' : h < 12 ? '上午好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好');
    setDateStr(
      now.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }),
    );
  }, []);

  // 大盘速览(欢迎区右侧胶囊):三大指数 + 涨跌家数 + 两市成交额 + 量能趋势
  const [marketHeader, setMarketHeader] = useState<MarketHeader | null>(null);
  const [amountTrend, setAmountTrend] = useState<AmountTrendResponse['items']>([]);
  const fetchMarketHeader = useCallback(async () => {
    // 指数与情绪**分开**加载:
    //   /market/overview 约 1s,/market/sentiment 首次约 5s(全市场 56 页分页)。
    //   用 Promise.all 会让整个大盘速览卡一起等 5 秒;拆开后指数先出,
    //   情绪卡稍后补齐(情绪卡自身有骨架占位)。
    const [ov, st] = await Promise.all([
      apiGet<MarketOverview>('/market/overview').catch(() => null),
      apiGet<MarketSentiment>('/market/sentiment').catch(() => null),
    ]);
    setMarketHeader((prev) => ({
      indexes: ov?.indexes.filter((x): x is MarketIndex => x != null) ?? prev?.indexes ?? [],
      gainers: ov?.gainers ?? prev?.gainers ?? [],
      losers: ov?.losers ?? prev?.losers ?? [],
      upTotal: st?.upTotal ?? prev?.upTotal ?? null,
      downTotal: st?.downTotal ?? prev?.downTotal ?? null,
      flatTotal: st?.flatTotal ?? prev?.flatTotal ?? null,
      amountYi: st?.amountYi ?? prev?.amountYi ?? null,
      buckets: st?.buckets ?? prev?.buckets ?? null,
      sampleSize: st?.sampleSize ?? prev?.sampleSize ?? null,
      partial: st?.partial ?? prev?.partial ?? false,
    }));
    apiGet<AmountTrendResponse>('/market/amount-trend?days=5')
      .then((r) => setAmountTrend(r.items ?? []))
      .catch(() => {});
  }, []);

  const fetchBase = useCallback(async () => {
    try {
      const [w, p, hh] = await Promise.all([
        apiGet<{ items: WatchlistItem[] }>('/watchlist'),
        apiGet<{ items: Position[] }>('/positions'),
        apiGet<HoldingsHealth>('/holdings-health').catch(() => null),
      ]);
      setPositions(p.items);
      const posName = new Map(p.items.map((x) => [x.stockCode, x.stockName]));
      // 持仓行轻提示 flag(M3.2 roadpmap):loss=红 / high_concentration=黄 / profit/flat=绿
      const healthFlag = new Map<string, WatchItem['healthFlag']>();
      for (const it of hh?.items ?? []) {
        if (it.status === 'loss') healthFlag.set(it.stockCode, 'loss');
        else if (it.status === 'high_concentration') healthFlag.set(it.stockCode, 'concentration');
        else if (it.status === 'profit') healthFlag.set(it.stockCode, 'profit');
      }
      // 自选 = 自选表 ∪ 持仓(持仓未加自选的自动并入,避免漏看)
      const merged = new Map<string, WatchItem>();
      for (const it of w.items) {
        merged.set(it.stockCode, {
          code: it.stockCode,
          name: it.stockName ?? posName.get(it.stockCode) ?? null,
          inPosition: posName.has(it.stockCode),
          quote: null,
          isFavorite: it.isFavorite,
          healthFlag: healthFlag.get(it.stockCode) ?? null,
        });
      }
      for (const pos of p.items) {
        if (!merged.has(pos.stockCode)) {
          merged.set(pos.stockCode, {
            code: pos.stockCode,
            name: pos.stockName,
            inPosition: true,
            quote: null,
            isFavorite: false,
            healthFlag: healthFlag.get(pos.stockCode) ?? null,
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
    } finally {
      setBaseLoaded(true);
    }
  }, []);

  useEffect(() => {
    fetchBase();
    fetchMarketHeader();
  }, [fetchBase, fetchMarketHeader]);

  useEffect(() => {
    if (!autoRefresh) {
      setSecondsLeft(0);
      return;
    }
    fetchBase();
    fetchMarketHeader();
    setSecondsLeft(15);
    const refresh = setInterval(() => {
      fetchBase().finally(() => {
        fetchMarketHeader();
        setSecondsLeft(15);
      });
    }, 15000);
    const tick = setInterval(
      () => setSecondsLeft((s) => Math.max(0, s - 1)),
      1000,
    );
    return () => {
      clearInterval(refresh);
      clearInterval(tick);
    };
  }, [autoRefresh, fetchBase, fetchMarketHeader]);

  const selectStock = useCallback((code: string) => {
    setActiveCode(code);
    activeCodeRef.current = code;
    setAnalysis(null);
    setAnalysisStarted(false);
    setSelectedQuote(null);
    // 记住这次盯的票,刷新后直接回到它(见上方 LAST_SELECTED_KEY 注释)
    try {
      localStorage.setItem(LAST_SELECTED_KEY, code);
    } catch {
      /* 隐私模式下 localStorage 不可写,忽略即可 */
    }
    apiGet<Quote>(`/quotes/${encodeURIComponent(code)}`)
      .then(setSelectedQuote)
      .catch(() => {});
    // 无存档回显:分析面板显示空态,由用户手动点「开始分析」(每次实时拉 K + 实时 LLM)
  }, []);

  /** 流式:用户手动点「开始分析/重新分析」 — 每次实时拉 K + 实时 LLM,无节点缓存 */
  const refreshAnalysis = useCallback(() => {
    const code = activeCode;
    if (!code) return;
    setAnalysisStarted(true);
    setAnalysisLoading(true);
    setAnalysisProgress(null);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 305000);
    const url = `${process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api'}/stock/${encodeURIComponent(code)}/analysis/stream`;
    consumeAnalysisStream(url, {
      signal: controller.signal,
      onEvent: (evt) => {
        if (activeCodeRef.current !== code) return;
        if (evt.event === 'indicators') {
          // 先用已有 analysis,只更新 indicators(避免 ai 闪烁)
          setAnalysis((prev) => ({
            ...(prev ?? ({} as AnalysisResult)),
            stockCode: code,
            latestKlineDate: evt.latest_kline_date ?? prev?.latestKlineDate ?? null,
            indicators: snakeToCamel(evt.data) as AnalysisResult['indicators'],
          } as AnalysisResult));
        } else if (evt.event === 'ai_started') {
          setAnalysisProgress(0);
        } else if (evt.event === 'ai_progress') {
          setAnalysisProgress(evt.elapsed_s);
        } else if (evt.event === 'ai_complete') {
          setAnalysis((prev) =>
            prev
              ? {
                  ...prev,
                  ai: snakeToCamel(evt.ai) as AnalysisResult['ai'],
                  aiSource: 'live',
                  aiError: null,
                  latestKlineDate: evt.latest_kline_date ?? prev.latestKlineDate ?? null,
                }
              : prev,
          );
        } else if (evt.event === 'ai_error') {
          setAnalysis((prev) => {
            if (!prev) return prev;
            const code = evt.code as 'unconfigured' | 'timeout' | 'failed';
            return { ...prev, aiError: code, aiSource: null };
          });
        } else if (evt.event === 'done') {
          // 流结束,分析结果由后端 ai_source=="live" 时落库,前端无需缓存
          setAnalysis((prev) => prev);
        }
      },
    })
      .catch(() => {
        if (activeCodeRef.current === code) setAnalysis(null);
      })
      .finally(() => {
        clearTimeout(timer);
        if (activeCodeRef.current === code) {
          setAnalysisLoading(false);
          setAnalysisProgress(null);
        }
      });
  }, [activeCode]);

  /** 重新分析:每次实时拉 K + 实时 LLM,与 refreshAnalysis 同语义 */
  const forceRefreshAnalysis = useCallback(() => {
    if (!activeCode) return;
    refreshAnalysis();
  }, [activeCode, refreshAnalysis]);

  const visibleItems = useMemo(() => {
    if (tab === 'favorite') {
      return watchAll.filter((it) => it.isFavorite);
    }
    return watchAll;
  }, [tab, watchAll]);

  /**
   * 恢复盯盘上下文(刷新后回到上次盯的票,没有历史就选列表首行)
   *
   * 只做一次 —— 用 ref 兜住,避免自动刷新重新拉数据时把用户的选股改掉。
   * 按涨跌幅排序时必须等报价到位,否则「首行」算错。
   */
  const restoredRef = useRef(false);
  useEffect(() => {
    if (restoredRef.current) return;
    if (activeCode) return; // 用户已经手动选过了
    if (watchAll.length === 0) return; // 自选还没加载完(或确实为空)

    const sortDir = readWatchlistSort();
    // 按涨跌幅排序时,报价是批量一次回来的 —— 报价没到位就算不出「首行」
    if (sortDir !== 'default' && !visibleItems.some((it) => it.quote != null)) return;

    restoredRef.current = true;

    // 1) 优先恢复上次盯的票(仍需在自选里,被删了就不恢复)
    const last = readLastSelected();
    if (last && watchAll.some((it) => it.code === last)) {
      selectStock(last);
      return;
    }
    // 2) 没有历史 → 选用户此刻看到的首行
    const first = pickFirstVisible(visibleItems, sortDir);
    if (first) selectStock(first.code);
  }, [activeCode, watchAll, visibleItems, selectStock]);

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
    <div className="h-full flex flex-col overflow-hidden">
      {/* ============ 顶栏:视角切换 + 指数 ticker + 自动刷新 + 主题 ============ */}
      <DeskTopBar
        tab={tab}
        onTabChange={setTab}
        indexes={marketHeader?.indexes ?? []}
        autoRefresh={autoRefresh}
        secondsLeft={secondsLeft}
        onToggleRefresh={() => setAutoRefresh((v) => !v)}
        dateStr={dateStr}
      />

      {/* ============ 市场宽度条(签名元素)============ */}
      <BreadthBar
        stats={
          marketHeader
            ? {
                upTotal: marketHeader.upTotal,
                downTotal: marketHeader.downTotal,
                flatTotal: marketHeader.flatTotal,
                amountYi: marketHeader.amountYi,
                buckets: marketHeader.buckets,
                sampleSize: marketHeader.sampleSize,
                partial: marketHeader.partial,
              }
            : null
        }
      />

      {/* ============ 三栏工作台 ============ */}
      <div className="flex-1 min-h-0 overflow-y-auto lg:overflow-hidden">
        {/*
          三栏在 ≥1024px 一直保持,**只有窄于 1024px 才纵向堆叠**。
          (试过 1024~1280px 把决策栏放到第二行:决策栏内容是 auto 行,
          一旦内容比视口高,auto 行会吃光空间、把 1fr 行压成 0 高度,
          列表和图表直接消失 —— 所以宁可收窄右栏也不换行。)
        */}
        <div className="lg:h-full lg:grid lg:grid-cols-[236px_minmax(0,1fr)_268px] lg:grid-rows-1 xl:grid-cols-[252px_minmax(0,1fr)_304px]">
          {/* ---------- 左:行情列表 ---------- */}
          <aside className="h-[38vh] lg:h-full min-h-0 overflow-hidden">
            <WatchList
              variant="rail"
              items={visibleItems}
              activeCode={activeCode}
              favoriteOnly={tab === 'favorite'}
              onSelect={selectStock}
              onChanged={fetchBase}
            />
          </aside>

          {/* ---------- 中:图表舞台(K 线是绝对主角)---------- */}
          <section className="min-w-0 lg:h-full lg:min-h-0 lg:overflow-y-auto flex flex-col bg-bg-base">
            {/* 标的 header */}
            {activeCode ? (
              <div className="shrink-0 bg-bg-surface border-b border-border-def px-3 py-2 flex items-center gap-x-4 gap-y-1.5 flex-wrap">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={clsx(
                      'w-7 h-7 rounded-md bg-gradient-to-br text-white text-xs font-bold flex items-center justify-center shrink-0',
                      chipColor(activeCode),
                    )}
                  >
                    {(selectedQuote?.name ?? activeCode).slice(0, 1)}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 min-w-0 flex-wrap">
                      <span className="font-semibold text-text-pri text-[15px] truncate">
                        {selectedQuote?.name ?? activeCode}
                      </span>
                      <span className="text-[10.5px] text-text-ter font-mono">{activeCode}</span>
                      {activePosition && (
                        <span className="text-[10px] px-1.5 py-px rounded-sm bg-accent-subtle text-accent border border-accent/25 font-medium">
                          持仓
                        </span>
                      )}
                    </div>
                    {positionPnl && (
                      <div className="flex items-center gap-3 mt-0.5 text-[11px] font-mono flex-wrap">
                        <span className={pctClass(positionPnl.todayPnl)}>
                          {positionPnl.todayPnl != null
                            ? `今日 ${positionPnl.todayPnl >= 0 ? '+' : ''}¥${positionPnl.todayPnl.toFixed(2)}`
                            : '今日 --'}
                        </span>
                        <span className={pctClass(positionPnl.floatingPnl)}>
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
                </div>

                {/* 现价 */}
                <div className="flex items-baseline gap-2">
                  <span className="text-[24px] font-mono font-semibold tabular-nums text-text-pri leading-none">
                    {selectedQuote
                      ? Number(selectedQuote.currentPrice) === 0
                        ? '停牌'
                        : selectedQuote.currentPrice
                      : '--'}
                  </span>
                  <span className={clsx('text-[13px] font-mono tabular-nums', pctClass(selectedQuote?.changePct))}>
                    {selectedQuote
                      ? Number(selectedQuote.currentPrice) === 0
                        ? '停牌'
                        : `${selectedQuote.changePct > 0 ? '+' : ''}${selectedQuote.changePct.toFixed(2)}%`
                      : '行情加载中'}
                  </span>
                </div>

                {/* 当日关键读数 */}
                <div className="flex items-center gap-3.5 text-[10.5px] font-mono ml-auto">
                  <Meta label="最高" value={selectedQuote?.high} />
                  <Meta label="最低" value={selectedQuote?.low} />
                  <Meta label="昨收" value={selectedQuote?.prevClose} />
                  <Meta
                    label="成交额"
                    value={
                      selectedQuote?.amount != null
                        ? `${(Number(selectedQuote.amount) / 1e8).toFixed(2)} 亿`
                        : null
                    }
                  />
                </div>
              </div>
            ) : (
              <div className="shrink-0 bg-bg-surface border-b border-border-def px-3 py-2.5 flex items-center gap-3 flex-wrap">
                <span className="text-[13px] text-text-sec">
                  {!baseLoaded
                    ? '正在加载自选与持仓…'
                    : watchAll.length === 0
                      ? '自选列表为空,先添加关注的股票再开始盯盘'
                      : `${greeting},从左侧列表选一只股票开始盯盘`}
                </span>
                <span className="text-[10.5px] text-text-ter font-mono ml-auto">
                  自选 {watchAll.length} · 持仓 {positions.length} · 关注{' '}
                  {watchAll.filter((it) => it.isFavorite).length}
                </span>
              </div>
            )}

            {/* 周期切换 + 操作 */}
            <div className="shrink-0 bg-bg-surface border-b border-border-def px-3 h-9 flex items-center gap-2 overflow-x-auto">
              <SegmentedControl
                options={PERIODS}
                value={period}
                onChange={setPeriod}
                size="md"
              />
              <div className="flex items-center gap-1.5 ml-auto shrink-0">
                <Button size="sm" variant="secondary" onClick={() => setShowCalc(true)} title="成本计算器">
                  🧮 <span className="hidden xl:inline">计算器</span>
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setShowHealth(true)} title="持仓体检">
                  🩺 <span className="hidden xl:inline">体检</span>
                </Button>
                <Link
                  href={
                    activeCode
                      ? `/replay-history?code=${encodeURIComponent(activeCode)}`
                      : '/replay-history'
                  }
                >
                  <Button size="sm" variant="secondary" title="复盘">
                    📊 <span className="hidden xl:inline">复盘</span>
                  </Button>
                </Link>
                {activeCode && (
                  <Link href={`/stock/${encodeURIComponent(activeCode)}`}>
                    <Button size="sm" variant="secondary" title="个股详情">
                      🔍 <span className="hidden xl:inline">详情</span>
                    </Button>
                  </Link>
                )}
              </div>
            </div>

            {/* 图表区 */}
            <div className="flex-1 min-h-[300px] flex flex-col gap-2 p-2">
              {activeCode ? (
                <>
                  {period === 'daily' && (
                    <div className="shrink-0">
                      <CompareChart stockCode={activeCode} height={116} />
                    </div>
                  )}
                  <div className="flex-1 min-h-0 flex flex-col">
                    {period === 'intraday' ? (
                      <IntradayChart stockCode={activeCode} fill />
                    ) : (
                      <KLineChart stockCode={activeCode} period={period} showVolume fill />
                    )}
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-text-ter text-sm">
                  {!baseLoaded
                    ? '正在加载行情…'
                    : watchAll.length === 0
                      ? '自选列表为空,添加标的后这里会显示 K 线'
                      : '选择股票后显示 K 线图'}
                </div>
              )}
            </div>

            {/* 关键价位 */}
            <KeyLevels analysis={analysis} />
          </section>

          {/* ---------- 右:决策栏 ---------- */}
          <aside className="lg:h-full lg:min-h-0 lg:overflow-y-auto bg-bg-surface border-t lg:border-t-0 lg:border-l border-border-def">
            {/* 22:00 今日反思(组件内部有交易时段守卫,非触发时返回 null) */}
            <ReflectionCard />
            <DecisionColumn
              positions={positions}
              analysis={analysis}
              analysisStarted={analysisStarted}
              analysisLoading={analysisLoading}
              analysisProgress={analysisProgress}
              onRefresh={() => refreshAnalysis()}
              onForceRefresh={forceRefreshAnalysis}
              onRetry={() => refreshAnalysis()}
              gainers={marketHeader?.gainers ?? []}
              losers={marketHeader?.losers ?? []}
              amountTrend={amountTrend}
              chat={{
                stockCode: activeCode,
                stockName: selectedQuote?.name ?? null,
                avgCost: activePosition ? Number(activePosition.avgCost) : null,
                currentPrice: selectedQuote ? Number(selectedQuote.currentPrice) : null,
                changePct:
                  selectedQuote?.changePct != null ? Number(selectedQuote.changePct) : null,
                height: chatHeight,
                onHeightChange: setChatHeight,
              }}
            />
          </aside>
        </div>
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
    </div>
  );
}

/** 标的 header 里的当日读数(最高 / 最低 / 昨收 / 成交额) */
function Meta({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <span className="flex items-baseline gap-1 whitespace-nowrap">
      <span className="text-text-ter text-[9.5px] tracking-wider">{label}</span>
      <span className="text-text-sec">{value ?? '--'}</span>
    </span>
  );
}
