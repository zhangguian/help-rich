'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { AnimatePresence, motion } from 'framer-motion';

import { apiBaseUrl } from '@/lib/api';
import {
  clearChatHistory,
  getChatHistory,
  setChatHistory,
  type ChatHistoryItem,
} from '@/lib/chatHistory';

import { GlassCard } from '@/components/ui/GlassCard';
import { Button } from '@/components/ui/Button';

interface Msg {
  id: number;
  role: 'user' | 'ai';
  text: string;
  streaming?: boolean;
}

/** 与后端 stock_advice_service.MAX_HISTORY_TURNS 保持一致 */
const MAX_HISTORY_TURNS = 6;

interface QuickPromptContext {
  avgCost: number | null;
  currentPrice: number | null;
  changePct: number | null;
}

/** 根据当前股票上下文(持仓成本/当前价/涨跌) 生成 3-5 个小白友好的快捷提问 */
function buildQuickPrompts(ctx: QuickPromptContext): string[] {
  const out: string[] = [];
  const { avgCost, currentPrice, changePct } = ctx;
  if (avgCost != null && currentPrice != null && avgCost > 0) {
    const pnlPct = ((currentPrice / avgCost) - 1) * 100;
    if (pnlPct >= 0) {
      out.push(`成本 ${avgCost.toFixed(2)} 元,浮盈 ${pnlPct.toFixed(1)}%,该止盈吗?`);
    } else {
      out.push(`成本 ${avgCost.toFixed(2)} 元,浮亏 ${(-pnlPct).toFixed(1)}%,还能补仓吗?`);
    }
    out.push(`我 ${avgCost.toFixed(2)} 元的成本,该止损吗?`);
  } else {
    out.push('现在能买入吗?');
  }
  if (changePct != null && changePct > 0.5) {
    out.push('今天为什么涨这么多?');
  } else if (changePct != null && changePct < -0.5) {
    out.push('今天为什么跌?还能拿吗?');
  }
  out.push('下周走势怎么看?');
  return out.slice(0, 5);
}

/**
 * 右侧下栏 · AI 对话助手(roadmap 功能5)
 *
 * 切换股票:从 IndexedDB 缓存按 stockCode 读出历史问答回显,继续提问时把
 * 最近 6 轮随 request 一起发后端,后端走 LLM 原生 messages 数组实现真多轮上下文。
 *
 * UI 提示:首次加载到历史消息时,列表顶部出现「以下为上次对话缓存」小提示,
 * 用户点 × 关闭;开始新一轮提问时也自动关闭。
 *
 * 快捷提问词(chips):输入框上方一行 chip,点击即发送;根据是否持仓 + 当日涨跌
 * 动态生成 3-5 条小白友好的提问,降低初次使用门槛。
 */
