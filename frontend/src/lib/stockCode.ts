/**
 * 前端股票代码规范化(与后端 app/core/stock_code.py 规则一致,P3.5.1)
 *
 * 内部统一格式:600519.SH / 000001.SZ / 830799.BJ
 * 市场推断:6/9→SH,0/1/2/3→SZ,4/8→BJ
 */

const MARKET_BY_PREFIX: Array<[string, string]> = [
  ['6', 'SH'],
  ['9', 'SH'],
  ['0', 'SZ'],
  ['1', 'SZ'],
  ['2', 'SZ'],
  ['3', 'SZ'],
  ['4', 'BJ'],
  ['8', 'BJ'],
];

/** 任意格式 → 带后缀统一格式;非法返回 null */
export function normalizeCode(code: string): string | null {
  if (!code) return null;
  let c = code.trim().toLowerCase();
  // 去 sh/sz/bj 前缀
  if ((c.startsWith('sh') || c.startsWith('sz') || c.startsWith('bj')) && c.length >= 8) {
    c = c.slice(2);
  }
  // 带后缀
  if (c.includes('.')) {
    const parts = c.split('.');
    if (parts.length !== 2) return null;
    const [num, market] = parts;
    if (!num || !market) return null;
    if (num.length !== 6 || !/^\d{6}$/.test(num)) return null;
    const m = market.toUpperCase();
    if (!['SH', 'SZ', 'BJ'].includes(m)) return null;
    return `${num}.${m}`;
  }
  // 纯 6 位 → 推断
  if (/^\d{6}$/.test(c)) {
    for (const [prefix, market] of MARKET_BY_PREFIX) {
      if (c.startsWith(prefix)) return `${c}.${market}`;
    }
  }
  return null;
}
