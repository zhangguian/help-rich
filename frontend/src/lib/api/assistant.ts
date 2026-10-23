/**
 * 全局 AI 助手 API client(阶段 T4)
 *
 * 与个股问答(`/api/stock/{code}/chat/stream`)的差别:
 * 助手是**全局**的 —— 请求里只带一个可选的 `stockCode`(前端当前选中的那只),
 * 后端会把「当前选中票 + 持仓 + ★关注 + 今日作战计划 + 今日盘中复盘 + 指数快照」
 * 拼成一份事实包。
 *
 * **SSE 事件格式**(与个股问答一致):
 *   data: {"text": "增量文本"}
 *   data: {"error": "错误信息"}
 *   data: {"done": true}
 *
 * 为什么用 fetch 而不是 EventSource:EventSource 只支持 GET、且不能自定义 header;
 * 这里要 POST 一个 JSON body(问题 + 历史),所以走 fetch + ReadableStream 逐帧解析。
 */
import { apiBaseUrl } from '@/lib/api';

/** 一条历史消息(与后端 _to_llm_messages 的入参形状一致) */
export interface AssistantHistoryItem {
  role: 'user' | 'ai';
  text: string;
}

export interface AssistantStreamOptions {
  question: string;
  /** 前端当前选中的票(可空) */
  stockCode?: string | null;
  history?: AssistantHistoryItem[];
  signal?: AbortSignal;
  /** 每段增量文本 */
  onText: (piece: string) => void;
  /** 流内错误(后端推 error 事件时) */
  onError?: (message: string) => void;
  /** 流正常结束 */
  onDone?: () => void;
}

/**
 * 消费助手 SSE 流。
 *
 * 失败语义:
 * - HTTP 非 2xx → 抛 Error(带后端 detail.message,例如「未配置 LLM Key」)
 * - 流内 `error` 事件 → 调 onError,并停止消费
 */
export async function streamAssistant(opts: AssistantStreamOptions): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/assistant/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...(opts.signal ? { signal: opts.signal } : {}),
    body: JSON.stringify({
      question: opts.question,
      stock_code: opts.stockCode ?? null,
      history: opts.history ?? [],
    }),
  });

  if (!res.ok) {
    let msg = `请求失败 (HTTP ${res.status})`;
    try {
      const data = await res.json();
      const detail = data?.detail;
      if (detail?.message) msg = detail.message;
      else if (typeof detail === 'string') msg = detail;
    } catch {
      /* 保留默认文案 */
    }
    throw new Error(msg);
  }
  if (!res.body) throw new Error('空响应体');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      let evt: { text?: string; error?: string; done?: boolean };
      try {
        evt = JSON.parse(payload);
      } catch {
        continue; // 忽略坏帧
      }
      if (typeof evt.error === 'string') {
        opts.onError?.(evt.error);
        return;
      }
      if (evt.done) {
        opts.onDone?.();
        return;
      }
      if (typeof evt.text === 'string') opts.onText(evt.text);
    }
  }
  // 流自然结束(后端没发 done 事件)也算完成
  opts.onDone?.();
}
