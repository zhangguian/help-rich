"""GB-001 IR-3:评分样本外校准测试

- 纯函数:_bucket_for / _pct_return / _index_to_close
- 端到端 compute_calibration(评分+流水+K线 → 校准表)
  - 样本不足(< 3)→ insufficient=true
  - 样本充足 → avg / median / win_rate 正确
  - K 线缺失 → 跳过,不计入
"""
import asyncio
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.score_calibration import (
    HORIZON_DAYS,
    MIN_SAMPLES,
    SCORE_BUCKETS,
    _bucket_for,
    _index_to_close,
    _pct_return,
    compute_calibration,
)


# ============ 纯函数 ============

class TestBucketFor:
    def test_low_bucket(self):
        assert _bucket_for(0) == ("0-71", 0, 71)
        assert _bucket_for(71) == ("0-71", 0, 71)

    def test_mid_bucket(self):
        assert _bucket_for(72) == ("72-95", 72, 95)
        assert _bucket_for(80) == ("72-95", 72, 95)
        assert _bucket_for(95) == ("72-95", 72, 95)

    def test_high_bucket(self):
        assert _bucket_for(96) == ("96-120", 96, 120)
        assert _bucket_for(120) == ("96-120", 96, 120)


class TestPctReturn:
    def test_basic(self):
        assert _pct_return("10.000", "11.000") == pytest.approx(10.0)

    def test_loss(self):
        assert _pct_return("10.000", "9.000") == pytest.approx(-10.0)

    def test_zero_via_zero_price(self):
        # 0 close 视为非法 → 0.0 兜底
        assert _pct_return("0.000", "10.000") == 0.0

    def test_round_trip(self):
        assert _pct_return("10.000", "10.000") == 0.0


class TestIndexToClose:
    def test_basic(self):
        klines = [
            {"date": "2026-07-01", "close": "10.000"},
            {"date": "2026-07-02", "close": "10.500"},
        ]
        out = _index_to_close(klines)
        assert out[date(2026, 7, 1)] == "10.000"
        assert out[date(2026, 7, 2)] == "10.500"

    def test_skip_invalid_date(self):
        klines = [
            {"date": "not-a-date", "close": "10.000"},
            {"date": "2026-07-01", "close": "10.000"},
        ]
        out = _index_to_close(klines)
        assert len(out) == 1

    def test_skip_missing_close(self):
        klines = [
            {"date": "2026-07-01", "close": ""},
            {"date": "2026-07-02", "close": "10.500"},
        ]
        out = _index_to_close(klines)
        assert len(out) == 1


# ============ 端到端 (compute_calibration) ============

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    """清空评分 + 流水 + K 线,保证断言独立"""
    from app.db import async_session
    from app.models.orm import KlineCache, TradeScore, Transaction
    from sqlalchemy import delete

    async def _do():
        async with async_session() as session:
            await session.execute(delete(TradeScore))
            await session.execute(delete(Transaction))
            await session.execute(delete(KlineCache))
            await session.commit()

    asyncio.run(_do())
    yield


def _seed_buy_trade(client, trade_id: int, stock_code: str, trade_date: date, score: int):
    """插入 (transaction, trade_score) — 直接 SQLAlchemy 拿 session"""
    _seed_buy_trades_bulk([(trade_id, stock_code, trade_date, score)])


def _seed_buy_trades_bulk(rows: list[tuple[int, str, date, int]]):
    """批量插入 (transaction, trade_score) — 一次 asyncio.run 提交,避免多次 loop 切换丢数据"""
    from app.db import async_session
    from app.models.orm import TradeScore, Transaction

    async def _do():
        async with async_session() as s:
            for trade_id, stock_code, trade_date, score in rows:
                s.add(Transaction(
                    id=trade_id,
                    stock_code=stock_code,
                    stock_name="测试",
                    action="buy",
                    shares=100,
                    price="10.000",
                    trade_date=trade_date,
                ))
                s.add(TradeScore(
                    trade_id=trade_id,
                    score=score,
                    score_breakdown="{}",
                    ai_status="success",
                    ai_provider="deepseek",
                ))
            await s.commit()

    asyncio.run(_do())


