"""三段式 Agent 调度器测试(阶段4)。

重点:时间窗判定的**幂等性**与**边界条件**(重复触发、周末、窗口外)。

⚠️ 阶段 T2:`due_windows` 变成 **async**(要读交易日历 → 需要 IO),且新增
**交易日判定**(非交易日不触发)。这里把交易日历**打桩成工作日口径**
(不打桩真实网络);真实交易日历的行为由 `tests/test_workflow_scheduler.py` 覆盖。
"""
from datetime import datetime, timedelta

import pytest

from app.modules.analysis.workflow_scheduler import (
    RETRY_DEADLINE,
    SLOT_LABEL,
    TIME_WINDOWS,
    due_windows,
    mark_attempt,
    reset_fired,
)


@pytest.fixture(autouse=True)
def _stub_trading_calendar(monkeypatch):
    """把交易日历打桩成「工作日即交易日」,并阻断真实网络取数。"""
    from app.core import trading_calendar as tc
    from app.services import trading_calendar_service as tcs

    async def _ensure(force: bool = False):
        return tc.current_calendar()

    monkeypatch.setattr(tcs, "ensure_trading_calendar", _ensure)
    monkeypatch.setattr(tc, "is_trading_day", lambda d: d.weekday() < 5)
    monkeypatch.setattr(
        tc,
        "trading_days_hint",
        lambda: {
            "source": "index_kline",
            "estimated": False,
            "trade_date": "2026-10-19",
        },
    )


@pytest.fixture(autouse=True)
def _clear_fired():
    reset_fired()
    yield
    reset_fired()


def _dt(y, m, d, hh, mm, weekday=None):
    dt = datetime(y, m, d, hh, mm)
    if weekday is not None:
        # 2026-10-19 是周一;往后推 weekday 天
        dt = datetime(2026, 10, 19 + weekday, hh, mm)
    return dt


class TestDueWindows:
    @pytest.mark.parametrize(
        "kind,hour,minute",
        [(k, h, m) for k, h, m, _ in TIME_WINDOWS],
    )
    async def test_each_window_fires_at_its_time(self, kind, hour, minute):
        now = _dt(2026, 10, 19, hour, minute)
        assert kind in await due_windows(now)

    async def test_no_window_outside_windows(self):
        # 10:00 不在任何窗口内
        assert await due_windows(_dt(2026, 10, 19, 10, 0)) == []

    async def test_weekend_skipped(self):
        # 2026-10-25 是周日
        assert await due_windows(datetime(2026, 10, 25, 8, 30)) == []
        assert await due_windows(datetime(2026, 10, 24, 8, 30)) == []  # 周六

    async def test_idempotent_same_minute(self):
        """同一分钟内重复检查:**没成功产出就一直 due**;产出成功后才不再 due。

        ⚠️ 2026-10-27 契约变更:`due_windows` 不再自己标记「已跑」——
        标记只发生在**产出成功之后**(见 `mark_attempt`)。
        否则失败一次 = 当天放弃:盘中复盘最常见的失败原因就是
        「当日作战计划还没生成」,一失败这档就永远产不出来。
        """
        now = _dt(2026, 10, 19, 8, 30)
        assert "premarket" in await due_windows(now)
        assert "premarket" in await due_windows(now)
        assert "premarket" in await due_windows(now)
        # 产出成功 → 标记 → 不再 due
        mark_attempt("premarket", now, ok=True)
        assert "premarket" not in await due_windows(now)

    async def test_idempotent_across_minutes_in_window(self):
        """窗口内的后续分钟:未成功产出前一直 due;成功后不再 due。"""
        assert "premarket" in await due_windows(_dt(2026, 10, 19, 8, 30))
        assert "premarket" in await due_windows(_dt(2026, 10, 19, 8, 35))
        assert "premarket" in await due_windows(_dt(2026, 10, 19, 8, 59))
        mark_attempt("premarket", _dt(2026, 10, 19, 8, 30), ok=True)
        assert "premarket" not in await due_windows(_dt(2026, 10, 19, 8, 35))

    async def test_new_day_fires_again(self):
        """隔天应重新触发。"""
        assert "premarket" in await due_windows(_dt(2026, 10, 19, 8, 30))
        assert "premarket" in await due_windows(_dt(2026, 10, 20, 8, 30))

    async def test_boundary_minutes(self):
        """窗口起止边界都应触发;过了**补跑截止**才不再触发。

        ⚠️ 2026-10-27 契约变更:窗口 = 「触发时刻」,补跑截止 = 「放弃时刻」。
        窗口结束后(到补跑截止之前)仍然 due —— 那正是产出失败后的重试窗口。
        """
        for kind, h, start, end in TIME_WINDOWS:
            reset_fired()
            assert kind in await due_windows(_dt(2026, 10, 19, h, start)), f"{kind} 起点应触发"
            reset_fired()
            assert kind in await due_windows(_dt(2026, 10, 19, h, end)), f"{kind} 终点应触发"
            reset_fired()
            # 窗口结束后的下一分钟:仍在补跑有效期内 → 还能重试
            win_end = datetime(2026, 10, 19, h, end)
            assert kind in await due_windows(win_end + timedelta(minutes=1)), (
                f"{kind} 窗口后仍在补跑有效期内,应可重试"
            )
            reset_fired()
            # 过了补跑截止 → 放弃这一档
            dl_hour, dl_minute = RETRY_DEADLINE[kind]
            deadline = datetime(2026, 10, 19, dl_hour, dl_minute)
            assert kind not in await due_windows(deadline + timedelta(minutes=1)), (
                f"{kind} 过了补跑截止不应再触发"
            )


