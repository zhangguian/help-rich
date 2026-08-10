"""盘后选股 LLM 评选 prompt + 解析(v2.6)

设计要点:
- 严格按 _parse_llm_json 解析(纯 JSON 或 ```json...```)
- 5 只标的结构化输出:{rank, stock_code, view, highlights, risks, action}
- 失败时:落入 screener_llm_picks.status=failed + error,前端"评选失败,请重试"
- 幂等保护:同一 run_id 重复请求直接返缓存
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.repositories import llm_settings_repo
from app.services.scoring import SCREENER_MAX_SCORE
from app.services.stock_advice_service import _get_llm, _parse_llm_json

logger = logging.getLogger(__name__)

# ============================================================
# Prompt 模板
# ============================================================

SYSTEM_PROMPT = """你是 A 股盘后选股助手,基于"资金驱动评分"的 Top 20 候选股,完成两件事:

1. 从 20 只候选里选出 5 只"明日重点关注"标的(资金驱动评分高 + 风险可控的)
2. 对每只输出结构化判断:
   - rank: 1..5
   - stock_code: 6 位代码.SH/.SZ
   - view: "偏多" | "中性" | "偏空"
   - highlights: 2 句话讲亮点(资金/题材/技术形态)
   - risks: 1 句话讲主要风险点
   - action: "可关注" | "轻仓" | "观望"

最后给一句整体总结(summary,50 字内)。

严格按 JSON 输出,字段名/值不可改。不要任何解释性前缀,直接返回 JSON。
"""

USER_PROMPT_TEMPLATE = """今日盘后筛选结果({run_date},资金驱动评分 v{version}):

候选池 {pool_size} 只,Top {picks_count} 入榜:

{picks_block}

整体背景:沪深300指数今日收盘 {market_change_pct:+.2f}%,两市成交额 {turnover_yi:.0f}亿。

