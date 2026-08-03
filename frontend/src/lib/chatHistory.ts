/**
 * AI 问一问对话历史缓存(IndexedDB)
 *
 * 按 stockCode 隔离存储多轮问答;切换股票从 IDB 读出回显,刷新页面后仍保留。
 * 写入时自动截断到 MAX_MESSAGES_PER_STOCK,防止长期累积撑爆。
 * IndexedDB 不可用(隐私模式等)时静默失败,不影响主流程。
 *
 * DB 升级历史:
 *   v1: out-of-line key(put(value, code), get(code))
 *   v2: keyPath:'code'(每个 record 自带 code 字段,store 自动按 code 索引,更可靠)
 *   旧数据不迁移(v1→v2 直接重建 store),用户首次升级后 chat history 从零开始。
 */
export interface ChatHistoryItem {
  role: 'user' | 'ai';
  text: string;
}

const DB_NAME = 'chat-history-db';
const STORE = 'history';
const DB_VERSION = 2;
/** 单只股票保留最近 N 条消息(N=40 ≈ 20 轮问答) */
export const MAX_MESSAGES_PER_STOCK = 40;

interface HistoryRecord {
  code: string;
  items: ChatHistoryItem[];
  ts: number;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (event) => {
        const db = req.result;
        const oldVersion = event.oldVersion;
        if (oldVersion < 1) {
          db.createObjectStore(STORE, { keyPath: 'code' });
        } else if (oldVersion < 2) {
          // v1 用 out-of-line key,迁到 v2 的 keyPath:直接重建 store,旧数据丢弃
          db.deleteObjectStore(STORE);
          db.createObjectStore(STORE, { keyPath: 'code' });
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

/** 读该只股票的历史问答;无 / 失败 → 空数组 */
export async function getChatHistory(code: string): Promise<ChatHistoryItem[]> {
  try {
    const db = await openDb();
    const record = await new Promise<HistoryRecord | undefined>((resolve, reject) => {
      const req = tx(db, 'readonly').get(code);
      req.onsuccess = () => resolve(req.result as HistoryRecord | undefined);
      req.onerror = () => reject(req.error);
    });
    return record?.items ?? [];
  } catch (e) {
    console.warn('[chat-history] getChatHistory failed:', e);
    return [];
  }
}

/** 写入历史(items 为空时删除该股票记录) */
export async function setChatHistory(
  code: string,
  items: ChatHistoryItem[],
): Promise<void> {
  try {
    const db = await openDb();
    const trimmed = items.slice(-MAX_MESSAGES_PER_STOCK);
    await new Promise<void>((resolve, reject) => {
      const req = trimmed.length > 0
        ? tx(db, 'readwrite').put({ code, items: trimmed, ts: Date.now() })
        : tx(db, 'readwrite').delete(code);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  } catch (e) {
    console.warn('[chat-history] setChatHistory failed:', e);
    /* 不抛出:缓存不可用不影响聊天 */
  }
}

/** 清空该只股票的历史(用户主动点 ×) */
export async function clearChatHistory(code: string): Promise<void> {
  await setChatHistory(code, []);
}