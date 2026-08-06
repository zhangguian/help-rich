/**
 * AI 分析结果缓存(IndexedDB,24h 时效)
 *
 * 分析含行情快照(指标 + AI 解读),切换股票 / 刷新页面后复用可省 LLM token;
 * 超 24h 自动作废,避免展示隔日过期指标误导。
 * IndexedDB 不可用(隐私模式等)时静默失败,不影响主流程。
 *
 * v2.5:key 升级为 `code|latestKlineDate|positionStatus`
 *   - 行情日变化 / 持仓状态变化 → 旧 key 自动失效,强制重新生成
 *   - 同一只股票可能存在多个 key(不同日期 / 不同持仓状态);读时按 ts 选最新未过期
 */
import type { AnalysisResult } from '@/lib/types';

const DB_NAME = 'stock-tools';
const STORE = 'analysis-cache';
/** 缓存有效期:24h */
export const ANALYSIS_TTL_MS = 24 * 60 * 60 * 1000;

interface CacheRecord {
  result: AnalysisResult;
  ts: number;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE)) {
          req.result.createObjectStore(STORE);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbPromise;
}

function tx(db: IDBDatabase, mode: IDBTransactionMode): IDBObjectStore {
  return db.transaction(STORE, mode).objectStore(STORE);
}

function buildCacheKey(code: string, result: AnalysisResult): string {
  const ts = result.latestKlineDate ?? 'no-ts';
  const ps = result.positionStatus ?? 'no-ps';
  return `${code}|${ts}|${ps}`;
}

interface CursorEntry {
  key: string;
  record: CacheRecord;
}

function listByCodePrefix(
  db: IDBDatabase,
  code: string,
  mode: IDBTransactionMode,
): Promise<CursorEntry[]> {
  const prefix = `${code}|`;
  return new Promise((resolve, reject) => {
    const out: CursorEntry[] = [];
    const store = tx(db, mode);
    const req = store.openCursor();
    req.onsuccess = () => {
      const cursor = req.result;
      if (cursor) {
        if (typeof cursor.key === 'string' && cursor.key.startsWith(prefix)) {
          out.push({ key: cursor.key as string, record: cursor.value as CacheRecord });
        }
        cursor.continue();
      } else {
        resolve(out);
      }
    };
    req.onerror = () => reject(req.error);
  });
}

/** 旧格式兼容:v2.5 之前的缓存里 ai.advice 是字符串,前端渲染需包装为对象
 *  新格式:ai.advice = {rationale, price, position_pct, trigger, holding_window, not_action, tStrategy?}
 *  包装策略:整段串放到 rationale,其余字段填空;前端可正常渲染但仅显示 rationale
 */
function migrateLegacyAdvice(result: AnalysisResult): AnalysisResult {
  const ai = result.ai;
  if (!ai) return result;
  const advice: unknown = (ai as { advice?: unknown }).advice;
  if (typeof advice !== 'string') return result;
  return {
    ...result,
    ai: {
      ...ai,
      advice: {
        rationale: advice,
        price: { entryOrExitRange: '', stopLoss: '' },
        positionPct: '',
        trigger: '',
        holdingWindow: '',
        notAction: '',
        tStrategy: null,
      },
    },
  };
}

/** 读缓存:按股票代码,挑最新 ts 且未过期的记录(可能有多个 key,选最新) */
export async function getAnalysisCache(code: string): Promise<AnalysisResult | null> {
  try {
    const db = await openDb();
    const entries = await listByCodePrefix(db, code, 'readonly');
    if (!entries.length) return null;
    const valid = entries
      .filter((e) => Date.now() - e.record.ts <= ANALYSIS_TTL_MS)
      .sort((a, b) => b.record.ts - a.record.ts);
    const result = valid[0]?.record.result ?? null;
    return result ? migrateLegacyAdvice(result) : null;
  } catch {
    return null;
  }
}

/** 写入缓存(result 为 null 时删除该 code 的所有记录) */
export async function setAnalysisCache(
  code: string,
  result: AnalysisResult | null,
): Promise<void> {
  try {
    const db = await openDb();
    if (result) {
      const key = buildCacheKey(code, result);
      await new Promise<void>((resolve, reject) => {
        const req = tx(db, 'readwrite').put({ result, ts: Date.now() }, key);
        req.onsuccess = () => resolve();
        req.onerror = () => reject(req.error);
      });
    } else {
      const entries = await listByCodePrefix(db, code, 'readwrite');
      await new Promise<void>((resolve, reject) => {
        const store = tx(db, 'readwrite');
        entries.forEach((e) => { store.delete(e.key); });
        store.transaction.oncomplete = () => resolve();
        store.transaction.onerror = () => reject(store.transaction.error);
      });
    }
  } catch {
    /* 静默:缓存不可用不影响主流程 */
  }
}