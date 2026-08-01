/**
 * Decimal/金额格式化工具(frontend-arch §12.5.2)
 *
 * 后端 Decimal 序列化为字符串(精度保护),前端不做算术,只格式化显示。
 */
import Decimal from 'decimal.js-light';

/** 数字 → 千分位 + 2 位小数(展示用) */
export function decimalFormat(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  try {
    const d = new Decimal(value);
    // 千分位 + 2 位小数
    return d.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  } catch {
    return String(value);
  }
}

/** 3 位小数(价格展示,如 10.500) */
export function priceFormat(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  try {
    const d = new Decimal(value);
    return d.toFixed(3).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  } catch {
    return String(value);
  }
}

/** 整数千分位(股数) */
export function intFormat(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** 百分比(2 位小数 + 符号) */
export function percentFormat(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}