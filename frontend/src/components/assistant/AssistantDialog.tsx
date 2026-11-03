'use client';

import { useEffect, useRef, useState } from 'react';

import { useAssistant } from './AssistantProvider';
import AssistantExpression from './AssistantExpression';

/** 快捷提问 */
const QUICK_ASKS = ['我该盯哪几只？', '哪些该止损？', '今天能加仓吗', '大盘怎么样', '我的浮盈呢'];

/** 数据来源标注(助手回答里的数字全部来自后端事实包,这里只说明来源面) */
const CITE = '数据来源：今日作战计划 · 实时行情 · 盘中复盘';

/**
 * 悬浮球展开后的对话框(阶段 T4)
 *
 * **上下文是全局的**:标题栏会显示「已带入 <当前选中的票>」——
 * 这是「全局助手 + 自动带当前选中票」的可见落点。
 * 没选中票时显示「未选中具体标的」,不装作带了。
 */
export default function AssistantDialog() {
  const { open, closePanel, messages, mood, sending, selectedName, selectedCode, send, clearHistory } =
    useAssistant();
  const [input, setInput] = useState('');
  const bodyRef = useRef<HTMLDivElement>(null);

  // 新消息进来时滚到底
  useEffect(() => {
    if (!open) return;
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, open]);

  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closePanel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, closePanel]);

  if (!open) return null;

  const submit = () => {
    const q = input.trim();
    if (!q || sending) return;
    setInput('');
    send(q);
  };

  const ctxText = selectedCode
    ? `全局上下文 · 已带入 ${selectedName ?? selectedCode}`
    : '全局上下文 · 未选中具体标的';

  return (
    <div
      data-testid="assistant-dialog"
      className="fixed bottom-[5.5rem] right-5 z-40 flex w-[392px] max-w-[calc(100vw-2.5rem)]
                 flex-col overflow-hidden rounded-xl border border-border-str
                 bg-bg-surface shadow-2xl"
    >
      {/* 头部 */}
      <div className="flex items-center gap-2.5 border-b border-border-def px-3 py-2.5">
        <AssistantExpression mood={mood} size={28} />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-text-pri">AI 助手</div>
          <div className="truncate text-[11px] text-text-ter">{ctxText}</div>
        </div>
        <button
          type="button"
          onClick={clearHistory}
          className="rounded px-1.5 py-0.5 text-[11px] text-text-ter hover:text-text-sec"
          title="清空对话历史"
        >
          清空
        </button>
        <button
          type="button"
          onClick={closePanel}
          aria-label="关闭"
          className="text-text-ter hover:text-text-pri text-lg leading-none"
        >
          ×
        </button>
      </div>

      {/* 消息区 */}
      <div ref={bodyRef} className="flex-1 overflow-y-auto px-3 py-3" style={{ maxHeight: '52vh' }}>
        {messages.length === 0 && (
          <div className="py-6 text-center text-xs text-text-ter">
            问点什么 —— 助手会自动带上你当前选中的那只票,
            <br />
            以及持仓、★关注、今日作战计划和盘中复盘。
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={m.role === 'user' ? 'mb-2 flex justify-end' : 'mb-3 flex justify-start'}
          >
            <div
              data-testid="assistant-message"
              data-role={m.role}
              data-streaming={m.streaming ? '1' : '0'}
              className={
                m.role === 'user'
                  ? 'max-w-[85%] rounded-lg rounded-br-sm bg-accent-subtle px-2.5 py-1.5 text-[12.5px] text-text-pri'
                  : `max-w-[92%] rounded-lg rounded-bl-sm border px-2.5 py-1.5 text-[12.5px] leading-relaxed ${
                      m.error
                        ? 'border-warn/40 bg-warn/10 text-warn'
                        : 'border-border-def bg-bg-elevated text-text-pri'
                    }`
              }
            >
              {m.text || (m.streaming ? '…' : '')}
              {m.streaming && <span className="ml-0.5 animate-pulse">▍</span>}
              {m.role === 'ai' && !m.streaming && !m.error && m.text && (
                <div className="mt-1 text-[10.5px] leading-snug text-text-ter">{CITE}</div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* 快捷提问 */}
      <div className="flex flex-wrap gap-1.5 border-t border-border-def px-3 py-2">
        {QUICK_ASKS.map((q) => (
          <button
            key={q}
            type="button"
            disabled={sending}
            onClick={() => send(q)}
            className="rounded-full border border-border-def bg-bg-elevated px-2.5 py-0.5
                       text-[11px] text-text-sec transition-colors hover:border-accent
                       hover:text-text-pri disabled:opacity-40"
          >
            {q}
          </button>
        ))}
      </div>

      {/* 输入区 */}
      <div className="flex items-center gap-2 border-t border-border-def px-3 py-2.5">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="问点什么…（回车发送）"
          data-testid="assistant-input"
          className="min-w-0 flex-1 rounded-lg border border-border-def bg-bg-base px-2.5 py-1.5
                     text-[12.5px] text-text-pri placeholder:text-text-ter
                     focus:border-accent focus:outline-none"
        />
        <button
          type="button"
          onClick={submit}
          disabled={sending || !input.trim()}
          data-testid="assistant-send"
          className="rounded-lg bg-accent px-3.5 py-1.5 text-[12.5px] font-bold text-white
                     transition-opacity disabled:opacity-40"
        >
          发送
        </button>
      </div>
    </div>
  );
}
