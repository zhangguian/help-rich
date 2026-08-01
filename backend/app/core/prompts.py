"""Prompt 模板(backend-arch §9.6 / project-book §4.3.3)

诊断评语模板,含自选股措辞分支:
- 不在自选股 → "观察中"措辞
- 在自选股但未持仓 → "关注标的首次建仓"措辞
"""

# 系统提示:克制的复盘助手
DIAGNOSE_SYSTEM = (
    "你是克制的复盘助手,2~3 句话讲清楚,只基于给定数据,"
    '不预测涨跌,不给出买卖指令,引用具体数据,末尾固定加"以上不构成投资建议"。'
)

# 用户模板占位符:{trade}{recent_summary}{score}{breakdown}{watchlist_hint}
DIAGNOSE_USER_TEMPLATE = """数据:
- 本次交易:{trade}
- 持仓占比:{concentration_pct}%
- 历史最近 5 笔:{recent_summary}
- 评分:{score} 分,各维度:{breakdown}
- 自选股状态:{watchlist_hint}

任务:
1) 指出本次操作的主要问题(或亮点),引用具体数据
2) 下次类似场景的改进建议(1 句)
"""


def build_diagnose_user_prompt(
    trade_line: str,
    concentration_pct: str,
    recent_summary: str,
    score: int,
    breakdown: dict,
    is_in_watchlist: bool,
) -> str:
    """组装用户消息(纯字符串,便于测试)"""
    if is_in_watchlist:
        watchlist_hint = "在自选股中"
    else:
        watchlist_hint = "不在自选股中(该股暂不在你的自选股,如已关注可考虑加入自选股持续观察)"

    return DIAGNOSE_USER_TEMPLATE.format(
        trade=trade_line,
        concentration_pct=concentration_pct,
        recent_summary=recent_summary,
        score=score,
        breakdown="、".join(f"{k} {v}分" for k, v in breakdown.items()),
        watchlist_hint=watchlist_hint,
    )


def build_trade_line(sanitized: dict) -> str:
    """交易行:600519 贵州茅台 买入 500-1000股 @2026-07-20"""
    action_cn = "买入" if sanitized.get("action") == "buy" else "卖出"
    return (
        f"{sanitized.get('stock_code')} {sanitized.get('stock_name')} "
        f"{action_cn} {sanitized.get('shares_bucket')}股 @{sanitized.get('trade_date')}"
    )


__all__ = [
    "DIAGNOSE_SYSTEM",
    "DIAGNOSE_USER_TEMPLATE",
    "build_diagnose_user_prompt",
    "build_trade_line",
]
