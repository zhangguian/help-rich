'use client';

/**
 * 诊断状态 store(P4.6 + P4.7)
 *
 * - pending:等待评分的交易 id 集合(模块级,不参与响应式)
 * - scores / breakdowns:tradeId → 评分 + 5 维度
 * - comments:tradeId → AI 评语文本
 * - aiStatus:tradeId → pending / scored / success / no_key / failed
 * - failed:tradeId → 失败原因
 */
import { create } from 'zustand';

export type AiStatus = 'pending' | 'scored' | 'success' | 'no_key' | 'failed';

interface DiagnoseState {
  scores: Record<number, number | null>;
  breakdowns: Record<number, Record<string, number> | null>;
  comments: Record<number, string | null>;
  aiStatus: Record<number, AiStatus>;
  failed: Record<number, string>;
  pendingIds: () => number[];
  setScore: (id: number, score: number | null, breakdown: Record<string, number> | null) => void;
  setComment: (id: number, comment: string | null) => void;
  setFailed: (id: number, reason: string) => void;
  markDone: (id: number) => void;
  addPending: (id: number) => void;
  reset: () => void;
}

// pending 是模块级 Set,避免进入 zustand 状态(不需要响应式)
const pending = new Set<number>();

export const useDiagnoseStore = create<DiagnoseState>((set, get) => ({
  scores: {},
  breakdowns: {},
  comments: {},
  aiStatus: {},
  failed: {},
  pendingIds: () => Array.from(pending),
  setScore: (id, score, breakdown) =>
    set((s) => ({
      scores: { ...s.scores, [id]: score },
      breakdowns: { ...s.breakdowns, [id]: breakdown },
      aiStatus: { ...s.aiStatus, [id]: score !== null ? 'scored' : s.aiStatus[id] ?? 'pending' },
    })),
  setComment: (id, comment) =>
    set((s) => ({
      comments: { ...s.comments, [id]: comment },
      aiStatus: { ...s.aiStatus, [id]: 'success' },
    })),
  setFailed: (id, reason) =>
    set((s) => ({
      failed: { ...s.failed, [id]: reason },
      aiStatus: { ...s.aiStatus, [id]: 'failed' },
    })),
  markDone: (id) => {
    pending.delete(id);
  },
  addPending: (id) => {
    pending.add(id);
    set((s) => ({ aiStatus: { ...s.aiStatus, [id]: 'pending' } }));
  },
  reset: () => {
    pending.clear();
    set({ scores: {}, breakdowns: {}, comments: {}, aiStatus: {}, failed: {} });
  },
}));