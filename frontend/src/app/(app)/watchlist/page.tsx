import { WatchlistPanel } from '@/components/screener/WatchlistPanel';

import { PageShell } from '@/components/shell/PageShell';

/** 观察池 — /watchlist */
export default function WatchlistPage() {
  return (
    <PageShell
      title="⭐ 观察池"
      subtitle="选股页标选标的的逐日 K 线记录与周/月胜率"
      backHref="/screener"
      backLabel="返回选股"
    >
      <WatchlistPanel />
    </PageShell>
  );
}
