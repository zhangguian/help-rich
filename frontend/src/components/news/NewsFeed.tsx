'use client';

import { useEffect, useState } from 'react';

import { apiGet } from '@/lib/api';

import { Card } from '@/components/ui/Card';
import { SkeletonState } from '@/components/ui/States';

interface NewsItem {
  id: number;
  richText: string;
  type: number;
  createTime: string;
  tag: Array<{ id: string; name: string }> | string;
}

/**
 * 新浪 7×24 快讯(guide §9.2,客户端拉取,不阻塞首页 SSR)
 */
export function NewsFeed() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<{ items: NewsItem[] }>('/news/sina?page=1&page_size=8')
      .then((r) => setItems(r.items))
      .catch((e) => setError(e?.response?.data?.detail?.message ?? '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section>
      <h2 className="text-lg font-semibold mb-3">📰 7×24 快讯</h2>
      {loading && <SkeletonState rows={3} height="h-10" />}
      {error && (
        <Card padding="md">
          <p className="text-up text-sm">⚠ {error}</p>
        </Card>
      )}
      {!loading && !error && (
        <Card padding="md" className="divide-y divide-bd-subtle">
          {items.length === 0 && (
            <p className="text-text-ter text-sm py-4 text-center">暂无快讯</p>
          )}
          {items.map((it) => (
            <article key={it.id} className="py-2.5">
              <p className="text-sm leading-relaxed">{it.richText}</p>
              <p className="text-xs text-text-ter mt-1">{it.createTime}</p>
            </article>
          ))}
        </Card>
      )}
    </section>
  );
}
