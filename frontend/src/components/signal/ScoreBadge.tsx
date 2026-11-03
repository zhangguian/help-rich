'use client';

import { useEffect, useState } from 'react';

import clsx from 'clsx';

/**
 * 评分徽章(P4.5,ui-ux §5.4)
 *
 * 6 维度各 20 分,满分 120 → 5 档颜色分段(原 100 分制档位 ×1.2):
 * >=96 good / 72-95 mid / 48-71 warn / 24-47 bad / <24 deepbad
 * 滚动数字动效(ui-ux §10.2):分数从 0 → 当前值
 */
type ScoreLevel = 'good' | 'mid' | 'warn' | 'bad' | 'deepbad';

/** 评分满分(6 维 × 20) */
export const SCORE_MAX = 120;

function levelOf(score: number): ScoreLevel {
  if (score >= 96) return 'good';
  if (score >= 72) return 'mid';
  if (score >= 48) return 'warn';
  if (score >= 24) return 'bad';
  return 'deepbad';
}

const levelClasses: Record<ScoreLevel, string> = {
  good: 'bg-down-bg text-down border-down/20',
  mid: 'bg-warn-bg text-warn border-warn/20',
  warn: 'bg-warn-bg text-warn border-warn/30',
  bad: 'bg-up-bg text-up border-up/30',
  deepbad: 'bg-up-bg text-up border-up/40',
};

export function ScoreBadge({
  score,
  loading = false,
  className,
}: {
  score: number | null;
  loading?: boolean;
  className?: string;
}) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (score === null) return;
    let raf = 0;
    const start = performance.now();
    const dur = 600;
    const from = display;
    const to = score;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      setDisplay(Math.round(from + (to - from) * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [score]);

  if (loading || score === null) {
    return (
      <span
        className={clsx(
          'inline-block w-10 h-5 rounded-sm bg-bg-subtle animate-pulse',
          className,
        )}
        title="评分计算中"
      />
    );
  }

  const level = levelOf(score);
  return (
    <span
      className={clsx(
        'inline-flex items-center justify-center min-w-[2.5rem] px-1.5 h-5 rounded-sm border font-mono text-xs font-semibold tabular-nums',
        levelClasses[level],
        className,
      )}
      title={`评分 ${score} / ${SCORE_MAX}`}
    >
      {display}
    </span>
  );
}