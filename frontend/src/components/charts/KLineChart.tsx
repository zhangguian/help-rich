'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

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

/** 主图叠加层开关(默认 MA 四线 + BOLL) */
export interface ChartOverlay {
  ma5?: boolean;
  ma10?: boolean;
  ma20?: boolean;
  ma60?: boolean;
  boll?: boolean;
  macd?: boolean;
  kdj?: boolean;
  volume?: boolean;
}

const DEFAULT_OVERLAY: Required<ChartOverlay> = {
  ma5: false,
  ma10: false,
  ma20: true,
  ma60: true,
  boll: true,
  macd: true,
  kdj: true,
  volume: true,
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
  /** 同一指标内多个值(预留,本版本未用) */
  values?: number[];
  /** hover 时是否显示的 series(用于决定是否亮起) */
  seriesRefs?: ISeriesApi<'Line'>[];
}

interface LegendRow {
  group: '主图 MA' | 'BOLL' | 'MACD' | 'KDJ';
  items: { key: string; label: string; color: string; series: ISeriesApi<'Line'> | null }[];
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
  // 图例:每条线在 hover 时间点的当前值(未 hover 时为 null)
  const [hoverValues, setHoverValues] = useState<Record<string, number | null>>({});

  const ov: Required<ChartOverlay> = { ...DEFAULT_OVERLAY, ...overlay, volume: showVolume };

