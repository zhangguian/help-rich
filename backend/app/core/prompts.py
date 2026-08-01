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


# ============================================================
# === 截图识别 Prompt(backend-arch §9.7.5 / P8) ===
# ============================================================

OCR_SYSTEM = (
    "你是同花顺 App 截图 OCR 文本解析专家。"
    "从 OCR 提取的文本中识别持仓 / 流水 / 自选股字段,返回合法 JSON。"
    '末尾固定加"以上不构成投资建议"。'
)

OCR_USER_TEMPLATE = """OCR 提取文本:
\"\"\"
{ocr_text}
\"\"\"

字段定义:
- 持仓:stock_code(6位), stock_name, shares(int), cost_price(3位小数), market_value(2位小数)
- 流水:stock_code, stock_name, action(buy/sell), shares(int), price(3位小数), trade_date(YYYY-MM-DD)
- 自选股:stock_code, stock_name

输出合法 JSON:
{{
  "screenshot_type": "position | transactions | watchlist",
  "items": [ ... ],
  "confidence": 0.0~1.0,
  "notes": "..."
}}

约束:代码读不清就标 confidence < 0.5;价格只取 OCR 数字,不要估算;JSON 合法无尾逗号。
"""


def build_ocr_prompt(ocr_text: str) -> str:
    """组装 OCR 解析 prompt"""
    return OCR_USER_TEMPLATE.format(ocr_text=ocr_text)


__all__ = [
    "DIAGNOSE_SYSTEM",
    "DIAGNOSE_USER_TEMPLATE",
    "build_diagnose_user_prompt",
    "build_trade_line",
    "OCR_SYSTEM",
    "OCR_USER_TEMPLATE",
    "build_ocr_prompt",
]
