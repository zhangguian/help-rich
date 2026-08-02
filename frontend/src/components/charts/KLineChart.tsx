'use client';

import { useEffect, useRef, useState } from 'react';

import clsx from 'clsx';

import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type LineSeriesPartialOptions,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type TimeScaleOptions,
} from 'lightweight-charts';

import { apiGet } from '@/lib/api';
import { TermHint } from '@/components/ui/TermHint';
import type { KlineIndicatorsResponse } from '@/lib/types';

export type KlinePeriod = 'daily' | 'weekly' | 'monthly' | '60min';

/** 指标组(整组开关) — 含画线组与图例展示组 */
export type OverlayGroup =
  | 'ma'
  | 'boll'
  | 'macd'
  | 'kdj'
  | 'volume'
  | 'rsi'
  | 'cci'
  | 'stoch'
  | 'mom'
  | 'wmsr'
  | 'skt'
  | 'fask';

/** 外部覆盖初始显隐(可选) */
export interface ChartOverlay {
  ma?: boolean;
  boll?: boolean;
  macd?: boolean;
  kdj?: boolean;
  volume?: boolean;
  rsi?: boolean;
  cci?: boolean;
  stoch?: boolean;
  mom?: boolean;
  wmsr?: boolean;
  skt?: boolean;
  fask?: boolean;
}

/** 默认显示:MA 四线 + MACD + 成交量;BOLL/KDJ/RSI/CCI/STOCH/MOM/WMSR/SKT/FASK 默认隐藏 */
const DEFAULT_VISIBLE: Record<OverlayGroup, boolean> = {
  ma: true,
  boll: false,
  macd: true,
  kdj: false,
  volume: true,
  rsi: false,
  cci: false,
  stoch: false,
  mom: false,
  wmsr: false,
  skt: false,
  fask: false,
};

