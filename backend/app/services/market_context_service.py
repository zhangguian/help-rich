"""市场环境聚合(大盘温度 / 行业强弱 + 资金 / 本股资金 / 相对强弱)

只读项目既有服务,**不新增任何抓取逻辑**;任一子项失败只降级该项,
对应字段置 None 并写入 degraded —— 绝不编数字。

⚠️ 两套行业命名口径(**必须分清,否则匹配永远失败**):
- **证监会行业名**(离线表 baostock,形如 "C39计算机、通信和其他电子设备制造业")
  → 用于 `get_sector_kline()`(行业等权 K 线),与 `overview_service.fetch_sector` 同源
- **新浪行业板块名**(形如 "电子元件")
  → 用于 `get_sector_fund_flow()`(板块资金流排行)
两套名字互不相通。`resolve_industry()` 优先返回证监会口径(离线表命中时),
因此**用它的返回值去匹配板块资金流通常会落空** —— 落空就如实降级,
同时用「今日资金主攻板块」补充市场主线信息(该口径恒可用)。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.decision_service import MarketContext
from app.services.fund_flow_service import list_recent
from app.services.industry_service import resolve_industry
from app.services.market_overview_service import fetch_market_sentiment, get_market_overview
from app.services.sector_fund_flow_service import get_sector_fund_flow
from app.services.sector_kline_service import get_sector_kline

logger = logging.getLogger(__name__)

MARKET_WARM_RATIO = 1.5   # 涨家数 > 跌家数 × 该系数 → 偏暖
MARKET_COLD_RATIO = 1.5   # 跌家数 > 涨家数 × 该系数 → 偏冷
LEADING_SECTOR_TOP_N = 3  # 今日资金主攻板块展示条数


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


async def _safe(coro_factory, label: str, degraded: list[str]):
    """跑一个 IO 调用;失败返回 None 并记录降级原因"""
    try:
        return await coro_factory()
    except Exception as e:  # noqa: BLE001
        logger.warning("市场环境 %s 取数失败: %s", label, e)
        degraded.append(f"{label} 不可用")
        return None


async def get_market_context(
    stock_code: str, stock_change_pct: float | None = None
) -> MarketContext:
    """聚合某只票的市场环境

    stock_change_pct: 该股当日涨跌幅(%),用于算相对强弱;None → 相对强弱为 None。
    """
    degraded: list[str] = []

    sentiment, overview, industry, flows, stock_flows = await asyncio.gather(
        _safe(lambda: fetch_market_sentiment(), "大盘情绪", degraded),
        _safe(lambda: get_market_overview(), "大盘指数", degraded),
        _safe(lambda: resolve_industry(stock_code), "行业归属", degraded),
        _safe(lambda: get_sector_fund_flow(fenlei=1, num=40, sort="netamount"),
              "板块资金流", degraded),
        _safe(lambda: list_recent(stock_code, limit=1), "本股资金流", degraded),
    )

    # ---- 大盘 ----
    market: dict[str, Any] = {
        "state": None, "up_total": None, "down_total": None, "flat_total": None,
        "limit_up": None, "limit_down": None, "sample_size": None,
        "change_pct": None, "summary": "大盘数据暂不可用",
    }
    if isinstance(sentiment, dict):
        up = sentiment.get("up_total")
        down = sentiment.get("down_total")
        market.update({
            "up_total": up, "down_total": down,
            "flat_total": sentiment.get("flat_total"),
            "limit_up": sentiment.get("limit_up"),
            "limit_down": sentiment.get("limit_down"),
            "sample_size": sentiment.get("sample_size"),
        })
        if isinstance(up, int) and isinstance(down, int) and up + down > 0:
            if up > down * MARKET_WARM_RATIO:
                market["state"] = "warm"
            elif down > up * MARKET_COLD_RATIO:
                market["state"] = "cold"
            else:
                market["state"] = "neutral"
            tone = {"warm": "偏暖", "cold": "偏冷", "neutral": "分化"}[market["state"]]
            summary = f"大盘{tone}:涨 {up} / 跌 {down}"
            # 涨停/跌停家数可能缺失(部分快照不返回)→ 缺就整段不写,不要输出「涨停 None」
            limits = []
            if market["limit_up"] is not None:
                limits.append(f"涨停 {market['limit_up']}")
            if market["limit_down"] is not None:
                limits.append(f"跌停 {market['limit_down']}")
            if limits:
                summary += "," + " / ".join(limits)
            market["summary"] = summary
    # 大盘涨跌幅:取上证指数真实涨跌幅(不用涨跌家数近似)
    market_chg = _index_change_pct(overview)
    if market_chg is not None:
        market["change_pct"] = market_chg

    # ---- 行业 ----
    industry_name = None
    if isinstance(industry, dict):
        industry_name = industry.get("industry")
    sector: dict[str, Any] = {
        "industry": industry_name, "change_pct": None, "vs_market_pct": None,
        "fund_net_yi": None, "fund_direction": None, "state": None,
        "leading": [], "summary": "行业归属未知" if industry_name is None else "",
    }

    # 行业等权 K 线(证监会口径,与 resolve_industry 一级结果同源)
    if industry_name:
        kline = await _safe(
            lambda: get_sector_kline(industry_name, period="daily", count=60),
            "行业K线", degraded,
        )
        chg = _sector_change_pct(kline)
        if chg is not None:
            sector["change_pct"] = chg
            if chg > 1:
                sector["state"] = "leading"
            elif chg > 0:
                sector["state"] = "warm"
            elif chg > -1:
                sector["state"] = "lagging"
            else:
                sector["state"] = "cold"

    # 行业相对大盘强弱(设计文档 §7.2:vs_market_pct = change_pct - 大盘 change_pct)
    if sector["change_pct"] is not None and market_chg is not None:
        sector["vs_market_pct"] = round(sector["change_pct"] - market_chg, 2)

    # 板块资金流(新浪口径):只有行业名恰好是新浪板块名时才命中,否则如实降级
    if isinstance(flows, list) and flows:
        # 今日资金主攻板块(该口径恒可用,回答「今天钱在往哪走」)
        # 只保留净流入为正的板块(「主攻」= 钱在往里流),按净流入降序取 Top N
        positive: list[tuple[float, dict[str, Any]]] = []
        for f in flows:
            net = _f(f.get("netamount_yi"))
            if net is not None and net > 0:
                positive.append((net, f))
        ranked = sorted(positive, key=lambda x: x[0], reverse=True)[:LEADING_SECTOR_TOP_N]
        sector["leading"] = [
            {"name": f.get("name"), "net_yi": round(net, 2)}
            for net, f in ranked
        ]
        if industry_name:
            for it in flows:
                if it.get("name") == industry_name:
                    net = _f(it.get("netamount_yi"))
                    if net is not None:
                        sector["fund_net_yi"] = net
                        sector["fund_direction"] = (
                            "in" if net > 0 else ("out" if net < 0 else None)
                        )
                    break
            else:
                degraded.append("板块资金流无该行业(行业名为证监会口径,与新浪板块名不同)")
    elif industry_name:
        degraded.append("板块资金流不可用")

    if sector["state"] and sector["fund_direction"] == "out":
        sector["state"] = {
            "leading": "warm", "warm": "lagging", "lagging": "cold", "cold": "cold",
        }[sector["state"]]

    parts: list[str] = []
    if industry_name:
        parts.append(f"所属 {industry_name}")
    if sector["change_pct"] is not None:
        parts.append(f"今日 {sector['change_pct']:+.2f}%")
    if sector["vs_market_pct"] is not None:
        parts.append(
            f"跑赢大盘 {sector['vs_market_pct']:+.2f}%"
            if sector["vs_market_pct"] >= 0
            else f"跑输大盘 {sector['vs_market_pct']:+.2f}%"
        )
    if sector["fund_net_yi"] is not None:
        parts.append(f"板块主力净流入 {sector['fund_net_yi']:+.2f} 亿")
    if sector["leading"]:
        top = "、".join(
            f"{s['name']} {s['net_yi']:+.1f}亿" for s in sector["leading"]
        )
        parts.append(f"资金主攻 {top}")
    sector["summary"] = " · ".join(parts) if parts else "行业数据暂不可用"

    # ---- 本股资金流 ----
    stock_flow: dict[str, Any] = {
        "direction": None, "amount_wan": None, "category": None, "summary": "暂无资金流数据",
    }
    if isinstance(stock_flows, list) and stock_flows:
        ff = stock_flows[0]
        amt = _f(getattr(ff, "amount", None))
        direction = getattr(ff, "direction", None)
        if direction in ("in", "out"):
            stock_flow["direction"] = direction
            stock_flow["amount_wan"] = amt
            stock_flow["category"] = getattr(ff, "category", None)
            verb = "净流入" if direction == "in" else "净流出"
            stock_flow["summary"] = (
                f"本股今日主力{verb} {amt:.2f} 万"
                if amt is not None else f"本股今日主力{verb}"
            )

    # ---- 相对强弱 ----
    relative: dict[str, Any] = {
        "vs_sector_pct": None, "vs_market_pct": None, "summary": "相对强弱暂无数据",
    }
    if stock_change_pct is not None:
        if sector["change_pct"] is not None:
            relative["vs_sector_pct"] = round(stock_change_pct - sector["change_pct"], 2)
        if market_chg is not None:
            relative["vs_market_pct"] = round(stock_change_pct - market_chg, 2)
        bits = []
        if relative["vs_sector_pct"] is not None:
            bits.append(f"强于行业 {relative['vs_sector_pct']:+.2f}%")
        if relative["vs_market_pct"] is not None:
            bits.append(f"强于大盘 {relative['vs_market_pct']:+.2f}%")
        if bits:
            relative["summary"] = f"本股 {stock_change_pct:+.2f}% · " + " · ".join(bits)

    return MarketContext(
        market=market,
        sector=sector,
        stock_flow=stock_flow,
        relative=relative,
        degraded=degraded,
    )


def _sector_change_pct(kline: Any) -> float | None:
    """行业等权 K 线近 1 日涨幅 %

    ⚠️ `get_sector_kline()` 返回的 items **只有 date / close**(等权合成收盘价),
    没有 open/high/low —— 所以只能算收盘对收盘的涨幅。
    """
    if not isinstance(kline, dict):
        return None
    items = kline.get("items") or []
    if len(items) < 2:
        return None
    try:
        prev = float(items[-2]["close"])
        cur = float(items[-1]["close"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if prev <= 0:
        return None
    return round((cur - prev) / prev * 100, 2)


def _index_change_pct(overview: Any) -> float | None:
    """大盘涨跌幅 %:取上证指数真实涨跌幅(不用涨跌家数近似)

    `get_market_overview()` → {"indexes": [{"code","name","close","change_pct",...}], ...}
    取第一个 change_pct 非空的指数。
    """
    if not isinstance(overview, dict):
        return None
    for idx in overview.get("indexes") or []:
        if not isinstance(idx, dict):
            continue
        chg = _f(idx.get("change_pct"))
        if chg is not None:
            return round(chg, 2)
    return None
