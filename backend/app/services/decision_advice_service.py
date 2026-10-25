"""操作建议服务(v0.10 · 事实包 → 白话)

**要解决的问题**:决策卡与 AI 解读对同一只票给出两套说法。
本模块把决策压成**事实包**(唯一数字真相源),再由规则或 LLM 把它翻成白话。

三层结构(越往下越不可信):

1. `build_fact_pack(decision)`   —— 纯函数:决策 → 事实包。**只含确定性数字**。
2. `compose_rule_advice(pack)`  —— 纯函数:规则白话兜底。零 LLM、零延迟、**永不空白**。
3. `narrate_with_llm(pack)`     —— LLM 只**翻译**事实包,不得改写任何数字;失败 → None。

**铁律**:
- LLM 只能引用事实包里的数字,不得改写 / 另算 / 补充未列出的价位;
- 事实包为 `None` 的字段,白话必须写「暂无」,不得用 0 或空串顶替;
- 白话**不得承诺收益**(设计文档 §10.4:胜率型概率提示,收益型无效)。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any

from app.llm.factory import provider_factory
from app.repositories.llm_settings_repo import llm_settings_repo

logger = logging.getLogger(__name__)

# 白话生成的 LLM 时间预算(秒)。按钮触发,超时即退回规则文案,不必等满。
LLM_ADVICE_BUDGET = 60.0
LLM_ADVICE_MAX_TOKENS = 1200

# 当日进程内缓存:(code|日期|headline) → advice。避免来回切票时反复烧 token。
_ADVICE_CACHE: dict[str, dict[str, Any]] = {}

DECISION_ADVICE_SYSTEM = """你是股票操作建议助理,面向完全不懂 K 线的小白股民。

硬性规则:
1. 【事实包】是**唯一真相源**。只能引用事实包里已有的数字,
   必须原样引用,不得改写、不得另算、不得四舍五入成别的值、不得补充事实包里没有的价位。
2. 事实包里没有的字段,一律写「暂无」,不得用 0、空串或猜测值顶替。
3. **不承诺收益**,不预测涨跌,不给出目标价。只说「现在该做什么、什么价位、等什么信号」。
4. 结论客观中性,不制造焦虑,结尾必须包含风险提示。
5. 术语用大白话:"跌破区间下沿"解释为"价格跌出网格区间,这套网格就不成立了,按止损走"。
6. 输出必须是合法 JSON(无 markdown 代码块包裹),不要任何解释文字。
7. **务必精简**:headline 不超过 60 字;bullets 最多 3 条,每条不超过 40 字。过长会被截断。

