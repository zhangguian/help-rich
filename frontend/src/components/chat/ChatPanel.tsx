'use client';

import { useEffect, useRef, useState } from 'react';

import { AnimatePresence, motion } from 'framer-motion';

import { apiPost } from '@/lib/api';

import { GlassCard } from '@/components/ui/GlassCard';
import { Button } from '@/components/ui/Button';

interface Msg {
  role: 'user' | 'ai';
  text: string;
}

/**
 * 右侧下栏 · AI 对话助手(roadmap 功能5)
 *
 * 结合行情 + 技术指标 + 持仓成本回答操作提问;单轮会话(切换股票清空)。
 */
export function ChatPanel({ stockCode }: { stockCode: string | null }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMessages([]);
  }, [stockCode]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, sending]);

  const send = async () => {
    const q = input.trim();
    if (!q || !stockCode || sending) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', text: q }]);
    setSending(true);
    try {
      const r = await apiPost<{ answer: string }>(
        `/stock/${encodeURIComponent(stockCode)}/chat`,
        { question: q },
      );
      setMessages((m) => [...m, { role: 'ai', text: r.answer }]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: 'ai', text: 'AI 暂不可用(未配置 Key 或服务异常),请稍后重试。' },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <GlassCard
      variant="active"
      padding="sm"
      className="flex-1 flex flex-col overflow-hidden gap-2 min-h-0"
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
          {messages.map((m, i) => (
            <motion.div
              key={i}
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
          发送
        </Button>
      </div>
    </GlassCard>
  );
}
