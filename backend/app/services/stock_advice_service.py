"""AI 个股解读服务(v0.4-roadmap 功能4/5)

指标(确定性)+ K线 → LLM 白话解读;强制 JSON + schema 校验。
LLM 不可用 / 输出非法 → ai=None,由前端降级纯指标展示(页面永不空白)。
"""
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.llm.factory import provider_factory
from app.repositories.llm_settings_repo import llm_settings_repo
from app.services.ta_service import compute_indicators

logger = logging.getLogger(__name__)

# LLM 调用总时间预算(秒):超过直接降级/503,保证接口快速返回,不被慢模型拖死
LLM_ANALYSIS_BUDGET = 25.0
LLM_QUESTION_BUDGET = 40.0

ANALYSIS_SYSTEM = """你是股票技术分析助理,面向完全不懂 K 线的小白股民。
硬性规则:
1. 只能解读输入数据,严禁编造任何价格 / 成交量 / 百分比数字
2. 引用的数字必须与输入完全一致,不改写、不四舍五入到别的值
3. 输出必须是合法 JSON(无 markdown 代码块包裹)
4. 结论客观,不承诺收益,结尾必须包含风险提示
5. 术语用大白话:"均线"可解释为"一段时间平均成本价","企稳点"解释为"价格站住不破的位置"

JSON 结构:
{
  "view": "bullish | bearish | neutral",
  "view_reason": "看多/看空依据(引用具体指标数字)",
  "trend": "K线走势描述(上涨通道/下降通道/震荡,当前处于什么阶段)",
  "volume_note": "放量/缩量解读",
  "key_levels": [{"type": "support|pressure|stabilize", "price": 123.45, "note": "小白视角说明"}],
  "advice": "给小白可执行的操作参考(不构成投资建议)",
  "risk_warning": "风险提示"
}
"""

QUESTION_SYSTEM = """你是股票操作顾问,面向小白股民。
规则:
1. 只能基于输入的技术指标 / K线 / 行情 / 用户持仓成本回答,严禁编造数字
2. 引用指标数字必须与输入一致
3. 回答要口语化、结构清晰(分点),先给结论再给理由
4. 不承诺收益;建议类回答结尾附"以上仅供参考,不构成投资建议"
"""


class StockAdviceUnavailable(Exception):
    """LLM 未配置 / 调用失败(问答场景无法降级时抛出)"""


async def _get_llm():
    active = await llm_settings_repo.get_active()
    return await provider_factory.get(active)


async def check_llm_available() -> None:
    """流式端点前置校验:LLM 未配置抛 StockAdviceUnavailable(响应开始前 503)"""
    if await _get_llm() is None:
        raise StockAdviceUnavailable("未配置 LLM Key,无法回答;可先查看技术指标")


