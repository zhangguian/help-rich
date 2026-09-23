/** ReflectionCard 22:00 消息面提示 API client (改动 C, v2.7) */
import { apiGet } from '../api';

export interface ReflectionContextSummary {
  announcementsCount: number;
  newsCount: number;
  topNewsTitle: string;
  fetchedFor: string[];
}

export interface ReflectionContextResponse {
  date: string;
  summary: ReflectionContextSummary | null;
  fetchedForCount: number;
  fetchedFor: string[];
}

export async function fetchReflectionContext(
  dateISO: string,
): Promise<ReflectionContextResponse | null> {
  try {
    return await apiGet<ReflectionContextResponse>(
      `/reflection-context?date=${dateISO}`,
    );
  } catch {
    // 失败静黙: 不打扰 22:00 弹窗体验
    return null;
  }
}
