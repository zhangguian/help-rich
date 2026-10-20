"""引导中心(阶段5)。

新用户第一次打开工具时,并不知道该做什么、缺什么配置。本服务把
「系统当前就绪度」聚合成一份可执行的引导清单。

设计原则:**不编造进度**。每一步的完成状态都来自真实的系统检查
(数据库有没有表、模型 Key 配没配、行情通不通、有没有持仓),
而不是一个前端自己维护的 localStorage 标记 —— 后者一旦和真实状态脱节,
用户会照着一个已经失效的清单操作。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import logger


@dataclass(slots=True)
class GuideStep:
    """一个引导步骤。"""

    key: str
    title: str
    description: str
    action_label: str
    action_href: str
    done: bool
    optional: bool = False
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "action_label": self.action_label,
            "action_href": self.action_href,
            "done": self.done,
            "optional": self.optional,
            "detail": self.detail,
        }


@dataclass(slots=True)
class OnboardingStatus:
    steps: list[GuideStep] = field(default_factory=list)

    @property
    def completed(self) -> int:
        return sum(1 for s in self.steps if s.done)

    @property
    def required_total(self) -> int:
        return sum(1 for s in self.steps if not s.optional)

    @property
    def required_done(self) -> int:
        return sum(1 for s in self.steps if not s.optional and s.done)

    @property
    def progress_pct(self) -> int:
        total = self.required_total
        if total == 0:
            return 100
        return round(self.required_done / total * 100)

    @property
    def finished(self) -> bool:
        return self.required_done >= self.required_total

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "progress_pct": self.progress_pct,
            "completed": self.completed,
            "required_done": self.required_done,
            "required_total": self.required_total,
            "finished": self.finished,
        }


class OnboardingService:
    """聚合系统就绪度。"""

    async def get_status(self) -> OnboardingStatus:
        st = OnboardingStatus()
        st.steps.append(await self._step_database())
        st.steps.append(await self._step_quote())
        st.steps.append(await self._step_llm())
        st.steps.append(await self._step_position())
        st.steps.append(self._step_notify())
        st.steps.append(await self._step_alert())
        st.steps.append(await self._step_screener())
        st.steps.append(self._step_paper())
        st.steps.append(await self._step_multi_account())
        return st

    # ---------- 各项检查 ----------

    async def _step_database(self) -> GuideStep:
        step = GuideStep(
            key="database",
            title="初始化数据库",
            description="首次使用需要建表并完成迁移,否则无法保存持仓与流水。",
            action_label="查看迁移状态",
            action_href="/settings",
            done=False,
        )
        try:
            from sqlalchemy import select

            from app.db import async_session
            from app.models.orm import Account, Position

            async with async_session() as s:
                await s.execute(select(Account.id).limit(1))
                await s.execute(select(Position.id).limit(1))
            step.done = True
            step.detail = "数据库就绪"
        except Exception as e:  # noqa: BLE001
            step.detail = f"未就绪:{e}"
        return step

    async def _step_quote(self) -> GuideStep:
        step = GuideStep(
            key="quote",
            title="验证行情数据源",
            description="所有分析都基于实时行情,请先确认能取到价格。",
            action_label="测试行情",
            action_href="/stock",
            done=False,
        )
        try:
            from app.services.quote_service import QuoteService

            q = await QuoteService().get_quote("600519.SH")
            if float(q.current_price) > 0:
                step.done = True
                step.detail = f"行情正常(贵州茅台 {q.current_price})"
            else:
                step.detail = "取到数据但价格为 0"
        except Exception as e:  # noqa: BLE001
            step.detail = f"行情不可用:{e}"
        return step

    async def _step_llm(self) -> GuideStep:
        step = GuideStep(
            key="llm",
            title="配置 AI 模型",
            description="AI 分析与多智能体报告依赖大模型 Key。不配也能用技术指标,但少了文字解读。",
            action_label="配置模型",
            action_href="/settings",
            done=False,
        )
        try:
            from app.repositories.llm_keys_repo import llm_keys_repo

            status = await llm_keys_repo.list_status()
            configured = [p for p, ok in (status.get("providers") or {}).items() if ok]
            if configured:
                step.done = True
                step.detail = f"已配置:{', '.join(configured)}"
            else:
                step.detail = "尚未配置任何模型 Key"
        except Exception as e:  # noqa: BLE001
            step.detail = f"检查失败:{e}"
        return step

    async def _step_position(self) -> GuideStep:
        step = GuideStep(
            key="position",
            title="录入持仓",
            description="录入持仓后,AI 才知道你的成本与仓位,给出的建议才有意义。",
            action_label="录入持仓",
            action_href="/positions",
            done=False,
        )
        try:
            from app.modules.portfolio.service import get_all_positions

            n = len(await get_all_positions())
            step.done = n > 0
            step.detail = f"当前 {n} 只持仓"
        except Exception as e:  # noqa: BLE001
            step.detail = f"检查失败:{e}"
        return step

    def _step_notify(self) -> GuideStep:
        step = GuideStep(
            key="notify",
            title="配置消息推送",
            description="把提醒推送到手机(钉钉 / 企业微信 / Bark / Webhook),不用一直盯着网页。",
            action_label="配置推送",
            action_href="/settings",
            done=False,
            optional=True,
        )
        return step

    async def _step_alert(self) -> GuideStep:
        step = GuideStep(
            key="alert",
            title="设置价格提醒",
            description="到价自动推送,避免错过买卖点。",
            action_label="创建提醒",
            action_href="/price-alerts",
            done=False,
        )
        try:
            from app.modules.alert.repository import price_alert_repo

            rules = await price_alert_repo.list_rules()
            step.done = len(rules) > 0
            step.detail = f"当前 {len(rules)} 条提醒规则"
        except Exception as e:  # noqa: BLE001
            step.detail = f"检查失败:{e}"
        return step

    async def _step_screener(self) -> GuideStep:
        step = GuideStep(
            key="screener",
            title="跑一次选股",
            description="每交易日 15:30 自动选股;也可以手动触发一次看效果。",
            action_label="查看选股",
            action_href="/screener",
            done=False,
            optional=True,
        )
        try:
            from app.modules.screener import repository as screener_repo

            run = await screener_repo.get_latest_run()
            step.done = run is not None
            step.detail = "已有选股记录" if run else "还没有选股记录"
        except Exception as e:  # noqa: BLE001
            step.detail = f"检查失败:{e}"
        return step

    def _step_paper(self) -> GuideStep:
        return GuideStep(
            key="paper",
            title="先模拟盘练手",
            description="先用模拟盘验证策略,不用真金白银试错。",
            action_label="打开模拟盘",
            action_href="/paper-trading",
            done=False,
            optional=True,
        )

    async def _step_multi_account(self) -> GuideStep:
        step = GuideStep(
            key="accounts",
            title="管理投资账户",
            description="有多个券商账户时分开统计,盈亏才不会算混。",
            action_label="管理账户",
            action_href="/accounts",
            done=False,
            optional=True,
        )
        try:
            from app.modules.portfolio.account_repository import account_repo

            rows = await account_repo.list_all()
            step.done = len(rows) > 1
            step.detail = f"当前 {len(rows)} 个账户"
        except Exception as e:  # noqa: BLE001
            step.detail = f"检查失败:{e}"
        return step


onboarding_service = OnboardingService()

__all__ = ["GuideStep", "OnboardingService", "OnboardingStatus", "onboarding_service"]
