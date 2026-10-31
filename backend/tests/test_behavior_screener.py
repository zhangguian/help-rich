"""找股模块单测(behavior_screener)

覆盖:
- 纯函数层:打分、分组、排序
- 流水线:快照不可用 → 降级不崩;命中 → 落库 → /latest 能读出
- 口径诚实性:候选池各级数字真实
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.behavior_screener import logic
from app.modules.behavior_screener import service as behavior_service
from app.services.behavior_signal_service import (
    KIND_DIP_BUY,
    KIND_LOCK_POSITION,
    KIND_MAIN_FORCE_MOVE,
    BehaviorMarker,
)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _dates(n: int, start: date = date(2026, 1, 1)) -> list[str]:
    out: list[str] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ============================================================
# 纯函数层
# ============================================================


class TestScoreHit:
    def test_fresher_scores_higher(self):
        m = BehaviorMarker(
            kind=KIND_MAIN_FORCE_MOVE, date="2026-10-30", date_index=0,
            text="⚡ 主力异动", position="aboveBar", color="#f59e0b",
            reason="依据", metrics={"r0_net_yi": 2.0},
        )
        fresh = logic.score_hit(m, days_ago=0)
        older = logic.score_hit(m, days_ago=5)
        assert fresh > older

    def test_missing_metrics_neutral(self):
        """缺强度指标 → 强度系数取 1.0(不编数字)。"""
        m = BehaviorMarker(
            kind=KIND_DIP_BUY, date="2026-10-30", date_index=0,
            text="🔻 低吸信号", position="belowBar", color="#22d3ee",
            reason="依据", metrics={},
        )
        # 只吃 类型权重(1.2) × 新鲜度(1.0) × 强度(缺→1.0) × 放大倍数(100)
        assert logic.score_hit(m, days_ago=0) == pytest.approx(120.0)

    def test_score_scale_makes_difference_visible(self):
        """放大倍数的作用:分数落在可辨区间(不是 1.3 vs 1.5 这种看不出差别的数)。"""
        m = BehaviorMarker(
            kind=KIND_MAIN_FORCE_MOVE, date="2026-10-30", date_index=0,
            text="⚡ 主力异动", position="aboveBar", color="#f59e0b",
            reason="依据", metrics={"r0_net_yi": 2.0},
        )
        score = logic.score_hit(m, days_ago=0)
        assert score >= 50.0
        assert score <= 200.0


class TestMainForceStrength:
    """主力异动的连续强度系数。

    真机踩过的坑:早期版本给「强」的票**统一加到上限**,
    结果同一天所有「强」的主力异动分数完全并列(实测前 5 名全是 170.0),
    排序形同虚设。这组测试把「不并列」钉死。
    """

    def _marker(self, metrics: dict):
        return BehaviorMarker(
            kind=KIND_MAIN_FORCE_MOVE, date="2026-10-30", date_index=0,
            text="⚡ 主力异动", position="aboveBar", color="#f59e0b",
            reason="依据", metrics=metrics,
        )

    def test_just_over_threshold_scores_lower_than_strong(self):
        """刚过判定线 << 全面达到强线。"""
        weak = self._marker({
            "r0x_ratio": 65.1, "change_pct": 2.01, "volume_ratio": 1.502,
            "r0_net_yi": 1.0,
        })
        strong = self._marker({
            "r0x_ratio": 85.0, "change_pct": 10.0, "volume_ratio": 3.5,
            "r0_net_yi": 8.0,
        })
        assert logic.score_hit(weak, days_ago=1) < logic.score_hit(strong, days_ago=1)

    def test_strong_hits_do_not_tie(self):
        """同为「强」的两条也要能分先后(不能并列同分)。"""
        a = self._marker({
            "r0x_ratio": 73.0, "change_pct": 10.01, "volume_ratio": 2.82,
            "r0_net_yi": 10.2,
        })
        b = self._marker({
            "r0x_ratio": 79.4, "change_pct": 3.90, "volume_ratio": 3.89,
            "r0_net_yi": 7.36,
        })
        score_a = logic.score_hit(a, days_ago=1)
        score_b = logic.score_hit(b, days_ago=1)
        assert score_a != score_b

    def test_missing_dims_fall_back_neutral(self):
        """缺维度 → 只用剩下的维度算,不编数字也不崩。"""
        m = self._marker({"r0x_ratio": 70.0})
        assert logic.score_hit(m, days_ago=0) > 0

    def test_strength_factor_within_bounds(self):
        """强度系数恒在 [0.5, 2.0]。"""
        huge = self._marker({
            "r0x_ratio": 99.0, "change_pct": 20.0, "volume_ratio": 9.0,
            "r0_net_yi": 50.0,
        })
        factor = logic._strength_factor(huge)
        assert 0.5 <= factor <= 2.0

    def test_strength_level_is_clean_enum(self):
        """强度等级是干净枚举(不带数值)—— 等级要能当枚举用,数值单独放 note。"""
        from app.core.config import BEHAVIOR_MAIN_FORCE_STRONG_PROGRESS
        from app.services.behavior_signal_service import _main_force_strength

        level, note, progress = _main_force_strength(90.0, 8.0, 4.0, 6.0)
        assert level == "强"
        assert "主力占比" in note
        assert progress is not None and progress >= BEHAVIOR_MAIN_FORCE_STRONG_PROGRESS
        level2, note2, progress2 = _main_force_strength(66.0, 2.1, 1.6, 0.2)
        assert level2 == "一般"
        assert note2
        assert progress2 is not None and progress2 < BEHAVIOR_MAIN_FORCE_STRONG_PROGRESS

    def test_level_and_score_are_consistent(self):
        """等级与分数同源:标「强」的票分数不低于标「一般」的同类票。"""
        from app.services.behavior_signal_service import _main_force_strength

        strong_metrics = {
            "r0x_ratio": 85.0, "change_pct": 10.0, "volume_ratio": 3.5,
            "r0_net_yi": 8.0,
        }
        weak_metrics = {
            "r0x_ratio": 65.1, "change_pct": 2.01, "volume_ratio": 1.502,
            "r0_net_yi": 0.6,
        }
        level_s, _, _ = _main_force_strength(85.0, 10.0, 3.5, 8.0)
        level_w, _, _ = _main_force_strength(65.1, 2.01, 1.502, 0.6)
        assert level_s == "强" and level_w == "一般"
        assert logic.score_hit(self._marker(strong_metrics), days_ago=1) > (
            logic.score_hit(self._marker(weak_metrics), days_ago=1)
        )

    def test_freshness_has_floor(self):
        """极久远的信号不会归零(有下限)。"""
        m = BehaviorMarker(
            kind=KIND_LOCK_POSITION, date="2026-01-01", date_index=0,
            text="🔒 锁仓信号", position="belowBar", color="#a78bfa",
            reason="依据", metrics={"total_main_net_yi": 1.0},
        )
        assert logic.score_hit(m, days_ago=99) > 0


class TestSignalDayChangePct:
    """信号**当日**的涨跌幅口径。

    真机踩过的坑:早期版本把**今天**(快照)的涨跌幅显示在「信号日 10-30」
    旁边,于是同一条记录里「+0.02%」和依据里的「当日涨跌 +10.00%」互相矛盾。
    这组测试把「取信号当日」钉死。
    """

    def _klines(self):
        return [
            {"date": "2026-10-28", "close": "10.00"},
            {"date": "2026-10-29", "close": "10.50"},
            {"date": "2026-10-30", "close": "11.00"},
        ]

    def test_prefers_marker_metrics(self):
        """marker 自带 change_pct → 直接用(与依据文字逐字一致)。"""
        m = BehaviorMarker(
            kind=KIND_MAIN_FORCE_MOVE, date="2026-10-30", date_index=2,
            text="⚡ 主力异动", position="aboveBar", color="#f59e0b",
            reason="依据", metrics={"change_pct": 10.01},
        )
        assert behavior_service._signal_day_change_pct(self._klines(), m) == 10.01

    def test_falls_back_to_kline(self):
        """marker 没有 change_pct → 从 K 线算(close / 前收 - 1)。"""
        m = BehaviorMarker(
            kind=KIND_DIP_BUY, date="2026-10-30", date_index=2,
            text="🔻 低吸信号", position="belowBar", color="#22d3ee",
            reason="依据", metrics={},
        )
        # 11.00 / 10.50 - 1 = 4.76%
        assert behavior_service._signal_day_change_pct(self._klines(), m) == 4.76

    def test_returns_none_when_not_computable(self):
        """算不出 → None(前端显示 '-'),不编数字。"""
        # 日期不在 K 线里 → 拿不到前收
        missing = BehaviorMarker(
            kind=KIND_DIP_BUY, date="2026-10-27", date_index=0,
            text="🔻 低吸信号", position="belowBar", color="#22d3ee",
            reason="依据", metrics={},
        )
        assert behavior_service._signal_day_change_pct(self._klines(), missing) is None
        # 第一根没有前收
        first = BehaviorMarker(
            kind=KIND_DIP_BUY, date="2026-10-28", date_index=0,
            text="🔻 低吸信号", position="belowBar", color="#22d3ee",
            reason="依据", metrics={},
        )
        assert behavior_service._signal_day_change_pct(self._klines(), first) is None


class TestGroupAndSort:
    def _hit(self, code: str, kind: str, score: float, days: int = 0):
        return logic.SignalHit(
            stock_code=code, stock_name="测试", kind=kind,
            signal_date="2026-10-30", days_ago=days, reason="依据",
            metrics={}, score=score,
        )

    def test_groups_by_kind(self):
        hits = [
            self._hit("600519.SH", KIND_DIP_BUY, 90.0),
            self._hit("000001.SZ", KIND_MAIN_FORCE_MOVE, 80.0),
            self._hit("600036.SH", KIND_DIP_BUY, 70.0),
        ]
        groups = logic.group_hits(hits)
        kinds = [g["kind"] for g in groups]
        assert KIND_DIP_BUY in kinds
        assert KIND_MAIN_FORCE_MOVE in kinds
        dip = next(g for g in groups if g["kind"] == KIND_DIP_BUY)
        assert dip["count"] == 2
        # 组内按分数降序
        assert [p["score"] for p in dip["picks"]] == [90.0, 70.0]

    def test_empty_kinds_not_included(self):
        assert logic.group_hits([]) == []

    def test_sort_by_score_desc(self):
        hits = [
            self._hit("A", KIND_DIP_BUY, 50.0, days=1),
            self._hit("B", KIND_DIP_BUY, 90.0, days=3),
        ]
        assert [h.stock_code for h in logic.sort_hits(hits)] == ["B", "A"]


# ============================================================
# 流水线
# ============================================================


class TestScanMarket:
    async def test_snapshot_unavailable_degrades(self, monkeypatch):
        """快照不可用 → 降级返回,不抛异常、不编数字。"""
        from app.data.market_snapshot import MarketSnapshotUnavailable

        async def boom(*a, **k):
            raise MarketSnapshotUnavailable("模拟快照不可用")

        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_market_snapshot", boom
        )
        result = await behavior_service.scan_market()
        assert result.universe.total == 0
        assert result.hits == []
        assert result.degraded

    async def test_pipeline_produces_hits(self, monkeypatch):
        """粗筛 → 逐票算信号 → 命中。"""
        dates = _dates(130)
        ks = [
            {
                "date": d, "open": "10.0", "high": "10.1", "low": "9.9",
                "close": "10.0", "volume": 100000,
            }
            for d in dates
        ]
        # 造一根主力异动:放量 + 上涨 + 资金流入
        idx = 120
        ks[idx].update(
            {"open": "10.0", "close": "10.5", "high": "10.6", "low": "9.95",
             "volume": 300000}
        )
        flows = [
            {
                "date": d, "net_amount": 1.0e8, "r0_net": 1.0e8,
                "r0x_ratio": 80.0, "r0_ratio": 60.0, "turnover": 20.0,
                "change_ratio": 0.02,
            }
            for d in dates
        ]
        flows[idx]["change_ratio"] = 0.05

        snapshot = [
            {
                "code": "600519.SH", "name": "贵州茅台", "price": 10.5,
                "change_pct": 5.0, "prev_close": 10.0, "amount_yi": 50.0,
                "limit_pct": 10.0, "volume": 300000,
            }
        ]

        async def fake_snapshot(*a, **k):
            return snapshot

        async def fake_klines(code, period="daily", count=120):
            return ks

        async def fake_flows(code, count=120, **k):
            return flows

        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_market_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.kline_service.fetch_klines",
            fake_klines,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_flow_daily", fake_flows
        )

        result = await behavior_service.scan_market(date(2026, 10, 30))
        assert result.universe.total == 1
        assert result.candidates_considered == 1
        assert result.hits
        # 造数同时满足「主力异动」与「锁仓」(连续 5 日资金为正且横盘)——
        # 两者都该被命中;具体谁排前面由打分决定,这里只断言主力异动确实命中了。
        kinds = {h.kind for h in result.hits}
        assert KIND_MAIN_FORCE_MOVE in kinds
        main_hit = next(h for h in result.hits if h.kind == KIND_MAIN_FORCE_MOVE)
        assert main_hit.stock_code == "600519.SH"
        assert main_hit.reason
        # 分数降序
        scores = [h.score for h in result.hits]
        assert scores == sorted(scores, reverse=True)


class TestApi:
    def test_latest_404_when_no_run(self, client):
        """没跑过 → 404(前端据此显示「还没跑」,不是「无命中」)。"""
        resp = client.get("/api/behavior-screener/latest")
        assert resp.status_code == 404

    def test_pool_reports_universe(self, client):
        resp = client.get("/api/behavior-screener/pool")
        assert resp.status_code == 200
        data = resp.json()
        assert "universe" in data
        assert "candidates_considered" in data

    def test_runs_empty(self, client):
        resp = client.get("/api/behavior-screener/runs?days=5")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_trigger_now_requires_env(self, client, monkeypatch):
        """未开环境变量 → 403(与 screener 同口径)。"""
        monkeypatch.delenv("SCREENER_ALLOW_TRIGGER", raising=False)
        resp = client.post("/api/behavior-screener/trigger-now")
        assert resp.status_code == 403

    async def test_run_then_latest(self, client, monkeypatch):
        """跑批落库 → /latest 能读出,且按信号类型分组。"""
        from app.modules.behavior_screener import repository as repo

        hit = logic.SignalHit(
            stock_code="600519.SH", stock_name="贵州茅台",
            kind=KIND_DIP_BUY, signal_date="2026-10-28", days_ago=2,
            reason="主力净额由 -0.79 亿转 +0.39 亿", metrics={"main_net_yi": 0.39},
            score=88.0, change_pct=0.89,
        )
        run = await repo.upsert_run(
            date(2026, 10, 30),
            pool_size=5574, main_board_count=3193, non_st_count=3053,
            after_filters_count=1941, candidates_considered=120,
            total_picks=1, elapsed_sec=8.2, note=None,
        )
        await repo.replace_picks(run.id, [{**hit.to_dict(), "run_date": date(2026, 10, 30)}])

        resp = client.get("/api/behavior-screener/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run"]["pool_size"] == 5574
        assert len(data["all"]) == 1
        assert data["all"][0]["kind_label"] == "低吸信号"
        assert data["groups"]
        assert data["groups"][0]["kind"] == KIND_DIP_BUY
        assert data["groups"][0]["picks"][0]["stock_code"] == "600519.SH"


class TestRunTrustFields:
    """闸 1 / 闸 4 的批次字段:真实分类计数 + 数据时点 + 是否盘中。"""

    async def test_trust_fields_roundtrip(self):
        from app.modules.behavior_screener import repository as repo

        run = await repo.upsert_run(
            date(2026, 10, 30),
            pool_size=5574, main_board_count=3193, non_st_count=3053,
            after_filters_count=1941, candidates_considered=1817,
            total_picks=402, elapsed_sec=53.1, note=None,
            hit_counts_json='{"main_force_move": 268, "dip_buy": 96}',
            data_as_of=date(2026, 10, 30),
            is_intraday=False,
        )
        assert run.hit_counts_json == '{"main_force_move": 268, "dip_buy": 96}'
        assert run.data_as_of == date(2026, 10, 30)
        assert run.is_intraday is False

    async def test_is_intraday_defaults_none(self):
        """不传 is_intraday → None(未知),**不编成「确定不是盘中」**。"""
        from app.modules.behavior_screener import repository as repo

        run = await repo.upsert_run(
            date(2026, 10, 29),
            pool_size=1, main_board_count=1, non_st_count=1,
            after_filters_count=1, candidates_considered=1,
            total_picks=0, elapsed_sec=0.1, note=None,
        )
        assert run.is_intraday is None
        assert run.hit_counts_json is None
        assert run.data_as_of is None

    async def test_upsert_run_updates_existing_row(self):
        """同日再 upsert → **覆盖同一行**(不是新增),三字段一起被更新。

        覆盖 brief Step 6 要求的「两条分支都赋值」里的 update 分支:
        同 `run_date` 二次 upsert 必须落回同一行,且三字段被新值覆盖。
        """
        from app.modules.behavior_screener import repository as repo

        first = await repo.upsert_run(
            date(2026, 10, 28),
            pool_size=1, main_board_count=1, non_st_count=1,
            after_filters_count=1, candidates_considered=1,
            total_picks=1, elapsed_sec=0.1, note=None,
            hit_counts_json='{"main_force_move": 1}',
            data_as_of=date(2026, 10, 28),
            is_intraday=True,
        )
        second = await repo.upsert_run(
            date(2026, 10, 28),
            pool_size=2, main_board_count=2, non_st_count=2,
            after_filters_count=2, candidates_considered=2,
            total_picks=2, elapsed_sec=0.2, note=None,
            hit_counts_json='{"main_force_move": 9}',
            data_as_of=date(2026, 10, 27),
            is_intraday=False,
        )
        assert first.id == second.id
        assert second.hit_counts_json == '{"main_force_move": 9}'
        assert second.data_as_of == date(2026, 10, 27)
        assert second.is_intraday is False


class TestTrustGates:
    """闸 1(数字闸)+ 闸 2(完备闸)的落库口径。

    真机踩过的坑:旧的 `hits[:60]` 全局截断让「真实 455 条」显示成「47 条」
    (差 29 倍),且 91% 的命中人间蒸发。这组测试把「不截断 + 真实计数」钉死。

    ⚠️ **造数与期望值都是实测反推的**(2026-10-31,写计划时用真实判定层跑过):
    - 「平价 + 逐日缩量 10% + 连续主力净流入」→ 只触发 `lock_position`,
      130 根 K 线产出 **103** 条原始命中;
    - 基准日 = K 线末根 = 2026-07-01,120 日历天窗口 = 2026-03-03 起
      → 窗口内 **70** 条、窗口外 **33** 条;
    - 70 > 60(旧上限)→ 数字能证明「没被截断」。
    """

    @staticmethod
    def _lock_shape(n: int = 130):
        """造「平价 + 逐日缩量 + 连续主力净流入」的数据。

        只触发 `lock_position`:
        - `change_ratio=0.0` → 主力异动要求涨跌幅 ≥2%,不达标
        - `net_amount` 恒正 → 低吸要求「由负转正」、高抛要求「由正转负」,都不达标
        - 逐日缩量 10% → 锁仓的「期间缩量」成立
        """
        dates = _dates(n)
        vol = 100000.0
        ks, flows = [], []
        for d in dates:
            ks.append({
                "date": d, "open": "10.0", "high": "10.1", "low": "9.9",
                "close": "10.0", "volume": int(vol),
            })
            flows.append({
                "date": d, "net_amount": 1.0e8, "r0_net": 1.0e8,
                "r0x_ratio": 0.0, "r0_ratio": 0.0, "turnover": 20.0,
                "change_ratio": 0.0,
            })
            vol *= 0.9
        return dates, ks, flows

    async def test_all_hits_persisted_not_truncated(self, monkeypatch):
        """命中 70 条(> 旧上限 60)→ 全部入库,total_picks = 70。"""
        import json as _json

        dates, ks, flows = self._lock_shape(130)

        snapshot = [
            {
                "code": "600519.SH", "name": "贵州茅台", "price": 10.0,
                "change_pct": 0.0, "prev_close": 10.0, "amount_yi": 50.0,
                "limit_pct": 10.0, "volume": 100000,
            }
        ]

        async def fake_snapshot(*a, **k):
            return snapshot

        async def fake_klines(code, period="daily", count=120):
            return ks

        async def fake_flows(code, count=120, **k):
            return flows

        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_market_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.kline_service.fetch_klines",
            fake_klines,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_flow_daily", fake_flows
        )

        from app.modules.behavior_screener import repository as repo

        result = await behavior_service.run_daily_scan(date(2026, 7, 1))
        assert result is not None
        run, hits = result
        # 全部入库,不截断(70 > 旧上限 60)
        assert len(hits) == 70
        assert run.total_picks == 70
        stored = await repo.get_picks_by_run(run.id)
        assert len(stored) == 70
        # 分组真实计数已落库
        counts = _json.loads(run.hit_counts_json)
        assert counts[KIND_LOCK_POSITION] == 70
        assert sum(counts.values()) == 70

    async def test_candidate_pool_not_truncated(self, monkeypatch):
        """候选池不再取前 120 —— 全部成交额达标的票都进逐票精算。"""
        # ⚠️ 代码必须是 **6 位**:`600000 + i`,不能写成 `f"6005{i:02d}.SH"`
        # (i ≥ 100 时会变成 7 位数 → 主板判定失败 → 只过 100 只,实测踩过)
        snapshot = [
            {
                "code": f"{600000 + i:06d}.SH", "name": f"票{i}", "price": 10.0,
                "change_pct": 1.0, "prev_close": 10.0, "amount_yi": 50.0,
                "limit_pct": 10.0, "volume": 1000,
            }
            for i in range(150)
        ]

        async def fake_snapshot(*a, **k):
            return snapshot

        async def fake_klines(code, period="daily", count=120):
            return []

        async def fake_flows(code, count=120, **k):
            return []

        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_market_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.kline_service.fetch_klines",
            fake_klines,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_flow_daily", fake_flows
        )

        result = await behavior_service.scan_market(date(2026, 7, 1))
        # 150 只全部进入精算(旧版只取 120)
        assert result.candidates_considered == 150
        assert result.universe.after_filters == 150

    async def test_hits_outside_window_filtered_out(self, monkeypatch):
        """超过 120 日历天的命中不进入 hits(过滤在 scan_market 内部)。"""
        dates, ks, flows = self._lock_shape(130)

        snapshot = [
            {
                "code": "600519.SH", "name": "贵州茅台", "price": 10.0,
                "change_pct": 0.0, "prev_close": 10.0, "amount_yi": 50.0,
                "limit_pct": 10.0, "volume": 100000,
            }
        ]

        async def fake_snapshot(*a, **k):
            return snapshot

        async def fake_klines(code, period="daily", count=120):
            return ks

        async def fake_flows(code, count=120, **k):
            return flows

        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_market_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.kline_service.fetch_klines",
            fake_klines,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_flow_daily", fake_flows
        )

        result = await behavior_service.scan_market(date(2026, 7, 1))
        # 原始命中 103 条 → 窗口内 70 条(窗口外 33 条被滤掉)
        assert len(result.hits) == 70
        # 每一条都在 120 日历天窗口内
        base = date(2026, 7, 1)
        threshold = base - timedelta(days=120)
        for h in result.hits:
            assert date.fromisoformat(h.signal_date) >= threshold
        # 分组计数与命中数一致
        assert sum(result.hit_counts.values()) == 70


class TestLatestApiTruth:
    """闸 1 的 API 口径:count 必须是真实命中数,不是返回条数。"""

    async def _seed(self, repo, kind: str, n: int):
        from app.modules.behavior_screener import logic as lg

        hits = [
            lg.SignalHit(
                stock_code=f"60000{i}.SH", stock_name=f"票{i}", kind=kind,
                signal_date="2026-10-28", days_ago=2, reason="依据",
                metrics={}, score=float(100 - i),
            )
            for i in range(n)
        ]
        run = await repo.upsert_run(
            date(2026, 10, 30),
            pool_size=5574, main_board_count=3193, non_st_count=3053,
            after_filters_count=1941, candidates_considered=1817,
            total_picks=n, elapsed_sec=53.1, note=None,
            hit_counts_json=json.dumps({kind: n}),
            data_as_of=date(2026, 10, 30), is_intraday=False,
        )
        await repo.replace_picks(
            run.id, [{**h.to_dict(), "run_date": date(2026, 10, 30)} for h in hits]
        )
        return run

    async def test_group_count_is_true_hit_count(self, client):
        """真实命中 70 条 → count 报 70(即使响应只带 60 条明细)。"""
        from app.modules.behavior_screener import repository as repo

        await self._seed(repo, KIND_MAIN_FORCE_MOVE, 70)
        resp = client.get("/api/behavior-screener/latest")
        assert resp.status_code == 200
        data = resp.json()
        group = next(
            g for g in data["groups"] if g["kind"] == KIND_MAIN_FORCE_MOVE
        )
        assert group["count"] == 70          # 真实命中数
        assert len(group["picks"]) == 60     # 明细只带前 60
        assert data["run"]["total_picks"] == 70

    async def test_run_exposes_trust_fields(self, client):
        from app.modules.behavior_screener import repository as repo

        await self._seed(repo, KIND_DIP_BUY, 3)
        data = client.get("/api/behavior-screener/latest").json()
        # ⚠️ 后端出 **snake_case**;驼峰由前端 axios 拦截器转换(见 frontend/src/lib/api.ts)。
        assert data["run"]["hit_counts"] == {KIND_DIP_BUY: 3}
        assert data["run"]["data_as_of"] == "2026-10-30"
        assert data["run"]["is_intraday"] is False

    async def test_pagination_returns_next_page(self, client):
        from app.modules.behavior_screener import repository as repo

        await self._seed(repo, KIND_MAIN_FORCE_MOVE, 70)
        resp = client.get(
            "/api/behavior-screener/latest",
            params={"kind": KIND_MAIN_FORCE_MOVE, "limit": 10, "offset": 60},
        )
        assert resp.status_code == 200
        page = resp.json()["page"]
        assert page["kind"] == KIND_MAIN_FORCE_MOVE
        assert page["total"] == 70
        assert len(page["picks"]) == 10      # 60..69 共 10 条

    async def test_legacy_run_without_counts_falls_back_to_loaded_rows(self, client):
        """存量批次行(没有 hit_counts_json)→ count 回退到**已载入条数**。

        铁律「缺数据 → 回退,绝不编数字」:既不写 0,也不凭空造一个总数。
        同时钉死 R1:`is_intraday` 缺失时是 `null`(未知),**不塌缩成 false**。
        """
        from app.modules.behavior_screener import repository as repo

        hit = logic.SignalHit(
            stock_code="600519.SH", stock_name="贵州茅台", kind=KIND_DIP_BUY,
            signal_date="2026-10-28", days_ago=2, reason="依据",
            metrics={}, score=88.0,
        )
        run = await repo.upsert_run(
            date(2026, 10, 30),
            pool_size=5574, main_board_count=3193, non_st_count=3053,
            after_filters_count=1941, candidates_considered=1817,
            total_picks=1, elapsed_sec=53.1, note=None,
            # 存量行:三个新字段都没写
        )
        await repo.replace_picks(
            run.id, [{**hit.to_dict(), "run_date": date(2026, 10, 30)}]
        )
        data = client.get("/api/behavior-screener/latest").json()
        group = next(g for g in data["groups"] if g["kind"] == KIND_DIP_BUY)
        assert group["count"] == 1           # 回退到已载入条数,不是 0
        assert data["run"]["hit_counts"] == {}
        assert data["run"]["data_as_of"] is None
        assert data["run"]["is_intraday"] is None   # 未知 = null,不是 False
