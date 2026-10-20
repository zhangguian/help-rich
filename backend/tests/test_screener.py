"""盘后选股模块测试(v2.6)

覆盖:
- repo: 4 张表 CRUD + UNIQUE + 替换
- service: 评分公式纯函数已在 test_scoring;这里测 get_pool / scoring 串联
- API: 5 个端点的 happy path + 失败
- LLM: _validate_picks 严格校验 + 幂等保护
"""
import asyncio
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import async_session
from app.main import app
from app.models.orm import (
    IndexConstituent,
    ScreenerLlmPick,
    ScreenerPick,
    ScreenerRun,
)
from app.modules.screener import repository as screener_repo
from app.modules.screener.llm_prompt import _validate_picks


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    """清空 4 张 screener 表 + IndexConstituent"""
    async def _do():
        async with async_session() as session:
            await session.execute(delete(ScreenerLlmPick))
            await session.execute(delete(ScreenerPick))
            await session.execute(delete(ScreenerRun))
            await session.execute(delete(IndexConstituent))
            await session.commit()

    asyncio.run(_do())
    yield


# ============================================================
# Repo:UNIQUE + UPSERT
# ============================================================


def test_index_constituent_unique():
    """UNIQUE(index_code, stock_code) 约束生效"""
    async def _do():
        # 1. 第一次写入 OK
        async with async_session() as session:
            session.add(IndexConstituent(
                index_code="000300.SH", stock_code="600519.SH",
                stock_name="贵州茅台", added_at=date.today(),
            ))
            await session.commit()
        # 2. 同 (index_code, stock_code) 重复 → 抛 IntegrityError
        with pytest.raises(Exception):
            async with async_session() as session:
                session.add(IndexConstituent(
                    index_code="000300.SH", stock_code="600519.SH",
                    stock_name="重名", added_at=date.today(),
                ))
                await session.commit()
        # 3. 不同 stock_code → OK
        async with async_session() as session:
            session.add(IndexConstituent(
                index_code="000300.SH", stock_code="000001.SZ",
                stock_name="平安银行", added_at=date.today(),
            ))
            await session.commit()
        # 4. 同 stock_code 不同 index_code → OK
        async with async_session() as session:
            session.add(IndexConstituent(
                index_code="000905.SH", stock_code="600519.SH",
                stock_name="贵州茅台", added_at=date.today(),
            ))
            await session.commit()
        # 5. 验证只有 3 条入库
        async with async_session() as session:
            from sqlalchemy import func, select
            stmt = select(func.count(IndexConstituent.id))
            n = (await session.execute(stmt)).scalar_one()
        assert n == 3

    asyncio.run(_do())


def test_screener_run_upsert():
    """同日两次 run_daily_pick → 同 run_id 覆盖,不新增"""
    async def _do():
        r1 = await screener_repo.upsert_run(
            run_date=date(2026, 8, 9), scoring_version="v1.0",
            pool_size=800, total_picks=20, elapsed_sec=10.0, note=None,
        )
        r2 = await screener_repo.upsert_run(
            run_date=date(2026, 8, 9), scoring_version="v1.1",
            pool_size=850, total_picks=18, elapsed_sec=11.0, note="手动重跑",
        )
        assert r1.id == r2.id
        assert r2.scoring_version == "v1.1"
        assert r2.total_picks == 18

    asyncio.run(_do())


def test_replace_picks_overwrite():
    """replace_picks 同一 run_id 第二次写入覆盖"""
    async def _do():
        run = await screener_repo.upsert_run(
            run_date=date(2026, 8, 9), scoring_version="v1.0",
            pool_size=800, total_picks=20, elapsed_sec=10.0,
        )
        await screener_repo.replace_picks(run.id, [
            {"rank": 1, "stock_code": "600519.SH", "stock_name": "茅台",
             "score": 90.0, "triggered_rules": ["main_inflow>=1.0亿"]},
        ])
        await screener_repo.replace_picks(run.id, [
            {"rank": 1, "stock_code": "000001.SZ", "stock_name": "平安",
             "score": 80.0, "triggered_rules": []},
            {"rank": 2, "stock_code": "000333.SZ", "stock_name": "美的",
             "score": 70.0, "triggered_rules": []},
        ])
        rows = await screener_repo.get_picks_by_run(run.id)
        assert len(rows) == 2
        assert rows[0].stock_code == "000001.SZ"
        assert rows[1].stock_code == "000333.SZ"

    asyncio.run(_do())


