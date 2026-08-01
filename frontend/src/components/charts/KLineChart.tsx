'use client';

import { useEffect, useRef } from 'react';

import {
  createChart,
  type CandlestickData,
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

/**
 * 日 K 线图(D,frontend-arch §11.5)
 *
 * - TradingView Lightweight Charts(~200KB)
 * - 绿色涨 / 红色跌(中国惯例)
 * - 自动适配容器尺寸
 */
export function KLineChart({ stockCode, height = 320 }: { stockCode: string; height?: number }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: 'transparent' },
        textColor: '#525252',
      },
      grid: {
        vertLines: { color: '#e5e5e5' },
        horzLines: { color: '#e5e5e5' },
      },
      timeScale: {
        borderColor: '#d4d4d4',
        timeVisible: false,
      },
      rightPriceScale: {
        borderColor: '#d4d4d4',
      },
      crosshair: {
        mode: 0, // Magnet
      },
    });
    const series = chart.addCandlestickSeries({
      upColor: '#dc2626', // 中国红涨
      downColor: '#16a34a', // 中国绿跌
      borderUpColor: '#dc2626',
      borderDownColor: '#16a34a',
      wickUpColor: '#dc2626',
      wickDownColor: '#16a34a',
    });
    chartRef.current = chart;
    seriesRef.current = series;

    // 自适应宽度
    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', onResize);

    // 拉数据
    apiGet<{ items: KlineItem[] }>(`/kline/${encodeURIComponent(stockCode)}?limit=60`)
      .then((d) => {
        const data: CandlestickData[] = d.items.map((it) => ({
          time: it.date,
          open: Number(it.open),
          high: Number(it.high),
          low: Number(it.low),
          close: Number(it.close),
        }));
        seriesRef.current?.setData(data);
        chartRef.current?.timeScale().fitContent();
      })
      .catch(() => {
        // 失败静默(MVP),真实环境可加 toast
      });

    return () => {
      window.removeEventListener('resize', onResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [stockCode, height]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height }}
      className="rounded-sm overflow-hidden"
    />
  );
}