"""T-M2.2 板块K线合成单测(纯函数 + mock 注入)"""
import asyncio

import pytest

from app.services.kline_service import KLineSourceUnavailable
from app.services.sector_kline_service import (
    _align_dates,
    get_sector_kline,
    load_industry_components,
    pick_components,
)


def _run(coro):
    return asyncio.run(coro)


def _series(code: str, base: float, days: int, gap: list[int] | None = None):
    """构造成分日K:同日起 `d1..dn`,close = base + d"""
    out = []
    missing = set(gap or [])
    for d in range(1, days + 1):
        if d in missing:
            continue
        out.append({
            "date": f"2026-01-{d:02d}",
            "close": base + d,
        })
    return out


class TestPickComponents:
    def test_pick_cap(self):
        comps = {"白酒": [f"6005{i:02d}.SH" for i in range(40)]}
        got = pick_components("白酒", comps)
        assert len(got) == 30  # MAX_COMPONENTS

    def test_empty(self):
        assert pick_components("白酒", {}) == []
        assert pick_components("不存在", {"白酒": []}) == []

    def test_real_map(self):
        """离线表能反查行业成分(真实表)"""
        comps = load_industry_components()
        assert comps and isinstance(comps, dict)
        # 茅台行业应有成分
        assert any("酒" in k for k in comps)


class TestAlignDates:
    def test_equal_weight_mean(self):
        a = _series("a", 10, 3)
        b = _series("b", 20, 3)
        out = _align_dates([a, b])
        # 每日期 close = (a + b)/2
        assert out == [
            {"date": "2026-01-01", "close": 16.0},
            {"date": "2026-01-02", "close": 17.0},
            {"date": "2026-01-03", "close": 18.0},
        ]

    def test_intersection_only(self):
        a = _series("a", 10, 3)
        b = _series("b", 20, 3, gap=[2])  # b 缺 1-02
        out = _align_dates([a, b])
        assert [r["date"] for r in out] == ["2026-01-01", "2026-01-03"]

    def test_empty(self):
        assert _align_dates([]) == []


class TestGetSectorKline:
    def test_success_via_mock(self):
        comps = {"白酒": ["600519.SH", "000568.SZ"]}
        calls: list[str] = []

        async def fake_fetch(code, period="daily", count=60):
            calls.append(code)
            return _series(code, 100 if code.startswith("600") else 30, 5)

        r = _run(get_sector_kline(
            "白酒", count=5, component_loader=lambda: comps, fetch_one=fake_fetch,
        ))
        assert r["industry"] == "白酒"
        assert r["count"] == 5
        assert r["components"] == 2
        assert set(calls) == {"600519.SH", "000568.SZ"}

    def test_all_components_fail(self):
        async def boom(code, period="daily", count=60):
            raise KLineSourceUnavailable("挂了")

        with pytest.raises(KLineSourceUnavailable):
            _run(get_sector_kline(
                "白酒", fetch_one=boom, component_loader=lambda: {"白酒": ["600519.SH"]},
            ))

    def test_partial_failure_skips(self):
        async def fake_fetch(code, period="daily", count=60):
            if code.startswith("600"):
                return _series(code, 10, 3)
            raise KLineSourceUnavailable("该成分挂了")

        r = _run(get_sector_kline(
            "白酒", component_loader=lambda: {"白酒": ["600519.SH", "000001.SZ"]},
            fetch_one=fake_fetch,
        ))
        assert r["components"] == 1  # 失败成分被跳过