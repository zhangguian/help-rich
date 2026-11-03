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
    """交易行:600519 贵州茅台 买入 500-1000股 @2026-07-20 14:38

    时间点可选:有就带上(评语里能看出「尾盘追单」这类时点语境),
    没有就只留日期(**不编造**时间)。
    """
    action_cn = "买入" if sanitized.get("action") == "buy" else "卖出"
    base = (
        f"{sanitized.get('stock_code')} {sanitized.get('stock_name')} "
        f"{action_cn} {sanitized.get('shares_bucket')}股 @{sanitized.get('trade_date')}"
    )
    trade_time = sanitized.get("trade_time")
    if trade_time:
        base += f" {str(trade_time)[:5]}"
    return base


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


# ============================================================
# === 一键复盘(per 股票 + 窗口聚合,v2.3) ===
# ============================================================

# 系统提示:克制的复盘助手(聚合视图,与 DIAGNOSE_SYSTEM 风格保持一致)
REPLAY_SYSTEM = (
    "你是克制的复盘助手,基于给定的窗口内流水 + 评分聚合 + 持仓快照,"
    "用 3 段(亮点/问题/建议)写 200~300 字综合复盘。只基于给定数据,"
    "不预测涨跌,不给出买卖指令,引用具体数字,末尾固定加"
    '"以上不构成投资建议"。'
)

# 用户模板占位符:{window_label}{tx_count}{buy_count}{sell_count}{score_avg}
# {dimension_avg}{top_issues}{concentration}{realized_pnl}{snapshot_lines}{watchlist_hint}
REPLAY_USER_TEMPLATE = """数据窗口:{window_label}(共 {tx_count} 笔流水,买入 {buy_count} 笔 / 卖出 {sell_count} 笔)

该窗口评分聚合:
- 平均分 {score_avg}
- 各维度均值:{dimension_avg_lines}

Top 3 问题维度(低分优先):
{top_issues_lines}

持仓上下文:
- 当前持仓占比 {concentration_pct}%
- 已实现盈亏(本次窗口内):¥{realized_pnl}
- 自选股状态:{watchlist_hint}

流水明细(本次窗口内):
{snapshot_lines}

任务(3 段输出):
1) 亮点:本次窗口内做得好的 1~2 点(引用具体数据)
2) 问题:本次窗口内主要的 1~2 个操作问题(引用维度低分原因)
3) 建议:下次类似场景的 1~2 条可执行改进(具体数字)
"""


def build_replay_user_prompt(
    window_label: str,
    tx_count: int,
    buy_count: int,
    sell_count: int,
    score_avg: str,
    dimension_avg: dict,
    top_issues: list,
    concentration_pct: str,
    realized_pnl: str,
    snapshot_lines: str,
    is_in_watchlist: bool,
) -> str:
    """组装一键复盘用户消息"""
    dimension_avg_lines = "、".join(
        f"{k} {v}分" for k, v in dimension_avg.items()
    ) if dimension_avg else "无评分数据(窗口内无单笔 diagnose)"

    top_issues_lines = "、".join(
        f"{it['dim']} {it['score']}分({it['hint']})"
        for it in top_issues
    ) if top_issues else "无明显低分维度"

    if is_in_watchlist:
        watchlist_hint = "在自选股中"
    else:
        watchlist_hint = "不在自选股中(可考虑加入自选持续观察)"

    return REPLAY_USER_TEMPLATE.format(
        window_label=window_label,
        tx_count=tx_count,
        buy_count=buy_count,
        sell_count=sell_count,
        score_avg=score_avg,
        dimension_avg_lines=dimension_avg_lines,
        top_issues_lines=top_issues_lines,
        concentration_pct=concentration_pct,
        realized_pnl=realized_pnl,
        snapshot_lines=snapshot_lines,
        watchlist_hint=watchlist_hint,
    )


__all__ = [
    "DIAGNOSE_SYSTEM",
    "DIAGNOSE_USER_TEMPLATE",
    "build_diagnose_user_prompt",
    "build_trade_line",
    "OCR_SYSTEM",
    "OCR_USER_TEMPLATE",
    "build_ocr_prompt",
    "REPLAY_SYSTEM",
    "REPLAY_USER_TEMPLATE",
    "build_replay_user_prompt",
]
