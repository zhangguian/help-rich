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
import type { KlineIndicatorsResponse } from '@/lib/types';

export type KlinePeriod = 'daily' | 'weekly' | 'monthly' | '60min';

/** 指标组(整组开关) */
export type OverlayGroup = 'ma' | 'boll' | 'macd' | 'kdj';

/** 外部覆盖初始显隐(可选) */
export interface ChartOverlay {
  ma?: boolean;
  boll?: boolean;
  macd?: boolean;
  kdj?: boolean;
}

/** 默认显示:MA 四线 + MACD;BOLL/KDJ 默认隐藏 */
const DEFAULT_VISIBLE: Record<OverlayGroup, boolean> = {
  ma: true,
  boll: false,
  macd: true,
  kdj: false,
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
}

interface LegendRow {
  group: OverlayGroup;
  label: string;
  items: LegendItem[];
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
      seriesMapRef.current = { ma: [], boll: [], macd: [], kdj: [] };
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
  const legendRows: LegendRow[] = [
    {
      group: 'ma',
      label: '主图 MA',
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
      items: [
        { key: 'bollUp', label: '上轨', color: COLOR.bollUp, decimals: 2 },
        { key: 'bollMid', label: '中轨', color: COLOR.bollMid, decimals: 2 },
        { key: 'bollDn', label: '下轨', color: COLOR.bollDn, decimals: 2 },
      ],
    },
    {
      group: 'macd',
      label: 'MACD',
      items: [
        { key: 'macdDif', label: 'DIF', color: COLOR.macdDif, decimals: 4 },
        { key: 'macdDea', label: 'DEA', color: COLOR.macdDea, decimals: 4 },
        { key: 'macdHist', label: 'HIST', color: COLOR.macdHistPos, decimals: 4 },
      ],
    },
    {
      group: 'kdj',
      label: 'KDJ',
      items: [
        { key: 'kdjK', label: 'K', color: COLOR.kdjK, decimals: 2 },
        { key: 'kdjD', label: 'D', color: COLOR.kdjD, decimals: 2 },
        { key: 'kdjJ', label: 'J', color: COLOR.kdjJ, decimals: 2 },
      ],
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
                  'text-text-ter font-medium',
                  !groupVisible && 'line-through',
                )}
              >
                {row.label}
              </span>
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
            </button>
          );
        })}
      </div>
    </div>
  );
}