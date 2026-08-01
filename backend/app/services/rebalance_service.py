"""智能调仓建议服务(A4)

基于持仓结构(集中度 / 板块分散 / 持仓数)生成"加仓 / 减仓 / 分散"建议。

MVP:**纯结构判断**,不依赖实时价(Position 模型没 current_price 字段)。
v0.3 接入实时价后扩展"浮盈"判断。

规则(启发式):
- 单股占比 > 30% → 建议减仓 10-20%(降集中度)
- 持仓 < 3 只 → 建议加仓其他板块
- 同板块 ≥ 3 只 → 建议分散
- 整仓占比悬殊(top1 > 50%) → 平衡提示

输出:
- actions: list[{type, stock_code, name, suggested_pct, reason, priority}]
- summary: 整体建议

纯本地计算,不依赖外网。
"""
from typing import TypedDict


class PositionLite(TypedDict):
    """持仓精简数据(纯本地,不依赖 ORM 字段)"""
    stock_code: str
    stock_name: str | None
    shares: int
    avg_cost: str
    market_value: float


class RebalanceAction(TypedDict):
    """调仓动作建议"""
    type: str  # "reduce" / "add" / "diversify" / "alert"
    priority: str  # "high" / "medium" / "low"
    stock_code: str | None
    stock_name: str | None
    title: str
    reason: str
    suggested_pct: float


class RebalanceSuggestion(TypedDict):
    total_market_value: float
    actions: list[RebalanceAction]
    summary: str


def _parse_money(s: str) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def calculate_rebalance(positions: list[PositionLite]) -> RebalanceSuggestion:
    """生成调仓建议(纯结构判断)"""
    n = len(positions)
    if n == 0:
        return RebalanceSuggestion(
            total_market_value=0.0,
            actions=[],
            summary="当前无持仓,无法生成调仓建议",
        )

    total = sum(p["market_value"] for p in positions)
    if total <= 0:
        total = 1e-9
    actions: list[RebalanceAction] = []

    # 1. 单股占比 > 30% → 减仓
    for p in positions:
        ratio = p["market_value"] / total * 100
        if ratio > 30:
            actions.append({
                "type": "reduce",
                "priority": "high",
                "stock_code": p["stock_code"],
                "stock_name": p["stock_name"],
                "title": f"建议减仓 {p['stock_code']}",
                "reason": (
                    f"单股占比 {ratio:.1f}%(阈值 30%),集中度风险高。"
                    f"建议减仓 10-20% 降低单股系统性风险。"
                ),
                "suggested_pct": 15.0,
            })

    # 2. top1 > 50% → 平衡提示
    if n >= 2:
        top_ratio = max(p["market_value"] for p in positions) / total * 100
        if top_ratio > 50:
            top_p = max(positions, key=lambda p: p["market_value"])
            actions.append({
                "type": "alert",
                "priority": "medium",
                "stock_code": top_p["stock_code"],
                "stock_name": top_p["stock_name"],
                "title": f"整仓偏重 {top_p['stock_code']}",
                "reason": (
                    f"top1 占比 {top_ratio:.1f}%(阈值 50%),仓位过于集中。"
                    f"建议分批减持,资金分散到其他标的。"
                ),
                "suggested_pct": 0.0,
            })

    # 3. 持仓数 < 3 → 加仓
    if n < 3:
        actions.append({
            "type": "add",
            "priority": "medium",
            "stock_code": None,
            "stock_name": None,
            "title": "持仓过少,建议加仓",
            "reason": (
                f"当前仅 {n} 只持仓,未充分分散。"
                f"建议选 2-3 个其他板块(消费/医药/科技等)的标的加仓,目标持仓 ≥ 5 只。"
            ),
            "suggested_pct": 0.0,
        })

    # 4. 同板块 ≥ 3 只 → 分散
    sector_groups: dict[str, list[PositionLite]] = {}
    for p in positions:
        sec = _infer_sector(p["stock_code"])
        sector_groups.setdefault(sec, []).append(p)
    for sec, ps in sector_groups.items():
        if len(ps) >= 3:
            actions.append({
                "type": "diversify",
                "priority": "medium",
                "stock_code": ps[0]["stock_code"],
                "stock_name": sec,
                "title": f"板块 {sec} 集中",
                "reason": (
                    f"板块 {sec} 有 {len(ps)} 只持仓,系统性风险高。"
                    f"建议减仓 1-2 只,资金分散到其他板块(目标单一板块 ≤ 2 只)。"
                ),
                "suggested_pct": 0.0,
            })

    # summary
    if not actions:
        summary = "✅ 持仓结构合理,无需调仓"
    else:
        high = sum(1 for a in actions if a["priority"] == "high")
        medium = sum(1 for a in actions if a["priority"] == "medium")
        summary = (
            f"共 {len(actions)} 条建议"
            + (f"({high} 条高优先级)" if high else "")
            + (f"({medium} 条中优先级)" if medium else "")
        )

    return RebalanceSuggestion(
        total_market_value=round(total, 2),
        actions=actions,
        summary=summary,
    )


def _infer_sector(stock_code: str) -> str:
    """简化版板块推断(同 risk_service)"""
    code = stock_code.split(".")[0]
    market = stock_code.split(".")[-1] if "." in stock_code else ""
    if market == "SH":
        if code.startswith(("60", "68")):
            return "沪主板"
    if market == "SZ":
        if code.startswith("00"):
            return "深主板"
        if code.startswith("30"):
            return "创业板"
    return "其他"


__all__ = ["calculate_rebalance", "PositionLite", "RebalanceSuggestion"]