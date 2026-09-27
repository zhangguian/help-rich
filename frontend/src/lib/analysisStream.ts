/**
 * SSE 消费器(分析流式端点)
 *
 * 后端 GET /api/stock/{code}/analysis/stream 输出 text/event-stream:
 *   data: {"event":"indicators", "data":{...}}\n\n
 *   data: {"event":"ai_started", "at":...}\n\n
 *   ...
 *   data: {"event":"done"}\n\n
 *
 * 前端按 event 字段分发;onEvent 拿到的是解析后的对象,可按需 setState。
 * AbortSignal 用于主动取消(组件卸载/超时)。
 */
export type AnalysisStreamEvent =
  | { event: 'indicators'; data: unknown; latest_kline_date: string | null }
  | { event: 'ai_started'; at: number }
  | { event: 'ai_progress'; elapsed_s: number }
  | { event: 'ai_complete'; ai: unknown; ai_source: 'live'; latest_kline_date: string | null }
  | { event: 'ai_error'; code: string; message: string }
  | { event: 'done' };

export interface ConsumeOptions {
  /** AbortSignal,例如超时定时器或组件卸载 */
  signal?: AbortSignal;
  /** 每个事件回调 */
  onEvent: (evt: AnalysisStreamEvent) => void;
}

export async function consumeAnalysisStream(
  url: string,
  opts: ConsumeOptions,
): Promise<void> {
  const res = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'text/event-stream' },
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  if (!res.ok) {
    throw new Error(`analysis stream HTTP ${res.status}`);
  }
  if (!res.body) throw new Error('empty stream body');

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
      try {
        const evt = JSON.parse(payload) as AnalysisStreamEvent;
        opts.onEvent(evt);
        if (evt.event === 'done') return;
      } catch {
        // ignore malformed frame
      }
    }
  }
}