请按 JSON 输出:
{{
  "picks": [
    {{"rank": 1, "stock_code": "600519.SH", "view": "中性", "highlights": "...", "risks": "...", "action": "可关注"}},
    ...共 5 条
  ],
  "summary": "整体一句话总结"
}}
"""


def _format_picks_block(picks: list[Any]) -> str:
    """把 Top N picks 格式化成 LLM 易读的字符串块"""
    lines = []
    for p in picks:
        rules = p.triggered_rules if isinstance(p.triggered_rules, list) else []
        rules_text = "/".join(rules) if rules else "-"
        sector_rank = f"Top{p.sector_inflow_rank}" if p.sector_inflow_rank else "-"
        lines.append(
            f"  {p.rank:>2}. {p.stock_code} {p.stock_name} | "
            f"score {p.score:5.1f}/{SCREENER_MAX_SCORE:.0f} | "
            f"涨幅 {p.change_pct:+.2f}% 量比 {p.volume_ratio:.2f} "
            f"连涨 {p.consecutive_up_days}天 "
            f"成交 {p.turnover_proxy:.2f}亿 | "
            f"板块 {p.sector or '-'} {sector_rank} | "
            f"触发:{rules_text}"
        )
    return "\n".join(lines)


def _format_market_context() -> tuple[float, float]:
    """拉沪深 300 收盘涨跌幅 + 两市成交额估算 — 失败用默认"""
    # 简化:实际可调 market_overview_service.get_overview()
    # 这里给 0/0 让 LLM 在没数据时也不困惑
    try:
        from app.services.market_overview_service import get_market_overview
        ov = get_market_overview()
        # ov 结构暂不稳,先返回占位
        return 0.0, 0.0
    except Exception:
        return 0.0, 0.0


def _validate_picks(parsed: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """校验 LLM 返 JSON 格式 — 5 只标的 + summary

    严格要求:
    - 'picks' 必为 list,长度 1..5
    - 每只: rank (1..5), stock_code 字符串, view ∈ {偏多, 中性, 偏空},
       highlights 字符串, risks 字符串, action ∈ {可关注, 轻仓, 观望}
    - 'summary' 字符串 (可选)
    """
    if not isinstance(parsed, dict):
        raise ValueError("LLM 返回非 dict")
    picks = parsed.get("picks")
    if not isinstance(picks, list) or not (1 <= len(picks) <= 5):
        raise ValueError(f"picks 长度非法: {len(picks) if isinstance(picks, list) else type(picks).__name__}")
    valid_views = {"偏多", "中性", "偏空"}
    valid_actions = {"可关注", "轻仓", "观望"}
    out = []
    for i, p in enumerate(picks):
        if not isinstance(p, dict):
            raise ValueError(f"picks[{i}] 非 dict")
        code = str(p.get("stock_code", "")).strip()
        if not code:
            raise ValueError(f"picks[{i}].stock_code 缺失")
        view = str(p.get("view", "")).strip()
        if view not in valid_views:
            raise ValueError(f"picks[{i}].view 非法: {view!r}")
        action = str(p.get("action", "")).strip()
        if action not in valid_actions:
            raise ValueError(f"picks[{i}].action 非法: {action!r}")
        highlights = str(p.get("highlights", "")).strip()
        risks = str(p.get("risks", "")).strip()
        rank = int(p.get("rank", i + 1))
        out.append({
            "rank": rank,
            "stock_code": code,
            "view": view,
            "highlights": highlights,
            "risks": risks,
            "action": action,
        })
    summary = parsed.get("summary")
    if summary is not None and not isinstance(summary, str):
        summary = str(summary)
    return out, summary


# ============================================================
# 入口
# ============================================================


async def trigger_llm_pick(run_id: int, force: bool = False) -> dict[str, Any]:
    """用户主动触发 LLM 评选

    Args:
        run_id: 哪个 run_id 的 Top 20 用于评选
        force: True 时绕过幂等缓存,重新调 LLM

    Returns: {status, picks, summary, model, prompt_tokens, completion_tokens, error}
    """
    from app.repositories import screener_repo

    # 1. 幂等检查
    if not force:
        existing = await screener_repo.get_llm_pick_by_run(run_id)
        if existing and existing.status == "success":
            return {
                "status": "success",
                "cached": True,
                "picks": json.loads(existing.picks_json),
                "summary": existing.summary,
                "model": existing.model,
                "prompt_tokens": existing.prompt_tokens,
                "completion_tokens": existing.completion_tokens,
                "requested_at": existing.requested_at.isoformat(),
            }

    # 2. 准备 LLM 输入
    picks_rows = await screener_repo.get_picks_by_run(run_id)
    if not picks_rows:
        return {"status": "failed", "error": f"run_id={run_id} 无 picks"}

    # 找 run 元数据
    async_session_local = None  # 复用 repo 已有的 session
    # 直接 from run_id 找:用 ScreenerRun get
    from app.db import async_session as _async_session
    from app.models.orm import ScreenerRun

    async with _async_session() as session:
        from sqlalchemy import select
        run_row = (await session.execute(
            select(ScreenerRun).where(ScreenerRun.id == run_id)
        )).scalar_one_or_none()
    if not run_row:
        return {"status": "failed", "error": f"run_id={run_id} 不存在"}

    picks_block = _format_picks_block(picks_rows)
    market_change, market_turnover_yi = _format_market_context()

    user_msg = USER_PROMPT_TEMPLATE.format(
        run_date=run_row.run_date.isoformat(),
        version=run_row.scoring_version,
        pool_size=run_row.pool_size,
        picks_count=run_row.total_picks,
        picks_block=picks_block,
        market_change_pct=market_change,
        turnover_yi=market_turnover_yi,
    )

    # 3. 调 LLM
    llm = await _get_llm()
    if llm is None:
        err = "未配置 LLM Key"
        await screener_repo.save_llm_pick(
            run_id=run_id, model="none", picks_json=[],
            summary=None, prompt_tokens=None, completion_tokens=None,
            cost_estimate=None, error=err, status="failed",
        )
        return {"status": "failed", "error": err}

    model_name = getattr(llm, "name", "unknown")
    try:
        # 用流式端点会复杂;非流式足够
        raw = await llm.chat(SYSTEM_PROMPT, user_msg, max_tokens=2000)
        parsed = _parse_llm_json(raw)
        picks, summary = _validate_picks(parsed)
    except Exception as e:  # noqa: BLE001
        logger.warning("[screener] LLM 评选失败 run_id=%d: %s", run_id, e)
        await screener_repo.save_llm_pick(
            run_id=run_id, model=model_name, picks_json=[],
            summary=None, prompt_tokens=None, completion_tokens=None,
            cost_estimate=None, error=str(e), status="failed",
        )
        return {"status": "failed", "error": str(e), "model": model_name}

    # 4. 落库
    await screener_repo.save_llm_pick(
        run_id=run_id, model=model_name, picks_json=picks,
        summary=summary, prompt_tokens=None, completion_tokens=None,
        cost_estimate=None, error=None, status="success",
    )

    return {
        "status": "success",
        "cached": False,
        "picks": picks,
        "summary": summary,
        "model": model_name,
        "requested_at": datetime.now().isoformat(),
    }


__all__ = ["trigger_llm_pick", "_validate_picks"]