'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import clsx from 'clsx';

import { apiGet, snakeToCamel } from '@/lib/api';
import { consumeAnalysisStream } from '@/lib/analysisStream';
import { pctClass, chipColor } from '@/lib/format';
import type {
  AmountTrendResponse,
  AnalysisResult,
  DecisionAdviceResponse,
  DecisionAdviceText,
  MarketIndex,
  MarketMover,
  MarketOverview,
  MarketSentiment,
  Position,
  Quote,
  StockDecision,
  WatchlistItem,
} from '@/lib/types';

import { AnalysisPanel } from '@/components/advice/AnalysisPanel';
import { CalculatorPanel } from '@/components/calculator/CalculatorPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { CompareChart } from '@/components/charts/CompareChart';
import { KLineChart, type KlinePeriod } from '@/components/charts/KLineChart';
import { BreadthBar } from '@/components/desk/BreadthBar';
import { DecisionColumn } from '@/components/desk/DecisionColumn';
import { DeskTopBar, type DeskTab } from '@/components/desk/DeskTopBar';
import { KeyLevels } from '@/components/desk/KeyLevels';
import { useAssistantActions } from '@/components/assistant/AssistantProvider';
import IntradayReviewPanel from '@/components/plan/IntradayReviewPanel';
import { useIntradayStore } from '@/stores/useIntradayStore';
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
import { useRefreshStore } from '@/stores/useRefreshStore';
import type { HoldingsHealth } from '@/lib/types';

/**
 * 首页筛选器(自选 / 关注 / 持仓)
 *
 * 此前此处是 9 个 tab,其中 6 个(大盘/板块/快讯/选股/观察池/设置)已由
 * 持久 NavRail 提升为独立路由,故不再需要本地 tab 切换;页签本体在 DeskTopBar。
 * 持仓明细(成本/盈亏/流水)见 /positions,这里只做「视角切换」。
 */
type TabKey = DeskTab;

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
 * P1(阶段10):轮询数据的内容签名
 *
 * 为什么需要:轮询每次都会新建对象/数组,直接比引用**永远不相等**,
 * 等于浅比较没做 —— 每轮轮询都把整页重渲染一遍。
 * 实测(prod build):一轮 15s 轮询会在主线程落下 55~69ms 的长任务。
 *
 * 为什么用 JSON.stringify 求签名、而不是手写字段清单:
 * 盯盘这份数据满打满算几 KB,序列化一次是几十微秒级,远小于一次全页重渲染;
 * 而手写字段清单一旦漏掉一个字段,就会变成「该更新却没更新」的静默错误 ——
 * 那比卡顿更难查。宁可多花几十微秒,也不要换一类更隐蔽的 bug。
 */
function contentSig(value: unknown): string {
  try {
    return JSON.stringify(value) ?? '';
  } catch {
    return '';
  }
}

/**
 * 决策端点的错误文案 —— 取出后端给的中文说明
 *
 * 后端抛的是 `HTTPException(detail={"code": ..., "message": "..."})`,
 * 而 axios 拦截器只认 `{code,message}`(顶层)或 `detail` 为**数组**(FastAPI 校验错误),
 * 所以它认不出这个形状 → 统一落到「请求失败 (HTTP 422)」,
 * 抛回的 `e.message` 是 `"Request failed with status code 502"`(英文且没说明原因)。
 * 这里自己取 detail.message,让决策卡显示「K 线数据获取失败」这种能看懂的话。
 */
