"""三段式 Agent 调度器测试(阶段4)。

重点:时间窗判定的**幂等性**与**边界条件**(重复触发、周末、窗口外)。
"""
from datetime import datetime

import pytest

from app.modules.analysis.workflow_scheduler import (
    SLOT_LABEL,
    TIME_WINDOWS,
    due_windows,
    reset_fired,
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
    def test_each_window_fires_at_its_time(self, kind, hour, minute):
        now = _dt(2026, 10, 19, hour, minute)
        assert kind in due_windows(now)

    def test_no_window_outside_windows(self):
        # 10:00 不在任何窗口内
        assert due_windows(_dt(2026, 10, 19, 10, 0)) == []

    def test_weekend_skipped(self):
        # 2026-10-25 是周日
        assert due_windows(datetime(2026, 10, 25, 8, 30)) == []
        assert due_windows(datetime(2026, 10, 24, 8, 30)) == []  # 周六

    def test_idempotent_same_minute(self):
        """同一分钟内重复检查只触发一次。"""
        now = _dt(2026, 10, 19, 8, 30)
        assert "premarket" in due_windows(now)
        assert "premarket" not in due_windows(now)
        assert "premarket" not in due_windows(now)

    def test_idempotent_across_minutes_in_window(self):
        """窗口内的后续分钟不应重复触发。"""
        assert "premarket" in due_windows(_dt(2026, 10, 19, 8, 30))
        assert "premarket" not in due_windows(_dt(2026, 10, 19, 8, 35))
        assert "premarket" not in due_windows(_dt(2026, 10, 19, 8, 59))

    def test_new_day_fires_again(self):
        """隔天应重新触发。"""
        assert "premarket" in due_windows(_dt(2026, 10, 19, 8, 30))
        assert "premarket" in due_windows(_dt(2026, 10, 20, 8, 30))

    def test_boundary_minutes(self):
        """窗口起止边界都应触发;窗口结束后不再触发。"""
        for kind, h, start, end in TIME_WINDOWS:
            reset_fired()
            assert kind in due_windows(_dt(2026, 10, 19, h, start)), f"{kind} 起点应触发"
            reset_fired()
            assert kind in due_windows(_dt(2026, 10, 19, h, end)), f"{kind} 终点应触发"
            reset_fired()
            # 窗口结束后的下一个小时(同一小时内的 +1 分钟)
            if end < 59:
                assert kind not in due_windows(_dt(2026, 10, 19, h, end + 1)), (
                    f"{kind} 窗口后不应触发"
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
