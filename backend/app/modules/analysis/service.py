"""多智能体编排(阶段4)。

执行策略:
- 前 4 个分析师**并发**执行(总耗时 ≈ 最慢的一个,不是之和)
- 多空辩论在分析师全部返回后进行(有依赖,顺序执行)
- 任何一步失败 → 降级(`degraded=True`)而非抛异常:
  LLM 没配 Key、返回非法 JSON、超时,都不应该让用户看到一个 500

降级到底会怎样?
- 分析师全挂 → 直接给一份「数据不足,建议观望」的报告,而不是空 500
- LLM 完全不可用 → 返回确定性指标的客观摘要(仍然有信息量)
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from app.core.logging import logger
from app.core.instrument import resolve_instrument
from app.core.stock_code import normalize_code
from app.modules.analysis.contracts import (
    ACTION_LABELS,
    AgentOpinion,
    AgentRole,
    DecisionReport,
    Stance,
)
from app.modules.analysis.prompts import (
    build_bear_prompt,
    build_bull_prompt,
    build_pm_prompt,
    build_risk_prompt,
    build_role_prompt,
)

# 单个 Agent 超时(秒)。LLM 慢不该拖垮整个分析。
AGENT_TIMEOUT = 45.0


def parse_json_reply(text: str) -> dict:
    """从 LLM 回复里稳健地提取 JSON。

    LLM 常在 JSON 前后带解释文字或 ```json 围栏,直接 json.loads 会炸。
    这里逐级降级:整串 → 去围栏 → 大括号截取。
    """
    if not text:
        return {}
    raw = text.strip()

    candidates = [raw]

    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        candidates.append(fence.group(1).strip())

    brace = re.search(r"\{.*\}", raw, re.S)
    if brace:
        candidates.append(brace.group(0))

    for c in candidates:
        try:
            out = json.loads(c)
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            continue
    return {}


async def _get_llm():
    """取当前激活的 LLM;没有则返回 None(触发降级)。"""
    from app.llm.factory import provider_factory
    from app.repositories.llm_settings_repo import llm_settings_repo

    try:
        provider = await llm_settings_repo.get_active()
        return await provider_factory.get(provider)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[multi-agent] 取 LLM 失败: {e}")
        return None


async def _ask(llm, system: str, user: str) -> dict:
    """调用 LLM 并解析 JSON。失败返回 {}。"""
    try:
        raw = await asyncio.wait_for(
            llm.chat(system=system, user_prompt=user, temperature=0.4),
            timeout=AGENT_TIMEOUT,
        )
        return parse_json_reply(raw)
    except asyncio.TimeoutError:
        logger.warning("[multi-agent] Agent 超时")
        return {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[multi-agent] Agent 调用失败: {e}")
        return {}


def _clamp(v, lo=0.0, hi=1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _valid_stance(v) -> str:
    s = str(v or "").lower()
    return s if s in (Stance.BULLISH.value, Stance.BEARISH.value, Stance.NEUTRAL.value) else Stance.NEUTRAL.value


class MultiAgentService:
    """多智能体深度分析。"""

    async def analyze(self, stock_code: str) -> DecisionReport:
        code = normalize_code(stock_code) or stock_code
        report = DecisionReport(stock_code=code)

        # ---------- 1. 确定性事实(LLM 不参与计算) ----------
        facts, stock_name, degraded_facts = await self._gather_facts(code)
        report.stock_name = stock_name
        report.key_levels = facts.get("key_levels", {}) or {}

        llm = await _get_llm()
        if llm is None:
            # 无 LLM:仍返回一份基于确定性指标的客观报告,不返回 500
            report.degraded = True
            report.action = "hold"
            report.summary = (
                "未配置 AI 模型,以下为基于技术指标的客观摘要,建议自行判断或先配置模型。"
            )
            report.debate_summary = degraded_facts or "未取到行情数据"
            return report

        report.model = _model_name(llm)

        # ---------- 2. 分析师并发 ----------
        roles = [
            AgentRole.TECHNICAL,
            AgentRole.FUND_FLOW,
            AgentRole.NEWS,
            AgentRole.FUNDAMENTAL,
        ]
        results = await asyncio.gather(
            *[self._run_role(llm, r.value, stock_name, facts) for r in roles],
            return_exceptions=True,
        )
        opinions: list[AgentOpinion] = []
        for role, res in zip(roles, results):
            if isinstance(res, Exception):
                opinions.append(
                    AgentOpinion(
                        role=role.value,
                        degraded=True,
                        degraded_reason=f"执行异常: {res}",
                    )
                )
            else:
                opinions.append(res)
        report.opinions = opinions

        # ---------- 3. 多空辩论(顺序) ----------
        op_dicts = [o.to_dict() for o in opinions]
        system_b, user_b = build_bull_prompt(stock_name, op_dicts, facts)
        system_s, user_s = build_bear_prompt(stock_name, op_dicts, facts)
        bull_raw, bear_raw = await asyncio.gather(
            _ask(llm, system_b, user_b), _ask(llm, system_s, user_s)
        )
        bull_op = self._to_opinion(AgentRole.BULL.value, bull_raw)
        bear_op = self._to_opinion(AgentRole.BEAR.value, bear_raw)
        report.opinions.extend([bull_op, bear_op])

        # ---------- 4. 风控审查 ----------
        # 品种差异:ETF 没有涨跌停/退市机制 → 风险清单必须换(见 prompts.build_risk_prompt)
        instrument_kind = resolve_instrument(code).kind
        system_r, user_r = build_risk_prompt(
            stock_name, bull_raw, bear_raw, facts, instrument_kind=instrument_kind
        )
        risk_raw = await _ask(llm, system_r, user_r)
        report.risk_review = risk_raw.get("argument", "")
        report.risk_flags = [
            str(x) for x in (risk_raw.get("risk_flags") or []) if str(x).strip()
        ]

        # ---------- 5. PM 裁决 ----------
        system_p, user_p = build_pm_prompt(
            stock_name, bull_raw, bear_raw, risk_raw, facts, instrument_kind=instrument_kind
        )
        pm_raw = await _ask(llm, system_p, user_p)
        action = str(pm_raw.get("action", "hold")).lower()
        if action not in ACTION_LABELS:
            action = "hold"  # LLM 给了非法动作 → 保守回落
        report.action = action
        report.confidence = _clamp(pm_raw.get("confidence", 0.3), 0.0, 1.0)
        report.summary = pm_raw.get("summary") or "模型未给出总结。"
        report.debate_summary = bull_op.argument or bear_op.argument or ""

        report.degraded = any(o.degraded for o in report.opinions)
        return report

    # ---------- 内部 ----------

    async def _run_role(
        self, llm, role: str, stock_name: str, facts: dict
    ) -> AgentOpinion:
        t0 = time.monotonic()
        system, user = build_role_prompt(role, stock_name, facts)
        raw = await _ask(llm, system, user)
        if not raw:
            return AgentOpinion(
                role=role,
                degraded=True,
                degraded_reason="模型未返回可解析的结果",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        return self._to_opinion(role, raw, int((time.monotonic() - t0) * 1000))

    @staticmethod
    def _to_opinion(role: str, raw: dict, latency_ms: int = 0) -> AgentOpinion:
        if not raw:
            return AgentOpinion(role=role, degraded=True, degraded_reason="无结果", latency_ms=latency_ms)
        return AgentOpinion(
            role=role,
            stance=_valid_stance(raw.get("stance")),
            confidence=_clamp(raw.get("confidence", 0.0)),
            argument=str(raw.get("argument", ""))[:500],
            key_points=[str(x) for x in (raw.get("key_points") or [])][:5],
            latency_ms=latency_ms,
        )

    async def _gather_facts(self, code: str) -> tuple[dict, str, str]:
        """收集确定性事实:技术指标 + 资金流 + 消息。

        单项失败不影响其它(缺哪项就在 facts 里标注「数据不足」)。
        """
        facts: dict = {}
        stock_name = code
        notes: list[str] = []

        # --- 技术指标 ---
        try:
            from app.services import kline_service, ta_service

            klines = await kline_service.fetch_klines(code, period="daily", count=120)
            if klines:
                ind = ta_service.compute_indicators(klines)
                facts["technical"] = ind
                q = klines[-1]
                stock_name = str(q.get("name") or stock_name) if q.get("name") else stock_name
            else:
                notes.append("技术面:无 K 线数据")
                facts["technical"] = {"data_quality": "数据不足:无K线"}
        except Exception as e:  # noqa: BLE001
            notes.append(f"技术面:取数失败({e})")
            facts["technical"] = {"data_quality": f"数据不足:{e}"}

        # --- 资金流 ---
        try:
            from app.services.fund_flow_service import list_recent as list_flow

            rows = await list_flow(code, limit=30)
            if rows:
                facts["fund_flow"] = {
                    "recent_count": len(rows),
                    "recent": [
                        {
                            "timestamp": str(getattr(r, "timestamp", ""))[:16],
                            "main_net_inflow": str(getattr(r, "main_net_inflow", "")),
                            "main_net_inflow_ratio": str(
                                getattr(r, "main_net_inflow_ratio", "")
                            ),
                        }
                        for r in rows[:10]
                    ],
                }
            else:
                facts["fund_flow"] = {"data_quality": "数据不足:无资金流记录"}
        except Exception as e:  # noqa: BLE001
            facts["fund_flow"] = {"data_quality": f"数据不足:{e}"}

        # --- 消息面(实时查 iFinD,不落库) ---
        try:
            from datetime import date as _date
            from datetime import timedelta as _td

            from app.data.ifind_news import fetch_news_for_stock

            end = _date.today()
            start = end - _td(days=14)
            res = await fetch_news_for_stock(
                code,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                news_size=5,
                notice_size=5,
            )
            news = (res or {}).get("news") or []
            anns = (res or {}).get("announcements") or []
            if news or anns:
                facts["news"] = {
                    "news": [
                        {"title": n.get("title", ""), "date": str(n.get("date", ""))[:10]}
                        for n in news
                    ],
                    "announcements": [
                        {"title": a.get("title", ""), "date": str(a.get("date", ""))[:10]}
                        for a in anns
                    ],
                }
            else:
                facts["news"] = {"data_quality": "数据不足:近 14 天无相关新闻/公告"}
        except Exception as e:  # noqa: BLE001
            facts["news"] = {"data_quality": f"数据不足:{e}"}

        return facts, stock_name, "; ".join(notes)


def _model_name(llm) -> str:
    for attr in ("model_name", "model", "name"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v:
            return v
    return "unknown"


multi_agent_service = MultiAgentService()

__all__ = ["MultiAgentService", "multi_agent_service", "parse_json_reply"]
