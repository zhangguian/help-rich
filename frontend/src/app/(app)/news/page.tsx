import { NewsFeed } from '@/components/news/NewsFeed';

import { PageShell } from '@/components/shell/PageShell';

/** 快讯 — /news */
export default function NewsPage() {
  return (
    <PageShell title="快讯" subtitle="7×24 市场快讯" icon="📰">
      <NewsFeed />
    </PageShell>
  );
}
