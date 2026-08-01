'use client';

import { useEffect, useState } from 'react';

import Link from 'next/link';

import { apiGet } from '@/lib/api';
import type { TransactionListResponse } from '@/lib/types';

import { Button } from '../ui/Button';

/**
 * Onboarding 三步引导(P7.1)
 *
 * - 检测:首次访问时,无流水 + 无 Key → 浮层提示
 * - 步骤 1:录入第一笔
 * - 步骤 2:查看评分
 * - 步骤 3:设置止损
 * - 关闭后写入 localStorage,不再出现
 */
const ONBOARDING_KEY = 'rich-onboarding-done';

export function OnboardingHint() {
  const [show, setShow] = useState(false);
  const [step, setStep] = useState(0);
  const [hasTransactions, setHasTransactions] = useState<boolean | null>(null);
  const [hasKeys, setHasKeys] = useState<boolean | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      if (localStorage.getItem(ONBOARDING_KEY)) return;
    } catch {
      return;
    }
    Promise.all([
      apiGet<TransactionListResponse>('/transactions').then(
        (r) => r.items.length > 0,
        () => false,
      ),
      apiGet<{ deepseek: boolean; minimax: boolean; doubao: boolean }>(
        '/llm/keys',
      ).then(
        (k) => k.deepseek || k.minimax || k.doubao,
        () => false,
      ),
    ]).then(([txOk, keyOk]) => {
      setHasTransactions(txOk);
      setHasKeys(keyOk);
      // 全部完成 → 不显示
      if (txOk && keyOk) return;
      setShow(true);
    });
  }, []);

  const close = () => {
    try {
      localStorage.setItem(ONBOARDING_KEY, '1');
    } catch {
      /* ignore */
    }
    setShow(false);
  };

  if (!show) return null;

  const STEPS = [
    {
      title: '👋 欢迎使用盘后诊股室',
      desc: '3 步快速体验:录入 → 评分 → 止损',
    },
    {
      title: '📋 第 1 步 · 录入第一笔交易',
      desc: hasTransactions
        ? '✅ 已录入,进入下一步'
        : '在流水页录入一笔买入/卖出',
      done: hasTransactions,
      cta: { label: '去录入', href: '/transactions' },
    },
    {
      title: '🤖 第 2 步 · 配置 LLM Key',
      desc: hasKeys
        ? '✅ 已配置,进入下一步'
        : '设置页填入 DeepSeek / MiniMax / 豆包 API Key',
      done: hasKeys,
      cta: { label: '去配置', href: '/settings' },
    },
    {
      title: '🛡 第 3 步 · 持仓页设止损',
      desc: '首页持仓卡 [+ 设止损],价格触达自动提醒',
    },
  ];

  const cur = STEPS[step]!;
  const isLast = step >= STEPS.length - 1;

  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-bg-surface rounded-md p-6 max-w-md w-full space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="text-xs text-text-ter">
            步骤 {step + 1} / {STEPS.length}
          </div>
          <button
            className="text-text-ter hover:text-text-pri text-xl leading-none"
            onClick={close}
            aria-label="关闭"
          >
            ×
          </button>
        </div>

        <h2 className="text-lg font-semibold">{cur.title}</h2>
        <p className="text-sm text-text-sec">{cur.desc}</p>

        <div className="flex justify-between items-center pt-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            ← 上一步
          </Button>
          <div className="flex gap-2">
            {cur.cta && (
              <Link href={cur.cta.href}>
                <Button variant="secondary" size="sm">
                  {cur.cta.label}
                </Button>
              </Link>
            )}
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                if (isLast) close();
                else setStep((s) => s + 1);
              }}
            >
              {isLast ? '完成' : '下一步 →'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}