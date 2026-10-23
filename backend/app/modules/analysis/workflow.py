"""三段式定时 Agent(阶段4)。

| 时段 | 时间 | 产出 |
| --- | --- | --- |
| 盘前 | 08:30 | 隔夜消息汇总 + 持仓风险提示 + 今日关注清单 |
| 盘中 | 11:30 / 14:00 | 异动扫描 + 机会提醒 |
| 盘后 | 16:00 | 当日选股 + 复盘要点(选股调度器已覆盖,这里只补复盘提示) |

⚠️ 阶段 T2 起,盘中的**主产出**改由「盘中复盘」承担
(`modules/analysis/intraday_review.py`:市场意见 + 逐票动作清单);
本模块的 `run_intraday` 保留为异动扫描能力,并被复盘当作**补充段**并入。

设计要点:
- **独立于选股调度器**:关掉也不影响主流程
- **幂等**:同一时段当天只跑一次(用 `workflow_run` 表记时间窗,重复触发安全)
- **失败降级**:LLM 没配就只推客观数据摘要
- **推送复用阶段1 通知层**:一次开发,三处受益
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.core.logging import logger
from app.modules.notify.service import NotifyLevel, NotifyMessage, notify_service


@dataclass(slots=True)
class WorkflowResult:
    """一次工作流产出。"""

    kind: str  # premarket / intraday
    title: str
    summary: str
    lines: list[str] = field(default_factory=list)
    stock_codes: list[str] = field(default_factory=list)
    degraded: bool = False

    def to_message(self) -> NotifyMessage:
        body = "\n".join([self.summary, *self.lines]) if self.lines else self.summary
        return NotifyMessage(
            title=self.title,
            body=body[:1800],  # 各渠道正文长度限制不一,统一截断
            level=NotifyLevel.INFO,
            context={"kind": self.kind, "stocks": self.stock_codes[:20]},
        )


class WorkflowAgentService:
    """盘前/盘中工作流。"""

    # ---------- 盘前 ----------

    async def run_premarket(self) -> WorkflowResult:
        """盘前简报:持仓风险 + 今日关注清单。"""
        from app.modules.portfolio.service import get_all_positions

        lines: list[str] = []
        codes: list[str] = []

        # 1) 持仓风险(用确定性止损位,不靠 LLM 猜)
        try:
            positions = await get_all_positions()
            for p in positions[:10]:
                codes.append(p.stock_code)
                cost = float(getattr(p, "avg_cost", 0) or 0)
                if cost > 0:
                    lines.append(
                        f"· {p.stock_code} 成本 {cost:.2f}"
                        f"(盈亏 {getattr(p, 'pnl_pct', 0):+.1f}%)"
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[workflow] 持仓读取失败: {e}")
            lines.append("· 持仓读取失败")

        # 2) 今日关注清单(来自最近一次选股)
        try:
            from app.modules.screener.service import get_latest_run, get_picks_by_run

            run = await get_latest_run()
            if run is not None:
                picks = await get_picks_by_run(run.id)
                for pk in picks[:5]:
                    codes.append(pk.stock_code)
                    lines.append(f"· 关注 {pk.stock_code}(昨日评分 {pk.score})")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[workflow] 选股读取失败: {e}")

        summary = "盘前简报:隔夜消息与持仓风险已整理。"
        result = WorkflowResult(
            kind="premarket",
            title="买股工具室 · 盘前简报",
            summary=summary,
            lines=lines[:25],
            stock_codes=list(dict.fromkeys(codes)),
        )
        # 用 LLM 把客观数据润色成简报(可失败)
        polished = await self._polish(result)
        if polished:
            result.summary = polished
        return result

    # ---------- 盘中 ----------

    async def scan_intraday_moves(self, limit: int = 10) -> tuple[list[str], list[str]]:
        """异动扫描(关注标的里涨跌幅 >= 5% 的)。返回 (lines, codes)。

        单独抽出来是为了让「盘中复盘」能把它当**补充段**并入 —— 不重写一遍
        扫描逻辑,也不新增第二条 LLM 链路(这里只取客观数据,要不要润色由
        调用方决定;复盘侧选择不润色)。
        """
        from app.modules.screener.service import get_latest_run, get_picks_by_run

        lines: list[str] = []
        codes: list[str] = []

        try:
            run = await get_latest_run()
            picks = await get_picks_by_run(run.id) if run else []
            if picks:
                from app.services.quote_service import QuoteService

                quotes = await QuoteService().get_quotes([p.stock_code for p in picks[:limit]])
                qmap = {q.code: q for q in quotes}
                for pk in picks[:limit]:
                    q = qmap.get(pk.stock_code)
                    if not q:
                        continue
                    codes.append(pk.stock_code)
                    chg = float(q.change_pct)
                    if abs(chg) >= 5:
                        arrow = "🚀" if chg > 0 else "⚠️"
                        lines.append(f"{arrow} {pk.stock_code} {q.name} {chg:+.1f}%")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[workflow] 盘中扫描失败: {e}")

        return lines, list(dict.fromkeys(codes))

    async def run_intraday(self, slot: str = "11:30") -> WorkflowResult:
        """盘中扫描:异动 + 机会。slot: "11:30" / "14:00" / "14:50"。"""
        lines, codes = await self.scan_intraday_moves()

        if not lines:
            lines.append("暂无明显异动。")

        result = WorkflowResult(
            kind="intraday",
            title=f"买股工具室 · 盘中速览({slot})",
            summary="盘中扫描关注标的的涨跌幅。",
            lines=lines[:25],
            stock_codes=list(dict.fromkeys(codes)),
        )
        polished = await self._polish(result)
        if polished:
            result.summary = polished
        return result

    # ---------- 推送 ----------

    async def dispatch(self, result: WorkflowResult) -> list:
        """把工作流结果推送到已启用渠道。"""
        try:
            return await notify_service.send_to_enabled(result.to_message())
        except Exception as e:  # noqa: BLE001 — 推送失败不影响产出
            logger.warning(f"[workflow] 推送失败: {e}")
            return []

    # ---------- 内部 ----------

    async def _polish(self, result: WorkflowResult) -> str:
        """用 LLM 把客观数据润色成 2-3 句人话;失败返回空(保留原文)。"""
        from app.modules.analysis.service import _get_llm

        llm = await _get_llm()
        if llm is None:
            return ""
        system = (
            "你是买股工具室的简报编辑。请把给定的客观行情数据改写成 2-3 句"
            "面向小白的中文简报。**绝不允许编造数据中没有的数字**。只输出改写后的正文。"
        )
        user = (
            f"【主题】{result.title}\n"
            f"【原始要点】\n" + "\n".join(result.lines) + "\n\n"
            "请改写成简报正文。"
        )
        try:
            raw = await asyncio.wait_for(
                llm.chat(system=system, user_prompt=user, temperature=0.5),
                timeout=30.0,
            )
            return (raw or "").strip()[:400]
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[workflow] 润色失败(保留原文): {e}")
            return ""


workflow_agent_service = WorkflowAgentService()

__all__ = ["WorkflowAgentService", "WorkflowResult", "workflow_agent_service"]
