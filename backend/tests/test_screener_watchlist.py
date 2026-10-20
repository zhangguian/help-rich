"""盘后选股 — 观察池 测试(v2.6)

覆盖:
- repo: add/remove/list/upsert daily / is_watched
- service: ISO 周/月分桶 + hit_rate 聚合
- API: 3 个端点 + 幂等
"""
import asyncio
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import async_session
from app.main import app
from app.models.orm import (
    ScreenerWatchlist,
    ScreenerWatchlistDaily,
)
from app.modules.screener import repository as screener_repo
from app.modules.screener.service import (
    _iso_month_label,
    _iso_week_label,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    """清空观察池 2 张表"""
    async def _do():
        async with async_session() as session:
            await session.execute(delete(ScreenerWatchlistDaily))
            await session.execute(delete(ScreenerWatchlist))
            await session.commit()
    asyncio.run(_do())
    yield


# ============================================================
# ISO 周/月标签
# ============================================================


def test_iso_week_label_basic():
    # 2026-08-09 周日 → ISO 2026-W32,week_start=2026-08-03 周一,week_end=2026-08-09 周日
    label, start, end = _iso_week_label(date(2026, 8, 9))
    assert label == "2026-W32"
    assert start == "2026-08-03"
    assert end == "2026-08-09"


def test_iso_week_label_year_boundary():
    # 2026-01-01 周四 → ISO 2026-W01
    label, start, end = _iso_week_label(date(2026, 1, 1))
    assert label == "2026-W01"
    assert start == "2025-12-29"  # 周一
    assert end == "2026-01-04"


def test_iso_month_label():
    label, start, end = _iso_month_label(date(2026, 8, 9))
    assert label == "2026-08"
    assert start == "2026-08-01"
    assert end == "2026-08-31"


# ============================================================
# repo: watchlist CRUD
# ============================================================


def test_watchlist_unique_stock_code():
    async def _do():
        await screener_repo.add_watchlist(
            stock_code="600519.SH", stock_name="茅台",
            marked_at=date(2026, 8, 9),
            marked_close="1300.00", marked_change_pct="0.015",
        )
        with pytest.raises(Exception):
            # 故意绕开幂等检查,直接 session.add
            from sqlalchemy.exc import IntegrityError
            async with async_session() as session:
                session.add(ScreenerWatchlist(
                    stock_code="600519.SH", stock_name="重复",
                    marked_at=date(2026, 8, 9),
                    status="active",
                ))
                await session.commit()
        # 通过 add_watchlist 重入 → 应返 existing,不抛错
        again = await screener_repo.add_watchlist(
            stock_code="600519.SH", stock_name="茅台",
            marked_at=date(2026, 8, 10),
            marked_close="1310.00", marked_change_pct="0.02",
        )
        # 幂等:marked_at 不会更新
        assert again.marked_at == date(2026, 8, 9)
    asyncio.run(_do())


def test_watchlist_remove_existing_and_missing():
    async def _do():
        await screener_repo.add_watchlist(
            stock_code="000001.SZ", stock_name="平安",
            marked_at=date(2026, 8, 9), marked_close="11.50",
            marked_change_pct="0.005",
        )
        removed = await screener_repo.remove_watchlist("000001.SZ")
        assert removed is True
        # 再次删除 → False
        removed2 = await screener_repo.remove_watchlist("000001.SZ")
        assert removed2 is False
    asyncio.run(_do())


def test_watchlist_codes_set():
    async def _do():
        for code in ["600519.SH", "000001.SZ", "300750.SZ"]:
            await screener_repo.add_watchlist(
                stock_code=code, stock_name=code,
                marked_at=date(2026, 8, 9), marked_close="1.0",
                marked_change_pct="0",
            )
        codes = await screener_repo.list_watchlist_codes(status="active")
        assert codes == {"600519.SH", "000001.SZ", "300750.SZ"}
    asyncio.run(_do())


# ============================================================
# repo: daily records upsert
# ============================================================


def test_upsert_daily_records_insert_and_update():
    async def _do():
        w = await screener_repo.add_watchlist(
            stock_code="600519.SH", stock_name="茅台",
            marked_at=date(2026, 8, 9), marked_close="100.00",
            marked_change_pct="0",
        )
        records = [
            {"trade_date": date(2026, 8, 10), "open_price": "101",
             "high_price": "102", "low_price": "100", "close_price": "101.5",
             "volume": 1000, "pct_from_marked": "0.015"},
            {"trade_date": date(2026, 8, 11), "open_price": "102",
             "high_price": "103", "low_price": "101", "close_price": "102.5",
             "volume": 2000, "pct_from_marked": "0.025"},
        ]
        added = await screener_repo.upsert_daily_records(w.id, records)
        assert added == 2

        # 再 upsert 同一天,update(不同 close)
        updated_records = [
            {"trade_date": date(2026, 8, 10), "open_price": "101",
             "high_price": "102", "low_price": "100", "close_price": "105",
             "volume": 1000, "pct_from_marked": "0.05"},
        ]
        added2 = await screener_repo.upsert_daily_records(w.id, updated_records)
        assert added2 == 0  # 不是新写入

        rows = await screener_repo.list_daily_records(w.id)
        assert len(rows) == 2
        # close_price 应被更新
        d10 = next(r for r in rows if r.trade_date == date(2026, 8, 10))
        assert float(d10.close_price) == 105.0
        assert float(d10.pct_from_marked) == 0.05
    asyncio.run(_do())


def test_list_latest_records():
    async def _do():
        wid = (await screener_repo.add_watchlist(
            stock_code="000001.SZ", stock_name="平安",
            marked_at=date(2026, 8, 9), marked_close="11.00",
        )).id
        wid2 = (await screener_repo.add_watchlist(
            stock_code="000002.SZ", stock_name="万科",
            marked_at=date(2026, 8, 9), marked_close="9.00",
        )).id
        # wid 有 2 条 daily;wid2 没有
        await screener_repo.upsert_daily_records(wid, [
            {"trade_date": date(2026, 8, 10), "open_price": "11",
             "high_price": "11.5", "low_price": "10.5", "close_price": "11.2",
             "volume": 100, "pct_from_marked": "0.018"},
            {"trade_date": date(2026, 8, 11), "open_price": "11",
             "high_price": "11.8", "low_price": "11.1", "close_price": "11.5",
             "volume": 200, "pct_from_marked": "0.045"},
        ])
        m = await screener_repo.list_latest_records([wid, wid2])
        assert m[wid].trade_date == date(2026, 8, 11)  # 最新那条
        assert m[wid2] is None
    asyncio.run(_do())


# ============================================================
# service: weekly summary
# ============================================================


def test_compute_watchlist_summary_empty():
    async def _do():
        result = await screener_service.compute_watchlist_summary() \
            if False else None
        from app.modules.screener import service as svc
        result = await svc.compute_watchlist_summary()
        assert result["summary"]["totalWatched"] == 0
        assert result["weeks"] == []
        assert result["months"] == []
    asyncio.run(_do())


def test_compute_watchlist_summary_weekly_buckets(monkeypatch):
    """mock K 线 + K 线真实拉,验证周聚合 + hit_rate"""

    async def _do():
        from app.modules.screener import service as svc

        # 加 2 只股
        w1 = await screener_repo.add_watchlist(
            stock_code="600519.SH", stock_name="茅台",
            marked_at=date(2026, 8, 10),  # 周一
            marked_close="100.00",
        )
        w2 = await screener_repo.add_watchlist(
            stock_code="000001.SZ", stock_name="平安",
            marked_at=date(2026, 8, 11),  # 周二
            marked_close="20.00",
        )
        # 直接 upsert daily records(不走 fetch_klines,简化)
        await screener_repo.upsert_daily_records(w1.id, [
            {"trade_date": date(2026, 8, 11), "open_price": "101",
             "high_price": "102", "low_price": "100", "close_price": "102.0",
             "volume": 100, "pct_from_marked": "0.02"},   # hit
            {"trade_date": date(2026, 8, 12), "open_price": "102",
             "high_price": "103", "low_price": "101", "close_price": "103.0",
             "volume": 100, "pct_from_marked": "0.03"},   # hit
        ])
        await screener_repo.upsert_daily_records(w2.id, [
            {"trade_date": date(2026, 8, 12), "open_price": "20",
             "high_price": "20.5", "low_price": "19.5", "close_price": "19.5",
             "volume": 100, "pct_from_marked": "-0.025"},  # miss
        ])

        result = await svc.compute_watchlist_summary()
        assert result["summary"]["totalWatched"] == 2
        # 周分桶:同一周内每只股只算其最新一天 → 2 entries (w1 最新 8/12 + w2 8/12)
        assert len(result["weeks"]) >= 1
        week = next(w for w in result["weeks"] if w["label"] == "2026-W33")
        assert week["stock_count"] == 2  # 2 只股各贡献最新一条
        assert week["hit_count"] == 1  # w1 最新 +3%
        assert week["miss_count"] == 1  # w2 -2.5%
        assert abs(week["hit_rate"] - 0.5) < 0.01
        assert week["avg_change_pct"] == pytest.approx((0.03 - 0.025) / 2, abs=1e-3)
    asyncio.run(_do())


def test_refresh_watchlist_daily_mocked(monkeypatch):
    """mock kline_service.fetch_klines,验证 pct_from_marked 计算"""

    async def _do():
        from app.modules.screener import service as svc

        w = await screener_repo.add_watchlist(
            stock_code="688981.SH", stock_name="中芯",
            marked_at=date(2026, 8, 9),
            marked_close="50.00",
        )
        # mock fetch_klines 返 [8/10=51, 8/11=49]
        async def _fake_klines(code, period="daily", count=60):
            return [
                {"date": "2026-08-10", "open": "50", "high": "52",
                 "low": "50", "close": "51", "volume": 1000},
                {"date": "2026-08-11", "open": "51", "high": "51",
                 "low": "49", "close": "49", "volume": 1000},
            ]
        monkeypatch.setattr(svc.kline_service, "fetch_klines", _fake_klines)

        added = await svc.refresh_watchlist_daily(w.id)
        assert added == 2
        rows = await screener_repo.list_daily_records(w.id)
        # (51-50)/50 = 0.02
        r1 = next(r for r in rows if r.trade_date == date(2026, 8, 10))
        assert abs(float(r1.pct_from_marked) - 0.02) < 1e-4
        # (49-50)/50 = -0.02
        r2 = next(r for r in rows if r.trade_date == date(2026, 8, 11))
        assert abs(float(r2.pct_from_marked) - (-0.02)) < 1e-4
    asyncio.run(_do())


# ============================================================
# API: 3 个端点
# ============================================================


def test_api_watchlist_add_idempotent(client):
    r = client.post("/api/screener/watchlist", json={
        "stock_code": "600519.SH",
        "stock_name": "贵州茅台",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["watched"] is True
    assert body["already_existed"] is False
    # 重复 → already_existed=True
    r2 = client.post("/api/screener/watchlist", json={
        "stock_code": "600519.SH",
        "stock_name": "贵州茅台",
    })
    assert r2.status_code == 200
    assert r2.json()["already_existed"] is True


def test_api_watchlist_remove(client):
    client.post("/api/screener/watchlist", json={
        "stock_code": "000001.SZ",
        "stock_name": "平安银行",
    })
    r = client.delete("/api/screener/watchlist/000001.SZ")
    assert r.status_code == 200
    assert r.json()["removed"] is True
    # 不存在的 → removed=False(200,不抛错)
    r2 = client.delete("/api/screener/watchlist/000001.SZ")
    assert r2.status_code == 200
    assert r2.json()["removed"] is False


def test_api_watchlist_summary_empty(client):
    r = client.get("/api/screener/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["totalWatched"] == 0
    assert body["weeks"] == []
    assert body["months"] == []


def test_api_latest_picks_include_is_watched(client):
    """/api/screener/latest picks 应带 is_watched 字段"""
    async def _seed():
        # 先放一个 run + pick
        run = await screener_repo.upsert_run(
            run_date=date(2026, 8, 9), scoring_version="v1.0",
            pool_size=10, total_picks=2, elapsed_sec=1.0,
        )
        await screener_repo.replace_picks(run.id, [
            {"rank": 1, "stock_code": "600519.SH", "stock_name": "茅台",
             "score": 90.0, "triggered_rules": []},
            {"rank": 2, "stock_code": "000001.SZ", "stock_name": "平安",
             "score": 80.0, "triggered_rules": []},
        ])
        # 标记一只
        await screener_repo.add_watchlist(
            stock_code="600519.SH", stock_name="茅台",
            marked_at=date(2026, 8, 9), marked_close="100.0",
        )
    asyncio.run(_seed())

    r = client.get("/api/screener/latest")
    assert r.status_code == 200
    picks = r.json()["picks"]
    assert any(p["stock_code"] == "600519.SH" and p["is_watched"] is True for p in picks)
    assert any(p["stock_code"] == "000001.SZ" and p["is_watched"] is False for p in picks)


def test_compute_watchlist_summary_today_change():
    """v2.6.1:今日单日涨跌 = 最新 pct - 上一个 pct"""
    async def _do():
        from app.modules.screener import service as svc

        # 加 2 只股
        w1 = await screener_repo.add_watchlist(
            stock_code="600519.SH", stock_name="茅台",
            marked_at=date(2026, 8, 10), marked_close="100.00",
        )
        w2 = await screener_repo.add_watchlist(
            stock_code="000001.SZ", stock_name="平安",
            marked_at=date(2026, 8, 10), marked_close="20.00",
        )
        # w1: 8/11 pct=0.02, 8/12 pct=0.05 → 今日 +3%
        # w2: 8/11 pct=-0.01, 8/12 pct=-0.03 → 今日 -2%
        await screener_repo.upsert_daily_records(w1.id, [
            {"trade_date": date(2026, 8, 11), "open_price": "100",
             "high_price": "103", "low_price": "100", "close_price": "102.0",
             "volume": 100, "pct_from_marked": "0.02"},
            {"trade_date": date(2026, 8, 12), "open_price": "102",
             "high_price": "106", "low_price": "102", "close_price": "105.0",
             "volume": 100, "pct_from_marked": "0.05"},
        ])
        await screener_repo.upsert_daily_records(w2.id, [
            {"trade_date": date(2026, 8, 11), "open_price": "20",
             "high_price": "20.2", "low_price": "19.8", "close_price": "19.8",
             "volume": 100, "pct_from_marked": "-0.01"},
            {"trade_date": date(2026, 8, 12), "open_price": "19.8",
             "high_price": "19.9", "low_price": "19.5", "close_price": "19.4",
             "volume": 100, "pct_from_marked": "-0.03"},
        ])

        result = await svc.compute_watchlist_summary()
        summary = result["summary"]
        # 2 只股都被计入
        assert summary["todayCounted"] == 2
        # 今日日期 = 最新记录日
        assert summary["todayDate"] == "2026-08-12"
        # 今日 hit=1 (w1 +3%), miss=1 (w2 -2%)
        assert summary["todayHitCount"] == 1
        assert summary["todayMissCount"] == 1
        # 平均今日涨跌 = (0.03 + -0.02) / 2 = 0.005
        assert abs(summary["todayAvgChange"] - 0.005) < 1e-3
    asyncio.run(_do())


def test_compute_watchlist_summary_today_change_insufficient_history():
    """v2.6.1:每日记录 < 2 条时,今日涨跌不计入(todayCounted=0)"""
    async def _do():
        from app.modules.screener import service as svc

        w = await screener_repo.add_watchlist(
            stock_code="688981.SH", stock_name="中芯",
            marked_at=date(2026, 8, 12), marked_close="50.00",
        )
        # 仅 1 条记录
        await screener_repo.upsert_daily_records(w.id, [
            {"trade_date": date(2026, 8, 12), "open_price": "50",
             "high_price": "51", "low_price": "49", "close_price": "50.5",
             "volume": 100, "pct_from_marked": "0.01"},
        ])
        result = await svc.compute_watchlist_summary()
        summary = result["summary"]
        assert summary["todayCounted"] == 0
        assert summary["todayAvgChange"] == 0.0
        assert summary["todayDate"] is None
    asyncio.run(_do())