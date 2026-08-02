/**
 * AI 分析结果缓存(IndexedDB,24h 时效)
 *
 * 分析含行情快照(指标 + AI 解读),切换股票 / 刷新页面后复用可省 LLM token;
 * 超 24h 自动作废,避免展示隔日过期指标误导。
 * IndexedDB 不可用(隐私模式等)时静默失败,不影响主流程。
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

/** 读缓存:过期返回 null 并惰性删除 */
export async function getAnalysisCache(code: string): Promise<AnalysisResult | null> {
  try {
    const db = await openDb();
    const record = await new Promise<CacheRecord | undefined>((resolve, reject) => {
      const req = tx(db, 'readonly').get(code);
      req.onsuccess = () => resolve(req.result as CacheRecord | undefined);
      req.onerror = () => reject(req.error);
    });
    if (!record) return null;
    if (Date.now() - record.ts > ANALYSIS_TTL_MS) {
      await setAnalysisCache(code, null);
      return null;
    }
    return record.result;
  } catch {
    return null;
  }
}

/** 写入缓存(result 为 null 时删除) */
export async function setAnalysisCache(
  code: string,
  result: AnalysisResult | null,
): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const req = result
        ? tx(db, 'readwrite').put({ result, ts: Date.now() }, code)
        : tx(db, 'readwrite').delete(code);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  } catch {
    /* 静默:缓存不可用不影响分析 */
  }
}