def test_llm_pick_unique_run_id():
    """screener_llm_picks.run_id UNIQUE — save_llm_pick 覆盖而不是新增"""
    async def _do():
        run = await screener_repo.upsert_run(
            run_date=date(2026, 8, 9), scoring_version="v1.0",
            pool_size=800, total_picks=20, elapsed_sec=10.0,
        )
        await screener_repo.save_llm_pick(
            run_id=run.id, model="deepseek", picks_json=[{"rank": 1}],
            summary=None, prompt_tokens=100, completion_tokens=50,
            cost_estimate=None, error=None, status="success",
        )
        await screener_repo.save_llm_pick(
            run_id=run.id, model="deepseek", picks_json=[{"rank": 2}],
            summary="new", prompt_tokens=200, completion_tokens=80,
            cost_estimate=None, error=None, status="success",
        )
        async with async_session() as session:
            from sqlalchemy import func, select
            stmt = select(func.count(ScreenerLlmPick.id)).where(
                ScreenerLlmPick.run_id == run.id
            )
            n = (await session.execute(stmt)).scalar_one()
        assert n == 1
        # 内容应是第二次的
        row = await screener_repo.get_llm_pick_by_run(run.id)
        assert row.summary == "new"
        assert row.completion_tokens == 80

    asyncio.run(_do())


# ============================================================
# _validate_picks(LLM 评选严格校验)
# ============================================================


def test_validate_picks_happy():
    parsed = {
        "picks": [
            {"rank": 1, "stock_code": "600519.SH", "view": "偏多",
             "highlights": "放量突破", "risks": "位置偏高", "action": "可关注"},
            {"rank": 2, "stock_code": "000001.SZ", "view": "中性",
             "highlights": "横盘整理", "risks": "无量", "action": "观望"},
        ],
        "summary": "震荡偏多,关注突破",
    }
    picks, summary = _validate_picks(parsed)
    assert len(picks) == 2
    assert summary == "震荡偏多,关注突破"


def test_validate_picks_invalid_view_raises():
    parsed = {"picks": [{"rank": 1, "stock_code": "X", "view": "看涨"}]}
    with pytest.raises(ValueError, match="view 非法"):
        _validate_picks(parsed)


def test_validate_picks_invalid_action_raises():
    parsed = {"picks": [{"rank": 1, "stock_code": "X", "view": "中性", "action": "买"}]}
    with pytest.raises(ValueError, match="action 非法"):
        _validate_picks(parsed)


def test_validate_picks_too_many_raises():
    parsed = {"picks": [{"rank": i, "stock_code": f"{i:06d}.SH", "view": "中性",
                         "action": "观望"} for i in range(6)]}
    with pytest.raises(ValueError, match="长度非法"):
        _validate_picks(parsed)


def test_validate_picks_missing_code_raises():
    parsed = {"picks": [{"rank": 1, "view": "中性", "action": "观望"}]}
    with pytest.raises(ValueError, match="stock_code"):
        _validate_picks(parsed)


# ============================================================
# API:5 个端点
# ============================================================


def test_api_pool_empty_returns_zero(client):
    """候选池为空(没跑初始化)→ count=0"""
    r = client.get("/api/screener/pool")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["preview"] == []