interface KlineItem {
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

const COLOR = {
  up: '#f43f5e',
  down: '#4ade80',
  ma5: '#fb923c',
  ma10: '#a78bfa',
  ma20: '#60a5fa',
  ma60: '#10b981',
  bollUp: 'rgba(244, 63, 94, 0.85)',
  bollMid: 'rgba(148, 163, 184, 0.85)',
  bollDn: 'rgba(74, 222, 128, 0.85)',
  macdDif: '#f59e0b',
  macdDea: '#6366f1',
  macdHistPos: 'rgba(244, 63, 94, 0.6)',
  macdHistNeg: 'rgba(74, 222, 128, 0.6)',
  kdjK: '#22d3ee',
  kdjD: '#fb7185',
  kdjJ: '#94a3b8',
};

interface LegendItem {
  key: string;
  label: string;
  color: string;
  decimals: number;
  /** TermHint 术语键(展示「?」知识点 tooltip) */
  term?: string;
}

interface LegendState {
  /** 后端 state 字符串,如 "overbought" / "oversold" / "neutral" */
  code: string | null;
  /** 简写中文(超买 / 超卖 / 金叉 / 死叉 / 中性 / ...) */
  label: string;
  /** 颜色 tone:up=红,down=绿,accent=高亮,ter=灰 */
  tone: 'up' | 'down' | 'accent' | 'ter';
}

interface LegendRow {
  group: OverlayGroup;
  label: string;
  items: LegendItem[];
  /** TermHint 术语键(整行加「?」) */
  term?: string;
  /** 图例整行显示的当前状态(从后端拿) */
  state?: LegendState | null;
  /** 整行的当前主值(如 RSI 末值、MACD 金叉) */
  currentValue?: string;
}

/** state code → 中文短词 + 颜色 tone(供 chip 显示) */
function stateOfIndicator(code: string | null): LegendState | null {
  if (!code) return null;
  const map: Record<string, { label: string; tone: LegendState['tone'] }> = {
    overbought: { label: '超买', tone: 'up' },
    oversold: { label: '超卖', tone: 'down' },
    bullish: { label: '偏多', tone: 'up' },
    bearish: { label: '偏空', tone: 'down' },
    strong_up: { label: '强势', tone: 'up' },
    strong_down: { label: '弱势', tone: 'down' },
    golden_cross: { label: '金叉', tone: 'up' },
    dead_cross: { label: '死叉', tone: 'down' },
    rising: { label: '上升', tone: 'up' },
    falling: { label: '下降', tone: 'down' },
    zero_cross_up: { label: '上穿 0', tone: 'up' },
    zero_cross_down: { label: '下穿 0', tone: 'down' },
    neutral: { label: '中性', tone: 'ter' },
  };
  const m = map[code];
  if (!m) return { code, label: code, tone: 'ter' };
  return { code, label: m.label, tone: m.tone };
}

function stateOfVolume(code: string | null): LegendState | null {
  if (!code) return null;
  if (code === 'expand') return { code, label: '放量', tone: 'up' };
  if (code === 'shrink') return { code, label: '缩量', tone: 'down' };
  return { code, label: '正常', tone: 'ter' };
}

/**
 * K 线图(K线智能分析 v1 升级版)
 *
 * - 数据源:`/api/kline/{code}/indicators?period=&limit=`(轻量,含全量指标序列,不触发 LLM)
 * - 主图:candlestick 红涨绿跌 + MA5/10/20/60 四线 + BOLL 上中下轨(虚线)
 * - 副图区:成交量柱 + MACD(HIST+DIF/DEA)+ KDJ(K/D/J);多 price scale 堆叠
 * - 信号标注:`series.setMarkers` 显示金叉死叉/形态/诱多诱空(§10.1)
 * - Hover 高亮:crosshair 跟随时,所有 line series 在右侧价格轴显示当前值(lightweight-charts 默认),
 *   图表下方图例同步显示每条线在 hover 时间点的值
 */
export function KLineChart({
  stockCode,
  period = 'daily',
  height = 420,
  overlay,
  showVolume = true,
}: {
  stockCode: string;
  period?: KlinePeriod;
  height?: number;
  overlay?: ChartOverlay;
  showVolume?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // 数据加载失败原因(展示给用户,避免静默空白)
  const [loadError, setLoadError] = useState<string | null>(null);
  // 指标末值快照(用于图例显示当前值 + state),从 /indicators 响应解析
  const [indicators, setIndicators] = useState<KlineIndicatorsResponse['indicators'] | null>(null);
  // 图例:每条线在 hover 时间点的当前值(未 hover 时为 null)
  const [hoverValues, setHoverValues] = useState<Record<string, number | null>>({});
  // 整组显隐(MA / BOLL / MACD / KDJ);volume 单独由 showVolume 控制
  const [visibleGroups, setVisibleGroups] = useState<Record<OverlayGroup, boolean>>(() => ({
    ...DEFAULT_VISIBLE,
    ...(overlay ?? {}),
  }));
  // series 按组引用,用于外部 toggle 时直接 applyOptions 不重建图表
  const seriesMapRef = useRef<Record<OverlayGroup, ISeriesApi<any>[]>>({
    ma: [],
    boll: [],
    macd: [],
    kdj: [],
    volume: [],
    rsi: [],
    cci: [],
    stoch: [],
    mom: [],
    wmsr: [],
    skt: [],
    fask: [],
  });

  useEffect(() => {
    if (!containerRef.current) return;
    setLoadError(null);
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: 'transparent' },
        textColor: 'rgba(255, 255, 255, 0.68)',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.06)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.06)' },
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.12)',
        timeVisible: false,
      } as TimeScaleOptions,
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.12)',
        scaleMargins: { top: 0.08, bottom: 0.4 },
      },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;

    const series = chart.addCandlestickSeries({
      upColor: COLOR.up,
      downColor: COLOR.down,
      borderUpColor: COLOR.up,
      borderDownColor: COLOR.down,
      wickUpColor: COLOR.up,
      wickDownColor: COLOR.down,
    });

    let volumeSeries: ISeriesApi<'Histogram'> | null = null;
    if (showVolume) {
      volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
        color: 'rgba(255, 255, 255, 0.4)',
      });
      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.78, bottom: 0.18 },
      });
    }

    // 全部指标组预创建(系列始终存在,显隐由 seriesMapRef 后续 applyOptions 控制)
    // MA 四线(主图)
    const maLines: Record<'ma5' | 'ma10' | 'ma20' | 'ma60', ISeriesApi<'Line'> | null> = {
      ma5: null,
      ma10: null,
      ma20: null,
      ma60: null,
    };
    (['ma5', 'ma10', 'ma20', 'ma60'] as const).forEach((k) => {
      const line = chart.addLineSeries({
        color: COLOR[k],
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: false,
      });
      maLines[k] = line;
      seriesMapRef.current.ma.push(line);
    });

    // BOLL 三轨(虚线)
    const bollLineOpts: LineSeriesPartialOptions = {
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    };
    const bollUp = chart.addLineSeries({ ...bollLineOpts, color: COLOR.bollUp });
    const bollMid = chart.addLineSeries({ ...bollLineOpts, color: COLOR.bollMid });
    const bollDn = chart.addLineSeries({ ...bollLineOpts, color: COLOR.bollDn });
    seriesMapRef.current.boll.push(bollUp, bollMid, bollDn);

    // MACD:hist + DIF + DEA(独立 priceScaleId)
    const macdHist = chart.addHistogramSeries({
      priceScaleId: 'macd',
      color: COLOR.macdHistPos,
    });
    const macdDif = chart.addLineSeries({
      priceScaleId: 'macd',
      color: COLOR.macdDif,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    const macdDea = chart.addLineSeries({
      priceScaleId: 'macd',
      color: COLOR.macdDea,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    seriesMapRef.current.macd.push(macdHist, macdDif, macdDea);
    chart.priceScale('macd').applyOptions({ scaleMargins: { top: 0.62, bottom: 0.08 } });

    // KDJ:K/D/J(独立 priceScaleId)
    const kdjLineOpt: LineSeriesPartialOptions = {
      priceScaleId: 'kdj',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    };
    const kdjK = chart.addLineSeries({ ...kdjLineOpt, color: COLOR.kdjK });
    const kdjD = chart.addLineSeries({ ...kdjLineOpt, color: COLOR.kdjD });
    const kdjJ = chart.addLineSeries({ ...kdjLineOpt, color: COLOR.kdjJ });
    seriesMapRef.current.kdj.push(kdjK, kdjD, kdjJ);
    chart.priceScale('kdj').applyOptions({ scaleMargins: { top: 0.4, bottom: 0.32 } });

    // 按初始可见性统一应用(visibleGroups 来自 props overlay)
    (Object.keys(seriesMapRef.current) as OverlayGroup[]).forEach((g) => {
      const v = visibleGroups[g];
      seriesMapRef.current[g].forEach((s) => {
        s.applyOptions({ visible: v });
      });
    });

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', onResize);

    apiGet<KlineIndicatorsResponse>(
      `/kline/${encodeURIComponent(stockCode)}/indicators?period=${period}&limit=120`,
    )
      .then((d) => {
        setLoadError(null);
        setIndicators(d.indicators);
        const items = d.items;
        const candle: CandlestickData[] = items.map((it) => ({
          time: it.date as Time,
          open: Number(it.open),
          high: Number(it.high),
          low: Number(it.low),
          close: Number(it.close),
        }));
        series.setData(candle);

        if (volumeSeries) {
          const vol: HistogramData[] = items.map((it) => ({
            time: it.date as Time,
            value: it.volume,
            color:
              Number(it.close) >= Number(it.open)
                ? 'rgba(244, 63, 94, 0.55)'
                : 'rgba(74, 222, 128, 0.55)',
          }));
          volumeSeries.setData(vol);
        }

        const tail = items.length;
        const ind = d.indicators;

        // MA 四线
        const maMap: Record<'ma5' | 'ma10' | 'ma20' | 'ma60', number[]> = {
          ma5: ind.maSeries.ma5,
          ma10: ind.maSeries.ma10,
          ma20: ind.maSeries.ma20,
          ma60: ind.maSeries.ma60,
        };
        (Object.keys(maMap) as Array<keyof typeof maMap>).forEach((k) => {
          const arr = maMap[k];
          const start = tail - arr.length;
          const data: LineData[] = arr.map((v, i) => ({
            time: items[start + i]?.date as Time,
            value: v,
          })).filter((p) => p.time);
          maLines[k]?.setData(data);
        });

        // BOLL
        {
          const offset = tail - ind.boll.upperSeries.length;
          const mapArr = (
            arr: number[],
          ): LineData[] =>
            arr.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
            })).filter((p) => p.time);
          bollUp.setData(mapArr(ind.boll.upperSeries));
          bollMid.setData(mapArr(ind.boll.midSeries));
          bollDn.setData(mapArr(ind.boll.lowerSeries));
        }

        // MACD
        {
          const offset = tail - ind.macd.histSeries.length;
          macdHist.setData(
            ind.macd.histSeries.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
              color: v >= 0 ? COLOR.macdHistPos : COLOR.macdHistNeg,
            })).filter((p) => p.time),
          );
          const lineArr = (
            arr: number[],
          ): LineData[] =>
            arr.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
            })).filter((p) => p.time);
          macdDif.setData(lineArr(ind.macd.difSeries));
          macdDea.setData(lineArr(ind.macd.deaSeries));
        }

        // KDJ
        {
          const offset = tail - ind.kdj.kSeries.length;
          const mapArr = (
            arr: number[],
          ): LineData[] =>
            arr.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
            })).filter((p) => p.time);
          kdjK.setData(mapArr(ind.kdj.kSeries));
          kdjD.setData(mapArr(ind.kdj.dSeries));
          kdjJ.setData(mapArr(ind.kdj.jSeries));
        }

        // 信号标注
        const markers: SeriesMarker<Time>[] = ind.signalSeries.map((m) => ({
          time: m.time as Time,
          position: m.position,
          color: m.color,
          shape: 'circle' as const,
          text: m.text,
        }));
        if (markers.length > 0) {
          try {
            series.setMarkers(markers);
          } catch {
            /* time 排序问题静默 */
          }
        }

        chart.timeScale().fitContent();

        // ---- Hover 同步(图例显示当前值,不改动 series 避免回调死循环) ----
        const tracked: { key: string; series: ISeriesApi<'Line'> }[] = [
          { key: 'ma5', series: maLines.ma5 },
          { key: 'ma10', series: maLines.ma10 },
          { key: 'ma20', series: maLines.ma20 },
          { key: 'ma60', series: maLines.ma60 },
          { key: 'bollUp', series: bollUp },
          { key: 'bollMid', series: bollMid },
          { key: 'bollDn', series: bollDn },
          { key: 'macdDif', series: macdDif },
          { key: 'macdDea', series: macdDea },
          { key: 'kdjK', series: kdjK },
          { key: 'kdjD', series: kdjD },
          { key: 'kdjJ', series: kdjJ },
        ].filter((x): x is { key: string; series: ISeriesApi<'Line'> } => x.series !== null);

        const handleCrosshair = (param: MouseEventParams) => {
          if (!param.time) {
            setHoverValues({});
            return;
          }
          const next: Record<string, number | null> = {};
          tracked.forEach(({ key, series }) => {
            const sd = param.seriesData.get(series) as { value?: number } | undefined;
            next[key] = sd?.value ?? null;
          });
          setHoverValues(next);
        };
        chart.subscribeCrosshairMove(handleCrosshair);

        (chart as unknown as { __cleanupCrosshair?: () => void }).__cleanupCrosshair = () => {
          chart.unsubscribeCrosshairMove(handleCrosshair);
        };
      })
      .catch((e) => {
        const msg =
          (e as { response?: { data?: { detail?: { message?: string } } } })
            ?.response?.data?.detail?.message ??
          (e instanceof Error ? e.message : null) ??
          '行情加载失败';
        setLoadError(msg);
        if (typeof console !== 'undefined') {
          console.warn('[KLineChart] load failed:', stockCode, period, e);
        }
      });

    return () => {
      window.removeEventListener('resize', onResize);
      const cleanup = (chart as unknown as { __cleanupCrosshair?: () => void }).__cleanupCrosshair;
      if (cleanup) cleanup();
      chart.remove();
      chartRef.current = null;
      seriesMapRef.current = {
        ma: [], boll: [], macd: [], kdj: [],
        volume: [], rsi: [], cci: [], stoch: [],
        mom: [], wmsr: [], skt: [], fask: [],
      };
    };
  }, [stockCode, period, height, showVolume]);

  // 切换整组显隐(同时驱动 React 状态与 lightweight-charts series)
  const toggleGroup = (g: OverlayGroup) => {
    const next = !visibleGroups[g];
    setVisibleGroups((v) => ({ ...v, [g]: next }));
    seriesMapRef.current[g].forEach((s) => {
      s.applyOptions({ visible: next });
    });
  };

  // ---- 图例行(整组开关:点击整行 → 切换该组显隐) ----
  // v3:在原有 MA/BOLL/MACD/KDJ 基础上新增 RSI/CCI/STOCH/MOM/WMSR/SKT/FASK
  // 每个新指标组不画线,仅显示当前末值 + state chip + 知识点 tooltip
  const ind = indicators;
  const legendRows: LegendRow[] = [
    {
      group: 'volume',
      label: '成交量',
      term: 'volume',
      currentValue: ind?.volume.ratio != null ? ind.volume.ratio.toFixed(2) : '—',
      state: ind?.volume.state
        ? stateOfVolume(ind.volume.state)
        : null,
      items: [],
    },
    {
      group: 'ma',
      label: 'MA',
      term: 'ma',
      items: [
        { key: 'ma5', label: 'MA5', color: COLOR.ma5, decimals: 2 },
        { key: 'ma10', label: 'MA10', color: COLOR.ma10, decimals: 2 },
        { key: 'ma20', label: 'MA20', color: COLOR.ma20, decimals: 2 },
        { key: 'ma60', label: 'MA60', color: COLOR.ma60, decimals: 2 },
      ],
    },
    {
      group: 'boll',
      label: 'BOLL',
      term: 'boll',
      items: [
        { key: 'bollUp', label: '上轨', color: COLOR.bollUp, decimals: 2 },
        { key: 'bollMid', label: '中轨', color: COLOR.bollMid, decimals: 2 },
        { key: 'bollDn', label: '下轨', color: COLOR.bollDn, decimals: 2 },
      ],
    },
    {
      group: 'macd',
      label: 'MACD',
      term: 'macd',
      state: ind?.macd?.cross
        ? { code: ind.macd.cross, label: ind.macd.cross === 'golden' ? '金叉' : '死叉',
            tone: ind.macd.cross === 'golden' ? 'up' : 'down' }
        : null,
      items: [
        { key: 'macdDif', label: 'DIF', color: COLOR.macdDif, decimals: 4 },
        { key: 'macdDea', label: 'DEA', color: COLOR.macdDea, decimals: 4 },
        { key: 'macdHist', label: 'HIST', color: COLOR.macdHistPos, decimals: 4 },
      ],
    },
    {
      group: 'kdj',
      label: 'KDJ',
      term: 'kdj',
      items: [
        { key: 'kdjK', label: 'K', color: COLOR.kdjK, decimals: 2 },
        { key: 'kdjD', label: 'D', color: COLOR.kdjD, decimals: 2 },
        { key: 'kdjJ', label: 'J', color: COLOR.kdjJ, decimals: 2 },
      ],
    },
    {
      group: 'rsi',
      label: 'RSI',
      term: 'rsi',
      currentValue: ind?.rsi?.rsi != null ? ind.rsi.rsi.toFixed(2) : '—',
      state: stateOfIndicator(ind?.rsi?.state ?? null),
      items: [],
    },
    {
      group: 'cci',
      label: 'CCI',
      term: 'cci',
      currentValue: ind?.cci?.cci != null ? ind.cci.cci.toFixed(2) : '—',
      state: stateOfIndicator(ind?.cci?.state ?? null),
      items: [],
    },
    {
      group: 'stoch',
      label: 'STOCH',
      term: 'stoch',
      currentValue: ind?.stoch?.fastk != null ? `K ${ind.stoch.fastk.toFixed(2)}` : '—',
      state: stateOfIndicator(ind?.stoch?.state ?? null),
      items: [
        { key: 'fastk', label: 'K', color: '#a78bfa', decimals: 2 },
        { key: 'fastd', label: 'D', color: '#fb923c', decimals: 2 },
      ],
    },
    {
      group: 'mom',
      label: 'MOM',
      term: 'mom',
      currentValue: ind?.mom?.mom != null ? ind.mom.mom.toFixed(2) : '—',
      state: stateOfIndicator(ind?.mom?.state ?? null),
      items: [],
    },
    {
      group: 'wmsr',
      label: 'WMSR',
      term: 'wmsr',
      currentValue: ind?.wmsr?.wmsr != null ? ind.wmsr.wmsr.toFixed(2) : '—',
      state: stateOfIndicator(ind?.wmsr?.state ?? null),
      items: [],
    },
    {
      group: 'skt',
      label: 'SKT',
      term: 'skt',
      currentValue: ind?.skt?.slowk != null ? `K ${ind.skt.slowk.toFixed(2)}` : '—',
      state: stateOfIndicator(ind?.skt?.state ?? null),
      items: [
        { key: 'slowk', label: 'K', color: '#22d3ee', decimals: 2 },
        { key: 'slowd', label: 'D', color: '#94a3b8', decimals: 2 },
      ],
    },
    {
      group: 'fask',
      label: 'FASK',
      term: 'fask',
      currentValue: ind?.fask?.fastk != null ? ind.fask.fastk.toFixed(2) : '—',
      state: stateOfIndicator(ind?.fask?.state ?? null),
      items: [],
    },
  ];

  return (
    <div>
      {loadError && (
        <div className="mb-2 px-3 py-1.5 rounded-md bg-down/10 border border-down/30 text-xs text-down">
          ⚠ K 线加载失败:{loadError}(打开浏览器 Console 查看详情)
        </div>
      )}
      <div
        ref={containerRef}
        style={{ width: '100%', height }}
        className="rounded-sm overflow-hidden"
      />
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {legendRows.map((row) => {
          const groupVisible = visibleGroups[row.group];
          return (
            <button
              type="button"
              key={row.group}
              onClick={() => toggleGroup(row.group)}
              className={clsx(
                'flex items-center gap-2 px-1 py-0.5 rounded transition-colors cursor-pointer select-none',
                'hover:bg-white/5',
                !groupVisible && 'opacity-40',
              )}
              title={groupVisible ? `点击隐藏 ${row.label}` : `点击显示 ${row.label}`}
            >
              <span
                className={clsx(
                  'text-text-ter font-medium inline-flex items-center',
                  !groupVisible && 'line-through',
                )}
              >
                {row.label}
                {row.term && <TermHint term={row.term} />}
              </span>
              {/* 单指标图例项(RSI/CCI/MOM 等):显示当前值 + state chip */}
              {row.items.length === 0 && row.currentValue && (
                <>
                  <span className="font-mono text-text-pri min-w-[3rem] text-right">
                    {!groupVisible ? '—' : row.currentValue}
                  </span>
                  {row.state && groupVisible && (
                    <StateChip state={row.state} />
                  )}
                </>
              )}
              {/* 折线图例项(MA/BOLL 等):保留旧 hover 显示 */}
              {row.items.map((it) => {
                const v = hoverValues[it.key];
                return (
                  <span
                    key={it.key}
                    className={clsx(
                      'inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded transition-colors',
                      v != null && groupVisible ? 'bg-white/10' : 'bg-transparent',
                    )}
                  >
                    <span
                      className="inline-block w-3 h-0.5 rounded-sm"
                      style={{ backgroundColor: it.color }}
                    />
                    <span className="text-text-pri">{it.label}</span>
                    <span className="font-mono text-text-sec min-w-[3.5rem] text-right">
                      {!groupVisible
                        ? '—'
                        : v != null
                          ? v.toFixed(it.decimals)
                          : '—'}
                    </span>
                  </span>
                );
              })}
              {/* 双线指标图例项(STOCH/SKT):K/D 当前末值 + state chip */}
              {row.items.length > 0 && row.currentValue && (
                <>
                  {row.state && groupVisible && (
                    <StateChip state={row.state} />
                  )}
                </>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** 图例状态小 chip(超买 / 超卖 / 金叉 / 死叉 / 中性 等) */
function StateChip({ state }: { state: LegendState }) {
  const toneCls =
    state.tone === 'up'
      ? 'bg-up/15 text-up border-up/30'
      : state.tone === 'down'
        ? 'bg-down/15 text-down border-down/30'
        : state.tone === 'accent'
          ? 'bg-accent/15 text-accent border-accent/30'
          : 'bg-white/5 text-text-ter border-white/15';
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-[10px] font-medium',
        toneCls,
      )}
    >
      <span className="w-1 h-1 rounded-full bg-current" />
      {state.label}
    </span>
  );
}