'use client';

import { useEffect, useRef, useState } from 'react';

import clsx from 'clsx';

import {
  createChart,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type MouseEventParams,
  type Time,
} from 'lightweight-charts';

import { apiGet } from '@/lib/api';

/** 分时点(后端 /kline/{code}/intraday) */
interface IntradayPoint {
  time: string; // "HH:MM"
  price: number;
  avg_price: number | null; // 均价线
  volume: number;
}

interface IntradayResponse {
  stock_code: string;
  date: string; // YYYY-MM-DD
  prev_close: string | null;
  count: number;
  items: IntradayPoint[];
}

/** "YYYY-MM-DD" + "HH:MM" → 北京时区 epoch 秒(lightweight timestamp) */
function toTs(date: string, time: string): Time {
  return Math.floor(new Date(`${date}T${time}:00+08:00`).getTime() / 1000) as Time;
}

/**
 * 分时图(M1.1 分时图,roadmap §7 交互规范)
 *
 * - 数据源:`/api/kline/{code}/intraday`(分钟线聚合)
 * - 红线 = 实时价格;黄线 = 当日均价;昨收 = 白色虚线基准
 * - 底部成交量副图(红涨绿跌,以 vs 昨收)
 * - 十字光标:图例联动显示 {时间, 价格, 均价}
 */
export function IntradayChart({
  stockCode,
  height = 420,
}: {
  stockCode: string;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<IntradayResponse | null>(null);
  // 十字光标 hover 值;未 hover 时为 null → 图例回退到最新一根
  const [hover, setHover] = useState<IntradayPoint | null>(null);
  const [hoverTime, setHoverTime] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    setError(null);
    setData(null);
    setHover(null);
    setHoverTime(null);
    let disposed = false;
    const container = containerRef.current;

    const chart = createChart(container, {
      width: container.clientWidth,
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
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.12)',
        scaleMargins: { top: 0.1, bottom: 0.26 },
      },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;

    const priceSeries = chart.addLineSeries({
      color: '#f43f5e',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    const avgSeries: ISeriesApi<'Line'> = chart.addLineSeries({
      color: '#facc15',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const volSeries = chart.addHistogramSeries({
      priceScaleId: 'volume',
      color: 'rgba(255, 255, 255, 0.35)',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });

    const onResize = () => {
      try {
        chart.applyOptions({ width: container.clientWidth });
      } catch {
        /* chart disposed */
      }
    };
    window.addEventListener('resize', onResize);

    const handleCrosshair = (param: MouseEventParams) => {
      if (!param.time) {
        setHover(null);
        setHoverTime(null);
        return;
      }
      setHoverTime(new Date(Number(param.time) * 1000).toTimeString().slice(0, 5));
      const sd = param.seriesData.get(priceSeries) as { value?: number } | undefined;
      const ad = param.seriesData.get(avgSeries) as { value?: number } | undefined;
      setHover({
        time: new Date(Number(param.time) * 1000).toTimeString().slice(0, 5),
        price: sd?.value ?? 0,
        avg_price: ad?.value ?? null,
        volume: 0,
      });
    };
    chart.subscribeCrosshairMove(handleCrosshair);

    apiGet<IntradayResponse>(`/kline/${encodeURIComponent(stockCode)}/intraday`)
      .then((d) => {
        if (disposed) return;
        setData(d);
        const pts = d.items;
        if (!pts.length) return;

        priceSeries.setData(
          pts.map((p) => ({ time: toTs(d.date, p.time), value: p.price })),
        );
        avgSeries.setData(
          pts
            .filter((p) => p.avg_price != null)
            .map((p) => ({ time: toTs(d.date, p.time), value: p.avg_price as number })),
        );

        const prevClose = d.prev_close != null ? Number(d.prev_close) : null;
        volSeries.setData(
          pts.map((p) => ({
            time: toTs(d.date, p.time),
            value: p.volume,
            color:
              prevClose != null
                ? p.price >= prevClose
                  ? 'rgba(244, 63, 94, 0.5)'
                  : 'rgba(74, 222, 128, 0.5)'
                : 'rgba(255, 255, 255, 0.35)',
          })),
        );

        if (prevClose != null) {
          try {
            priceSeries.createPriceLine({
              price: prevClose,
              color: 'rgba(255, 255, 255, 0.5)',
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: '昨收',
            });
          } catch {
            /* 重复创建静默 */
          }
        }

        chart.timeScale().fitContent();
      })
      .catch((e) => {
        const msg =
          (e as { response?: { data?: { detail?: { message?: string } } } })
            ?.response?.data?.detail?.message ??
          (e instanceof Error ? e.message : null) ??
          '分时加载失败';
        setError(msg);
      });

    return () => {
      disposed = true;
      window.removeEventListener('resize', onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [stockCode, height]);

  const pts = data?.items ?? [];
  const latest = hover ?? pts[pts.length - 1] ?? null;
  const prevCloseVal = data?.prev_close != null ? Number(data.prev_close) : null;
  const showTime = hoverTime ?? latest?.time ?? null;
  const latestPct =
    latest && prevCloseVal ? ((latest.price - prevCloseVal) / prevCloseVal) * 100 : null;
  const pctCls =
    latestPct == null
      ? 'text-text-sec'
      : latestPct > 0
        ? 'text-up'
        : latestPct < 0
          ? 'text-down'
          : 'text-text-sec';

  return (
    <div>
      {error && (
        <div className="mb-2 px-3 py-1.5 rounded-md bg-down/10 border border-down/30 text-xs text-down">
          ⚠ {error}
        </div>
      )}
      <div
        ref={containerRef}
        style={{ width: '100%', height }}
        className="rounded-sm overflow-hidden"
      />
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span className="text-text-ter">时间 {showTime ?? '--'}</span>
        <span className={clsx('font-mono', pctCls)}>
          价格 {latest ? latest.price.toFixed(2) : '--'}
          {latestPct != null && (
            <span className="text-text-ter">
              {' '}({latestPct >= 0 ? '+' : ''}
              {latestPct.toFixed(2)}%)
            </span>
          )}
        </span>
        <span className="text-text-ter font-mono">
          均价 {latest && latest.avg_price != null ? Number(latest.avg_price).toFixed(2) : '--'}
        </span>
        {data && <span className="text-text-ter">数据 · {data.date}</span>}
      </div>
    </div>
  );
}