export function ChatPanel({
  stockCode,
  stockName,
  avgCost,
  currentPrice,
  changePct,
}: {
  stockCode: string | null;
  stockName: string | null;
  avgCost: number | null;
  currentPrice: number | null;
  changePct: number | null;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  // 历史回显提示:仅当本次 stockCode 切换是从 IDB 加载到非空历史时显示
  const [showHistoryHint, setShowHistoryHint] = useState(false);
  const [hintDismissed, setHintDismissed] = useState(false);
const listRef = useRef<HTMLDivElement | null>(null);
  const idRef = useRef(0);
  // 同步最新 messages,供 switch effect 在清空前 flush 旧股票 IDB
  const messagesRef = useRef<Msg[]>([]);
  // 记录上次 effect 处理的 stockCode,用于切换时识别 oldCode 写 IDB
  const lastStockCodeRef = useRef<string | null>(null);

  // 快捷提问词:依据上下文(持仓成本/当前价/涨跌)动态生成 3-5 条
  const quickPrompts = useMemo(
    () => buildQuickPrompts({ avgCost, currentPrice, changePct }),
    [avgCost, currentPrice, changePct],
  );

  // 跟踪 messages 给 messagesRef(switch flush 时拿到最新值,避免依赖 React 闭包)
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // 切换股票 → 立即清空 UI(同步 schedule),然后异步 flush 旧 + 读新
  useEffect(() => {
    const myCode = stockCode;
    const oldCode = lastStockCodeRef.current;
    lastStockCodeRef.current = myCode;

    // 同步清空 UI(在 effect body 顶部,不等 IDB 操作):避免「等 IDB 写入完成才清空」
    // 导致切换瞬间还显示上一个股票的内容
    setMessages([]);
    idRef.current = 0;
    setShowHistoryHint(false);
    setHintDismissed(false);
    if (!myCode) return;

    // AbortController:effect cleanup(切股票 / 组件卸载)时取消过期 IDB 操作的后续装载
    const controller = new AbortController();

    (async () => {
      try {
        // 切走前:flush 旧股票已完成的问答到 IDB,关掉「切走 = 丢失」窗口
        if (oldCode && oldCode !== myCode) {
          const finalized = messagesRef.current.filter((m) => !m.streaming);
          if (finalized.length > 0) {
            const items: ChatHistoryItem[] = finalized.map((m) => ({
              role: m.role,
              text: m.text,
            }));
            await setChatHistory(oldCode, items);
          }
        }
        if (controller.signal.aborted) return;

        // 读新股票 IDB(独立 store with keyPath:'code',自动按 stockCode 隔离)
        const items = await getChatHistory(myCode);
        if (controller.signal.aborted) return;

        const loadedBase: Msg[] = items.map((it) => ({
          id: 0, // 占位,下面重新编号
          role: it.role,
          text: it.text,
        }));
        // 历史总是排在前;若用户在 IDB 异步读回前已抢先发了消息,保留新消息并重排 ID
        setMessages((prev) => {
          const all = [...loadedBase, ...prev];
          const renumbered = all.map((m, i) => ({ ...m, id: i + 1 }));
          idRef.current = renumbered.length;
          if (loadedBase.length > 0 && prev.length === 0) setShowHistoryHint(true);
          return renumbered;
        });
      } catch (e) {
        console.warn('[chat] switch effect error', e);
      }
    })();

    return () => controller.abort();
  }, [stockCode]);

  // 自动滚到底部
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, sending]);

  // 持久化 messages 到 IDB(去掉 streaming 临时态);300ms 防抖合并流式高频更新
  // 空 messages 不主动写(避免 IDB 异步慢时把新股票已有记录删掉);清空走 handleClear
  useEffect(() => {
    if (!stockCode) return;
    const timer = setTimeout(() => {
      const finalized = messages.filter((m) => !m.streaming);
      if (finalized.length === 0) return;
      const items: ChatHistoryItem[] = finalized.map((m) => ({
        role: m.role,
        text: m.text,
      }));
      void setChatHistory(stockCode, items);
    }, 300);
    return () => clearTimeout(timer);
  }, [messages, stockCode]);

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

  /** 取最近 N 轮已完成问答(不含当前发送中的)用于 body.history 字段
   * 用 messagesRef 而不是 messages state:state closure 可能在异步回调里过期;
   * ref 在每次 messages 变化后被 effect 同步,event handler 调用时一定是最新值。 */
  const buildHistory = (): ChatHistoryItem[] => {
    const finalized = messagesRef.current.filter((m) => !m.streaming);
    const slice = finalized.slice(-MAX_HISTORY_TURNS * 2);
    return slice.map((m) => ({ role: m.role, text: m.text }));
  };

  const send = async (overrideText?: string) => {
    const q = (overrideText ?? input).trim();
    if (!q || !stockCode || sending) return;
    setInput('');
    // 进入新一轮对话,关闭历史提示
    setShowHistoryHint(false);
    setHintDismissed(true);
    const msgId = ++idRef.current;
    const userMsgId = ++idRef.current;
    setMessages((m) => [
      ...m,
      { id: userMsgId, role: 'user', text: q },
      { id: msgId, role: 'ai', text: '', streaming: true },
    ]);
    setSending(true);

    const history = buildHistory();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const res = await fetch(
        `${apiBaseUrl()}/stock/${encodeURIComponent(stockCode)}/chat/stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({ question: q, stockName, history }),
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

  const handleClear = () => {
    if (!stockCode) return;
    setMessages([]);
    void clearChatHistory(stockCode);
    setShowHistoryHint(false);
    setHintDismissed(false);
  };

  const dismissHint = () => setHintDismissed(true);

  const hintVisible = showHistoryHint && !hintDismissed && messages.length > 0;

  return (
    <GlassCard
      variant="active"
      padding="sm"
      className="h-full flex flex-col overflow-hidden gap-2 min-h-0"
    >
      <div className="px-2 pt-1 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold text-text-pri truncate">
            AI 问一问{stockName && stockCode ? ` · ${stockName}` : ''}
          </span>
          {sending && (
            <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" />
          )}
        </div>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={handleClear}
            title="清空本轮对话(也会清除浏览器缓存的历史)"
            className="shrink-0 text-xs text-text-ter hover:text-text-pri px-1.5 py-0.5 rounded hover:bg-white/5"
          >
            🗑 清空
          </button>
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
        {hintVisible && (
          <div className="flex items-center justify-between gap-2 px-3 py-1.5 rounded-lg bg-white/5 border border-white/5 text-[11px] text-text-ter">
            <span>以下为上次对话缓存 · 共 {messages.length} 条</span>
            <button
              type="button"
              onClick={dismissHint}
              title="知道了"
              className="hover:text-text-pri w-4 h-4 leading-none"
            >
              ×
            </button>
          </div>
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

      {stockCode && !sending && quickPrompts.length > 0 && (
        <div className="flex gap-1.5 flex-wrap px-1 pt-1 border-t border-white/5">
          {quickPrompts.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => send(p)}
              className="px-3 py-1 rounded-full border border-white/10 hover:border-accent/50 text-xs text-text-sec hover:text-text-pri transition-colors"
            >
              {p}
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2 pt-1 border-t border-white/5">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          disabled={!stockCode || sending}
          placeholder={stockCode ? '输入你的问题…' : '先选择一只股票'}
          className="flex-1 px-3 py-2 text-sm rounded-xl bg-white/5 border border-white/10 focus:border-accent outline-none text-text-pri placeholder:text-text-ter disabled:opacity-40"
        />
        <Button onClick={() => send()} disabled={!stockCode || sending || !input.trim()} className="liquid-glass rounded-xl">
          {sending ? '回答中…' : '发送'}
        </Button>
      </div>
    </GlassCard>
  );
}