'use client';

import clsx from 'clsx';

/**
 * 状态设计三件套(P7.2,ui-ux §11)
 *
 * - SkeletonState:骨架屏(加载中)
 * - ErrorState:错误态(可重试)
 * - StaleState:数据陈旧态(> 15min 未刷新,提示 [刷新])
 */

interface SkeletonProps {
  rows?: number;
  height?: string;
  className?: string;
}

export function SkeletonState({ rows = 3, height = 'h-12', className }: SkeletonProps) {
  return (
    <div className={clsx('space-y-2', className)} aria-busy="true" aria-label="加载中">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className={clsx(
            'bg-bg-subtle rounded-sm animate-pulse',
            height,
          )}
        />
      ))}
    </div>
  );
}

interface ErrorProps {
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  message = '加载失败,请重试',
  onRetry,
  className,
}: ErrorProps) {
  return (
    <div
      role="alert"
      className={clsx(
        'bg-up-bg text-up rounded-sm p-3 text-sm flex items-center justify-between gap-2',
        className,
      )}
    >
      <span>⚠ {message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-xs underline hover:opacity-80"
        >
          重试
        </button>
      )}
    </div>
  );
}

interface StaleProps {
  lastUpdated: Date | string;
  thresholdMinutes?: number;
  onRefresh?: () => void;
  className?: string;
}

export function StaleState({
  lastUpdated,
  thresholdMinutes = 15,
  onRefresh,
  className,
}: StaleProps) {
  const last = typeof lastUpdated === 'string' ? new Date(lastUpdated) : lastUpdated;
  const ageMin = (Date.now() - last.getTime()) / 60_000;
  if (ageMin <= thresholdMinutes) return null;
  return (
    <div
      role="status"
      className={clsx(
        'bg-warn-bg text-warn rounded-sm p-2 text-xs flex items-center justify-between gap-2',
        className,
      )}
    >
      <span>
        数据已 {Math.floor(ageMin)} 分钟未刷新(阈值 {thresholdMinutes}min)
      </span>
      {onRefresh && (
        <button onClick={onRefresh} className="underline hover:opacity-80">
          刷新
        </button>
      )}
    </div>
  );
}