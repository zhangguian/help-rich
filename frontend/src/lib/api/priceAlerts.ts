/**
 * 到价提醒 · 实时事件类型
 *
 * 数据来源:后端 SSE `GET /api/price-alerts/stream`(框架见 docs/api-contract/api-contract.md)。
 *
 * ⚠️ 后端推的是 snake_case,前端统一在 hook 里用 `snakeToCamel` 转过,
 * 所以这里定义的类型**一律 camelCase**(与项目其它 api 模块同规矩)。
 */
import { apiPost } from '@/lib/api';

/** 触发的那条规则 */
export interface PriceAlertFiredAlert {
  id: number;
  stockCode: string;
  name: string;
  /** 可读条件,如「价格 <= 8.771」 */
  conditionsText: string;
  /** 触发瞬间的价格;拿不到就是 null(不编数字) */
  price: number | null;
  title: string;
  body: string;
}

/** 单个渠道的送达结果 */
export interface PriceAlertChannelResult {
  channel: string;
  ok: boolean;
  detail?: string | null;
}

/** 一次「真的响了」的提醒 */
export interface PriceAlertFiredEvent {
  event: 'price_alert_fired';
  /** 提醒种类:`pre_alert` = 预警(到价之前的「准备」信号);其余/null = 到价提醒 */
  kind?: string | null;
  /** 触发流水 id —— 前端靠它去重(断线补发 + 实时推送会撞车) */
  triggerId: number | null;
  triggeredAt: string | null;
  alert: PriceAlertFiredAlert;
  channels: PriceAlertChannelResult[];
}

/** 建连时的补发快照(最近 10 分钟内真的响了的) */
export interface PriceAlertSnapshotEvent {
  event: 'price_alert_snapshot';
  items: PriceAlertFiredEvent[];
}

/** 弹窗用的展示项(store 内部) */
export interface PriceAlertPopupItem extends PriceAlertFiredEvent {
  /** 前端生成的本地 id,用于关闭动画的 key */
  localId: string;
}

/**
 * 弹窗通路自检:让后端广播一条合成的「提醒响了」。
 * 零副作用(不碰规则、不记流水),用来当场验证弹窗到底弹不弹得出来。
 */
export async function testPriceAlertPopup(): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/price-alerts/test-popup', {});
}