def test_api_pool_with_seed(client):
    """种几条数据后能拉到"""
    async def _seed():
        async with async_session() as session:
            for code, name in [("600519.SH", "茅台"), ("000001.SZ", "平安")]:
                session.add(IndexConstituent(
                    index_code="000300.SH", stock_code=code,
                    stock_name=name, added_at=date.today(),
                ))
            await session.commit()
    asyncio.run(_seed())

    r = client.get("/api/screener/pool")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2


def test_api_latest_404_when_no_run(client):
    """无任何 run → 404"""
    r = client.get("/api/screener/latest")
    assert r.status_code == 404


def test_api_latest_returns_run_and_picks(client):
    """有 run 时返回 run 详情 + picks 列表"""
    async def _seed():
        run = await screener_repo.upsert_run(
            run_date=date(2026, 8, 9), scoring_version="v1.0",
            pool_size=800, total_picks=2, elapsed_sec=5.0,
        )
        await screener_repo.replace_picks(run.id, [
            {"rank": 1, "stock_code": "600519.SH", "stock_name": "茅台",
             "score": 90.5, "volume_ratio": 2.3, "change_pct": 5.2,
             "consecutive_up_days": 3, "sector": "白酒",
             "sector_inflow_rank": 2, "turnover_proxy": 12.3,
             "main_net_inflow_yi": 1.5,
             "triggered_rules": ["主力净流入≥1.0亿", "量比≥1.5"]},
        ])
    asyncio.run(_seed())

    r = client.get("/api/screener/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["run_date"] == "2026-08-9" or body["run"]["run_date"] == "2026-08-09"
    assert body["run"]["total_picks"] == 2  # upsert 用了 total_picks=2
    assert len(body["picks"]) == 1
    p = body["picks"][0]
    assert p["stock_code"] == "600519.SH"
    assert p["triggered_rules"] == ["主力净流入≥1.0亿", "量比≥1.5"]


def test_api_runs_list(client):
    """runs 端点返回最近 N 天"""
    async def _seed():
        for i in range(3):
            await screener_repo.upsert_run(
                run_date=date(2026, 8, 9 - i), scoring_version="v1.0",
                pool_size=800, total_picks=20, elapsed_sec=5.0,
            )
    asyncio.run(_seed())

    r = client.get("/api/screener/runs?days=5")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3


def test_api_llm_pick_404_when_no_run(client):
    """无 run 时 LLM 评选 → 404"""
    r = client.post("/api/screener/latest/llm-pick")
    assert r.status_code == 404


def test_api_llm_pick_cached(client, monkeypatch):
    """已有 LLM pick → 幂等直接返缓存,不重调 LLM"""
    async def _seed():
        run = await screener_repo.upsert_run(
            run_date=date(2026, 8, 9), scoring_version="v1.0",
            pool_size=800, total_picks=20, elapsed_sec=5.0,
        )
        await screener_repo.save_llm_pick(
            run_id=run.id, model="deepseek",
            picks_json=[{"rank": 1, "stock_code": "600519.SH", "view": "中性",
                         "highlights": "亮点", "risks": "风险", "action": "可关注"}],
            summary="已评过", prompt_tokens=100, completion_tokens=50,
            cost_estimate=None, error=None, status="success",
        )
    asyncio.run(_seed())

    # 把 trigger_llm_pick monkeypatch 成会失败以便验证没被调用
    # 注意:endpoint 内部 `from app.modules.screener.llm_prompt import trigger_llm_pick`
    # 所以 patch 源模块才对
    calls = {"n": 0}

    async def _fake_trigger(run_id, force=False):
        calls["n"] += 1
        return {"status": "failed", "error": "should not be called"}
    monkeypatch.setattr(
        "app.modules.screener.llm_prompt.trigger_llm_pick", _fake_trigger
    )

    r = client.post("/api/screener/latest/llm-pick")
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is True
    assert body["summary"] == "已评过"
    assert calls["n"] == 0  # 关键:缓存命中不调 LLM


def test_api_trigger_now_requires_allow_flag(client):
    """trigger-now 默认 403"""
    r = client.post("/api/screener/trigger-now")
    assert r.status_code == 403