import type { SignalMarker } from '@/lib/types';

/**
 * K 线信号标记的命中测试(K 线图悬停解释)
 *
 * ## 为什么需要自己算
 *
 * lightweight-charts 的 marker 是 `series.setMarkers()` 画在 **canvas** 上的,
 * 没有 DOM 节点 → 原生 `title` / `hover` 都不生效,鼠标移上去什么也不会发生。
 * 想做「悬停出解释」,只能自己做两层:
 *
 * 1. **几何命中测试**:复刻库内部绘制 marker 的公式,算出每个标记文字的中心坐标,
 *    鼠标落在附近就命中。
 * 2. **DOM 浮层**:命中后用自己的 DOM 浮层显示解释(浮层是 DOM,天然可 hover/可读屏)。
 *
 * ## 几何公式的来源
 *
 * 对齐 lightweight-charts 4.2.3 源码(见 node_modules/lightweight-charts):
 * - `shapeSize(barSpacing)` = clamp(barSpacing, 12, 30) → 再取偶数(calculateShapeHeight)
 * - `shapeMargin(barSpacing)` = max(clamp(barSpacing,12,30) * 0.1, 3) ≡ **恒为 3**
 * - `aboveBar` 的形状 y = priceToCoordinate(high) − halfSize − offset
 *   文字 y = 形状 y − halfSize − fontSize × 0.6(textBaseline=middle,故为文字中心)
 * - `belowBar` 对称:形状 y = priceToCoordinate(low) + halfSize + offset,
 *   文字 y = 形状 y + halfSize + shapeMargin + fontSize × 0.6
 * - 同一根 K 线上同方向的多个标记会**向上/向下堆叠**,每个标记占
 *   `fontSize × 1.2 + shapeSize + shapeMargin`
 * - 文字**水平居中于该根 K 线**(text x = barX − textWidth / 2)
 *
 * 公式对不齐的后果是「鼠标指着字却没反应」,所以:
 * - 文字宽度用**同一套字体**在 canvas 上 `measureText` 量出来(与库内部一致)
 * - 命中判定额外留了余量(半宽 +4px / 半高 fontSize×0.8)
 * - 命中不到文字时,再兜底测一次**小圆点**(库自己也是这么判的)
 */

/** lightweight-charts 的形状尺寸下限/上限 */
const MIN_SHAPE_SIZE = 12;
const MAX_SHAPE_SIZE = 30;
/** 文字与形状的相对间距系数(库内 Constants.TextMargin) */
const TEXT_MARGIN = 0.1;

export interface SignalMarkerHit {
  /** 在 signalSeries 里的下标 */
  index: number;
  /** 去掉 emoji 的标记名(如「BOLL 收口」),用于查词典 */
  name: string;
  /** 后端原始 text(含 emoji) */
  text: string;
  /** 文字中心 x(相对图表容器) */
  cx: number;
  /** 文字中心 y(相对图表容器) */
  cy: number;
  /** 命中半宽(文字宽的一半 + 余量) */
  halfW: number;
  /** 命中半高 */
  halfH: number;
  /** 小圆点中心(命中兜底:直接戳到圆点也算) */
  shapeX: number;
  shapeY: number;
  shapeR: number;
  /**
   * 信号发生**当日**的数值依据(仅四类异动行为标注有)。
   *
   * ⚠️ 与「当前这只票的真实数据」是**两回事**:
   * 现在线是末根 K 线的当前值,依据是信号当天的事实 ——
   * 不能混用,否则会把 10-28 的信号配上 10-30 的现价。
   */
  reason?: string | undefined;
}

/** 去掉后端 text 里的 emoji:「⚠️ BOLL 收口」→「BOLL 收口」 */
export function markerName(text: string): string {
  const i = text.indexOf(' ');
  const rest = i >= 0 ? text.slice(i + 1) : text;
  return rest.trim() || text.trim();
}

/** 复刻库的 `size$1`:clamp(barSpacing, 12, 30) */
function shapeBaseSize(barSpacing: number): number {
  return Math.min(Math.max(barSpacing, MIN_SHAPE_SIZE), MAX_SHAPE_SIZE);
}

/** 复刻库的 `calculateShapeHeight`:向上取偶数 */
function shapeHeight(barSpacing: number): number {
  const s = shapeBaseSize(barSpacing);
  return Math.ceil(s / 2) * 2;
}

/** 复刻库的 `shapeMargin`:max(clamp(bs,12,30)*0.1, 3) ≡ 3 */
function shapeMargin(): number {
  return 3;
}

