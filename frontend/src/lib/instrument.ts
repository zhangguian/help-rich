/**
 * 标的品种识别(场内 ETF / 股票)—— 与后端 app/core/instrument.py 规则一致
 *
 * **为什么前端也要有一份表**:品种徽章要出现在自选/持仓列表里,
 * 而那些列表接口不返回品种属性 → 前端得能本地查到「类别 / 跟踪指数 / 是否 T+0」。
 *
 * **怎么防两份表漂移**:前端这份 JSON 是**从后端表生成**的
 * (backend/app/data/etf_instruments.json → frontend/src/lib/etfInstruments.json),
 * 并且后端有一条测试逐项比对两份表
 * (backend/tests/test_instrument.py::TestFrontendTableConsistency)
 * —— 后端表一改而前端没同步,CI 就红。
 */
import etfInstruments from './etfInstruments.json';

export interface InstrumentMeta {
  /** 是否场内 ETF(命中品种表,或代码符合 ETF 格式) */
  isEtf: boolean;
  /** 品种类别 broad/industry/qdii/commodity/bond/money;null = 未知(表外 ETF) */
  category: string | null;
  /** 类别中文名(宽基/行业/QDII/商品/债券/货币) */
  categoryLabel: string | null;
  /** 跟踪指数名(ETF 专用) */
  indexName: string | null;
  /** 场内简称 */
  displayName: string | null;
  /** 是否当日可回转(T+0:跨境/黄金/商品 ETF) */
  t0: boolean;
  /** 是否命中品种表(false = 表外 ETF,已按保守口径处理) */
  known: boolean;
  /** 场内基金形态:'etf' | 'lof'(上市开放式基金,交易规则一致但不是 ETF) */
  form: 'etf' | 'lof';
}

type TableItem = {
  code: string;
  name?: string | null;
  index?: string | null;
  category?: string | null;
  t0?: boolean;
  form?: string | null;
};

const ITEMS = etfInstruments.items as TableItem[];
const CATEGORIES = etfInstruments.categories as Record<string, string>;

// 场内 ETF/LOF 的代码格式(与后端 core/instrument.py 一致):
//   5xxxxx.SH → 沪市 ETF(51/56/58)
//   1xxxxx.SZ → 深市 ETF/LOF(15/16)
const ETF_CODE_RE = /^(5\d{5}\.SH|1\d{5}\.SZ)$/;

const BY_CODE = new Map<string, TableItem>(ITEMS.map((it) => [it.code, it]));

const STOCK: InstrumentMeta = {
  isEtf: false,
  category: null,
  categoryLabel: null,
  indexName: null,
  displayName: null,
  t0: false,
  known: false,
  form: 'etf',
};

/** 按代码查品种(纯函数) */
export function resolveInstrument(code: string): InstrumentMeta {
  const c = (code || '').trim().toUpperCase();
  const hit = BY_CODE.get(c);
  if (hit) {
    const cat = hit.category ?? null;
    return {
      isEtf: true,
      category: cat,
      categoryLabel: cat ? (CATEGORIES[cat] ?? null) : null,
      indexName: hit.index ?? null,
      displayName: hit.name ?? null,
      t0: Boolean(hit.t0),
      known: true,
      form: hit.form === 'lof' ? 'lof' : 'etf',
    };
  }
  if (ETF_CODE_RE.test(c)) {
    // 表外 ETF:保守按 T+1(无据不判 T+0)—— 与后端一致
    return { ...STOCK, isEtf: true };
  }
  return STOCK;
}

/** 是否场内 ETF */
export function isEtf(code: string): boolean {
  return resolveInstrument(code).isEtf;
}

/** 徽章的 hover 说明(形态 + 类别 + 跟踪指数 + 交易规则) */
export function instrumentBadgeTitle(meta: InstrumentMeta): string {
  if (!meta.isEtf) return '';
  if (!meta.known) {
    return '场内 ETF · 品种表未收录 · 已按保守口径(T+1 / 股票费率)计算,交易规则可能有偏差';
  }
  // 场内 LOF 的交易规则与 ETF 一致,但不是 ETF —— 别在文案里混为一谈
  const parts = [meta.form === 'lof' ? '场内 LOF' : '场内 ETF'];
  if (meta.categoryLabel) parts.push(meta.categoryLabel);
  if (meta.indexName) parts.push(`跟踪 ${meta.indexName}`);
  if (meta.t0) parts.push('当日可回转交易(T+0)');
  return parts.join(' · ');
}
