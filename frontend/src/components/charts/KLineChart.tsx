'use client';

import { useEffect, useRef } from 'react';

import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts';

import { apiGet } from '@/lib/api';

interface KlineItem {
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

export type KlinePeriod = 'daily' | 'weekly' | 'monthly' | '60min';

/**
 * K 线图(v0.4 增强版,roadmap 功能6)
 *
 * - 主图 K 线(红涨绿跌,中国惯例)
 * - 成交量副图(与 K 线同色,可开关)
 * - 周期切换:日/周/月/60分(period 变化自动重拉)
 * - 向后兼容:默认 daily + 无量副图(旧引用不破坏)
 */
export function KLineChart({
  stockCode,
  period = 'daily',
  showVolume = true,
  height = 420,
}: {
  stockCode: string;
  period?: KlinePeriod;
  showVolume?: boolean;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);

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
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.12)',
        scaleMargins: { top: 0.08, bottom: showVolume ? 0.28 : 0.08 },
      },
      crosshair: {
        mode: 0, // Magnet
      },
    });
    const series = chart.addCandlestickSeries({
      upColor: '#f43f5e', // 中国红涨
      downColor: '#4ade80', // 中国绿跌
      borderUpColor: '#f43f5e',
      borderDownColor: '#4ade80',
      wickUpColor: '#f43f5e',
      wickDownColor: '#4ade80',
    });
    chartRef.current = chart;
    seriesRef.current = series;

    let volumeSeries: ISeriesApi<'Histogram'> | null = null;
    if (showVolume) {
      volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.78, bottom: 0 },
      });
      volumeRef.current = volumeSeries;
    }

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', onResize);

    apiGet<{ items: KlineItem[] }>(
      `/kline/${encodeURIComponent(stockCode)}?period=${period}&limit=120`,
    )
      .then((d) => {
        const data: CandlestickData[] = d.items.map((it) => ({
          time: it.date,
          open: Number(it.open),
          high: Number(it.high),
          low: Number(it.low),
          close: Number(it.close),
        }));
        series.setData(data);
        if (volumeSeries && showVolume) {
          const vol: HistogramData[] = d.items.map((it) => ({
            time: it.date,
            value: it.volume,
            color:
              Number(it.close) >= Number(it.open)
                ? 'rgba(244, 63, 94, 0.55)'
                : 'rgba(74, 222, 128, 0.55)',
          }));
          volumeSeries.setData(vol);
        }
        chart.timeScale().fitContent();
      })
      .catch(() => {
        // 失败静默(MVP),真实环境可加 toast
      });

    return () => {
      window.removeEventListener('resize', onResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volumeRef.current = null;
    };
  }, [stockCode, period, showVolume, height]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height }}
      className="rounded-sm overflow-hidden"
    />
  );
}
