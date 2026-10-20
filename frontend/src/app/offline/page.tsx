'use client';

import Link from 'next/link';

/** 断网回退页(Service Worker 导航失败时命中) */
export default function OfflinePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <div className="text-6xl" aria-hidden>
        📡
      </div>
      <h1 className="text-2xl font-semibold text-text-pri">当前处于离线状态</h1>
      <p className="max-w-md text-sm leading-relaxed text-text-sec">
        买股工具室需要联网获取实时行情与持仓数据。
        行情一旦过期就可能误导决策,因此离线时我们不会展示缓存的旧价格。
      </p>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg-base transition hover:opacity-90"
        >
          重新加载
        </button>
        <Link
          href="/"
          className="rounded-lg border border-border-base px-4 py-2 text-sm font-medium text-text-pri transition hover:bg-bg-elev"
        >
          返回首页
        </Link>
      </div>
    </main>
  );
}