class TestSlotLabels:
    def test_all_windows_have_labels(self):
        for kind, _, _, _ in TIME_WINDOWS:
            assert kind in SLOT_LABEL


class TestWorkflowResult:
    def test_to_message_truncates_long_body(self):
        from app.modules.analysis.workflow import WorkflowResult

        r = WorkflowResult(
            kind="premarket",
            title="标题",
            summary="摘要",
            lines=[f"第 {i} 行" for i in range(500)],
            stock_codes=["600519.SH"],
        )
        msg = r.to_message()
        assert len(msg.body) <= 1800
        assert msg.title == "标题"

    def test_to_message_with_no_lines(self):
        from app.modules.analysis.workflow import WorkflowResult

        r = WorkflowResult(kind="intraday", title="T", summary="只有摘要", lines=[])
        assert r.to_message().body == "只有摘要"


class TestPremarketDegradation:
    @pytest.mark.asyncio
    async def test_premarket_works_without_llm(self, monkeypatch):
        """没配 LLM 时盘前简报仍能产出(只是不润色)。"""
        from app.modules.analysis import workflow as svc_mod

        svc = svc_mod.WorkflowAgentService()

        async def no_llm():
            return None

        monkeypatch.setattr("app.modules.analysis.service._get_llm", no_llm)

        result = await svc.run_premarket()
        assert result.kind == "premarket"
        assert result.summary  # 有内容
        assert isinstance(result.lines, list)


class TestDispatchDegradation:
    @pytest.mark.asyncio
    async def test_dispatch_never_raises(self, monkeypatch):
        """推送失败必须吞掉异常,不能影响工作流产出。"""
        from app.modules.analysis import workflow as svc_mod

        svc = svc_mod.WorkflowAgentService()
        result = svc_mod.WorkflowResult(
            kind="premarket", title="T", summary="S", lines=[], stock_codes=[]
        )

        async def boom(*args, **kwargs):
            raise RuntimeError("网络炸了")

        # 打到 workflow 实际调用的那个对象上。阶段6 迁移后 workflow 不再直接
        # 碰 notify 的仓储,只经由 notify_service.send_to_enabled ——
        # 所以 patch 目标也跟着从仓储换成服务。
        monkeypatch.setattr(svc_mod.notify_service, "send_to_enabled", boom)
        out = await svc.dispatch(result)
        assert out == []


class TestScreenerRepoImport:
    """回归:`screener_repo` 必须来自 screener 模块的 repository。

    历史缺陷(2026-10-22 修复):workflow 里写的是 `from app.repositories import
    screener_repo` —— 那取到的是 `app.repositories` 这个**包**(其下从来没有
    screener_repo.py,只有真正的来源 app/modules/screener/repository.py),
    于是:
      - run_premarket 的 import 在 try 内 → 被同函数 except 吞掉,「今日关注清单」
        静默消失,不报错;
      - run_intraday 的 import 在 try 外 → 调用即 ImportError,盘中扫描整条链路
        直接不可用。

    项目其余 11 处都用 `from app.modules.screener import repository as screener_repo`。
    """

    @staticmethod
    async def _seed_run():
        """播一批选股记录,让「今日关注清单」有内容可断言。"""
        from datetime import date

        from app.modules.screener import repository as screener_repo

        run = await screener_repo.upsert_run(
            run_date=date.today(),
            scoring_version="test",
            pool_size=800,
            total_picks=2,
            elapsed_sec=1.0,
            note="workflow 回归测试",
        )
        await screener_repo.replace_picks(
            run.id,
            [
                {"rank": 1, "stock_code": "600519.SH", "stock_name": "贵州茅台", "score": 88.5},
                {"rank": 2, "stock_code": "000001.SZ", "stock_name": "平安银行", "score": 77.0},
            ],
        )
        return run

    @staticmethod
    def _no_llm(monkeypatch):
        """关掉 LLM 润色,避免测试联网。"""

        async def no_llm():
            return None

        monkeypatch.setattr("app.modules.analysis.service._get_llm", no_llm)

    @pytest.mark.asyncio
    async def test_premarket_keeps_watchlist_section(self, monkeypatch):
        """用例 A:run_premarket 不抛异常,且「· 关注 」段落不能被静默吞掉。"""
        from app.modules.analysis import workflow as svc_mod

        self._no_llm(monkeypatch)
        await self._seed_run()

        svc = svc_mod.WorkflowAgentService()
        result = await svc.run_premarket()  # 修前:不抛异常,但关注清单整段丢失

        assert result.kind == "premarket"
        watch_lines = [ln for ln in result.lines if ln.startswith("· 关注 ")]
        assert watch_lines, f"「今日关注清单」被静默吞掉了,lines={result.lines!r}"
        assert any("600519.SH" in ln for ln in watch_lines)
        assert "600519.SH" in result.stock_codes

    @pytest.mark.asyncio
    async def test_intraday_does_not_raise_import_error(self, monkeypatch):
        """用例 B:run_intraday 不抛 ImportError(修前在函数开头就炸)。"""
        from app.modules.analysis import workflow as svc_mod

        self._no_llm(monkeypatch)

        svc = svc_mod.WorkflowAgentService()
        # 空库(无选股记录)→ 不取行情、不联网,只验证 import 与降级路径
        result = await svc.run_intraday("11:30")

        assert result.kind == "intraday"
        assert "11:30" in result.title
        assert result.lines  # 至少给出「暂无明显异动」等占位,不会空
