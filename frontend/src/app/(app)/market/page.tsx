import { MarketOverviewPage } from '@/components/market/MarketOverviewPage';

/** 大盘 — /market */
export default function MarketPage() {
  return (
    <main className="p-5 h-[calc(100vh-2.5rem)] overflow-hidden">
      <MarketOverviewPage />
    </main>
  );
}
