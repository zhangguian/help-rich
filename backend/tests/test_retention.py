"""数据裁剪(retention)的回归测试。

这些用例锁死两个真实发生过的问题:

1. `screener_picks` 表**没有** created_at(日期挂在父表 screener_runs.run_date 上),
   而早先的 `_prune_daily` 统一用 `model.created_at` 删,一进循环就
   `AttributeError: type object 'ScreenerPick' has no attribute 'created_at'`。
   异常从 `run_retention` 抛出 → main.py 启动钩子只打一行 warning 就跳过 →
   **VACUUM 永远不执行** → 本地库涨到 411MB,其中 105148/105305 页是空页(99.8%),
   于是启动时打开 411MB 库 + 333MB WAL 从 6s 变成 85s。

2. `fund_flow` 的保留窗口子查询被提到循环外,且条件写成 `stock_code == stock_code`
   (恒真),语义从"每只股票各留 N 条"错成"全库只留 N 条"。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.db import async_session
from app.models.orm import DailyAnalysis, FundFlow, ScreenerPick, ScreenerRun
from app.services import retention as R


async def _seed_flows(code: str, n: int, start: datetime) -> None:
    async with async_session() as s:
        for i in range(n):
            s.add(
                FundFlow(
                    stock_code=code,
                    timestamp=start + timedelta(minutes=i),
                    direction="in",
                    amount="1.5",
                    category="main",
                )
            )
        await s.commit()


async def _count_flows() -> int:
    async with async_session() as s:
        rows = (await s.execute(select(FundFlow))).scalars().all()
    return len(rows)


async def _flows_of(code: str) -> list[datetime]:
    async with async_session() as s:
        rows = (
            await s.execute(
                select(FundFlow).where(FundFlow.stock_code == code).order_by(FundFlow.timestamp)
            )
        ).scalars().all()
    return [r.timestamp for r in rows]


class TestFundFlowKeepWindow:
    async def test_keeps_n_rows_per_stock_not_n_in_total(self):
        """每只票各留 2 条 —— 旧实现会全库只剩 2 条。"""
        base = datetime(2026, 10, 1, 9, 30)
        await _seed_flows("600000", 5, base)
        await _seed_flows("000001", 5, base)

        deleted, total = await R._prune_fund_flow(keep_per_stock=2)

        assert total == 10
        assert deleted == 6
        assert await _count_flows() == 4
        left_a = await _flows_of("600000")
        left_b = await _flows_of("000001")
        assert len(left_a) == 2
        assert len(left_b) == 2

    async def test_keeps_the_newest_rows(self):
        """留下的必须是最近的两条,而不是最早的两条。"""
        base = datetime(2026, 10, 1, 9, 30)
        await _seed_flows("600000", 5, base)

        await R._prune_fund_flow(keep_per_stock=2)

        left = await _flows_of("600000")
        assert left == [base + timedelta(minutes=3), base + timedelta(minutes=4)]

    async def test_noop_when_below_limit(self):
        await _seed_flows("600000", 3, datetime(2026, 10, 1, 9, 30))
        deleted, total = await R._prune_fund_flow(keep_per_stock=500)
        assert (deleted, total) == (0, 3)


class TestScreenerPrune:
    async def test_prunes_by_run_date_and_cascades_picks(self):
        """screener_picks 没有时间列,必须靠父表 run_date + 外键级联删。"""
        old = date.today() - timedelta(days=400)
        fresh = date.today() - timedelta(days=1)
        async with async_session() as s:
            old_run = ScreenerRun(run_date=old, pool_size=500, total_picks=1)
            fresh_run = ScreenerRun(run_date=fresh, pool_size=500, total_picks=1)
            s.add_all([old_run, fresh_run])
            await s.commit()
            s.add_all(
                [
                    ScreenerPick(
                        run_id=old_run.id,
                        rank=1,
                        stock_code="600000",
                        stock_name="浦发银行",
                        score=88.0,
                    ),
                    ScreenerPick(
                        run_id=fresh_run.id,
                        rank=1,
                        stock_code="000001",
                        stock_name="平安银行",
                        score=90.0,
                    ),
                ]
            )
            await s.commit()

        deleted = await R._prune_screener_runs(keep_days=180)

        assert deleted == 1
        async with async_session() as s:
            from sqlalchemy import select

            runs = (await s.execute(select(ScreenerRun))).scalars().all()
            picks = (await s.execute(select(ScreenerPick))).scalars().all()
        assert [r.run_date for r in runs] == [fresh]
        assert [p.stock_code for p in picks] == ["000001"]

    async def test_keeps_recent_runs(self):
        async with async_session() as s:
            s.add(ScreenerRun(run_date=date.today() - timedelta(days=3)))
            await s.commit()
        assert await R._prune_screener_runs(keep_days=180) == 0


class TestDailyAnalysisPrune:
    async def test_prunes_by_created_at(self):
        old = datetime.now() - timedelta(days=400)
        async with async_session() as s:
            s.add(
                DailyAnalysis(
                    stock_code="600000",
                    analysis_date=old.date(),
                    dimension_avg="{}",
                    top_issues="[]",
                    created_at=old,
                    updated_at=old,
                )
            )
            s.add(
                DailyAnalysis(
                    stock_code="000001",
                    analysis_date=date.today(),
                    dimension_avg="{}",
                    top_issues="[]",
                )
            )
            await s.commit()

        assert await R._prune_daily_analyses(keep_days=365) == 1

        from sqlalchemy import select

        async with async_session() as s:
            rest = (await s.execute(select(DailyAnalysis))).scalars().all()
        assert [r.stock_code for r in rest] == ["000001"]


class TestRunRetention:
    async def test_does_not_raise_when_one_table_fails(self, monkeypatch):
        """一张表炸了不能拖垮整轮裁剪 —— 否则整库永远不会被清理。"""

        async def boom(_keep: int):
            raise AttributeError("type object 'ScreenerPick' has no attribute 'created_at'")

        monkeypatch.setattr(R, "_prune_fund_flow", boom)

        async with async_session() as s:
            s.add(ScreenerRun(run_date=date.today() - timedelta(days=400)))
            await s.commit()

        stats = await R.run_retention(vacuum=False)

        # fund_flow 失败被吞掉,但 screener_runs 仍然被裁掉 1 行
        assert stats["deleted"] == 1
        assert stats["vacuumed"] == 0

    async def test_returns_declared_keys(self):
        stats = await R.run_retention(vacuum=False)
        assert set(stats) == {"deleted", "remaining", "vacuumed"}


class TestVacuumDecision:
    """VACUUM 的触发条件:空闲页够多 **且** 占比够高。"""

    def test_big_free_space_triggers(self):
        # 411MB 级别的库:105305 页里 105148 页空闲
        assert R._needs_vacuum(105148, 105305) is True

    def test_small_free_space_does_not_trigger(self):
        assert R._needs_vacuum(10, 500) is False

    def test_moderate_free_space_but_low_ratio_does_not_trigger(self):
        # 5000 页空闲,但整库 40 万页 → 占比 1.25%,不值得 VACUUM 一次
        assert R._needs_vacuum(5000, 400_000) is False

    def test_free_space_just_over_threshold_with_zero_pages(self):
        assert R._needs_vacuum(2500, 0) is True
