'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { streamAssistant, type AssistantHistoryItem } from '@/lib/api/assistant';
import type { AssistantMood } from '@/lib/assistantExpressions';
import { getChatHistory, setChatHistory } from '@/lib/chatHistory';

/**
 * 全局 AI 助手的**单例状态**。
 *
 * **为什么是 Provider 而不是页面级 state**:助手是全站的 —— 悬浮球挂在 AppShell 上,
 * 任何页面都能唤起它;而且它要自动带上「当前选中的那只票」,
 * 那只票是盯盘页的本地状态。Provider 放在 AppShell 里,盯盘页通过
 * `setSelectedStock()` 把选中票报上来,助手在任何页面都拿得到。
 *
 * **历史隔离**:助手的对话存在 IndexedDB 的 `__assistant__` key 下,
 * 与个股问答(`chatHistory` 按 stockCode 分桶)**互不串味**。
 *
 * **表情状态机**(表情库见 lib/assistantExpressions.ts):
 *   idle → loading_history → idle
 *   收到提问 → received → searching(后端拼事实包)→ thinking(等首 token)
 *            → speaking(流式输出)→ done
 *   出错 → error ;LLM 未配置 → unavailable ;长时间无交互 → sleeping
 */
export interface AssistantMessage {
  id: number;
  role: 'user' | 'ai';
  text: string;
  /** 正在流式输出 */
  streaming?: boolean;
  /** 是错误消息 */
  error?: boolean;
  /** 数据来源标注 */
  cite?: string;
}

export interface AssistantContextValue {
  open: boolean;
  messages: AssistantMessage[];
  mood: AssistantMood;
  sending: boolean;
  /** 当前选中的票(助手自动带进事实包) */
  selectedCode: string | null;
  selectedName: string | null;
  openPanel: () => void;
  closePanel: () => void;
  toggle: () => void;
  send: (question: string) => void;
  clearHistory: () => void;
  setSelectedStock: (code: string | null, name?: string | null) => void;
}

/**
 * **动作**上下文:只放**引用稳定**的回调。
 *
 * ⚠️ 为什么单独拆一个 context:盯盘页要用 `setSelectedStock` 把选中票报上来。
 * 如果它消费的是**完整** context,助手每吐一个 token 都会改 `messages` → context value 变化
 * → **盯盘页跟着重渲染**(44 行列表 + 14 张图)—— 这会把阶段10 的性能优化直接打回去。
 *
 * 所以:盯盘页只吃这份**永远不变**的动作 context;对话框/悬浮球自己吃状态 context。
 */
export interface AssistantActionsValue {
  openPanel: () => void;
  closePanel: () => void;
  toggle: () => void;
  setSelectedStock: (code: string | null, name?: string | null) => void;
}

const AssistantContext = createContext<AssistantContextValue | null>(null);
const AssistantActionsContext = createContext<AssistantActionsValue | null>(null);

/** 助手历史的 IndexedDB key —— 与个股问答分开,不会串味 */
const ASSISTANT_HISTORY_KEY = '__assistant__';

/** 本地留存多少条历史消息(≈20 轮);与个股问答的 MAX_MESSAGES_PER_STOCK 同量级 */
const MAX_HISTORY_ITEMS = 40;

/** 多少毫秒没交互就「睡着」(表情换成睡眠) */
const SLEEP_AFTER_MS = 5 * 60 * 1000;

/** 「完成」表情停留多久后回到 idle */
const DONE_LINGER_MS = 1600;

