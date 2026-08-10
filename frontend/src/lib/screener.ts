/** screener 模块的 API client(v2.6) */
import { apiDelete, apiGet, apiPost } from './api';

export interface ScreenerRun {
  id: number;
  runDate: string;
  generatedAt: string | null;
  scoringVersion: string;
  poolSize: number;
  totalPicks: number;
  elapsedSec: number | null;
  note: string | null;
}

export interface ScreenerPick {
  rank: number;
  stockCode: string;
  stockName: string;
  score: number;
  mainNetInflowYi: number | null;
  volumeRatio: number | null;
  changePct: number | null;
  turnoverProxy: number | null;
  consecutiveUpDays: number;
  sector: string | null;
  sectorInflowRank: number | null;
  triggeredRules: string[];
  /** v2.6:该股是否已被用户标入观察池 */
  isWatched: boolean;
  /** v2.6.1:本地规则拼接的入选理由(1-2 句中文);NULL 表示旧 run 未补算 */
  reason: string | null;
}

export interface LlmPickItem {
  rank: number;
  stockCode: string;
  view: '偏多' | '中性' | '偏空';
  highlights: string;
  risks: string;
  action: '可关注' | '轻仓' | '观望';
}

export interface LlmPicksResponse {
  runId: number;
  runDate: string;
  status: 'success' | 'failed';
  cached: boolean;
  model: string | null;
  summary: string | null;
  picks: LlmPickItem[];
  requestedAt: string | null;
}

export interface ScreenerLatestResponse {
  run: ScreenerRun;
  picks: ScreenerPick[];
}

export interface ScreenerPoolResponse {
  count: number;
  preview: Array<{ stockCode: string; stockName: string }>;
}

export interface ScreenerRunsResponse {
  count: number;
  runs: ScreenerRun[];
}

export async function fetchScreenerLatest(): Promise<ScreenerLatestResponse> {
  return apiGet<ScreenerLatestResponse>('/screener/latest');
}

export async function fetchScreenerPool(): Promise<ScreenerPoolResponse> {
  return apiGet<ScreenerPoolResponse>('/screener/pool');
}

export async function fetchScreenerRuns(days = 10): Promise<ScreenerRunsResponse> {
  return apiGet<ScreenerRunsResponse>(`/screener/runs?days=${days}`);
}

export async function triggerLlmPick(force = false): Promise<LlmPicksResponse> {
  return apiPost<LlmPicksResponse>(`/screener/latest/llm-pick${force ? '?force=true' : ''}`);
}

// ============================================================
// v2.6 观察池(Watchlist)
// ============================================================

export interface WatchlistAddRequest {
  stockCode: string;
  stockName: string;
  note?: string;
}

export interface WatchlistAddResponse {
  watched: boolean;
  alreadyExisted: boolean;
  watchlistId: number;
  markedAt: string;
  markedClose: string | null;
}

export interface WatchlistRemoveResponse {
  removed: boolean;
}

/** 单只股在某个 period 内的最新表现 */
export interface WatchlistStockInPeriod {
  watchlistId: number;
  stockCode: string;
  stockName: string;
  markedAt: string;
  markedClose: string | null;
  status: 'active' | 'closed';
  latestPctFromMarked: number | null;
}

/** 周/月分桶记录 */
export interface PeriodBucket {
  label: string;            // "2026-W32" / "2026-08"
  start: string;            // ISO date
  end: string;
  stockCount: number;
  avgChangePct: number;     // 0.025 = +2.5%
  hitCount: number;
  missCount: number;
  hitRate: number;          // 0~1
  stocks: WatchlistStockInPeriod[];
}

export interface WatchlistSummary {
  summary: {
    totalWatched: number;
    overallAvgChange: number;
    overallHitRate: number;
    /** v2.6.1:今日单日平均涨跌(最新 pct - 上一个 pct) */
    todayAvgChange: number;
    /** v2.6.1:今日上涨股数 */
    todayHitCount: number;
    /** v2.6.1:今日下跌股数 */
    todayMissCount: number;
    /** v2.6.1:被计入今日涨跌的股数(有 ≥2 条 daily record 的) */
    todayCounted: number;
    /** v2.6.1:今日日期(YYYY-MM-DD,最新 daily record 的 trade_date) */
    todayDate: string | null;
    refreshedAt: string | null;
  };
  weeks: PeriodBucket[];
  months: PeriodBucket[];
}

export async function addToWatchlist(payload: WatchlistAddRequest): Promise<WatchlistAddResponse> {
  return apiPost<WatchlistAddResponse>('/screener/watchlist', payload);
}

export async function removeFromWatchlist(stockCode: string): Promise<WatchlistRemoveResponse> {
  return apiDelete<WatchlistRemoveResponse>(`/screener/watchlist/${encodeURIComponent(stockCode)}`);
}

export async function fetchWatchlistSummary(refresh = false): Promise<WatchlistSummary> {
  return apiGet<WatchlistSummary>(`/screener/watchlist${refresh ? '?refresh=true' : ''}`);
}