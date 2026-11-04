"""价格提醒服务(阶段1)。

把「条件引擎 + 仓储 + 通知渠道 + 去重限流」编排成用例:
- CRUD:创建/更新时先 `validate` 条件树,非法立即拒绝(给用户明确反馈)
- 触发:对每条启用规则求值 → 命中则走通知(带冷却/日限流)→ 记流水
"""
from __future__ import annotations

import json

from app.core.logging import logger
from app.core.stock_code import normalize_code
from app.modules.alert.repository import price_alert_repo
from app.modules.notify.service import (
    NotifyLevel,
    NotifyMessage,
    notify_service,
)
from app.modules.alert.engine import (
    AlertContext,
    describe,
    evaluate,
    fingerprint,
    notification_meta,
    validate,
)
from app.services.event_bus import event_bus

# 前端 SSE 按事件名过滤(与 signal 模块的 EVENT_SIGNAL_FIRED 同一套路)
EVENT_PRICE_ALERT_FIRED = "price_alert_fired"


def build_fired_payload(
    alert,
    trig=None,
    price: float | None = None,
    conditions_text: str = "",
    channels: list | None = None,
    kind: str | None = None,
) -> dict:
    """构造「提醒响了」的事件负载。

    **实时推送与断线补发必须共用这一个函数** —— 两边字段不一致的话,
    前端就得写两套解析,迟早漏字段。两边都带 `trigger_id`,前端靠它去重。

    `kind`:提醒种类(来自条件树顶层的 `kind`,如 `"pre_alert"` 预警)——
    前端据此显示不同徽章,不靠猜 name 前缀。
    """
    price_txt = f"{price:.2f}" if price is not None else "?"
    triggered_at = None
    if trig is not None and getattr(trig, "triggered_at", None) is not None:
        triggered_at = trig.triggered_at.isoformat()
    return {
        "event": EVENT_PRICE_ALERT_FIRED,
        "trigger_id": trig.id if trig is not None else None,
        "triggered_at": triggered_at,
        "kind": kind,
        "alert": {
            "id": alert.id,
            "stock_code": alert.stock_code,
            "name": alert.name,
            "conditions_text": conditions_text,
            "price": price,
            "title": f"价格提醒 · {alert.stock_code}",
            "body": (
                f"{alert.name}\n"
                f"触发条件:{conditions_text}\n"
                f"当前价:{price_txt}"
            ),
        },
        "channels": channels or [],
    }


