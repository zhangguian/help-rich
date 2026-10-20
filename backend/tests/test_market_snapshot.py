"""全市场快照测试(app.data.market_snapshot)

覆盖 2026-10-20 那次"首页采样冒充全市场"的根因所在:
- 涨跌停按**板块**判定,不是所有股票都 ±10%
- 坏数据(停牌 / 涨跌幅非数值 / 无代码)在快照层就被丢弃,不进统计
- 翻页去重(symbol 唯一)
- 结果带 60s 缓存,避免每次请求都打 56 页
"""
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.data.market_snapshot import (
    MarketSnapshotUnavailable,
    bucket_by_limit,
    fetch_market_snapshot,
    limit_pct,
    reset_market_snapshot_cache,
)


def _raw(
    symbol: str,
    name: str = "测试股",
    trade: str = "10.0",
    changepercent: str = "1.0",
    settlement: str = "9.9",
    amount: str = "100000000",
    volume: str = "1000",
) -> dict[str, Any]:
    """一条新浪 hs_a 原始行"""
    return {
        "symbol": symbol,
        "code": symbol[2:] if len(symbol) > 2 else symbol,
        "name": name,
        "trade": trade,
        "changepercent": changepercent,
        "settlement": settlement,
        "amount": amount,
        "volume": volume,
    }


# ============ 板块感知涨跌停 ============


def test_limit_pct_by_board():
    """创业板/科创板 ±20%,北交所 ±30%,ST ±5%,其他主板 ±10%"""
    assert limit_pct("300750", "宁德时代") == 20.0
    assert limit_pct("301001", "某创业股") == 20.0
    assert limit_pct("688981", "中芯国际") == 20.0
    assert limit_pct("689009", "某科创股") == 20.0
    assert limit_pct("920001", "北交所股") == 30.0
    assert limit_pct("430047", "北交所股") == 30.0
    assert limit_pct("830799", "北交所股") == 30.0
    assert limit_pct("600000", "ST某某") == 5.0
    assert limit_pct("600000", "*ST某某") == 5.0
    assert limit_pct("600000", "浦发银行") == 10.0
    assert limit_pct("000001", "平安银行") == 10.0


def test_bucket_by_limit_uses_board_threshold():
    """涨停判定用板块阈值(容忍 0.1 个百分点浮点误差),中间档沿用 5% / 1%"""
    # 创业板 ±20%:+10% 只是 up_5_10,+20% 才是涨停
    assert bucket_by_limit(10.0, 20.0) == "up_5_10"
    assert bucket_by_limit(19.9, 20.0) == "limit_up"
    assert bucket_by_limit(20.0, 20.0) == "limit_up"
    assert bucket_by_limit(19.8, 20.0) == "up_5_10"
    # 主板 ±10%
    assert bucket_by_limit(10.0, 10.0) == "limit_up"
    assert bucket_by_limit(9.8, 10.0) == "up_5_10"
    assert bucket_by_limit(-10.0, 10.0) == "limit_down"
    assert bucket_by_limit(-9.8, 10.0) == "down_5_10"
    assert bucket_by_limit(-9.9, 10.0) == "limit_down"
    # ST ±5%
    assert bucket_by_limit(5.0, 5.0) == "limit_up"
    assert bucket_by_limit(-5.0, 5.0) == "limit_down"
    # 中间档
    assert bucket_by_limit(5.0, 10.0) == "up_5_10"
    assert bucket_by_limit(1.0, 10.0) == "up_1_5"
    assert bucket_by_limit(0.05, 10.0) == "up_0_1"
    assert bucket_by_limit(0.0, 10.0) == "flat"
    assert bucket_by_limit(-0.05, 10.0) == "down_0_1"
    assert bucket_by_limit(-1.5, 10.0) == "down_1_5"
    assert bucket_by_limit(-5.5, 10.0) == "down_5_10"


# ============ 归一化 / 过滤 / 去重 ============


