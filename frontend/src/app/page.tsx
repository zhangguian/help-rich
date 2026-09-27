'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import Link from 'next/link';
import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';

import { apiGet, snakeToCamel } from '@/lib/api';
import { consumeAnalysisStream } from '@/lib/analysisStream';
import type {
  AmountTrendResponse,
  AnalysisResult,
  MarketIndex,
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
import { GlassCard } from '@/components/ui/GlassCard';
import { LiquidModal } from '@/components/ui/LiquidModal';
import { WatchList, type WatchItem } from '@/components/watch/WatchList';

type TabKey = 'watch' | 'favorite' | 'position' | 'market' | 'sector' | 'news' | 'settings' | 'screener' | 'watchlist';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'watch', label: '自选' },
  { key: 'favorite', label: '⭐ 关注' },
  { key: 'position', label: '持仓' },
  { key: 'market', label: '大盘' },
  { key: 'sector', label: '板块资金' },
  { key: 'news', label: '快讯' },
  { key: 'screener', label: '📈 选股' },
  { key: 'watchlist', label: '⭐ 观察池' },
  { key: 'settings', label: '设置' },
];

const PERIODS: { key: KlinePeriod; label: string }[] = [
  { key: 'intraday', label: '分时' },
  { key: 'daily', label: '日K' },
  { key: 'weekly', label: '周K' },
  { key: 'monthly', label: '月K' },
  { key: '60min', label: '60分' },
];

/** 欢迎横幅右侧的大盘速览数据(三大指数 + 涨跌家数/区间分布/两市成交额) */
interface MarketHeader {
  indexes: MarketIndex[];
  upTotal: number | null;
  downTotal: number | null;
  flatTotal: number | null;
  amountYi: number | null;
  buckets: MarketSentiment['buckets'] | null;
}

/** Logo 章渐变色(按代码哈希取色,稳定不变) */
const CHIP_COLORS = [
  'from-blue-500 to-sky-400',
  'from-violet-500 to-purple-400',
  'from-cyan-500 to-teal-400',
  'from-amber-500 to-orange-400',
  'from-rose-500 to-pink-400',
];
const chipColor = (code: string) => {
  let h = 0;
  for (let i = 0; i < code.length; i++) h = (h * 31 + code.charCodeAt(i)) >>> 0;
  return CHIP_COLORS[h % CHIP_COLORS.length];
};

/** 成交额(亿元)格式化:保留 1 位小数 + 千分位 */
function decimal(v: number): string {
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
}