class PriceAlertService:
    # ---------- CRUD ----------

    async def create(
        self,
        stock_code: str,
        conditions: dict,
        name: str = "",
        cooldown_sec: int = 1800,
        daily_limit: int = 5,
        expires_at=None,
        channels: list[str] | None = None,
    ) -> int:
        code = normalize_code(stock_code) or stock_code
        validate(conditions)  # 非法直接抛 AlertConditionError
        return await price_alert_repo.create(
            stock_code=code,
            name=name or f"{code} {describe(conditions)}"[:60],
            conditions_json=json.dumps(conditions, ensure_ascii=False),
            cooldown_sec=cooldown_sec,
            daily_limit=daily_limit,
            expires_at=expires_at,
            enabled=True,
            channels_json=json.dumps(channels, ensure_ascii=False) if channels else None,
        )

    async def update(self, alert_id: int, **kwargs) -> bool:
        if "conditions" in kwargs and kwargs["conditions"] is not None:
            validate(kwargs["conditions"])
            kwargs["conditions_json"] = json.dumps(kwargs["conditions"], ensure_ascii=False)
            del kwargs["conditions"]
        if "channels" in kwargs:
            ch = kwargs.pop("channels")
            kwargs["channels_json"] = json.dumps(ch, ensure_ascii=False) if ch else None
        return await price_alert_repo.update(alert_id, **kwargs)

    async def delete(self, alert_id: int) -> bool:
        return await price_alert_repo.delete(alert_id)

    async def list_alerts(self, stock_code: str | None = None) -> list[dict]:
        rows = await price_alert_repo.list_all(stock_code)
        return [self._to_dict(r) for r in rows]

    async def get_alert(self, alert_id: int):
        return await price_alert_repo.get(alert_id)

    async def list_triggers(self, alert_id: int, limit: int = 20):
        return await price_alert_repo.list_triggers(alert_id, limit)

    # ---------- 触发 ----------

    async def evaluate_alert(self, alert, ctx: AlertContext) -> bool:
        """单条规则求值(不发送)。调度器/单测用。"""
        try:
            conditions = json.loads(alert.conditions_json)
        except (json.JSONDecodeError, TypeError):
            return False
        return evaluate(conditions, ctx)

    async def fire(self, alert, ctx: AlertContext) -> list | None:
        """命中后推送(带去重/限流)。返回各渠道结果,被限流返回 None。"""
        try:
            conditions = json.loads(alert.conditions_json)
        except (json.JSONDecodeError, TypeError):
            return None

        channels = await self._channels_for(alert)

        price_txt = f"{ctx.price:.2f}" if ctx.price is not None else "?"
        conditions_text = describe(conditions)
        message = NotifyMessage(
            title=f"价格提醒 · {alert.stock_code}",
            body=(
                f"{alert.name}\n触发条件:{conditions_text}\n"
                f"当前价:{price_txt}"
            ),
            level=NotifyLevel.INFO,
            context={"stock_code": alert.stock_code, "price": ctx.price},
        )

        results = await notify_service.notify_with_limit(
            message,
            channels=channels,
            configs=None,  # 由 notify 自行解密取配置,alert 不触碰其仓储
            alert_key=f"alert:{alert.id}",
            fingerprint=fingerprint(conditions, ctx),
            cooldown_sec=alert.cooldown_sec,
            daily_limit=alert.daily_limit,
        )
        if results is None:
            # 被冷却/限流:记一笔 skipped,便于前端解释"为什么没推"
            await price_alert_repo.record_trigger(
                alert.id, status="skipped",
                snapshot={"price": ctx.price}, results=[]
            )
            return None

        status = "matched" if any(r.ok for r in results) else "failed"
        trig = await price_alert_repo.record_trigger(
            alert.id,
            status=status,
            snapshot={"price": ctx.price, "change_pct": ctx.change_pct},
            results=[{"channel": r.channel, "ok": r.ok, "detail": r.detail} for r in results],
        )
        await self._publish_fired(alert, ctx, conditions_text, results, trig, conditions)
        await self._disable_if_once(alert, conditions)
        return results

    async def _disable_if_once(self, alert, conditions: dict) -> bool:
        """**一次性**提醒:命中后自动停用(不删除,保留触发历史)。

        用于「预警」:进了一次准备区就不该反复提醒 —— 价格再在预警线附近晃,
        用户已经被提醒过��次了。价格离开预警区后,由清单同步逻辑**重新武装**它。
        """
        if not notification_meta(conditions).get("once"):
            return False
        try:
            await price_alert_repo.update(int(alert.id), enabled=False)
            return True
        except Exception as e:  # noqa: BLE001 — 停用失败不该让提醒链路崩掉
            logger.warning(f"[price-alert] 一次性提醒停用失败 {alert.id}: {e}")
            return False

    async def _publish_fired(
        self,
        alert,
        ctx: AlertContext,
        conditions_text: str,
        results: list,
        trig=None,
        conditions: dict | None = None,
    ) -> None:
        """把「真的响了」这件事广播到事件总线,供前端 SSE 弹应用内提示。

        ⚠️ 只在**通过冷却/日限流**(results is not None)时广播 —— 被限流的那次
        用户什么都没收到,再弹一次应用内提示等于骗人。
        """
        try:
            await event_bus.publish(
                build_fired_payload(
                    alert,
                    trig=trig,
                    price=ctx.price,
                    conditions_text=conditions_text,
                    channels=[
                        {"channel": r.channel, "ok": r.ok, "detail": r.detail}
                        for r in results
                    ],
                    kind=notification_meta(conditions or {}).get("kind"),
                )
            )
        except Exception as e:  # noqa: BLE001 — 广播失败不该让提醒链路崩掉
            logger.warning(f"[price-alert] 广播触发事件失败: {e}")

    async def scan(self, quotes: dict[str, AlertContext]) -> int:
        """批量评估所有启用规则。quotes: {stock_code: AlertContext}。

        返回本次触发条数。任一规则异常不影响其它规则。
        """
        alerts = await price_alert_repo.list_enabled_active()
        fired = 0
        for alert in alerts:
            ctx = quotes.get(alert.stock_code)
            if ctx is None:
                continue
            try:
                if not await self.evaluate_alert(alert, ctx):
                    continue
                results = await self.fire(alert, ctx)
                if results is not None:
                    fired += 1
            except Exception as e:  # noqa: BLE001 — 单条规则异常不拖垮扫描
                logger.warning(f"[price-alert] 规则 {alert.id} 评估异常: {e}")
        return fired

    async def pre_alert_codes(self) -> set[str]:
        """已停用的**预警提醒**对应的标的代码。

        调度器要为它们拉行情,才能判断「价格是否已离开预警区」→ 重新武装。
        停用的到价提醒(挂单消失导致的)不在其中 —— 那种不该再武装。
        """
        try:
            rows = await price_alert_repo.list_disabled()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[price-alert] 读取停用规则失败: {e}")
            return set()
        codes: set[str] = set()
        for row in rows:
            try:
                conditions = json.loads(row.conditions_json or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if notification_meta(conditions).get("kind") == "pre_alert":
                codes.add(row.stock_code)
        return codes

    async def rearm_pre_alerts(self, contexts: dict[str, AlertContext]) -> int:
        """**一次性预警提醒**离开预警区后重新武装,返回重新武装的条数。

        为什么必须有这一步:预警命中后会自动停用(`once`),而「重新武装」
        原本只挂在**清单页同步**里 —— 页面关着就不会重新武装,
        预警响一次就哑了。用户要的恰恰是「页面关着也能收到」,
        所以这一步必须由**后端调度器**承担,而不是依赖前端开着。

        判据:**当前价不再满足预警条件**(与「命中」互为补集)。
        不需要知道方向,也不需要知道预警线是多少 —— 条件树本身就是判据。

        ⚠️ **已退役(`retired: true`)的预警不重新武装**:
        这个判据分不清「一次性命中后停用」和「挂单已消失、被业务侧停用」——
        后者的做T已经结束,重新武装等于继续替一笔不存在的交易订阅提醒。

        行情取不到 → 不做任何动作(宁可少武装一次,也不编数据)。
        """
        try:
            rows = await price_alert_repo.list_disabled()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[price-alert] 读取停用规则失败: {e}")
            return 0

        rearmed = 0
        for row in rows:
            try:
                conditions = json.loads(row.conditions_json or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            meta = notification_meta(conditions)
            if meta.get("kind") != "pre_alert":
                continue
            if meta.get("retired"):
                # 挂单已消失 → 业务侧主动退役,不是「命中后停用」,别再武装回去
                continue
            ctx = contexts.get(row.stock_code)
            if ctx is None or ctx.price is None:
                continue  # 行情未知 → 不动它
            if evaluate(conditions, ctx):
                continue  # 还在预警区 → 保持停用
            try:
                if await price_alert_repo.update(int(row.id), enabled=True):
                    rearmed += 1
                    logger.info(
                        f"[price-alert] 预警 {row.id}({row.stock_code}) 已离开预警区,重新武装"
                    )
            except Exception as e:  # noqa: BLE001 — 单条失败不拖垮整轮
                logger.warning(f"[price-alert] 预警 {row.id} 重新武装失败: {e}")
        return rearmed

    # ---------- 内部 ----------

    async def _channels_for(self, alert) -> list[str]:
        """规则未指定渠道时,跟随全局已启用的渠道。

        ⚠️ 这里必须真的去读全局配置 —— 早先的实现硬编码 `return ["console"]`,
        与本函数的注释(以及用户在「通知设置」里的直觉)相反:
        后果是「桌面通知」开着也**永远收不到**到价提醒,只有日志。
        规则自己指定了渠道(`channels_json`)时以规则为准。

        读不到配置 / 一个渠道都没启用时兜底到 console —— 至少写日志,
        宁可「只有日志」也不要「什么都不发」。
        """
        if alert.channels_json:
            try:
                ch = json.loads(alert.channels_json)
                if ch:
                    return ch
            except (json.JSONDecodeError, TypeError):
                pass
        try:
            enabled = await notify_service.enabled_channels()
        except Exception as e:  # noqa: BLE001 — 配置读不到不该让提醒整条链路崩掉
            logger.warning(f"[price-alert] 读取已启用渠道失败,按 console 兜底: {e}")
            enabled = []
        return enabled or ["console"]

    @staticmethod
    def _to_dict(row) -> dict:
        try:
            conditions = json.loads(row.conditions_json)
        except (json.JSONDecodeError, TypeError):
            conditions = {}
        try:
            channels = json.loads(row.channels_json) if row.channels_json else None
        except (json.JSONDecodeError, TypeError):
            channels = None
        return {
            "id": row.id,
            "stock_code": row.stock_code,
            "name": row.name,
            "conditions": conditions,
            "conditions_text": describe(conditions),
            "cooldown_sec": row.cooldown_sec,
            "daily_limit": row.daily_limit,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "enabled": row.enabled,
            "channels": channels,
            "triggered_count": row.triggered_count,
            "last_triggered_at": (
                row.last_triggered_at.isoformat() if row.last_triggered_at else None
            ),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


price_alert_service = PriceAlertService()

__all__ = ["PriceAlertService", "price_alert_service"]
