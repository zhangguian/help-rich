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
    validate,
)


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

        channels = self._channels_for(alert)

        price_txt = f"{ctx.price:.2f}" if ctx.price is not None else "?"
        message = NotifyMessage(
            title=f"价格提醒 · {alert.stock_code}",
            body=(
                f"{alert.name}\n触发条件:{describe(conditions)}\n"
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
        await price_alert_repo.record_trigger(
            alert.id,
            status=status,
            snapshot={"price": ctx.price, "change_pct": ctx.change_pct},
            results=[{"channel": r.channel, "ok": r.ok, "detail": r.detail} for r in results],
        )
        return results

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

    # ---------- 内部 ----------

    def _channels_for(self, alert) -> list[str]:
        """规则未指定渠道时,跟随全局已启用的渠道。"""
        if alert.channels_json:
            try:
                ch = json.loads(alert.channels_json)
                if ch:
                    return ch
            except (json.JSONDecodeError, TypeError):
                pass
        return ["console"]  # 兜底:至少写日志

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