  useEffect(() => {
    if (!containerRef.current) return;
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
    if (ov.volume) {
      volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
        color: 'rgba(255, 255, 255, 0.4)',
      });
      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.78, bottom: 0.18 },
      });
    }

    // 收集所有 line series 用于图例 + 高亮控制
    const maLines: Record<'ma5' | 'ma10' | 'ma20' | 'ma60', ISeriesApi<'Line'> | null> = {
      ma5: null,
      ma10: null,
      ma20: null,
      ma60: null,
    };

    // BOLL 三轨(虚线)
    let bollUp: ISeriesApi<'Line'> | null = null;
    let bollMid: ISeriesApi<'Line'> | null = null;
    let bollDn: ISeriesApi<'Line'> | null = null;
    if (ov.boll) {
      const lineOpts: LineSeriesPartialOptions = {
        lineWidth: 1,
        lineStyle: 2, // Dashed
        color: COLOR.bollMid,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: false,
      };
      bollUp = chart.addLineSeries({ ...lineOpts, color: COLOR.bollUp });
      bollMid = chart.addLineSeries({ ...lineOpts, color: COLOR.bollMid });
      bollDn = chart.addLineSeries({ ...lineOpts, color: COLOR.bollDn });
    }

    // MACD:hist + DIF + DEA(独立 priceScaleId)
    let macdHist: ISeriesApi<'Histogram'> | null = null;
    let macdDif: ISeriesApi<'Line'> | null = null;
    let macdDea: ISeriesApi<'Line'> | null = null;
    if (ov.macd) {
      macdHist = chart.addHistogramSeries({
        priceScaleId: 'macd',
        color: COLOR.macdHistPos,
      });
      macdDif = chart.addLineSeries({
        priceScaleId: 'macd',
        color: COLOR.macdDif,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      macdDea = chart.addLineSeries({
        priceScaleId: 'macd',
        color: COLOR.macdDea,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      chart.priceScale('macd').applyOptions({ scaleMargins: { top: 0.62, bottom: 0.08 } });
    }

    // KDJ:K/D/J(独立 priceScaleId)
    let kdjK: ISeriesApi<'Line'> | null = null;
    let kdjD: ISeriesApi<'Line'> | null = null;
    let kdjJ: ISeriesApi<'Line'> | null = null;
    if (ov.kdj) {
      const lineOpt: LineSeriesPartialOptions = {
        priceScaleId: 'kdj',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: false,
      };
      kdjK = chart.addLineSeries({ ...lineOpt, color: COLOR.kdjK });
      kdjD = chart.addLineSeries({ ...lineOpt, color: COLOR.kdjD });
      kdjJ = chart.addLineSeries({ ...lineOpt, color: COLOR.kdjJ });
      chart.priceScale('kdj').applyOptions({ scaleMargins: { top: 0.4, bottom: 0.32 } });
    }

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

        // MA 序列对齐:ma_series 末尾 N 个对应 items 末尾 N 个
        const tail = items.length;
        const ind = d.indicators;
        const maMap: Record<'ma5' | 'ma10' | 'ma20' | 'ma60', number[]> = {
          ma5: ind.maSeries.ma5,
          ma10: ind.maSeries.ma10,
          ma20: ind.maSeries.ma20,
          ma60: ind.maSeries.ma60,
        };
        const maFlags = {
          ma5: ov.ma5,
          ma10: ov.ma10,
          ma20: ov.ma20,
          ma60: ov.ma60,
        };
        (Object.keys(maMap) as Array<keyof typeof maMap>).forEach((k) => {
          if (!maFlags[k]) return;
          const arr = maMap[k];
          const start = tail - arr.length;
          const data: LineData[] = arr.map((v, i) => ({
            time: items[start + i]?.date as Time,
            value: v,
          })).filter((p) => p.time);
          const line = chart.addLineSeries({
            color: COLOR[k],
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: true,
            crosshairMarkerVisible: false,
          });
          line.setData(data);
          maLines[k] = line;
        });

        // BOLL 序列对齐
        if (ov.boll && bollUp && bollMid && bollDn) {
          const offset = tail - ind.boll.upperSeries.length;
          bollUp.setData(
            ind.boll.upperSeries.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
            })).filter((p) => p.time),
          );
          bollMid.setData(
            ind.boll.midSeries.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
            })).filter((p) => p.time),
          );
          bollDn.setData(
            ind.boll.lowerSeries.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
            })).filter((p) => p.time),
          );
        }

        // MACD
        if (ov.macd && macdHist && macdDif && macdDea) {
          const offset = tail - ind.macd.histSeries.length;
          macdHist.setData(
            ind.macd.histSeries.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
              color: v >= 0 ? COLOR.macdHistPos : COLOR.macdHistNeg,
            })).filter((p) => p.time),
          );
          macdDif.setData(
            ind.macd.difSeries.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
            })).filter((p) => p.time),
          );
          macdDea.setData(
            ind.macd.deaSeries.map((v, i) => ({
              time: items[offset + i]?.date as Time,
              value: v,
            })).filter((p) => p.time),
          );
        }

        // KDJ
        if (ov.kdj && kdjK && kdjD && kdjJ) {
          const offset = tail - ind.kdj.kSeries.length;
          const map = (
            arr: number[],
          ): LineData[] =>
            arr.map((v, i) => ({ time: items[offset + i]?.date as Time, value: v }))
              .filter((p) => p.time);
          kdjK.setData(map(ind.kdj.kSeries));
          kdjD.setData(map(ind.kdj.dSeries));
          kdjJ.setData(map(ind.kdj.jSeries));
        }

        // 信号标注(lightweight-charts v4 需要 shape 字段)
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
        // 收集「可读值」的 series 列表(主图 MA / BOLL / MACD / KDJ)
        const tracked: { key: string; series: ISeriesApi<'Line'> }[] = (
          [
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
          ].filter((x): x is { key: string; series: ISeriesApi<'Line'> } => x.series !== null)
        );

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
      .catch(() => {
        /* 失败静默 */
      });

    return () => {
      window.removeEventListener('resize', onResize);
      // 取消 crosshair 订阅(若已注册)
      const cleanup = (chart as unknown as { __cleanupCrosshair?: () => void }).__cleanupCrosshair;
      if (cleanup) cleanup();
      chart.remove();
      chartRef.current = null;
      bollUp = bollMid = bollDn = null;
      macdHist = macdDif = macdDea = null;
      kdjK = kdjD = kdjJ = null;
      volumeSeries = null;
    };
  }, [stockCode, period, height, ov.ma5, ov.ma10, ov.ma20, ov.ma60, ov.boll, ov.macd, ov.kdj, ov.volume, showVolume]);

  // ---- 图例行(hover 时显示当前值,非 hover 时静态展示颜色) ----
  const legendRows = useMemo<LegendRow[]>(() => {
    const rows: LegendRow[] = [];
    if (ov.ma5 || ov.ma10 || ov.ma20 || ov.ma60) {
      rows.push({
        group: '主图 MA',
        items: [
          ov.ma5 && { key: 'ma5', label: 'MA5', color: COLOR.ma5, series: null },
          ov.ma10 && { key: 'ma10', label: 'MA10', color: COLOR.ma10, series: null },
          ov.ma20 && { key: 'ma20', label: 'MA20', color: COLOR.ma20, series: null },
          ov.ma60 && { key: 'ma60', label: 'MA60', color: COLOR.ma60, series: null },
        ].filter(Boolean) as LegendRow['items'],
      });
    }
    if (ov.boll) {
      rows.push({
        group: 'BOLL',
        items: [
          { key: 'bollUp', label: '上轨', color: COLOR.bollUp, series: null },
          { key: 'bollMid', label: '中轨', color: COLOR.bollMid, series: null },
          { key: 'bollDn', label: '下轨', color: COLOR.bollDn, series: null },
        ],
      });
    }
    if (ov.macd) {
      rows.push({
        group: 'MACD',
        items: [
          { key: 'macdDif', label: 'DIF', color: COLOR.macdDif, series: null },
          { key: 'macdDea', label: 'DEA', color: COLOR.macdDea, series: null },
          { key: 'macdHist', label: 'HIST', color: COLOR.macdHistPos, series: null },
        ],
      });
    }
    if (ov.kdj) {
      rows.push({
        group: 'KDJ',
        items: [
          { key: 'kdjK', label: 'K', color: COLOR.kdjK, series: null },
          { key: 'kdjD', label: 'D', color: COLOR.kdjD, series: null },
          { key: 'kdjJ', label: 'J', color: COLOR.kdjJ, series: null },
        ],
      });
    }
    return rows;
  }, [ov.ma5, ov.ma10, ov.ma20, ov.ma60, ov.boll, ov.macd, ov.kdj]);

  return (
    <div>
      <div
        ref={containerRef}
        style={{ width: '100%', height }}
        className="rounded-sm overflow-hidden"
      />
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {legendRows.map((row) => (
          <div key={row.group} className="flex items-center gap-2">
            <span className="text-text-ter font-medium">{row.group}</span>
            {row.items.map((it) => {
              const v = hoverValues[it.key];
              return (
                <span
                  key={it.key}
                  className={clsx(
                    'inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded transition-colors',
                    v != null ? 'bg-white/10' : 'bg-transparent',
                  )}
                >
                  <span
                    className="inline-block w-3 h-0.5 rounded-sm"
                    style={{ backgroundColor: it.color }}
                  />
                  <span className="text-text-pri">{it.label}</span>
                  <span className="font-mono text-text-sec min-w-[3.5rem] text-right">
                    {v != null
                      ? it.key.startsWith('kdj')
                        ? v.toFixed(2)
                        : it.key === 'macdHist' || it.key === 'macdDif' || it.key === 'macdDea'
                          ? v.toFixed(4)
                          : v.toFixed(2)
                      : '—'}
                  </span>
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}