"""LLM 数据脱敏(backend-arch §9.5 / project-book §4.3.3)

传给 LLM 前只保留 5 项字段:
- 股票代码 / 名称
- 操作方向
- 股数区间(不分桶到精确股数)
- 交易日期
- 持仓占比

不传:精确价格、金额、持仓成本。
"""


def bucket_shares(shares: int) -> str:
    """股数分桶(脱敏:不给精确股数)"""
    if shares < 100:
        return "<100"
    if shares < 500:
        return "100-500"
    if shares < 1000:
        return "500-1000"
    if shares < 5000:
        return "1000-5000"
    return "5000+"


def sanitize_for_llm(trade: dict, concentration_pct: float | None = None) -> dict:
    """交易信息脱敏

    Args:
        trade: 原始交易 dict(stock_code / stock_name / action / shares / trade_date)
        concentration_pct: 持仓占比百分比(0~100 或 None)

    Returns:
        只含 5 项脱敏字段的 dict
    """
    return {
        "stock_code": trade.get("stock_code", ""),
        "stock_name": trade.get("stock_name", ""),
        "action": trade.get("action", ""),
        "shares_bucket": bucket_shares(int(trade.get("shares", 0))),
        "trade_date": trade.get("trade_date", ""),
        "concentration_pct": (
            f"{concentration_pct:.1f}" if concentration_pct is not None else "未知"
        ),
    }


__all__ = ["bucket_shares", "sanitize_for_llm"]
