"""多智能体分析 —— 角色与数据契约(阶段4)。

**核心原则(继承项目既有设计)**:LLM 只做**推理与翻译**,不做数值计算。
所有指标由 `ta_service.compute_indicators` 等确定性算法算出,
再作为「事实」喂给各角色 Agent。这样:
- 结论可复核(有确定性指标兜底)
- LLM 幻觉不会污染数字
- 单个 Agent 失败不影响整体(降级为"数据不足")

流程(对应 PanWatch 的 TradingAgents 式辩论):
```text
技术面 Agent ┐
资金面 Agent ├─▶ 多头 Agent ─┐
消息面 Agent ┤               ├─▶ 风控 Agent ──▶ PM Agent ──▶ 决策书
基本面 Agent ┘               ┘
```
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentRole(str, Enum):
    """参与辩论的角色。"""

    TECHNICAL = "technical"      # 技术面
    FUND_FLOW = "fund_flow"      # 资金面
    NEWS = "news"                # 消息面
    FUNDAMENTAL = "fundamental"  # 基本面
    BULL = "bull"                # 多头(汇总看多论据)
    BEAR = "bear"                # 空头(汇总看空论据)
    RISK = "risk"                # 风控审查
    PM = "pm"                    # 投资经理(最终裁决)


# 角色标签(前端展示用)
ROLE_LABELS: dict[str, str] = {
    AgentRole.TECHNICAL.value: "技术面分析师",
    AgentRole.FUND_FLOW.value: "资金面分析师",
    AgentRole.NEWS.value: "消息面分析师",
    AgentRole.FUNDAMENTAL.value: "基本面分析师",
    AgentRole.BULL.value: "多头研究员",
    AgentRole.BEAR.value: "空头研究员",
    AgentRole.RISK.value: "风控经理",
    AgentRole.PM.value: "投资经理",
}


class Stance(str, Enum):
    """结论倾向。"""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


STANCE_LABELS: dict[str, str] = {
    Stance.BULLISH.value: "看多",
    Stance.BEARISH.value: "看空",
    Stance.NEUTRAL.value: "中性",
}


class Action(str, Enum):
    """PM 最终决策动作。"""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"


ACTION_LABELS: dict[str, str] = {
    Action.STRONG_BUY.value: "重仓买入",
    Action.BUY.value: "轻仓买入",
    Action.HOLD.value: "持有观望",
    Action.REDUCE.value: "减仓",
    Action.SELL.value: "清仓",
}


@dataclass
class AgentOpinion:
    """单个角色的意见。失败时用 `degraded=True` 标记,不抛异常。"""

    role: str
    stance: str = Stance.NEUTRAL.value
    confidence: float = 0.0        # 0..1
    argument: str = ""              # 论证(2-3 句,大白话)
    key_points: list[str] = field(default_factory=list)
    degraded: bool = False          # True = 数据不足,结论仅供参考
    degraded_reason: str = ""
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "label": ROLE_LABELS.get(self.role, self.role),
            "stance": self.stance,
            "stance_label": STANCE_LABELS.get(self.stance, self.stance),
            "confidence": round(self.confidence, 3),
            "argument": self.argument,
            "key_points": self.key_points,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "latency_ms": self.latency_ms,
        }


@dataclass
class DecisionReport:
    """整场多智能体分析的产出。"""

    stock_code: str
    stock_name: str = ""
    opinions: list[AgentOpinion] = field(default_factory=list)
    debate_summary: str = ""
    risk_review: str = ""
    risk_flags: list[str] = field(default_factory=list)
    action: str = Action.HOLD.value
    action_label: str = ""
    confidence: float = 0.0
    summary: str = ""
    key_levels: dict = field(default_factory=dict)  # {support: [...], resistance: [...]}
    disclaimer: str = "以上为 AI 多智能体分析结果,仅供参考,不构成投资建议。"
    degraded: bool = False
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "opinions": [o.to_dict() for o in self.opinions],
            "debate_summary": self.debate_summary,
            "risk_review": self.risk_review,
            "risk_flags": self.risk_flags,
            "action": self.action,
            "action_label": self.action_label or ACTION_LABELS.get(self.action, self.action),
            "confidence": round(self.confidence, 3),
            "summary": self.summary,
            "key_levels": self.key_levels,
            "disclaimer": self.disclaimer,
            "degraded": self.degraded,
            "model": self.model,
        }


__all__ = [
    "ACTION_LABELS",
    "Action",
    "AgentOpinion",
    "AgentRole",
    "DecisionReport",
    "ROLE_LABELS",
    "STANCE_LABELS",
    "Stance",
]