JSON 结构(必填,不允许字段缺失):
{
  "headline": "一句话结论(不超过 60 字)",
  "bullets": ["要点 1", "要点 2", "要点 3"]
}
"""


# ============================================================
# 1. 事实包(纯函数 · 唯一数字真相源)
# ============================================================

def build_fact_pack(
    decision: dict[str, Any],
    as_of: str | None = None,
) -> dict[str, Any]:
    """把决策压成事实包。**只含确定性数字**,不含任何 LLM 措辞。

    Args:
        decision: `build_decision()` 的输出
        as_of: K 线最新日(数据时间);None = 不标注
    """
    actions = [
        a for a in (decision.get("actions") or [])
        if a.get("status") in ("now", "armed")
    ]
    return {
        "stock_code": decision.get("stock_code"),
        "as_of": as_of,
        "verdict": decision.get("verdict"),
        "headline": decision.get("headline"),
        "role": decision.get("role"),
        "confidence": decision.get("confidence"),
        "position_status": decision.get("position_status"),
        "actions": actions,
        "suggestions": decision.get("suggestions"),
        "t_plan": decision.get("t_plan"),
        "grid_plan": decision.get("grid_plan"),
        "cost_anchor": decision.get("cost_anchor"),
        "time_window": decision.get("time_window"),
        "cost_effect": decision.get("cost_effect"),
        "instrument_rule": decision.get("instrument_rule"),
        "concentration": decision.get("concentration"),
        "stop_loss": decision.get("stop_loss"),
        "position_pct": decision.get("position_pct"),
        "do_not": decision.get("do_not") or [],
        "degraded": (decision.get("data_quality") or {}).get("degraded") or [],
    }


# ============================================================
# 2. 规则白话兜底(纯函数 · 永不空白)
# ============================================================

def _cell(pack: dict[str, Any], group: str, key: str) -> str:
    cell = (pack.get(group) or {}).get(key)
    if not isinstance(cell, dict):
        return ""
    return str(cell.get("value") or "").strip()


def _grid_summary(grid: dict[str, Any]) -> str:
    """网格块 → 一句话(只给数字与条件,不承诺收益)"""
    if not grid.get("suitable"):
        return f"网格不建议:{grid.get('unsuitable_signals') or '条件不满足'}"
    mode = "加仓模式" if grid.get("mode") == "add" else "底仓模式"
    bits = [
        f"区间 {grid.get('range_low')}~{grid.get('range_high')} 元",
        f"{grid.get('grids')} 格",
    ]
    if grid.get("net_profit_per_grid") is not None:
        bits.append(f"每格净收益 {grid.get('net_profit_per_grid')} 元")
    if grid.get("cash_needed") is not None:
        bits.append(f"需资金 {grid.get('cash_needed')} 元")
    bits.append(mode)
    return "网格可配置:" + ",".join(bits)


def compose_rule_advice(pack: dict[str, Any]) -> dict[str, Any]:
    """规则白话:1 句结论 + ≤3 条要点(零 LLM、零延迟、永不空白)"""
    headline = str(pack.get("headline") or "").strip()
    if not headline:
        headline = "暂无可用结论,请稍后再看"

    price_v = _cell(pack, "suggestions", "price")
    trigger_v = _cell(pack, "suggestions", "trigger")
    stop_v = _cell(pack, "suggestions", "stop_loss")
    pos_v = _cell(pack, "suggestions", "position")
    grid = pack.get("grid_plan") or {}

    bullets: list[str] = []
    if price_v:
        bullets.append(f"价位:{price_v}")
    elif trigger_v:
        bullets.append(f"触发:{trigger_v}")
    if grid:
        bullets.append(_grid_summary(grid))
    stop_pos = [x for x in (f"止损 {stop_v}" if stop_v else "", f"仓位 {pos_v}" if pos_v else "") if x]
    if stop_pos:
        bullets.append(" · ".join(stop_pos))

    return {"headline": headline, "bullets": bullets[:3]}


# ============================================================
# 3. LLM 白话(只翻译,不改数字)
# ============================================================

async def _get_llm():
    active = await llm_settings_repo.get_active()
    return await provider_factory.get(active)


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """严格优先:纯 JSON 或 ```json 包裹;再退一步用括号配对抽取。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("LLM 输出里找不到 JSON 对象")
    return json.loads(text[start:end + 1])


async def narrate_with_llm(pack: dict[str, Any]) -> dict[str, Any] | None:
    """把事实包翻译成白话。LLM 不可用 / 超时 / 解析失败 → None(调用方退回规则文案)。"""
    try:
        llm = await _get_llm()
    except Exception as exc:  # noqa: BLE001
        logger.warning("取 LLM 失败,退回规则文案: %s", exc)
        return None
    if llm is None:
        return None

    user_msg = (
        "【事实包】(唯一真相源,只能原样引用其中的数字):\n"
        + json.dumps(pack, ensure_ascii=False, indent=2)
    )
    try:
        raw = await asyncio.wait_for(
            llm.chat(
                DECISION_ADVICE_SYSTEM,
                user_msg,
                max_tokens=LLM_ADVICE_MAX_TOKENS,
            ),
            timeout=LLM_ADVICE_BUDGET,
        )
    except TimeoutError:
        logger.warning("白话生成超时(>%ss),退回规则文案", LLM_ADVICE_BUDGET)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("白话生成失败,退回规则文案: %s", exc)
        return None

    try:
        data = _parse_llm_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("白话 JSON 解析失败,退回规则文案: %s", exc)
        return None

    headline = str(data.get("headline") or "").strip()
    raw_bullets = data.get("bullets")
    bullets: list[str] = []
    if isinstance(raw_bullets, list):
        for b in raw_bullets:
            text = str(b or "").strip()
            if text:
                bullets.append(text)
    if not headline:
        return None
    return {"headline": headline, "bullets": bullets[:3]}


# ============================================================
# 4. 编排 + 当日缓存
# ============================================================

def _cache_key(code: str, decision: dict[str, Any]) -> str:
    headline = str(decision.get("headline") or "")
    return f"{code}|{date.today().isoformat()}|{headline}"


async def build_advice(
    code: str,
    decision: dict[str, Any],
    use_llm: bool = True,
    as_of: str | None = None,
) -> dict[str, Any]:
    """编排:决策 → 事实包 → (可选)LLM 白话 → 规则文案兜底。

    Returns:
        {"advice": {"headline", "bullets", "source", "generated_at"}, "degraded": [...]}
    """
    pack = build_fact_pack(decision, as_of=as_of)
    degraded = list(pack.get("degraded") or [])

    advice = compose_rule_advice(pack)
    source = "rule"

    if use_llm:
        key = _cache_key(code, decision)
        cached = _ADVICE_CACHE.get(key)
        if cached is not None:
            advice = dict(cached)
            source = "llm"
        else:
            narrated = await narrate_with_llm(pack)
            if narrated is not None:
                advice = narrated
                source = "llm"
                _ADVICE_CACHE[key] = dict(narrated)
            else:
                degraded.append("AI 白话不可用,已退回规则文案")

    return {
        "advice": {
            "headline": advice.get("headline", ""),
            "bullets": list(advice.get("bullets") or []),
            "source": source,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "degraded": degraded,
    }


def clear_advice_cache() -> None:
    """清空当日缓存(测试用)"""
    _ADVICE_CACHE.clear()


__all__ = [
    "build_fact_pack",
    "compose_rule_advice",
    "narrate_with_llm",
    "build_advice",
    "clear_advice_cache",
    "DECISION_ADVICE_SYSTEM",
]