/**
 * 卡片工作台 v0.6(复刻企业版设计稿结构)
 *
 * 一整块浅蓝圆角仪表盘容器:蓝底内嵌导航栏 + hero 问候区(玻璃扇片装饰)+ 浮动持仓小卡
 * (骑跨蓝/白交界),下方白色内容区承载统计卡行 / K线大卡 + AI 双卡 / 盯盘列表卡。
 * 大盘/板块资金/快讯/选股/观察池/设置 tab 时白色内容区被对应面板占满。
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
    try {
      const [ov, st] = await Promise.all([
        apiGet<MarketOverview>('/market/overview'),
        apiGet<MarketSentiment>('/market/sentiment'),
      ]);
      setMarketHeader({
        indexes: ov.indexes.filter((x): x is MarketIndex => x != null),
        upTotal: st?.upTotal ?? null,
        downTotal: st?.downTotal ?? null,
        flatTotal: st?.flatTotal ?? null,
        amountYi: st?.amountYi ?? null,
        buckets: st?.buckets ?? null,
      });
      apiGet<AmountTrendResponse>('/market/amount-trend?days=5')
        .then((r) => setAmountTrend(r.items ?? []))
        .catch(() => {});
    } catch {
      /* toast 已由拦截器处理 */
    }
  }, []);

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
          isFavorite: it.isFavorite,
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
    if (tab === 'position') {
      return positions.map((p) => ({
        code: p.stockCode,
        name: p.stockName,
        inPosition: true,
        quote: quotesMap[p.stockCode] ?? null,
        isFavorite: false,
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

  const isDashboardTab = tab === 'watch' || tab === 'favorite' || tab === 'position';

  // 浮动持仓小卡(参考图用户卡):持仓优先,无持仓回退自选;选中股居中抬升
  const floatCards = useMemo(() => {
    const base = positions.length > 0
      ? positions.map((p) => ({ code: p.stockCode, name: p.stockName }))
      : watchAll.slice(0, 5).map((it) => ({ code: it.code, name: it.name ?? it.code }));
    return base.slice(0, 5);
  }, [positions, watchAll]);
  const floatCenter = useMemo(() => {
    if (activeCode) {
      const idx = floatCards.findIndex((c) => c.code === activeCode);
      if (idx >= 0) return idx;
    }
    return Math.max(0, Math.floor(floatCards.length / 2));
  }, [activeCode, floatCards]);

  /** 统计行第 4 卡:AI 助手对话卡(参考图 AI助手卡样式:气泡 + 时间戳) */
  const aiHelperCard = (
    <GlassCard padding="md" className="min-h-[150px] flex flex-col">
      <div className="flex items-center gap-3">
        <span className="w-10 h-10 rounded-2xl bg-accent-subtle flex items-center justify-center text-lg shrink-0">🤖</span>
        <div className="text-xs text-text-sec">AI 助手</div>
        {analysis?.ai && (
          <span
            className={clsx(
              'ml-auto px-2 py-0.5 rounded-lg text-xs font-semibold border',
              analysis.ai.view === 'bullish'
                ? 'text-up border-up/40 bg-up-bg'
                : analysis.ai.view === 'bearish'
                  ? 'text-down border-down/40 bg-down-bg'
                  : 'text-text-sec border-border-def bg-bg-subtle',
            )}
          >
            {analysis.ai.view === 'bullish' ? '看多' : analysis.ai.view === 'bearish' ? '看空' : '中性'}
          </span>
        )}
      </div>
      <div className="mt-3 flex-1 space-y-2 min-h-0">
        {/* 用户指令气泡 */}
        <div className="flex items-start gap-2">
          <span className="w-6 h-6 rounded-lg bg-accent-subtle flex items-center justify-center text-[11px] shrink-0">✦</span>
          <div className="flex-1 text-xs text-text-sec bg-bg-subtle rounded-xl rounded-tl-sm px-3 py-2 leading-relaxed line-clamp-2">
            {activeCode
              ? `请分析 ${selectedQuote?.name ?? activeCode} 的当前走势与操作参考。`
              : '在下方列表选择一只股票,AI 将结合技术指标给出白话解读。'}
          </div>
        </div>
        {/* AI 回复气泡 */}
        <div className="flex items-start gap-2">
          <span className="w-6 h-6 rounded-lg bg-gradient-to-br from-blue-500 to-sky-400 text-white flex items-center justify-center text-[10px] font-bold shrink-0">
            AI
          </span>
          <div className="flex-1 text-xs text-text-pri bg-bg-subtle border border-border-def rounded-xl rounded-tl-sm px-3 py-2 leading-relaxed line-clamp-2">
            {analysisLoading
              ? analysisProgress != null
                ? `思考中…(${analysisProgress}s)`
                : '分析中…'
              : analysis?.ai
                ? analysis.ai.trend
                : '点「开始分析」获取解读。'}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-[10px] text-text-ter font-mono">
          {analysis?.latestKlineDate ? `数据截至 ${analysis.latestKlineDate}` : ''}
        </span>
        <Button
          size="sm"
          className="rounded-full"
          onClick={() => (analysis?.ai ? forceRefreshAnalysis() : refreshAnalysis())}
          disabled={analysisLoading || !activeCode}
        >
          {analysis?.ai ? '🔄 重新分析' : '✨ 开始分析'}
        </Button>
      </div>
    </GlassCard>
  );

  /** 第二行左卡:市场情绪区间分布(参考图带图例数字的图表卡) */
  const sentimentCard = (() => {
    const b = marketHeader?.buckets ?? null;
    const bars = b
      ? [
          { v: b.limitUp, label: '涨停', tone: 'up' as const },
          { v: b.up5_10, label: '+5~10', tone: 'up' as const },
          { v: b.up1_5, label: '+1~5', tone: 'up' as const },
          { v: b.up0_1, label: '+0~1', tone: 'up' as const },
          { v: b.flat, label: '平', tone: 'flat' as const },
          { v: b.down0_1, label: '-0~1', tone: 'down' as const },
          { v: b.down1_5, label: '-1~5', tone: 'down' as const },
          { v: b.down5_10, label: '-5~10', tone: 'down' as const },
          { v: b.limitDown, label: '跌停', tone: 'down' as const },
        ]
      : null;
    const max = bars ? Math.max(...bars.map((x) => x.v), 1) : 1;
    const toneColor = (tone: 'up' | 'flat' | 'down') =>
      tone === 'up' ? 'rgba(225, 29, 72, 0.5)' : tone === 'down' ? 'rgba(22, 163, 74, 0.5)' : 'rgba(100, 116, 139, 0.35)';
    return (
      <GlassCard padding="md" className="min-h-[150px] flex flex-col">
        <div className="flex items-center gap-3">
          <span className="w-10 h-10 rounded-2xl bg-up-bg flex items-center justify-center text-lg shrink-0">🌡️</span>
          <div className="text-xs text-text-sec">市场情绪 · 全A 区间分布</div>
          <span className="ml-auto text-xs font-mono text-text-ter">
            <span className="text-up font-semibold">{marketHeader?.upTotal ?? '--'}</span> 涨 ·{' '}
            <span className="text-down font-semibold">{marketHeader?.downTotal ?? '--'}</span> 跌
          </span>
        </div>
        <div className="flex items-end gap-1.5 h-16 mt-3" aria-hidden>
          {bars
            ? bars.map((x) => (
                <div key={x.label} className="flex-1 flex flex-col items-center justify-end gap-1 h-full" title={`${x.label} ${x.v} 家`}>
                  <div
                    className="w-full rounded-t-[4px] min-w-[4px]"
                    style={{ height: `${Math.max((x.v / max) * 100, 4)}%`, backgroundColor: toneColor(x.tone) }}
                  />
                </div>
              ))
            : Array.from({ length: 9 }).map((_, i) => (
                <div key={i} className="flex-1 h-3 rounded-t-[4px] bg-bg-subtle animate-pulse" />
              ))}
        </div>
        <div className="flex justify-between text-[10px] text-text-ter mt-1.5 font-mono">
          {bars ? bars.map((x) => <span key={x.label}>{x.label}</span>) : null}
        </div>
      </GlassCard>
    );
  })();

  /** 第二行右卡:两市量能 5 日趋势(参考图带图例数字的图表卡) */
  const amountCard = (() => {
    const max = Math.max(...amountTrend.map((i) => i.volumeYi), 1e-9);
    const last = amountTrend.length > 0 ? amountTrend[amountTrend.length - 1] : null;
    return (
      <GlassCard padding="md" className="min-h-[150px] flex flex-col xl:col-span-2">
        <div className="flex items-center gap-3">
          <span className="w-10 h-10 rounded-2xl bg-accent-subtle flex items-center justify-center text-lg shrink-0">💱</span>
          <div className="text-xs text-text-sec">两市量能 · 近 5 日</div>
          <span className="ml-auto text-xs font-mono text-text-ter">
            最新 <span className="text-text-pri font-semibold">{last ? last.volumeYi.toFixed(0) : '--'}</span> 亿手
          </span>
        </div>
        <div className="flex items-end gap-3 h-16 mt-3 px-2" aria-hidden>
          {amountTrend.length > 0
            ? amountTrend.map((it) => (
                <div key={it.date} className="flex-1 flex flex-col items-center justify-end gap-1 h-full" title={`${it.date} ${it.volumeYi.toFixed(0)} 亿手`}>
                  <div
                    className="w-3/5 rounded-t-[5px] bg-accent/35"
                    style={{ height: `${Math.max((it.volumeYi / max) * 100, 6)}%` }}
                  />
                </div>
              ))
            : Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex-1 h-3 rounded-t-[5px] bg-bg-subtle animate-pulse" />
              ))}
        </div>
        <div className="flex justify-between text-[10px] text-text-ter mt-1.5 font-mono px-2">
          {amountTrend.length > 0
            ? amountTrend.map((it) => <span key={it.date}>{it.date.slice(5)}</span>)
            : <span>加载中…</span>}
        </div>
      </GlassCard>
    );
  })();

  return (
    <main className="min-h-screen w-full flex justify-center px-4 py-6">
      <div
        className="w-full max-w-[1720px] rounded-[28px] overflow-hidden shadow-2xl shadow-blue-300/40 flex flex-col"
        style={{ background: 'linear-gradient(165deg, #6f9fec 0%, #9cc0f5 28%, #c9def9 62%, #e9f2fe 100%)' }}
      >
        {/* 导航栏(容器蓝底内,参考图 Clario 顶栏) */}
        <header className="relative z-20 flex items-center justify-between gap-3 px-6 pt-5 flex-wrap">
          <div className="flex items-center gap-2.5">
            <span className="w-9 h-9 rounded-xl bg-white/90 text-blue-600 flex items-center justify-center text-lg shadow-sm">
              📈
            </span>
            <span className="text-lg font-bold text-white drop-shadow-sm whitespace-nowrap">买股工具室</span>
          </div>
          <nav className="flex items-center gap-1.5 flex-wrap">
            {TABS.map((t) => {
              const isActive = tab === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={clsx(
                    'relative px-3.5 py-1.5 text-sm rounded-full transition-colors whitespace-nowrap',
                    isActive
                      ? 'text-blue-600 font-semibold'
                      : 'text-white/85 hover:text-white hover:bg-white/15',
                  )}
                >
                  {isActive && (
                    <motion.span
                      layoutId="tab-pill"
                      className="absolute inset-0 rounded-full bg-white shadow-md shadow-blue-900/15"
                      transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                    />
                  )}
                  <span className="relative">{t.label}</span>
                </button>
              );
            })}
          </nav>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setAutoRefresh((v) => !v)}
              title={autoRefresh ? '点击关闭自动刷新' : '点击开启自动刷新(15s 一次)'}
              className={clsx(
                'flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors',
                autoRefresh
                  ? 'bg-white text-blue-600 font-semibold shadow-sm'
                  : 'bg-white/15 text-white/85 hover:bg-white/25',
              )}
            >
              <span
                className={clsx(
                  'w-2 h-2 rounded-full',
                  autoRefresh ? 'bg-accent animate-pulse' : 'bg-white/50',
                )}
              />
              自动刷新{' '}
              {autoRefresh ? (secondsLeft > 0 ? `${secondsLeft}s` : '刷新中…') : 'OFF'}
            </button>
            <span className="text-xs text-white/70 hidden lg:inline">数据源:新浪 · AI 本地配置</span>
          </div>
        </header>

        {/* Hero 问候区(容器蓝底内,参考图「所有客户数据」横幅) */}
        <section className="relative z-10 px-6 pt-5 pb-24">
          {/* 玻璃扇片装饰 */}
          <div className="absolute right-64 top-1/2 -translate-y-1/2 hidden xl:flex items-center pointer-events-none">
            {[-24, -8, 8, 24].map((deg) => (
              <div
                key={deg}
                className="w-12 h-24 rounded-2xl bg-white/30 border border-white/45 backdrop-blur-sm -ml-2 first:ml-0"
                style={{ transform: `rotate(${deg}deg) translateY(${Math.abs(deg) / 2.4}px)` }}
              />
            ))}
          </div>
          <div className="absolute -right-16 -bottom-16 w-72 h-72 rounded-full bg-white/20 blur-3xl pointer-events-none" />
          <p className="text-[11px] font-semibold text-white/75 tracking-[0.2em] uppercase relative">持仓总览 · 实时行情</p>
          <h2 className="text-[30px] leading-tight font-bold text-white mt-1.5 relative drop-shadow-sm">
            {greeting},祝盯盘顺利
          </h2>
          <div className="mt-4 flex gap-2 relative flex-wrap">
            <span className="px-3 py-1 rounded-full bg-white/90 text-blue-600 text-xs font-semibold shadow-sm">{dateStr}</span>
            <span className="px-3 py-1 rounded-full bg-white/20 backdrop-blur text-xs text-white">📈 自选 {watchAll.length}</span>
            <span className="px-3 py-1 rounded-full bg-white/20 backdrop-blur text-xs text-white">💼 持仓 {positions.length}</span>
            <span className="px-3 py-1 rounded-full bg-white/20 backdrop-blur text-xs text-white">⭐ 特别关注 {watchAll.filter((it) => it.isFavorite).length}</span>
          </div>

          {/* 右侧三大指数状态胶囊(参考图「状态/涨跌」pills),点击进大盘页 */}
          <div className="absolute right-6 top-5 hidden lg:flex flex-col gap-2 items-end">
            {(marketHeader?.indexes ?? []).slice(0, 3).map((idx) => (
              <button
                key={idx.code}
                onClick={() => setTab('market')}
                className="flex items-center gap-2 rounded-full bg-white/18 backdrop-blur px-3 py-1.5 text-xs text-white hover:bg-white/28 transition-colors"
                title={`${idx.name} · 点击查看大盘详情`}
              >
                <span className="font-semibold">{idx.name}</span>
                <span className="font-mono">{idx.currentPrice}</span>
                <span className={clsx('font-mono font-semibold', idx.changePct > 0 ? 'text-rose-100' : 'text-emerald-100')}>
                  {idx.changePct > 0 ? '+' : ''}
                  {idx.changePct.toFixed(2)}%
                </span>
              </button>
            ))}
          </div>
        </section>

        {/* 浮动持仓小卡:骑跨蓝/白交界(参考图联系人卡行) */}
        <div className="relative z-20 px-6 -mt-16 flex justify-center gap-3 flex-wrap">
          {isDashboardTab && floatCards.length === 0 && (
            <div className="bg-white/85 rounded-2xl px-5 py-3 text-sm text-text-ter shadow-lg shadow-blue-900/10">
              添加自选 / 持仓后,这里会展示股票小卡
            </div>
          )}
          {isDashboardTab &&
            floatCards.map((c, i) => {
              const q = quotesMap[c.code] ?? null;
              const halted = q != null && Number(q.currentPrice) === 0;
              const isCenter = i === floatCenter;
              return (
                <button
                  key={c.code}
                  onClick={() => selectStock(c.code)}
                  className={clsx(
                    'bg-white rounded-2xl px-4 py-3 flex items-center gap-3 text-left transition-all',
                    isCenter
                      ? 'ring-2 ring-blue-300 shadow-xl shadow-blue-900/15 scale-[1.05]'
                      : 'shadow-lg shadow-blue-900/10 hover:-translate-y-0.5',
                  )}
                >
                  <span
                    className={clsx(
                      'w-10 h-10 rounded-xl bg-gradient-to-br text-white text-base font-bold flex items-center justify-center shrink-0 shadow-sm',
                      chipColor(c.code),
                    )}
                  >
                    {(c.name ?? c.code).slice(0, 1)}
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5">
                      <span className="text-sm font-semibold text-text-pri truncate max-w-[8rem]">{c.name ?? c.code}</span>
                      <span className="text-[10px] text-text-ter font-mono">{c.code}</span>
                    </span>
                    <span className="flex items-center gap-2 mt-0.5">
                      <span className="text-sm font-mono font-semibold text-text-pri">
                        {!q ? '--' : halted ? '停牌' : q.currentPrice}
                      </span>
                      {q && !halted && (
                        <span
                          className={clsx(
                            'px-1.5 py-px rounded-md text-[11px] font-mono font-semibold',
                            q.changePct > 0 ? 'bg-up-bg text-up' : q.changePct < 0 ? 'bg-down-bg text-down' : 'bg-bg-subtle text-text-ter',
                          )}
                        >
                          {q.changePct > 0 ? '+' : ''}
                          {q.changePct.toFixed(2)}%
                        </span>
                      )}
                    </span>
                  </span>
                </button>
              );
            })}
        </div>

        {/* 白色内容区(嵌在蓝色容器下半部,参考图白色卡片区) */}
        <div className="relative z-10 bg-[#f5f9fe] px-5 pb-6 pt-6 flex flex-col gap-5">
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 16, filter: 'blur(6px)' }}
              animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, y: -12, filter: 'blur(6px)' }}
              transition={{ duration: 0.26, ease: 'easeOut' }}
              className="flex-1 min-h-0 flex flex-col gap-5"
            >
              {isDashboardTab ? (
                <>
                  {/* 22:00 今日反思 + 消息面提示(改动 C);组件内部已做 22:00 与当日交易守卫,
                      非触发条件时返回 null,无需在此判断 */}
                  <ReflectionCard />

                  {/* 统计卡行:总市值 / 总浮盈 / 今日盈亏 / AI 助手(参考图 4 卡行) */}
                  {positions.length > 0 ? (
                    <PositionStatsCards positions={positions} extra={aiHelperCard} />
                  ) : (
                    <div className="grid grid-cols-2 xl:grid-cols-4 gap-5">
                      {[
                        { label: '上涨家数', value: marketHeader?.upTotal, cls: 'text-up', icon: '🔺', chip: 'bg-up-bg' },
                        { label: '下跌家数', value: marketHeader?.downTotal, cls: 'text-down', icon: '🔻', chip: 'bg-down-bg' },
                        { label: '平盘家数', value: marketHeader?.flatTotal, cls: 'text-text-pri', icon: '➖', chip: 'bg-bg-subtle' },
                        {
                          label: '两市成交额',
                          value: marketHeader?.amountYi,
                          cls: 'text-text-pri',
                          icon: '💱',
                          chip: 'bg-accent-subtle',
                          fmt: (v: number) => `${decimal(v)} 亿`,
                        },
                      ].map((c) => (
                        <GlassCard key={c.label} padding="md" className="min-h-[150px] flex flex-col">
                          <div className="flex items-center gap-3">
                            <span className={`w-10 h-10 rounded-2xl flex items-center justify-center text-lg shrink-0 ${c.chip}`}>
                              {c.icon}
                            </span>
                            <div className="text-xs text-text-sec">{c.label}</div>
                          </div>
                          <div className={clsx('text-[26px] font-mono font-bold mt-3 leading-none', c.cls)}>
                            {c.value == null ? '--' : c.fmt ? c.fmt(c.value) : c.value}
                          </div>
                          <div className="text-xs text-text-ter mt-1.5">暂无持仓,展示市场情绪</div>
                        </GlassCard>
                      ))}
                      {aiHelperCard}
                    </div>
                  )}

                  {/* 第二行:市场情绪 + 两市量能(参考图带图例数字的图表卡) */}
                  <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
                    {sentimentCard}
                    {amountCard}
                  </div>

                  {/* K线大卡(2/3)+ AI 双卡列(1/3) */}
                  <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 items-start">
                    <div className="xl:col-span-2 flex flex-col gap-4 min-w-0">
                      {tab === 'position' && positionView === 'table' ? (
                        <PositionSummaryTable positions={positions} onSelect={selectStock} />
                      ) : tab === 'position' && positionView === 'flow' && activeCode ? (
                        <GlassCard padding="md">
                          <StockFlowTab
                            stockCode={activeCode}
                            stockName={selectedQuote?.name ?? null}
                          />
                        </GlassCard>
                      ) : (
                        <>
                          {activeCode ? (
                            <GlassCard padding="md" className="flex items-center justify-between gap-3 flex-wrap shrink-0">
                              <div className="flex items-center gap-3 min-w-0">
                                <span
                                  className={clsx(
                                    'w-11 h-11 rounded-2xl bg-gradient-to-br text-white text-base font-bold flex items-center justify-center shrink-0 shadow-sm shadow-blue-500/25',
                                    chipColor(activeCode),
                                  )}
                                >
                                  {(selectedQuote?.name ?? activeCode).slice(0, 1)}
                                </span>
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2.5 min-w-0 flex-wrap">
                                    <span className="font-semibold text-text-pri text-lg truncate">
                                      {selectedQuote?.name ?? activeCode}
                                    </span>
                                    <span className="text-xs text-text-ter font-mono">{activeCode}</span>
                                    {activePosition && (
                                      <span className="text-[10px] px-2 py-px rounded-full bg-accent-subtle text-accent border border-accent/25 font-medium">
                                        已持仓
                                      </span>
                                    )}
                                  </div>
                                  {positionPnl && (
                                    <div className="flex items-center gap-3 mt-1 text-xs font-mono flex-wrap">
                                      <span className={pctClass(positionPnl.todayPnl ?? undefined)}>
                                        {positionPnl.todayPnl != null
                                          ? `今日 ${positionPnl.todayPnl >= 0 ? '+' : ''}¥${positionPnl.todayPnl.toFixed(2)}`
                                          : '今日 --'}
                                      </span>
                                      <span className={pctClass(positionPnl.floatingPnl ?? undefined)}>
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
                              <div className="flex items-center gap-4 flex-wrap">
                                <div className="text-right">
                                  <div className="text-3xl font-mono font-bold text-text-pri leading-tight">
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
                                </div>
                                <div className="flex flex-col gap-1.5">
                                  <div className="flex gap-2">
                                    <Button size="sm" variant="secondary" onClick={() => setShowCalc(true)}>
                                      🧮 成本计算器
                                    </Button>
                                    <Button size="sm" variant="secondary" onClick={() => setShowHealth(true)}>
                                      🩺 持仓分析
                                    </Button>
                                  </div>
                                  <Link
                                    href={activeCode
                                      ? `/replay-history?code=${encodeURIComponent(activeCode)}`
                                      : '/replay-history'}
                                  >
                                    <Button size="sm" variant="secondary" className="w-full">
                                      📊 复盘历史
                                    </Button>
                                  </Link>
                                </div>
                              </div>
                            </GlassCard>
                          ) : (
                            <GlassCard padding="lg" className="shrink-0 text-center">
                              <p className="text-text-ter text-sm">↓ 从下方盯盘列表选择一只自选 / 持仓股票</p>
                            </GlassCard>
                          )}

                          <div className="flex items-center justify-between gap-2 shrink-0 flex-wrap">
                            {/* 左侧:持仓 tab 视图切换 */}
                            {tab === 'position' && (
                              <div className="flex items-center gap-1.5">
                                {(
                                  [
                                    { key: 'kline', label: '📈 K 线' },
                                    { key: 'flow', label: '📋 流水' },
                                    { key: 'table', label: '📋 持仓表' },
                                  ] as const
                                ).map((v) => (
                                  <button
                                    key={v.key}
                                    onClick={() => setPositionView(v.key)}
                                    disabled={v.key === 'flow' && !activeCode}
                                    className={clsx(
                                      'px-3 py-1.5 text-sm rounded-full transition-colors border',
                                      positionView === v.key
                                        ? 'bg-accent text-white border-accent shadow-sm shadow-blue-500/25'
                                        : 'bg-bg-surface text-text-sec hover:text-text-pri border-border-def disabled:opacity-40 disabled:cursor-not-allowed',
                                    )}
                                  >
                                    {v.label}
                                  </button>
                                ))}
                              </div>
                            )}
                            {/* 右侧:周期切换(持仓表/流水视图下隐藏) */}
                            {!(tab === 'position' && (positionView === 'table' || positionView === 'flow')) && (
                              <div className="flex items-center gap-1.5">
                                {PERIODS.map((p) => (
                                  <button
                                    key={p.key}
                                    onClick={() => setPeriod(p.key)}
                                    className={clsx(
                                      'px-3 py-1.5 text-sm rounded-full transition-colors border',
                                      period === p.key
                                        ? 'bg-accent text-white border-accent shadow-sm shadow-blue-500/25'
                                        : 'bg-bg-surface text-text-sec hover:text-text-pri border-border-def',
                                    )}
                                  >
                                    {p.label}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>

                          {activeCode ? (
                            <GlassCard padding="sm" className="w-full">
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
                            </GlassCard>
                          ) : (
                            <GlassCard padding="lg" className="w-full flex items-center justify-center min-h-[320px]">
                              <p className="text-text-ter text-sm">
                                {tab === 'position' && positionView === 'flow'
                                  ? '先选一只股票才能查看流水与复盘'
                                  : '选择股票后显示 K 线图'}
                              </p>
                            </GlassCard>
                          )}
                        </>
                      )}
                    </div>

                    {/* 右列:AI 分析 + AI 问一问 */}
                    <div className="flex flex-col gap-4 min-w-0">
                      <AnalysisPanel
                        analysis={analysis}
                        started={analysisStarted}
                        loading={analysisLoading}
                        aiProgress={analysisProgress}
                        onRefresh={() => refreshAnalysis()}
                        onForceRefresh={forceRefreshAnalysis}
                        onRetry={() => refreshAnalysis()}
                      />
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
                  </div>

                  {/* 盯盘列表卡(全宽) */}
                  <WatchList
                    items={visibleItems}
                    activeCode={activeCode}
                    favoriteOnly={tab === 'favorite'}
                    onSelect={selectStock}
                    onChanged={fetchBase}
                  />
                </>
              ) : tab === 'screener' ? (
                <ScreenerPanel />
              ) : tab === 'watchlist' ? (
                <WatchlistPanel />
              ) : tab === 'sector' ? (
                <SectorBoard />
              ) : tab === 'news' ? (
                <NewsFeed />
              ) : tab === 'market' ? (
                <MarketOverviewPage />
              ) : (
                <SettingsPanel />
              )}
            </motion.div>
          </AnimatePresence>
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
    </main>
  );
}
