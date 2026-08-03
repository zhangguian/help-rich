'use client';

import { useEffect, useRef, useState } from 'react';

import clsx from 'clsx';

import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts';

import { apiGet } from '@/lib/api';

/** 三线叠加数据(/api/kline/{code}/overview) */
interface OverviewPoint {
  date: string;
  close: number;
}
interface OverviewResponse {
  stockCode: string;
  industry: string | null;
  count: number;
  lines: { stock: OverviewPoint[]; index: OverviewPoint[]; sector: OverviewPoint[] };
  sectorUnavailable: boolean;
}

const LINE_COLOR = { stock: '#3B82F6', index: '#F59E0B', sector: '#8B5CF6' } as const;
type LineKey = keyof typeof LINE_COLOR;
const LINE_LABEL: Record<LineKey, string> = { stock: '该股', index: '大盘', sector: '行业' };

/**
 * M2.3 三线叠加:个股 / 大盘(000001) / 行业(成分等权) 归一化对比
 *
 * - 数据源:/api/kline/{code}/overview(后端已完成归一化,基准=首个共同日100,
 *   右轴即相对涨跌)
 * - 图例点击切换显隐(lineWidth 0 隐藏);行业不可用自动隐藏并置灰
 */
export function CompareChart({ stockCode, height = 180 }: { stockCode: string; height?: number }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<Partial<Record<LineKey, ISeriesApi<'Line'>>>>({});
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState<Record<LineKey, boolean>>({
    stock: true,
    index: true,
    sector: true,
  });

  // 拉数据(切换股票重载;加载失败降级提示,不影响主图)
  useEffect(() => {
    let cancelled = false;
    setError(null);
    setData(null);
    apiGet<OverviewResponse & { industry: string | null }>(
      `/kline/${encodeURIComponent(stockCode)}/overview`,
      { timeout: 20000 },
    )
      .then((d) => {
        if (cancelled) return;
        setData(d);
        // 行业不可用(tab)默认隐藏行业线
        if (d.sectorUnavailable || !d.lines.sector?.length) {
          setVisible((v) => ({ ...v, sector: false }));
        }
      })
      .catch(() => {
        if (!cancelled) setError('三线对比加载失败(可能网络波动)');
      });
    return () => {
      cancelled = true;
    };
  }, [stockCode]);

  // 建图
  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: { background: { color: 'transparent' }, textColor: 'rgba(255,255,255,0.68)' },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.05)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      timeScale: { borderColor: 'rgba(255,255,255,0.12)', timeVisible: false, rightOffset: 3 },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.12)', scaleMargins: { top: 0.1, bottom: 0.12 } },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;
    (Object.keys(LINE_COLOR) as LineKey[]).forEach((k) => {
      seriesRef.current[k] = chart.addLineSeries({
        color: LINE_COLOR[k],
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: true,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      });
    });

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && chartRef.current) chartRef.current.applyOptions({ width: w });
    });
    ro.observe(containerRef.current);
    return () => {
      disposed = true;
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = {};
    };
  }, [height]);

  // 数据 → 序列
  useEffect(() => {
    if (!data) return;
    (Object.keys(LINE_COLOR) as LineKey[]).forEach((k) => {
      const s = seriesRef.current[k];
      const pts = data.lines[k];
      if (!s) return;
      try {
        s.setData(
          (pts ?? []).map((p) => ({ time: p.date as Time, value: p.close }) as LineData),
        );
      } catch {
        /* chart disposed */
      }
    });
  }, [data]);

  // 显隐切换(隐藏时把 color 设成透明;lightweight-charts 不支持 lineWidth=0)
  useEffect(() => {
    (Object.keys(LINE_COLOR) as LineKey[]).forEach((k) => {
      const s = seriesRef.current[k];
      if (!s) return;
      const canShow = k !== 'sector' || !!data?.lines.sector?.length;
      const on = visible[k] && canShow;
      try {
        s.applyOptions({ color: on ? LINE_COLOR[k] : 'transparent' });
      } catch {
        /* chart disposed */
      }
    });
  }, [visible, data]);

  return (
    <div>
      <div className="flex items-center gap-1.5 flex-wrap mb-1">
        <span className="text-xs text-text-ter uppercase tracking-wide">三线叠加</span>
        {(Object.keys(LINE_LABEL) as LineKey[]).map((k) => {
          const disabled = k === 'sector' && (!data?.lines.sector?.length || data?.sectorUnavailable);
          const on = visible[k];
          return (
            <button
              key={k}
              disabled={!!disabled}
              onClick={() => setVisible((v) => ({ ...v, [k]: !v[k] }))}
              className={clsx(
                'text-[10px] px-1.5 py-px rounded-full border transition-opacity',
                disabled && 'opacity-30 cursor-not-allowed',
                !on && 'opacity-40',
              )}
              style={{ color: LINE_COLOR[k], borderColor: `${LINE_COLOR[k]}55` }}
              title={disabled ? '行业数据暂不可用' : LINE_LABEL[k]}
            >
              <span
                className="inline-block w-1.5 h-1.5 rounded-full mr-1 align-middle"
                style={{ backgroundColor: on ? LINE_COLOR[k] : 'transparent' }}
              />
              {LINE_LABEL[k]}
            </button>
          );
        })}
        <span className="text-[10px] text-text-ter ml-auto">基准=100 · 看谁相对涨得多</span>
      </div>
      {error ? (
        <div className="text-xs text-warn h-[180px] flex items-center justify-center">{error}</div>
      ) : (
        <div ref={containerRef} style={{ height }} className="w-full" />
      )}
    </div>
  );
}