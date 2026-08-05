'use client';

import { Suspense, useEffect, useState } from 'react';

import { useRouter, useSearchParams } from 'next/navigation';

import { WinrateCard } from '@/components/positions/WinrateCard';
import { DailyAnalysisList } from '@/components/positions/DailyAnalysisList';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';

/**
 * 复盘历史页(v2.4)
 *
 * 顶部胜率卡(5/10/30/60/90 天) + 历史分析列表(N 天后涨跌 + 评语展开)
 * URL: /replay-history?code=601899.SH
 */
function ReplayHistoryInner() {
  const router = useRouter();
  const search = useSearchParams();
  const [code, setCode] = useState<string>(search?.get('code') ?? '');
  const [draft, setDraft] = useState<string>(search?.get('code') ?? '');

  useEffect(() => {
    const c = search?.get('code') ?? '';
    if (c) {
      setCode(c);
      setDraft(c);
    }
  }, [search]);

  const submit = () => {
    const v = draft.trim().toUpperCase();
    if (!v) return;
    setCode(v);
    router.replace(`/replay-history?code=${encodeURIComponent(v)}`);
  };

  return (
    <div className="min-h-screen bg-bg-base px-4 py-6 max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">📊 复盘历史</h1>
        <a
          href="/"
          className="text-xs text-text-ter hover:text-text-sec"
        >
          ← 返回首页
        </a>
      </div>

      {/* 股票代码选择 */}
      <Card padding="md">
        <div className="flex items-center gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            placeholder="股票代码,如 601899.SH 或 000001"
            className="flex-1 px-3 py-2 text-sm rounded-lg bg-white/5 border border-white/10 focus:border-accent outline-none text-text-pri placeholder:text-text-ter font-mono"
          />
          <Button onClick={submit} variant="secondary" size="sm">
            查看
          </Button>
        </div>
        <p className="text-xs text-text-ter mt-2">
          提示:在首页持仓列表点击某只股票后,URL 带 ?code=XXX 直接跳转;或在上方手动输入代码。
        </p>
      </Card>

      {code ? (
        <>
          <WinrateCard stockCode={code} />
          <DailyAnalysisList stockCode={code} />
        </>
      ) : (
        <Card padding="lg" className="text-center">
          <p className="text-text-ter text-sm">
            请输入股票代码查看 AI 分析历史与胜率。
          </p>
        </Card>
      )}
    </div>
  );
}

export default function ReplayHistoryPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-bg-base px-4 py-6 max-w-4xl mx-auto">
        <div className="text-text-ter text-sm">加载中…</div>
      </div>
    }>
      <ReplayHistoryInner />
    </Suspense>
  );
}