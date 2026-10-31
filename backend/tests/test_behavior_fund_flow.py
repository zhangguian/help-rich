"""逐日资金流缓存层单测(behavior_fund_flow_service)

钉死计划 §3.2.1 的关键行为:
- **首次 miss → 拉真实接口 → 落库**
- **二次命中 DB → 零外网请求**
- **按日期对齐**(绝不按索引)
- **接口失败 → 抛 FundFlowUnavailable**,不返回假数据
"""
from __future__ import annotations

from datetime import date

import pytest

from app.services import behavior_fund_flow_service as svc


class TestAlignByDate:
    def test_keyed_by_date(self):
        rows = [
            {"date": "2026-10-30", "net_amount": 1.0},
            {"date": "2026-10-29", "net_amount": 2.0},
        ]
        out = svc.align_by_date(rows)
        assert set(out.keys()) == {"2026-10-30", "2026-10-29"}
        assert out["2026-10-29"]["net_amount"] == 2.0

    def test_empty_and_invalid(self):
        assert svc.align_by_date(None) == {}
        assert svc.align_by_date([]) == {}
        assert svc.align_by_date([{"date": ""}, "not-a-dict"]) == {}

    def test_duplicate_date_keeps_last(self):
        rows = [
            {"date": "2026-10-30", "net_amount": 1.0},
            {"date": "2026-10-30", "net_amount": 9.0},
        ]
        out = svc.align_by_date(rows)
        assert out["2026-10-30"]["net_amount"] == 9.0


class TestParseRow:
    def test_parses_all_fields(self):
        row = {
            "opendate": "2026-10-30",
            "changeratio": "0.0281019",
            "turnover": "47.9387",
            "netamount": "1573592085.31",
            "r0_net": "1377802257.63",
            "r0x_ratio": "80.44",
        }
        parsed = svc._parse_row(row)
        assert parsed is not None
        assert parsed["date"] == "2026-10-30"
        assert parsed["net_amount"] == pytest.approx(1573592085.31)
        assert parsed["r0_net"] == pytest.approx(1377802257.63)
        assert parsed["r0x_ratio"] == pytest.approx(80.44)
        assert parsed["change_ratio"] == pytest.approx(0.0281019)

    def test_missing_opendate_returns_none(self):
        assert svc._parse_row({"netamount": "1"}) is None
        assert svc._parse_row("not-a-dict") is None


class TestSinaSymbol:
    def test_conversion(self):
        assert svc._to_sina_symbol("600519.SH") == "sh600519"
        assert svc._to_sina_symbol("000001.SZ") == "sz000001"
        assert svc._to_sina_symbol("600519") == "sh600519"


class TestFetchFlowDaily:
    async def test_miss_then_cache_hit(self, monkeypatch):
        """首次 miss → 拉接口 → 落库;二次 → 命中 DB,零外网请求。"""
        calls = {"n": 0}

        async def fake_fetch(stock_code: str, count: int):
            calls["n"] += 1
            return [
                {
                    "date": "2026-10-30",
                    "net_amount": 1.5e8,
                    "r0_net": 1.0e8,
                    "r0x_ratio": 80.0,
                    "r0_ratio": 60.0,
                    "turnover": 30.0,
                    "change_ratio": 0.02,
                },
                {
                    "date": "2026-10-29",
                    "net_amount": -0.5e8,
                    "r0_net": -0.3e8,
                    "r0x_ratio": -20.0,
                    "r0_ratio": -10.0,
                    "turnover": 20.0,
                    "change_ratio": -0.01,
                },
            ]

        monkeypatch.setattr(svc, "_fetch_sina_flow_daily", fake_fetch)

        first = await svc.fetch_flow_daily("600519.SH", count=120, use_cache=True)
        assert calls["n"] == 1
        assert len(first) == 2
        # 返回必须按日期升序
        assert first[0]["date"] < first[1]["date"]

        second = await svc.fetch_flow_daily("600519.SH", count=120, use_cache=True)
        # 命中缓存 → 不再打外网
        assert calls["n"] == 1
        assert len(second) == 2
        assert second[0]["date"] == first[0]["date"]
        assert second[0]["net_amount"] == first[0]["net_amount"]

    async def test_source_unavailable_raises(self, monkeypatch):
        """真实接口失败 → 抛 FundFlowUnavailable(不返回假数据)。"""

        async def boom(stock_code: str, count: int):
            raise svc.FundFlowUnavailable("模拟接口不可用")

        monkeypatch.setattr(svc, "_fetch_sina_flow_daily", boom)

        with pytest.raises(svc.FundFlowUnavailable):
            await svc.fetch_flow_daily("600519.SH", count=120, use_cache=False)

    async def test_empty_response_raises(self, monkeypatch):
        async def empty(stock_code: str, count: int):
            return []

        monkeypatch.setattr(svc, "_fetch_sina_flow_daily", empty)
        with pytest.raises(svc.FundFlowUnavailable):
            await svc.fetch_flow_daily("600519.SH", count=120, use_cache=False)


class TestNeedsRefresh:
    def test_empty_needs_refresh(self):
        assert svc._needs_refresh([]) is True

    def test_recent_cache_ok(self):
        # 今天的数据 → 不需要重拉
        rows = [{"date": date.today().isoformat()}]
        assert svc._needs_refresh(rows) is False

    def test_stale_after_close(self, monkeypatch):
        monkeypatch.setattr(svc, "_is_post_close", lambda *a, **k: True)
        monkeypatch.setattr(
            svc, "_last_trading_day", lambda *a, **k: date(2026, 10, 30)
        )
        rows = [{"date": "2026-10-28"}]
        assert svc._needs_refresh(rows) is True