async def test_fetch_market_snapshot_normalizes_rows():
    """原始新浪行 → 归一化行(code 带市场后缀 / amount 转亿元 / 带板块涨跌停幅度)"""
    reset_market_snapshot_cache()
    raw = [_raw(
        "sh600519", "贵州茅台",
        trade="1700.0", changepercent="2.5", settlement="1658.54",
        amount="3500000000", volume="12345",
    )]

    async def fake_page(client, page):
        return raw if page == 1 else []

    with patch("app.data.market_snapshot._fetch_page", fake_page):
        rows = await fetch_market_snapshot(use_cache=False)

    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == "600519.SH"
    assert r["name"] == "贵州茅台"
    assert r["price"] == 1700.0
    assert r["change_pct"] == 2.5
    assert r["prev_close"] == 1658.54
    assert r["amount_yi"] == 35.0        # 35 亿
    assert r["volume"] == 12345
    assert r["limit_pct"] == 10.0        # 主板
    reset_market_snapshot_cache()


async def test_fetch_market_snapshot_filters_bad_rows_and_dedupes():
    """停牌(price<=0)/涨跌幅非数值/无代码 → 丢弃;symbol 重复 → 只留一条"""
    reset_market_snapshot_cache()
    page1 = [
        _raw("sh600000", "正常股"),
        _raw("sh600001", "坏涨跌幅", changepercent="bad"),
        _raw("sh600002", "停牌股", trade="0"),
        _raw("sh600000", "重复股"),        # symbol 重复
        {"symbol": "", "name": "无代码股"},  # 无 symbol
    ]

    async def fake_page(client, page):
        return page1 if page == 1 else []

    with patch("app.data.market_snapshot._fetch_page", fake_page):
        rows = await fetch_market_snapshot(use_cache=False)

    assert [r["code"] for r in rows] == ["600000.SH"]
    assert rows[0]["name"] == "正常股"
    reset_market_snapshot_cache()


async def test_fetch_market_snapshot_dedupes_across_pages():
    """翻页边界重复也要去重(symbol 唯一性守恒)"""
    reset_market_snapshot_cache()

    async def fake_page(client, page):
        if page == 1:
            return [_raw("sh600000"), _raw("sz000001")]
        if page == 2:
            return [_raw("sz000001"), _raw("sh600002")]  # 跨页重复
        return []

    with patch("app.data.market_snapshot._fetch_page", fake_page):
        rows = await fetch_market_snapshot(use_cache=False)

    assert sorted(r["code"] for r in rows) == ["000001.SZ", "600000.SH", "600002.SH"]
    reset_market_snapshot_cache()


# ============ 缓存 / 失败语义 ============


async def test_fetch_market_snapshot_uses_cache():
    """60s 缓存命中 → 不重复打网络(全量翻页 56 页,不能每次请求都重拉)"""
    reset_market_snapshot_cache()
    calls = {"n": 0}

    async def fake_page(client, page):
        calls["n"] += 1
        return [_raw("sh600000")] if page == 1 else []

    with patch("app.data.market_snapshot._fetch_page", fake_page):
        first = await fetch_market_snapshot()
        pages_first_call = calls["n"]
        second = await fetch_market_snapshot()

    assert pages_first_call > 1          # 第一次确实翻页拉全量
    assert calls["n"] == pages_first_call  # 第二次命中缓存,不再打网络
    assert first == second
    reset_market_snapshot_cache()


async def test_fetch_market_snapshot_unavailable_on_network_error():
    """网络失败 → MarketSnapshotUnavailable(调用方决定降级,不返回假数据)"""
    reset_market_snapshot_cache()

    async def boom(client, page):
        raise httpx.ConnectError("boom")

    with patch("app.data.market_snapshot._fetch_page", boom):
        with pytest.raises(MarketSnapshotUnavailable):
            await fetch_market_snapshot(use_cache=False)
    reset_market_snapshot_cache()


async def test_fetch_market_snapshot_unavailable_when_first_page_empty():
    """第一页就空 → 不可用(不是"市场今天没股票")"""
    reset_market_snapshot_cache()

    async def empty(client, page):
        return []

    with patch("app.data.market_snapshot._fetch_page", empty):
        with pytest.raises(MarketSnapshotUnavailable):
            await fetch_market_snapshot(use_cache=False)
    reset_market_snapshot_cache()
