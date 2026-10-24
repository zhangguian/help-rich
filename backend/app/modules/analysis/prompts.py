"""多智能体 Prompt 构建(阶段4)。

**约束写进 prompt 里**:Agent 只能基于给定的「确定性事实」推理,
不得自行计算或臆测数字。这是本项目"LLM 只做翻译"原则在多智能体场景的延续。
"""
from __future__ import annotations

import json
from typing import Any

from app.modules.analysis.contracts import ROLE_LABELS, AgentRole

_SYSTEM = (
    "你是一名严谨的 A 股投资研究分析师，服务于面向小白的买股辅助工具。\n"
    "铁律：\n"
    "1. 你只能使用【确定性事实】中给出的数字与结论，**绝不允许自己计算或编造任何数字**。\n"
    "2. 若某项事实标注为「数据不足」，你必须在结论中如实说明，不得假装有该数据。\n"
    "3. 输出面向小白，说人话，不用专业黑话；不要用「建议买入」这类指令式表述。\n"
    "4. 只输出 JSON，不要任何多余文字或 Markdown 代码块标记。"
)

_JSON_RULES = {
    AgentRole.TECHNICAL: (
        '{"stance":"bullish|bearish|neutral","confidence":0.0~1.0,'
        '"argument":"2-3句论证","key_points":["要点1","要点2"]}'
    ),
}


def _fmt_facts(facts: dict[str, Any]) -> str:
    """把事实字典渲染成紧凑文本(控制 token)。"""
    return json.dumps(facts, ensure_ascii=False, default=str, indent=0)[:4000]


def build_role_prompt(role: str, stock_name: str, facts: dict[str, Any]) -> tuple[str, str]:
    """返回 (system, user) 二元组。"""
    role_zh = ROLE_LABELS.get(role, role)
    focus = {
        AgentRole.TECHNICAL.value: (
            "你是【技术面分析师】。基于均线、量能、形态、支撑压力位判断趋势方向。"
            "重点回答：现在处于什么趋势？关键价位在哪？有没有反转信号？"
        ),
        AgentRole.FUND_FLOW.value: (
            "你是【资金面分析师】。基于主力净流入、量比、换手率判断资金动向。"
            "重点回答：钱是在进还是在出？进出的力度如何？是否具备持续性？"
        ),
        AgentRole.NEWS.value: (
            "你是【消息面分析师】。基于公告、新闻、舆情判断事件影响。"
            "重点回答：最近有什么消息？利好还是利空？影响是短期还是长期？"
        ),
        AgentRole.FUNDAMENTAL.value: (
            "你是【基本面分析师】。基于估值与财务指标判断安全边际。"
            "重点回答：现在贵不贵？基本面有没有硬伤？（如数据不足请明说）"
        ),
    }.get(role, f"你是{role_zh}。基于给定事实做客观分析。")

    user = (
        f"{focus}\n\n"
        f"【标的】{stock_name}\n\n"
        f"【确定性事实】(这些数字由系统算法算出,直接引用,不要自己算)\n{_fmt_facts(facts)}\n\n"
        f"【输出格式】严格输出 JSON:\n"
        f'{{"stance":"bullish|bearish|neutral","confidence":0.0~1.0,'
        f'"argument":"2-3句大白话论证","key_points":["要点1","要点2"]}}'
    )
    return _SYSTEM, user


def build_bull_prompt(
    stock_name: str, opinions: list[dict], facts: dict[str, Any]
) -> tuple[str, str]:
    user = (
        "你是【多头研究员】。你的任务是把所有看多论据汇总成有说服力的论证，"
        "同时**不要回避明显的风险**。\n\n"
        f"【标的】{stock_name}\n\n"
        f"【各角色观点】\n{_fmt_facts({'opinions': opinions})}\n\n"
        f"【确定性事实】\n{_fmt_facts(facts)}\n\n"
        '【输出格式】严格输出 JSON:\n'
        '{"stance":"bullish","confidence":0.0~1.0,"argument":"多头论证",'
        '"key_points":["看多理由1","看多理由2"]}'
    )
    return _SYSTEM, user