/** 量文字宽度:与库内部用同一套字体(canvas measureText),避免「量不准导致命中偏移」 */
let measureCtx: CanvasRenderingContext2D | null = null;
export function measureSignalText(text: string, fontSize: number, fontFamily: string): number {
  if (typeof document === 'undefined') return text.length * fontSize * 0.6;
  if (!measureCtx) {
    const c = document.createElement('canvas');
    measureCtx = c.getContext('2d');
  }
  if (!measureCtx) return text.length * fontSize * 0.6;
  measureCtx.font = `${fontSize}px ${fontFamily}`;
  return measureCtx.measureText(text).width;
}

export interface SignalMarkerGeometryInput {
  /** 后端 signal_series */
  markers: SignalMarker[];
  /** date → 当根 K 线的 OHLC(用于 priceToCoordinate) */
  barOf: Map<string, { high: number; low: number; close: number }>;
  /** 时间 → x 坐标(chart.timeScale().timeToCoordinate) */
  timeToX: (time: string) => number | null;
  /** 价格 → y 坐标(series.priceToCoordinate) */
  priceToY: (price: number) => number | null;
  /** 当前柱间距(用于形状尺寸) */
  barSpacing: number;
  /** 图表字号 */
  fontSize: number;
  /** 图表字体 */
  fontFamily: string;
}

/** 复刻库的 marker 布局,算出每个标记文字的中心坐标与命中框 */
export function computeSignalMarkerHits(
  input: SignalMarkerGeometryInput,
): SignalMarkerHit[] {
  const { markers, barOf, timeToX, priceToY, barSpacing, fontSize, fontFamily } = input;
  const size = shapeHeight(barSpacing);
  const halfSize = size / 2;
  const margin = shapeMargin();
  const circleSize = shapeBaseSize(barSpacing) * 0.8;
  const out: SignalMarkerHit[] = [];

  // 同方向堆叠的累计偏移(库内按「每根新 K 线重置」)
  let offAbove = 0;
  let offBelow = 0;
  let prevTime: string | null = null;

  markers.forEach((m, index) => {
    if (m.time !== prevTime) {
      offAbove = 0;
      offBelow = 0;
      prevTime = m.time;
    }
    const x = timeToX(m.time);
    const bar = barOf.get(m.time);
    if (x == null || !bar) return;

    let shapeY: number;
    let textY: number;
    if (m.position === 'aboveBar') {
      const highY = priceToY(bar.high);
      if (highY == null) return;
      shapeY = highY - halfSize - (margin + offAbove);
      textY = shapeY - halfSize - fontSize * (0.5 + TEXT_MARGIN);
      offAbove += fontSize * (1 + 2 * TEXT_MARGIN) + size + margin;
    } else if (m.position === 'belowBar') {
      const lowY = priceToY(bar.low);
      if (lowY == null) return;
      shapeY = lowY + halfSize + (margin + offBelow);
      textY = shapeY + halfSize + margin + fontSize * (0.5 + TEXT_MARGIN);
      offBelow += fontSize * (1 + 2 * TEXT_MARGIN) + size + margin;
    } else {
      const closeY = priceToY(bar.close);
      if (closeY == null) return;
      shapeY = closeY;
      textY = shapeY + halfSize + margin + fontSize * (0.5 + TEXT_MARGIN);
    }

    const width = measureSignalText(m.text, fontSize, fontFamily);
    out.push({
      index,
      name: markerName(m.text),
      text: m.text,
      cx: x,
      cy: textY,
      halfW: width / 2 + 4,
      halfH: fontSize * 0.8,
      shapeX: x,
      shapeY,
      shapeR: 2 + circleSize / 2,
      reason: m.reason,
    });
  });

  return out;
}

/**
 * 命中判定:先测文字框(取最接近的一个),再兜底测小圆点。
 * 坐标系与 lightweight-charts 的 pane 坐标一致(相对图表容器左上角)。
 */
export function hitTestSignalMarker(
  hits: SignalMarkerHit[],
  x: number,
  y: number,
): SignalMarkerHit | null {
  let best: SignalMarkerHit | null = null;
  let bestScore = Infinity;
  for (const h of hits) {
    const dx = x - h.cx;
    const dy = y - h.cy;
    if (Math.abs(dx) > h.halfW || Math.abs(dy) > h.halfH) continue;
    const score = Math.abs(dx) / h.halfW + Math.abs(dy) / h.halfH;
    if (score < bestScore) {
      bestScore = score;
      best = h;
    }
  }
  if (best) return best;
  for (const h of hits) {
    const dx = x - h.shapeX;
    const dy = y - h.shapeY;
    if (Math.sqrt(dx * dx + dy * dy) <= h.shapeR) return h;
  }
  return null;
}
