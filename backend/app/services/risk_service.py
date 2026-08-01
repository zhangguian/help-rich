"""风险敞口报告服务(C1)

输入:持仓列表(从 positions 表)
输出:
- 单股集中度(各股占总投资比例)+ 持仓数 + 行业分散度
- 板块相关性(用 stock_code 前缀推断板块,简化版 MVP)
- 风险评分(0~100,越高越危险)

不依赖外网,纯本地计算。
"""
from collections import Counter, defaultdict
from typing import TypedDict


class PositionExposure(TypedDict):
    stock_code: str
    stock_name: str | None
    shares: int
    avg_cost: str
    market_value: float  # 持仓市值(简化:用 cost,无实时价时)


class RiskReport(TypedDict):
    total_positions: int
    total_market_value: float
    single_stock_concentration: dict[str, float]  # stock_code → 占比 %
    top_holding_ratio: float  # 单股最大占比
    hhi_index: float  # Herfindahl-Hirschman 指数(0~10000)
    sector_breakdown: dict[str, float]  # 板块 → 占比 %
    sector_count: int
    risk_score: int  # 0~100
    risk_level: str  # "低" / "中" / "高"
    warnings: list[str]


def _infer_sector(stock_code: str) -> str:
    """根据股票代码前缀推断板块(简化版 MVP)

    真实场景需要外部映射表(同花顺行业 / 东财行业),v0.3 再接。
    """
    code = stock_code.split(".")[0]
    # 简化:代码前 3 位 → 板块大类(实际需要 industry 表)
    # MVP:按 code 首位归类(不精确,但能给"分散度"直觉)
    # SH: 6xxxxx / 9xxxxx → 大盘
    # SZ: 0xxxxx / 3xxxxx → 深主板 / 创业板
    market = stock_code.split(".")[-1] if "." in stock_code else ""
    if market == "SH":
        if code.startswith(("60", "68")):
            return "沪主板"
        if code.startswith(("9", "5")):
            return "沪其他"
    if market == "SZ":
        if code.startswith("00"):
            return "深主板"
        if code.startswith("30"):
            return "创业板"
        if code.startswith("20"):
            return "深B股"
    if market == "BJ":
        return "北交所"
    return "其他"


def calc_risk(positions: list[PositionExposure]) -> RiskReport:
    """计算风险敞口报告"""
    n = len(positions)
    if n == 0:
        return RiskReport(
            total_positions=0,
            total_market_value=0.0,
            single_stock_concentration={},
            top_holding_ratio=0.0,
            hhi_index=0.0,
            sector_breakdown={},
            sector_count=0,
            risk_score=0,
            risk_level="低",
            warnings=["当前无持仓,无法评估风险"],
        )

    # 1. 持仓市值(用 shares × avg_cost 估算,无实时价)
    values: dict[str, float] = {}
    for p in positions:
        v = p["shares"] * float(p["avg_cost"])
        values[p["stock_code"]] = v

    total = sum(values.values())
    if total <= 0:
        total = 1e-9  # 防止除零

    # 2. 单股占比
    concentration = {code: round(v / total * 100, 2) for code, v in values.items()}
    top_ratio = max(concentration.values()) if concentration else 0.0

    # 3. HHI 指数(Herfindahl-Hirschman):sum(占比^2),0~10000
    hhi = round(sum(r ** 2 for r in concentration.values()), 2)

    # 4. 板块分布
    sectors: dict[str, float] = defaultdict(float)
    for p in positions:
        sec = _infer_sector(p["stock_code"])
        sectors[sec] += values[p["stock_code"]]
    sector_breakdown = {s: round(v / total * 100, 2) for s, v in sectors.items()}
    sector_count = len(sectors)

    # 5. 风险评分(0~100,越高越危险)
    # 权重:单股最大占比 40% + HHI 30% + 持仓数 15% + 板块数 15%
    top_score = min(100.0, top_ratio * 2)  # 50% 占比 = 100 分
    hhi_score = min(100.0, hhi / 100.0)  # HHI 10000 = 100 分
    concentration_score = min(100.0, hhi / 50.0)  # 加权
    diversity_score = max(0.0, 100.0 - sector_count * 25.0)  # 4+ 板块=0 分,1 板块=75 分

    risk_score = int(
        top_score * 0.40 + hhi_score * 0.30 + concentration_score * 0.15 + diversity_score * 0.15
    )
    risk_score = max(0, min(100, risk_score))

    # 风险等级
    if risk_score >= 70:
        level = "高"
    elif risk_score >= 40:
        level = "中"
    else:
        level = "低"

    # 6. 警告
    warnings: list[str] = []
    if top_ratio >= 30:
        warnings.append(f"单股占比 {top_ratio:.1f}% 超 30%,集中度风险高")
    if hhi >= 2500:
        warnings.append(f"HHI 指数 {hhi:.0f},行业高度集中(标 2500+)")
    if sector_count == 1 and n >= 3:
        warnings.append("所有持仓在同一板块,系统性风险高")
    if n < 3:
        warnings.append(f"持仓仅 {n} 只,未充分分散")
    if total < 10000:
        warnings.append("总市值较小,小额账户建议加仓分散")

    return RiskReport(
        total_positions=n,
        total_market_value=round(total, 2),
        single_stock_concentration=concentration,
        top_holding_ratio=round(top_ratio, 2),
        hhi_index=hhi,
        sector_breakdown=sector_breakdown,
        sector_count=sector_count,
        risk_score=risk_score,
        risk_level=level,
        warnings=warnings,
    )


__all__ = ["calc_risk", "PositionExposure", "RiskReport"]