def build_bear_prompt(
    stock_name: str, opinions: list[dict], facts: dict[str, Any]
) -> tuple[str, str]:
    user = (
        "你是【空头研究员】。你的任务是把这只票的**风险与看空理由**讲清楚。"
        "你要刻意寻找多头论证里的漏洞，不要客气。\n\n"
        f"【标的】{stock_name}\n\n"
        f"【各角色观点】\n{_fmt_facts({'opinions': opinions})}\n\n"
        f"【确定性事实】\n{_fmt_facts(facts)}\n\n"
        '【输出格式】严格输出 JSON:\n'
        '{"stance":"bearish","confidence":0.0~1.0,"argument":"看空论证",'
        '"key_points":["风险1","风险2"]}'
    )
    return _SYSTEM, user


def build_risk_prompt(
    stock_name: str,
    bull: dict | None,
    bear: dict | None,
    facts: dict[str, Any],
    instrument_kind: str = "stock",
) -> tuple[str, str]:
    # ETF 没有涨跌停、没有退市机制 → 风险清单必须换,否则 LLM 会输出不存在的风险
    if instrument_kind == "etf":
        risk_examples = (
            "（如折溢价、跟踪误差、流动性不足、跨境品种的汇率波动、"
            "T+0 品种的当日回转风险、数据不足导致的盲区）"
        )
    else:
        risk_examples = "（如涨跌停、流动性、政策、退市风险、数据不足导致的盲区）"
    user = (
        "你是【风控经理】。多空双方都已陈词，现在做**风险审查**。"
        f"你要指出：还有哪些风险没被双方提及？{risk_examples}\n\n"
        f"【标的】{stock_name}\n\n"
        f"【多头观点】\n{_fmt_facts(bull or {})}\n\n"
        f"【空头观点】\n{_fmt_facts(bear or {})}\n\n"
        f"【确定性事实】\n{_fmt_facts(facts)}\n\n"
        '【输出格式】严格输出 JSON:\n'
        '{"argument":"风控结论(2-3句)","risk_flags":["风险1","风险2"],'
        '"key_points":["要点"]}'
    )
    return _SYSTEM, user


def build_pm_prompt(
    stock_name: str,
    bull: dict | None,
    bear: dict | None,
    risk: dict | None,
    facts: dict[str, Any],
    instrument_kind: str = "stock",
) -> tuple[str, str]:
    # ETF 无退市/ST → 换成 ETF 语境下的严重风险
    if instrument_kind == "etf":
        severe = "风险严重(如跟踪指数大幅下跌/折溢价过大/数据严重缺失) → sell"
    else:
        severe = "风险严重(如退市/ST/数据严重缺失) → sell"
    user = (
        "你是【投资经理】，做最终裁决。\n"
        "决策原则：\n"
        "- 双方证据大体均衡且有显著风险 → hold（观望）\n"
        "- 多头论据明显占优且风险可控 → buy；非常强 → strong_buy\n"
        f"- 空头论据明显占优 → reduce；{severe}\n"
        "- 不要因为「有人看多」就买，要看论据质量。\n\n"
        f"【标的】{stock_name}\n\n"
        f"【多头观点】\n{_fmt_facts(bull or {})}\n\n"
        f"【空头观点】\n{_fmt_facts(bear or {})}\n\n"
        f"【风控意见】\n{_fmt_facts(risk or {})}\n\n"
        f"【确定性事实】\n{_fmt_facts(facts)}\n\n"
        '【输出格式】严格输出 JSON:\n'
        '{"action":"strong_buy|buy|hold|reduce|sell","confidence":0.0~1.0,'
        '"summary":"给小白看的3-4句总结","key_points":["结论要点1","结论要点2"]}'
    )
    return _SYSTEM, user


__all__ = [
    "build_bear_prompt",
    "build_bull_prompt",
    "build_pm_prompt",
    "build_risk_prompt",
    "build_role_prompt",
]