class TestCalibrationE2E:
    def test_5_trades_in_72_95_bucket(self, monkeypatch):
        """5 笔 72-95 评分 → 只该桶 calibrated(120 分制桶边界)"""
        base = date(2026, 7, 1)
        _seed_buy_trades_bulk([
            (1, "600519.SH", base, 72),
            (2, "600519.SH", base, 80),
            (3, "600519.SH", base, 85),
            (4, "600519.SH", base, 90),
            (5, "600519.SH", base, 95),
        ])
        fake_klines = _build_fake_klines(base, count=30)
        monkeypatch.setattr(
            "app.services.score_calibration.fetch_klines",
            lambda *a, **k: _async_return(fake_klines),
        )

        result = asyncio.run(compute_calibration())

        assert result["horizon_days"] == HORIZON_DAYS
        assert result["sample_count"] == 5
        mid = next(b for b in result["buckets"] if b["label"] == "72-95")
        assert mid["count"] == 5
        assert mid["insufficient"] is False
        assert mid["avg_return"] is not None
        assert mid["avg_return"] > 0  # 单调递增
        assert mid["win_rate"] == 1.0
        # 0-71 与 96-120 样本为 0
        low = next(b for b in result["buckets"] if b["label"] == "0-71")
        high = next(b for b in result["buckets"] if b["label"] == "96-120")
        assert low["count"] == 0
        assert low["insufficient"] is True
        assert high["count"] == 0
        assert high["insufficient"] is True
        assert result["calibrated"] is True

    def test_insufficient_returns_zero_count(self, monkeypatch):
        """1 笔评分 → bucket 样本不足"""
        _seed_buy_trades_bulk([(1, "600519.SH", date(2026, 7, 1), 55)])
        fake_klines = _build_fake_klines(date(2026, 7, 1), count=30)
        monkeypatch.setattr(
            "app.services.score_calibration.fetch_klines",
            lambda *a, **k: _async_return(fake_klines),
        )

        result = asyncio.run(compute_calibration())
        low = next(b for b in result["buckets"] if b["label"] == "0-71")
        assert low["count"] == 1
        assert low["insufficient"] is True
        assert low["avg_return"] is None
        assert result["calibrated"] is False

    def test_skips_trade_with_insufficient_klines(self, monkeypatch):
        """K 线窗口不足 → 跳过"""
        base = date(2026, 7, 1)
        _seed_buy_trades_bulk([
            (1, "600519.SH", base, 60),
            (2, "600519.SH", base, 65),
            (3, "600519.SH", base, 70),
        ])
        # K 线只 5 根(不够 20 日窗口)
        fake_klines = _build_fake_klines(base, count=5)
        monkeypatch.setattr(
            "app.services.score_calibration.fetch_klines",
            lambda *a, **k: _async_return(fake_klines),
        )

        result = asyncio.run(compute_calibration())
        assert result["sample_count"] == 0
        assert result["calibrated"] is False

    def test_no_data_returns_empty(self, monkeypatch):
        """空 DB → 全部 insufficient"""
        result = asyncio.run(compute_calibration())
        assert result["sample_count"] == 0
        assert result["calibrated"] is False
        for b in result["buckets"]:
            assert b["count"] == 0
            assert b["insufficient"] is True

    def test_sell_trades_excluded(self, monkeypatch):
        """sell 评分不计入校准(只验证 buy 评分)"""
        from app.db import async_session
        from app.models.orm import TradeScore, Transaction

        async def _do():
            async with async_session() as s:
                s.add(Transaction(
                    id=1, stock_code="600519.SH", stock_name="x",
                    action="sell", shares=100, price="10.000",
                    trade_date=date(2026, 7, 1),
                ))
                s.add(TradeScore(
                    trade_id=1, score=80, score_breakdown="{}",
                    ai_status="success", ai_provider="deepseek",
                ))
                await s.commit()

        asyncio.run(_do())
        fake_klines = _build_fake_klines(date(2026, 7, 1), count=30)
        monkeypatch.setattr(
            "app.services.score_calibration.fetch_klines",
            lambda *a, **k: _async_return(fake_klines),
        )

        result = asyncio.run(compute_calibration())
        assert result["sample_count"] == 0
        assert result["calibrated"] is False


class TestCalibrationAPI:
    def test_api_returns_table(self, monkeypatch):
        """GET /api/score-calibration 返回校准表 JSON"""
        base = date(2026, 7, 1)
        _seed_buy_trades_bulk([
            (1, "600519.SH", base, 60),
            (2, "600519.SH", base, 65),
            (3, "600519.SH", base, 70),
            (4, "600519.SH", base, 75),
            (5, "600519.SH", base, 78),
        ])
        fake_klines = _build_fake_klines(base, count=30)
        monkeypatch.setattr(
            "app.services.score_calibration.fetch_klines",
            lambda *a, **k: _async_return(fake_klines),
        )

        with TestClient(app) as c:
            r = c.get("/api/score-calibration")
            assert r.status_code == 200
            data = r.json()
            assert data["horizon_days"] == HORIZON_DAYS
            assert "buckets" in data
            assert len(data["buckets"]) == 3
            assert all("label" in b for b in data["buckets"])


def _async_return(value):
    """构造一个 awaitable 返回 value"""
    async def _coro():
        return value
    return _coro()


def _build_fake_klines(start: date, count: int, daily_growth: float = 0.01) -> list[dict]:
    """根据起始日生成 N 根日 K,每日 +1%(跳周末)"""
    rows = []
    d = start
    price = 10.0
    for i in range(count):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        if i > 0:
            price *= 1 + daily_growth
        close = f"{price:.3f}"
        rows.append({"date": d.isoformat(), "close": close})
        d += timedelta(days=1)
    return rows
