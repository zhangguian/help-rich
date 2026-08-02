'use client';

import { useEffect, useRef, useState } from 'react';

import { AnimatePresence, motion } from 'framer-motion';

import { apiBaseUrl } from '@/lib/api';

import { GlassCard } from '@/components/ui/GlassCard';
import { Button } from '@/components/ui/Button';

interface Msg {
  id: number;
  role: 'user' | 'ai';
  text: string;
  streaming?: boolean;
}

/**
 * 右侧下栏 · AI 对话助手(roadmap 功能5)
 *
 * 结合行情 + 技术指标 + 持仓成本回答操作提问;单轮会话(切换股票清空)。
 * 走 /chat/stream SSE 流式接口,打字机效果输出。
 */
export function ChatPanel({ stockCode }: { stockCode: string | null }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);
  const idRef = useRef(0);

  useEffect(() => {
    setMessages([]);
  }, [stockCode]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, sending]);

  /** 终结某条 AI 消息:text 覆盖或追加,streaming 置 false */
  const finalize = (id: number, text: string, replace: boolean) => {
    setMessages((m) =>
      m.map((x) =>
        x.id === id
          ? { ...x, text: replace ? text : x.text + text, streaming: false }
          : x,
      ),
    );
  };

  const send = async () => {
    const q = input.trim();
    if (!q || !stockCode || sending) return;
    setInput('');
    const msgId = ++idRef.current;
    const userMsgId = ++idRef.current;
    setMessages((m) => [
      ...m,
      { id: userMsgId, role: 'user', text: q },
      { id: msgId, role: 'ai', text: '', streaming: true },
    ]);
    setSending(true);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const res = await fetch(
        `${apiBaseUrl()}/stock/${encodeURIComponent(stockCode)}/chat/stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({ question: q }),
        },
      );
      if (!res.ok) {
        let msg = `请求失败 (HTTP ${res.status})`;
        try {
          const data = await res.json();
          const detail = data?.detail;
          if (detail?.message) msg = detail.message;
          else if (typeof detail === 'string') msg = detail;
        } catch {
          /* keep default */
        }
        finalize(msgId, msg, true);
        return;
      }
      if (!res.body) throw new Error('empty body');

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let streamError: string | null = null;
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
          if (payload === '[DONE]') continue;
          let evt: { text?: string; error?: string; done?: boolean };
          try {
            evt = JSON.parse(payload);
          } catch {
            continue;
          }
          if (typeof evt.error === 'string') streamError = evt.error;
          else if (evt.done) streamError = null;
          else if (typeof evt.text === 'string') {
            const piece = evt.text;
            setMessages((m) =>
              m.map((x) => (x.id === msgId ? { ...x, text: x.text + piece } : x)),
            );
          }
        }
      }
      finalize(msgId, streamError ?? '', streamError != null);
    } catch {
      finalize(msgId, 'AI 输出中断(网络异常),请重试。', true);
    } finally {
      clearTimeout(timer);
      setSending(false);
    }
  };

  return (
    <GlassCard
      variant="active"
      padding="sm"
      className="flex-1 flex flex-col overflow-hidden gap-2 h-full"
    >
      <div className="px-2 pt-1 flex items-center gap-2">
        <span className="text-sm font-semibold text-text-pri">AI 问一问</span>
        {sending && (
          <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" />
        )}
      </div>

      <div ref={listRef} className="flex-1 overflow-y-auto space-y-2 min-h-0 px-1">
        {messages.length === 0 && (
          <p className="text-text-ter text-xs text-center py-6">
            {stockCode
              ? '例如:我 60 块的成本,现在该止损吗?'
              : '选择左侧股票后可提问,如「现在能买吗」'}
          </p>
        )}
        <AnimatePresence initial={false}>
          {messages.map((m) => (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              <div
                className={`text-xs mb-1 ${
                  m.role === 'user' ? 'text-right text-text-ter' : 'text-accent'
                }`}
              >
                {m.role === 'user' ? '我' : 'AI'}
              </div>
              <div
                className={`text-sm leading-relaxed whitespace-pre-wrap rounded-xl px-3 py-2 ${
                  m.role === 'user'
                    ? 'bg-accent-subtle text-text-pri ml-8'
                    : 'bg-white/5 text-text-sec'
                }`}
              >
                {m.text}
                {m.streaming && <span className="text-accent">▍</span>}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      <div className="flex gap-2 pt-1 border-t border-white/5">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          disabled={!stockCode || sending}
          placeholder={stockCode ? '输入你的问题…' : '先选择一只股票'}
          className="flex-1 px-3 py-2 text-sm rounded-xl bg-white/5 border border-white/10 focus:border-accent outline-none text-text-pri placeholder:text-text-ter disabled:opacity-40"
        />
        <Button onClick={send} disabled={!stockCode || sending || !input.trim()}>
          {sending ? '回答中…' : '发送'}
        </Button>
      </div>
    </GlassCard>
  );
}