def _parse_llm_json(raw: str) -> dict:
    """解析 LLM 返回 JSON(容忍 markdown 代码块包裹)"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM 返回非法 JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("LLM 返回非对象 JSON")
    return data


def _validate_analysis(d: dict) -> dict:
    """schema 校验:view 枚举 + 关键字段存在"""
    view = d.get("view")
    if view not in {"bullish", "bearish", "neutral"}:
        raise ValueError(f"view 非法: {view}")
    for field in ("view_reason", "trend", "volume_note", "advice", "risk_warning"):
        if not isinstance(d.get(field), str):
            d[field] = ""
    levels = d.get("key_levels")
    if not isinstance(levels, list):
        d["key_levels"] = []
    return d


def _summarize_klines(klines: list[dict[str, Any]], limit: int = 30) -> list[dict]:
    """最近 limit 根 [date, close, volume](喂 LLM 精简上下文)"""
    return [
        {"date": r["date"], "close": r["close"], "volume": r["volume"]}
        for r in klines[-limit:]
    ]


def _build_context(klines: list[dict[str, Any]]) -> dict:
    """指标 + K线摘要 + 现价"""
    indicators = compute_indicators(klines)
    return {
        "latest_close": indicators["latest_close"],
        "ma": indicators["ma"],
        "volume": indicators["volume"],
        "channel": indicators["channel"],
        "support_pressure": indicators["support_pressure"],
        "stabilize": indicators["stabilize"],
        "recent_klines": _summarize_klines(klines),
    }


async def get_stock_analysis(
    stock_code: str, klines: list[dict[str, Any]]
) -> dict:
    """指标 + AI 解读;LLM 失败 → ai=None(纯指标降级)"""
    indicators = compute_indicators(klines)
    result: dict[str, Any] = {
        "stock_code": stock_code,
        "indicators": indicators,
        "ai": None,
    }

    llm = await _get_llm()
    if llm is None:
        return result

    ctx = json.dumps(_build_context(klines), ensure_ascii=False)
    try:
        raw = await asyncio.wait_for(
            llm.chat(ANALYSIS_SYSTEM, f"以下为该股票技术指标与最近K线:\n{ctx}"),
            timeout=LLM_ANALYSIS_BUDGET,
        )
        parsed = _parse_llm_json(raw)
        result["ai"] = _validate_analysis(parsed)
    except asyncio.TimeoutError:
        logger.warning("个股分析 LLM 超时(>%ss),降级纯指标: %s", LLM_ANALYSIS_BUDGET, stock_code)
    except Exception as e:
        logger.warning("个股分析 LLM 失败,降级纯指标(%s): %s", stock_code, e)
    return result


async def ask_stock_question(
    stock_code: str,
    question: str,
    klines: list[dict[str, Any]],
    position_cost: float | None = None,
) -> str:
    """操作问答:结合行情 + 指标 + 持仓成本,返回白话回复文本"""
    llm = await _get_llm()
    if llm is None:
        raise StockAdviceUnavailable("未配置 LLM Key,无法回答;可先查看技术指标")

    prompt = _build_question_prompt(question, klines, position_cost)
    try:
        raw = await asyncio.wait_for(
            llm.chat(QUESTION_SYSTEM, prompt, temperature=0.4),
            timeout=LLM_QUESTION_BUDGET,
        )
    except asyncio.TimeoutError as e:
        raise StockAdviceUnavailable(f"LLM 响应超时(>{LLM_QUESTION_BUDGET}s)") from e
    except Exception as e:
        raise StockAdviceUnavailable(f"LLM 调用失败: {e}") from e
    return raw.strip()


def _build_question_prompt(
    question: str,
    klines: list[dict[str, Any]],
    position_cost: float | None,
) -> str:
    """操作问答的完整 user prompt(chat / chat/stream 共用)"""
    ctx = json.dumps(_build_context(klines), ensure_ascii=False)
    cost_line = (
        f"\n用户持仓成本: {position_cost} 元/股(成本是用户隐私,回答中不要复述精确数字,只用来说明盈亏方向)"
        if position_cost is not None
        else "\n用户暂无该股持仓"
    )
    return (
        f"该股技术指标与最近K线:\n{ctx}{cost_line}\n"
        f"用户提问: {question}"
    )


async def ask_stock_question_stream(
    stock_code: str,
    question: str,
    klines: list[dict[str, Any]],
    position_cost: float | None = None,
) -> AsyncIterator[str]:
    """操作问答流式版:逐段产出回答增量(不含思考内容)

    调用方需 async for 完整消费;LLM 未配置 / 调用失败抛 StockAdviceUnavailable。
    """
    llm = await _get_llm()
    if llm is None:
        raise StockAdviceUnavailable("未配置 LLM Key,无法回答;可先查看技术指标")

    prompt = _build_question_prompt(question, klines, position_cost)
    try:
        async for piece in llm.chat_stream(QUESTION_SYSTEM, prompt, temperature=0.4):
            yield piece
    except Exception as e:
        raise StockAdviceUnavailable(f"LLM 调用失败: {e}") from e