function decisionErrorText(e: unknown): string {
  const err = e as {
    response?: { data?: { detail?: { message?: string } } };
    message?: string;
  };
  return (
    err?.response?.data?.detail?.message ?? (e instanceof Error ? e.message : '未知错误')
  );
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
  // P1(阶段10):这里原本还有一个 quotesMap,全文件只有声明和赋值、**从来没有被读过**
  // ——纯死状态,却让每轮轮询多触发一次全页重渲染。已删除(它承载的信息
  // 本来就在 watchAll[].quote 里)。
  const [period, setPeriod] = useState<KlinePeriod>('daily');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysisStarted, setAnalysisStarted] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  // 流式进度:LLM 启动 30s 后开始推,这里存最新的 elapsed_s(供 AnalysisPanel 显示「思考中…Ns」)
  const [analysisProgress, setAnalysisProgress] = useState<number | null>(null);
  const [selectedQuote, setSelectedQuote] = useState<Quote | null>(null);
  // 操作决策卡(确定性引擎):与 AI 解读**并行**拉取,互不阻塞 —— 不等 LLM 就能看到「该干什么」
  const [decision, setDecision] = useState<StockDecision | null>(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  // 请求序号守卫:快速切票时,A 的慢响应不得覆盖 B 的结果(否则会显示另一只票的价位)
  const decisionSeq = useRef(0);
  // v0.10「AI 写白话」:按钮触发的现场白话(显式烧 token,不自动调)
  const [decisionAdvice, setDecisionAdvice] = useState<DecisionAdviceText | null>(null);
  const [decisionAdviceNote, setDecisionAdviceNote] = useState<string | null>(null);
  const [decisionAdviceLoading, setDecisionAdviceLoading] = useState(false);
  // 白话请求的序号守卫(与决策卡分开计数:点「写白话」不能影响决策卡自己的请求序号)
  const adviceSeq = useRef(0);
  // 当前选中股票(异步回调防串:分析/缓存返回时比对,避免贴到别的股票面板)
  const activeCodeRef = useRef<string | null>(null);
  const [showCalc, setShowCalc] = useState(false);
  const [showHealth, setShowHealth] = useState(false);
  const [positionView, setPositionView] = useState<'kline' | 'flow' | 'table'>('kline');
  // 自动刷新开关(默认关):开启后 15s 周期 fetchBase;同步到 localStorage
  // 初始一律 false;挂载后 useEffect 读 localStorage 修正 — 避免 SSR/CSR className 不匹配
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  // 倒计时显示(秒):开启时从 15 开始倒数,1s 一刷;关闭时为 0。
  // P7(阶段10):这个数字只被顶栏一个小按钮用到,住在本组件的 state 里会让
  // **每秒整页重渲染**(44 行自选 + 14 张图全走 React diff + 样式重算)。
  // 挪进独立 store 后,每秒只有那个按钮重渲染。
  const setSecondsLeft = useRefreshStore((s) => s.setSecondsLeft);
  const tickSecondsLeft = useRefreshStore((s) => s.tick);
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
  // P1(阶段10):轮询治理 —— 在途保护 + 内容没变不 setState
  const overviewInFlightRef = useRef(false);
  const sentimentInFlightRef = useRef(false);
  const overviewSigRef = useRef('');
  const sentimentSigRef = useRef('');
  const trendSigRef = useRef('');

  /**
   * 指数速览(快档,15s)
   *
   * 为什么单独拆出来:原来 `/market/overview` 和 `/market/sentiment` 用
   * `Promise.all` 捆在一起 —— 情绪接口服务端本身就要 ~2.5s(全市场分页),
   * 捆在一起会让整个大盘速览干等它,指数也跟着晚 2.5s 才出现。
   * 拆开后指数 ~1.4s 就到,情绪卡自己后补(它本身有骨架占位)。
   */
  const fetchMarketOverview = useCallback(async (): Promise<boolean> => {
    // 在途保护:上一轮没回来就跳过本轮,避免慢接口堆成请求雪崩
    if (overviewInFlightRef.current) return true;
    overviewInFlightRef.current = true;
    try {
      const ov = await apiGet<MarketOverview>('/market/overview').catch(() => null);
      if (!ov) return false;
      const indexes = ov.indexes.filter((x): x is MarketIndex => x != null);
      const gainers = ov.gainers ?? [];
      const losers = ov.losers ?? [];
      // 内容没变 → 保留旧引用,页面零重渲染
      const sig = contentSig({ indexes, gainers, losers });
      if (sig === overviewSigRef.current) return true;
      overviewSigRef.current = sig;
      setMarketHeader((prev) => ({
        indexes,
        gainers,
        losers,
        upTotal: prev?.upTotal ?? null,
        downTotal: prev?.downTotal ?? null,
        flatTotal: prev?.flatTotal ?? null,
        amountYi: prev?.amountYi ?? null,
        buckets: prev?.buckets ?? null,
        sampleSize: prev?.sampleSize ?? null,
        partial: prev?.partial ?? false,
      }));
      return true;
    } finally {
      overviewInFlightRef.current = false;
    }
  }, []);

  /**
   * 情绪 + 量能趋势(慢档,60s)
   *
   * 慢档的原因就是它慢:`/market/sentiment` 服务端要 ~2.5s。
   * 盯盘时需要「新」的是报价(快档),情绪拉一次能看很久。
   */
  const fetchMarketSentiment = useCallback(async (): Promise<boolean> => {
    if (sentimentInFlightRef.current) return true;
    sentimentInFlightRef.current = true;
    try {
      const st = await apiGet<MarketSentiment>('/market/sentiment').catch(() => null);
      if (st) {
        const next = {
          upTotal: st.upTotal ?? null,
          downTotal: st.downTotal ?? null,
          flatTotal: st.flatTotal ?? null,
          amountYi: st.amountYi ?? null,
          buckets: st.buckets ?? null,
          sampleSize: st.sampleSize ?? null,
          partial: st.partial ?? false,
        };
        const sig = contentSig(next);
        if (sig !== sentimentSigRef.current) {
          sentimentSigRef.current = sig;
          setMarketHeader((prev) => ({
            indexes: prev?.indexes ?? [],
            gainers: prev?.gainers ?? [],
            losers: prev?.losers ?? [],
            ...next,
          }));
        }
      }
      const trend = await apiGet<AmountTrendResponse>('/market/amount-trend?days=5').catch(() => null);
      if (trend) {
        const items = trend.items ?? [];
        const tsig = contentSig(items);
        if (tsig !== trendSigRef.current) {
          trendSigRef.current = tsig;
          setAmountTrend(items);
        }
      }
      return true;
    } finally {
      sentimentInFlightRef.current = false;
    }
  }, []);

  // P1(阶段10):自选 + 持仓 + 报价(快档,15s)
  const baseInFlightRef = useRef(false);
  const baseSigRef = useRef('');

  const fetchBase = useCallback(async (): Promise<boolean> => {
    // 在途保护:上一轮没跑完就跳过本轮。
    // 理由:慢接口堆积会形成请求雪崩,每条响应回来都触发一次全页重渲染。
    if (baseInFlightRef.current) return true;
    baseInFlightRef.current = true;
    try {
      const [w, p, hh] = await Promise.all([
        apiGet<{ items: WatchlistItem[] }>('/watchlist'),
        apiGet<{ items: Position[] }>('/positions'),
        apiGet<HoldingsHealth>('/holdings-health').catch(() => null),
      ]);
      const posName = new Map(p.items.map((x) => [x.stockCode, x.stockName]));
      // 持仓浮盈比例(%)—— 持仓视角下直接显示在行里,扫一眼就知道哪只亏
      const posPnlPct = new Map<string, number | null>();
      for (const pos of p.items) {
        const floating = pos.floatingPnl != null ? Number(pos.floatingPnl) : null;
        const cost = Number(pos.totalCost);
        posPnlPct.set(
          pos.stockCode,
          cost > 0 && floating != null ? (floating / cost) * 100 : null,
        );
      }
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
          positionPnlPct: posPnlPct.get(it.stockCode) ?? null,
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
            positionPnlPct: posPnlPct.get(pos.stockCode) ?? null,
          });
        }
      }
      // 报价一次性并进来。
      // 原来分两次 setState(先没报价的一版、再有报价的一版)→ 每轮多一次全页重渲染;
      // 合成一次后,列表带着报价一起出现,也不会闪一帧「—」。
      const codes = Array.from(merged.keys());
      const quotes = codes.length
        ? await apiGet<Quote[]>(`/quotes?codes=${codes.join(',')}`).catch(() => [] as Quote[])
        : [];
      const qmap = new Map(quotes.map((q) => [q.code, q]));
      const nextWatchAll = Array.from(merged.values()).map((it) => ({
        ...it,
        quote: qmap.get(it.code) ?? null,
      }));

      // 内容没变 → 保留旧引用,零重渲染
      const sig = contentSig({ positions: p.items, watchAll: nextWatchAll });
      if (sig !== baseSigRef.current) {
        baseSigRef.current = sig;
        setPositions(p.items);
        setWatchAll(nextWatchAll);
      }
      return true;
    } catch {
      /* toast 已由拦截器处理 */
      return false;
    } finally {
      baseInFlightRef.current = false;
      setBaseLoaded(true);
    }
  }, []);

  // 首屏:三条链各自独立 —— 指数先到,情绪后补,互不等待
  useEffect(() => {
    fetchBase();
    fetchMarketOverview();
    fetchMarketSentiment();
  }, [fetchBase, fetchMarketOverview, fetchMarketSentiment]);

  // P1(阶段10):轮询节奏 —— 分档频率 + 可见性暂停 + 失败退避
  //
  // 分档理由:盯盘最需要「新」的是**报价**(15s),指数次之(15s);
  // 而**情绪**(/market/sentiment)服务端本身就要 ~2.5s,拉一次能看很久 —— 60s 一档。
  const FAST_MS = 15_000;
  const SLOW_MS = 60_000;
  const visibleRef = useRef(true);
  const failStreakRef = useRef(0);

  // 页面不可见(切到别的标签页)→ 暂停轮询。
  // 理由:后台标签页的轮询既没人看,又会把请求堆起来。
  useEffect(() => {
    const onVis = () => {
      visibleRef.current = !document.hidden;
    };
    document.addEventListener('visibilitychange', onVis);
    visibleRef.current = !document.hidden;
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  useEffect(() => {
    if (!autoRefresh) {
      setSecondsLeft(0);
      return;
    }
    failStreakRef.current = 0;

    let fastTimer: ReturnType<typeof setTimeout> | null = null;
    let slowTimer: ReturnType<typeof setTimeout> | null = null;
    let tickTimer: ReturnType<typeof setInterval> | null = null;

    // 快档:报价 + 指数(15s)。失败退避:连续失败时 15s → 22.5s → 30s(封顶)。
    const scheduleFast = () => {
      if (fastTimer) clearTimeout(fastTimer);
      const delay = FAST_MS + Math.min(failStreakRef.current, 2) * (FAST_MS / 2);
      fastTimer = setTimeout(async () => {
        if (!visibleRef.current) {
          // 页面不可见 → 这一轮不发请求,直接等下一轮
          scheduleFast();
          return;
        }
        const okBase = await fetchBase();
        const okOverview = await fetchMarketOverview();
        if (okBase && okOverview) failStreakRef.current = 0;
        else failStreakRef.current = Math.min(failStreakRef.current + 1, 2);
        setSecondsLeft(Math.round(delay / 1000));
        scheduleFast();
      }, delay);
    };

    // 慢档:情绪 + 量能(60s)
    const scheduleSlow = () => {
      if (slowTimer) clearTimeout(slowTimer);
      slowTimer = setTimeout(async () => {
        if (visibleRef.current) await fetchMarketSentiment();
        scheduleSlow();
      }, SLOW_MS);
    };

    fetchBase();
    fetchMarketOverview();
    setSecondsLeft(Math.round(FAST_MS / 1000));
    scheduleFast();
    scheduleSlow();
    tickTimer = setInterval(tickSecondsLeft, 1000);

    return () => {
      if (fastTimer) clearTimeout(fastTimer);
      if (slowTimer) clearTimeout(slowTimer);
      if (tickTimer) clearInterval(tickTimer);
    };
  }, [
    autoRefresh,
    fetchBase,
    fetchMarketOverview,
    fetchMarketSentiment,
    setSecondsLeft,
    tickSecondsLeft,
  ]);

  /**
   * 决策卡:纯确定性、无 LLM —— 与 analysis 并行拉取,互不阻塞
   *
   * 为什么要 60s 超时:该端点会串起 5 个外部数据源(全市场情绪快照 5500+ 只
   * 逐页翻页 + 大盘指数 + 行业归属 + 行业等权 K 线 + 板块/个股资金流),
   * 实测冷启动 5.8~7.6s、稳态 0.6~1.5s;而 axios 默认 timeout 只有 10000ms
   * (api.ts:23),慢一点就直接超时 → 决策卡永远显示「暂不可用」。
   */
  const fetchDecision = useCallback(async (code: string) => {
    const seq = ++decisionSeq.current; // 本次请求的序号
    setDecisionLoading(true);
    setDecisionError(null);
    setDecision(null); // 立刻清掉上一只票的决策,避免旧价位残留
    try {
      const r = await apiGet<{ decision: StockDecision }>(
        `/stock/${encodeURIComponent(code)}/decision`,
        { timeout: 60000 },
      );
      if (seq !== decisionSeq.current) return; // 已有更新的请求,丢弃本次结果
      setDecision(r.decision ?? null);
    } catch (e) {
      if (seq !== decisionSeq.current) return;
      setDecision(null);
      setDecisionError(decisionErrorText(e));
    } finally {
      if (seq === decisionSeq.current) setDecisionLoading(false);
    }
  }, []);

  /**
   * 「AI 写白话」:按钮触发,现场把决策事实包翻译成大白话。
   *
   * - **不自动调**:首屏不烧 token,用户点了才发请求;
   * - **序号守卫**:与决策卡同款 —— 慢响应不得贴到已经切走的票上;
   * - **失败即兜底**:LLM 不可用 → 后端退回规则文案(source='rule'),前端照常显示。
   */
  const fetchDecisionAdvice = useCallback(async (code: string) => {
    const seq = ++adviceSeq.current;
    setDecisionAdviceLoading(true);
    try {
      const r = await apiGet<DecisionAdviceResponse>(
        `/stock/${encodeURIComponent(code)}/decision-advice`,
        { timeout: 60000 },
      );
      if (seq !== adviceSeq.current) return;
      setDecisionAdvice(r.advice ?? null);
      setDecisionAdviceNote(
        r.advice?.source === 'rule' ? 'AI 白话不可用,已退回规则文案' : null,
      );
    } catch {
      if (seq !== adviceSeq.current) return;
      setDecisionAdvice(null);
      setDecisionAdviceNote('白话生成失败,已保留规则文案');
    } finally {
      if (seq === adviceSeq.current) setDecisionAdviceLoading(false);
    }
  }, []);

  const writeDecisionAdvice = useCallback(() => {
    if (!activeCode) return;
    void fetchDecisionAdvice(activeCode);
  }, [activeCode, fetchDecisionAdvice]);

  const selectStock = useCallback(
    (code: string) => {
      setActiveCode(code);
      activeCodeRef.current = code;
      setAnalysis(null);
      setAnalysisStarted(false);
      setSelectedQuote(null);
      // 切票 → 作废上一只票的现场白话(否则会把 A 的白话贴到 B 上)
      adviceSeq.current += 1;
      setDecisionAdvice(null);
      setDecisionAdviceNote(null);
      setDecisionAdviceLoading(false);
      // 记住这次盯的票,刷新后直接回到它(见上方 LAST_SELECTED_KEY 注释)
      try {
        localStorage.setItem(LAST_SELECTED_KEY, code);
      } catch {
        /* 隐私模式下 localStorage 不可写,忽略即可 */
      }
      apiGet<Quote>(`/quotes/${encodeURIComponent(code)}`)
        .then(setSelectedQuote)
        .catch(() => {});
      // 决策卡:与 AI 解读并行,不等 LLM
      fetchDecision(code);
      // 无存档回显:分析面板显示空态,由用户手动点「开始分析」(每次实时拉 K + 实时 LLM)
    },
    [fetchDecision],
  );

  /* ---------------- 阶段10:盘中复盘入口 + 全局助手上下文 ---------------- */

  // 把「当前选中的票」报给全局助手 —— 助手会自动带进事实包,
  // 所以在任何页面唤起它,都知道你现在盯的是哪只。
  // ⚠️ 只消费**动作** context(引用稳定)—— 用完整 context 的话,
  //    助手每吐一个 token 都会让盯盘页整页重渲染,把性能优化打回去。
  const { setSelectedStock } = useAssistantActions();
  const selectedName = selectedQuote?.name ?? null;
  useEffect(() => {
    setSelectedStock(activeCode, selectedName);
  }, [activeCode, selectedName, setSelectedStock]);

  // 顶栏「盘中复盘」胶囊的今日状态(是否交易日 / 已产出哪几档 / 下一档倒计时)
  const loadSchedule = useIntradayStore((s) => s.loadSchedule);
  const panelOpen = useIntradayStore((s) => s.panelOpen);
  const closePanel = useIntradayStore((s) => s.closePanel);
  useEffect(() => {
    void loadSchedule();
  }, [loadSchedule]);

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
        } else if (evt.event === 'cache_hit') {
          // 命中当日缓存:后端把**完整**分析结果(含 ai)放在 data 里。
          // ⚠️ 之前这里什么都不做 → 缓存命中时 ai 永远为空,
          //    点了「开始分析」却看不到 AI 解读,决策卡的「AI 解读」白话也拿不到。
          const cached = snakeToCamel((evt.data ?? {}) as Record<string, unknown>) as Partial<
            AnalysisResult & Record<string, unknown>
          >;
          setAnalysis((prev) => ({
            ...(prev ?? ({} as AnalysisResult)),
            stockCode: code,
            indicators: (cached.indicators ?? prev?.indicators) as AnalysisResult['indicators'],
            ai: (cached.ai ?? null) as AnalysisResult['ai'],
            aiSource: 'live',
            aiError: null,
            latestKlineDate:
              (cached.latestKlineDate as string | null) ?? prev?.latestKlineDate ?? null,
            positionStatus: cached.positionStatus ?? prev?.positionStatus,
            costBasisPct: cached.costBasisPct ?? prev?.costBasisPct,
            signalWinrate: cached.signalWinrate ?? prev?.signalWinrate,
            industry: cached.industry ?? prev?.industry,
            industrySource: cached.industrySource ?? prev?.industrySource,
            industryNote: cached.industryNote ?? prev?.industryNote,
            currentPrice: cached.currentPrice ?? prev?.currentPrice,
            quoteChangePct: cached.quoteChangePct ?? prev?.quoteChangePct,
          } as AnalysisResult));
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
    if (tab === 'position') {
      // 持仓视角:watchAll 已经是「自选 ∪ 持仓」,按 inPosition 过滤即为全部持仓
      return watchAll.filter((it) => it.inPosition);
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
              mode={tab}
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
              decision={decision}
              decisionLoading={decisionLoading}
              decisionError={decisionError}
              decisionAdvice={decisionAdvice}
              decisionAdviceNote={decisionAdviceNote}
              decisionAdviceLoading={decisionAdviceLoading}
              onWriteDecisionAdvice={writeDecisionAdvice}
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
        size="2xl"
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

      {/* 阶段10:盘中复盘抽屉(顶栏胶囊点开) */}
      <IntradayReviewPanel open={panelOpen} onClose={closePanel} />
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