export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [mood, setMood] = useState<AssistantMood>('idle');
  const [sending, setSending] = useState(false);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);

  const idRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const sleepTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** 最新消息的镜像 —— 用来在流结束时持久化,避免在 setState 更新函数里做副作用 */
  const messagesRef = useRef<AssistantMessage[]>([]);
  messagesRef.current = messages;

  /* ---------------- 表情状态机辅助 ---------------- */

  const bumpWake = useCallback(() => {
    if (sleepTimerRef.current) {
      clearTimeout(sleepTimerRef.current);
      sleepTimerRef.current = null;
    }
    setMood((m) => (m === 'sleeping' ? 'idle' : m));
    sleepTimerRef.current = setTimeout(() => setMood((m) => (m === 'idle' ? 'sleeping' : m)), SLEEP_AFTER_MS);
  }, []);

  useEffect(() => {
    sleepTimerRef.current = setTimeout(() => setMood((m) => (m === 'idle' ? 'sleeping' : m)), SLEEP_AFTER_MS);
    return () => {
      if (sleepTimerRef.current) clearTimeout(sleepTimerRef.current);
      if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
      abortRef.current?.abort();
    };
  }, []);

  /* ---------------- 历史 ---------------- */

  useEffect(() => {
    let alive = true;
    setMood('loading_history');
    void (async () => {
      const items = await getChatHistory(ASSISTANT_HISTORY_KEY);
      if (!alive) return;
      if (items.length > 0) {
        setMessages(
          items.map((it, i) => ({
            id: 100000 + i,
            role: it.role,
            text: it.text,
          })),
        );
      }
      setMood('idle');
    })();
    return () => {
      alive = false;
    };
  }, []);

  /* ---------------- 对话 ---------------- */

  const send = useCallback(
    (rawQuestion: string) => {
      const question = rawQuestion.trim();
      if (!question || sending) return;
      bumpWake();

      const userId = ++idRef.current;
      const aiId = ++idRef.current;
      setMessages((m) => [
        ...m,
        { id: userId, role: 'user', text: question },
        { id: aiId, role: 'ai', text: '', streaming: true },
      ]);
      setSending(true);
      setMood('received');

      // 历史:只带最近若干轮(与后端 MAX_HISTORY_TURNS 对齐,后端还会再截一次)
      const baseItems = messages
        .filter((m) => m.text.trim() && !m.error)
        .slice(-12)
        .map((m) => ({ role: m.role, text: m.text }));
      // 本轮要落库的历史 = 旧历史 + 本次提问 + 本次回答
      // ⚠️ 回答文本用**局部变量**累积,不用 state —— .finally() 触发时
      //    React 的 setState 可能还没提交,那时读 state 会丢掉最后一截。
      const nextItems: AssistantHistoryItem[] = [...baseItems, { role: 'user', text: question }];
      let aiText = '';

      const controller = new AbortController();
      abortRef.current = controller;

      const patch = (fn: (m: AssistantMessage) => AssistantMessage) =>
        setMessages((prev) => prev.map((x) => (x.id === aiId ? fn(x) : x)));

      setMood('searching');
      void streamAssistant({
        question,
        stockCode: selectedCode,
        history: baseItems,
        signal: controller.signal,
        onText: (piece) => {
          aiText += piece;
          setMood((m) => (m === 'speaking' ? m : 'speaking'));
          patch((m) => ({ ...m, text: m.text + piece, streaming: true }));
        },
        onError: (message) => {
          patch((m) => ({ ...m, text: message, streaming: false, error: true }));
          setMood('error');
          setSending(false);
        },
        onDone: () => {
          patch((m) => ({ ...m, streaming: false }));
          setMood('done');
          setSending(false);
          if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
          doneTimerRef.current = setTimeout(() => setMood((m) => (m === 'done' ? 'idle' : m)), DONE_LINGER_MS);
        },
      })
        .catch((e: unknown) => {
          const msg = e instanceof Error ? e.message : '助手暂时无法回答';
          patch((m) => ({ ...m, text: msg, streaming: false, error: true }));
          // LLM 没配置(503)是一种「不可用」,不是「出错」——表情不一样
          setMood(msg.includes('未配置 LLM') ? 'unavailable' : 'error');
          setSending(false);
        })
        .finally(() => {
          abortRef.current = null;
          const items = aiText.trim()
            ? [...nextItems, { role: 'ai' as const, text: aiText }]
            : nextItems;
          void setChatHistory(ASSISTANT_HISTORY_KEY, items.slice(-MAX_HISTORY_ITEMS));
        });
    },
    [bumpWake, messages, selectedCode, sending],
  );

  const clearHistory = useCallback(() => {
    setMessages([]);
    void setChatHistory(ASSISTANT_HISTORY_KEY, []);
    setMood('idle');
    bumpWake();
  }, [bumpWake]);

  const setSelectedStock = useCallback(
    (code: string | null, name?: string | null) => {
      setSelectedCode(code);
      setSelectedName(name ?? null);
    },
    [],
  );

  const openPanel = useCallback(() => {
    bumpWake();
    setOpen(true);
  }, [bumpWake]);
  const closePanel = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => {
    bumpWake();
    setOpen((v) => !v);
  }, [bumpWake]);

  const value = useMemo<AssistantContextValue>(
    () => ({
      open,
      messages,
      mood,
      sending,
      selectedCode,
      selectedName,
      openPanel,
      closePanel,
      toggle,
      send,
      clearHistory,
      setSelectedStock,
    }),
    [
      open,
      messages,
      mood,
      sending,
      selectedCode,
      selectedName,
      openPanel,
      closePanel,
      toggle,
      send,
      clearHistory,
      setSelectedStock,
    ],
  );

  // 动作 context:**只含引用稳定的回调** → value 永远不变 → 消费它的页面永不因助手重渲染
  const actions = useMemo<AssistantActionsValue>(
    () => ({ openPanel, closePanel, toggle, setSelectedStock }),
    [openPanel, closePanel, toggle, setSelectedStock],
  );

  return (
    <AssistantActionsContext.Provider value={actions}>
      <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>
    </AssistantActionsContext.Provider>
  );
}

/** 取助手状态上下文(必须在 AssistantProvider 内使用) */
export function useAssistant(): AssistantContextValue {
  const ctx = useContext(AssistantContext);
  if (!ctx) throw new Error('useAssistant 必须在 <AssistantProvider> 内使用');
  return ctx;
}

/**
 * 取助手的**动作**(引用稳定)。
 *
 * 页面只需要「把选中票报给助手」这类动作时,**必须用这个**而不是 `useAssistant()` ——
 * 后者会在助手每吐一个 token 时触发整页重渲染。
 */
export function useAssistantActions(): AssistantActionsValue {
  const ctx = useContext(AssistantActionsContext);
  if (!ctx) throw new Error('useAssistantActions 必须在 <AssistantProvider> 内使用');
  return ctx;
}
