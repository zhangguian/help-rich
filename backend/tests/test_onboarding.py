"""引导中心测试(阶段5)。

核心不变量:**进度由系统真实状态判定,不编造**。
已完成的步骤数不能超过必做步骤数;系统不可用时进度必须"低"而不是"满"。
"""
import pytest

from app.services.onboarding_service import GuideStep, OnboardingStatus, onboarding_service


class TestOnboardingStatus:
    def test_empty_is_finished(self):
        st = OnboardingStatus()
        assert st.progress_pct == 100
        assert st.finished is True

    def test_progress_counts_only_required(self):
        st = OnboardingStatus(
            steps=[
                GuideStep("a", "A", "", "", "", done=True),          # 必做,完成
                GuideStep("b", "B", "", "", "", done=False),         # 必做,未完成
                GuideStep("c", "C", "", "", "", done=True, optional=True),
            ]
        )
        assert st.required_total == 2
        assert st.required_done == 1
        assert st.progress_pct == 50
        assert st.finished is False

    def test_optional_steps_do_not_block_finish(self):
        st = OnboardingStatus(
            steps=[
                GuideStep("a", "A", "", "", "", done=True),
                GuideStep("z", "Z", "", "", "", done=False, optional=True),
            ]
        )
        assert st.finished is True
        assert st.progress_pct == 100

    def test_step_to_dict(self):
        d = GuideStep("k", "标题", "描述", "按钮", "/href", done=True).to_dict()
        assert d["key"] == "k"
        assert d["done"] is True
        assert d["action_href"] == "/href"
        assert d["optional"] is False

    def test_status_to_dict_shape(self):
        st = OnboardingStatus(steps=[GuideStep("a", "A", "", "", "", done=True)])
        d = st.to_dict()
        for k in ("steps", "progress_pct", "completed", "required_done", "required_total", "finished"):
            assert k in d


class TestOnboardingService:
    @pytest.mark.asyncio
    async def test_returns_all_known_steps(self):
        st = await onboarding_service.get_status()
        keys = [s.key for s in st.steps]
        for expected in (
            "database", "quote", "llm", "position",
            "notify", "alert", "screener", "paper", "accounts",
        ):
            assert expected in keys, f"缺少引导步骤 {expected}"

    @pytest.mark.asyncio
    async def test_database_step_is_done_in_tests(self):
        """测试库 schema 已建好,数据库步骤应当完成。"""
        st = await onboarding_service.get_status()
        db = next(s for s in st.steps if s.key == "database")
        assert db.done is True

    @pytest.mark.asyncio
    async def test_failure_degrades_to_not_done(self, monkeypatch):
        """行情源挂掉时,步骤应标记为未完成并说明原因,而不是让整个引导接口 500。"""

        class BoomQuote:
            async def get_quote(self, code):
                raise RuntimeError("行情源挂了")

        import app.services.quote_service as qs

        monkeypatch.setattr(qs, "QuoteService", BoomQuote)

        quote = await onboarding_service._step_quote()
        assert quote.done is False
        assert "行情不可用" in quote.detail

    @pytest.mark.asyncio
    async def test_get_status_survives_all_checks_failing(self, monkeypatch):
        """即便每一项检查都抛异常,get_status 仍应返回完整清单。"""

        async def boom(*args, **kwargs):
            raise RuntimeError("全挂了")

        class BoomQuoteService:
            """替身必须保留 .get_quote 方法。

            直接拿一个 async 函数替换 QuoteService 类是不行的:生产代码写的是
            `await QuoteService().get_quote(...)`,替换成函数后 `QuoteService()`
            返回的是一个未被 await 的协程,`.get_quote` 立刻 AttributeError ——
            测试虽然仍"绿",但走的是完全无关的失败路径,降级逻辑根本没被验证。
            """

            async def get_quote(self, *args, **kwargs):
                raise RuntimeError("全挂了")

        monkeypatch.setattr(
            __import__("app.services.quote_service", fromlist=["QuoteService"]),
            "QuoteService",
            BoomQuoteService,
        )
        monkeypatch.setattr(
            "app.modules.portfolio.service.get_all_positions", boom
        )

        st = await onboarding_service.get_status()
        assert len(st.steps) >= 9
        assert st.progress_pct < 100

        # 确认失败确实是「行情不可用」那条路径,而不是别的地方炸了
        quote = next(s for s in st.steps if s.key == "quote")
        assert quote.done is False
        assert "行情不可用" in quote.detail

    @pytest.mark.asyncio
    async def test_progress_never_exceeds_100(self):
        st = await onboarding_service.get_status()
        assert 0 <= st.progress_pct <= 100
        assert st.required_done <= st.required_total
