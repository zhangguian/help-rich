"""四信号判定层单测(behavior_signal_service)

覆盖计划里的三个关键回归点:
1. **序列长度无关性** —— 同一份数据在 120 根与 300 根输入下,历史部分信号一致
2. **日期对齐** —— 资金流与 K 线按日期对齐,绝不按索引(错位一天是静默错误)
3. **不编数字** —— 缺数据不产出信号,降级说明写清原因
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.behavior_signal_service import (
    KIND_DISTRIBUTE,
    KIND_DIP_BUY,
    KIND_LOCK_POSITION,
    KIND_MAIN_FORCE_MOVE,
    detect_behavior_markers,
)


# ============================================================
# 造数工具
# ============================================================


def _dates(n: int, start: date = date(2026, 1, 1)) -> list[str]:
    """生成 n 个连续交易日的日期字符串(跳过周末)。"""
    out: list[str] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _flat_klines(n: int = 130, close: float = 10.0) -> list[dict]:
    """横盘 K 线:开=收=close,高低各 ±0.1,量固定。"""
    dates = _dates(n)
    return [
        {
            "date": d,
            "open": str(close),
            "high": f"{close + 0.1:.4f}",
            "low": f"{close - 0.1:.4f}",
            "close": str(close),
            "volume": 100000,
        }
        for d in dates
    ]


def _flow(
    date_: str,
    *,
    net_yi: float = 0.0,
    r0_yi: float = 0.0,
    r0x: float = 0.0,
    change_pct: float = 0.0,
    turnover: float = 3.0,
) -> dict:
    """造一条资金流(单位换算成接口口径:元 / 小数涨跌幅)。"""
    return {
        "date": date_,
        "net_amount": net_yi * 1e8,
        "r0_net": r0_yi * 1e8,
        "r0x_ratio": r0x,
        "r0_ratio": r0x,
        "turnover": turnover,
        "change_ratio": change_pct / 100,
    }


def _flows_from(rows: list[dict]) -> dict[str, dict]:
    """列表 → {date: row}(模拟 align_by_date 的结果)。"""
    return {r["date"]: r for r in rows}


# ============================================================
# 1. 主力异动
# ============================================================


class TestMainForceMove:
    def test_positive(self):
        ks = _flat_klines(130)
        # 造一根放量上涨的 K 线
        idx = 100
        ks[idx]["close"] = "10.5"
        ks[idx]["open"] = "10.0"
        ks[idx]["high"] = "10.6"
        ks[idx]["low"] = "9.95"
        ks[idx]["volume"] = 300000  # 前 5 日均量 100000 → 量比 3.0

        d = ks[idx]["date"]
        flows = _flows_from([
            _flow(d, net_yi=2.0, r0_yi=1.5, r0x=80.0, change_pct=5.0),
        ])
        result = detect_behavior_markers(ks, flows)

        hits = [m for m in result.markers if m.kind == KIND_MAIN_FORCE_MOVE]
        assert len(hits) == 1
        m = hits[0]
        assert m.date == d
        assert m.position == "aboveBar"
        assert "超大单净额" in m.reason
        # 依据里必须带实测数值
        assert "1.50" in m.reason or "+1.50" in m.reason
        assert m.metrics["r0_net_yi"] == pytest.approx(1.5)
        assert m.metrics["volume_ratio"] == pytest.approx(3.0, abs=0.01)

    def test_negative_when_r0_net_is_negative(self):
        """超大单净额为负 → 不产「主力异动」(反例)。"""
        ks = _flat_klines(130)
        idx = 100
        ks[idx]["volume"] = 300000
        d = ks[idx]["date"]
        flows = _flows_from([
            _flow(d, net_yi=2.0, r0_yi=-1.5, r0x=80.0, change_pct=5.0),
        ])
        result = detect_behavior_markers(ks, flows)
        assert not [m for m in result.markers if m.kind == KIND_MAIN_FORCE_MOVE]

    def test_negative_when_volume_not_expanded(self):
        """未放量 → 不产「主力异动」(反例)。"""
        ks = _flat_klines(130)
        idx = 100
        d = ks[idx]["date"]
        flows = _flows_from([
            _flow(d, net_yi=2.0, r0_yi=1.5, r0x=80.0, change_pct=5.0),
        ])
        result = detect_behavior_markers(ks, flows)
        assert not [m for m in result.markers if m.kind == KIND_MAIN_FORCE_MOVE]

    def test_no_flow_no_marker(self):
        """缺资金流 → 不产任何依赖资金的信号(不编数字)。"""
        ks = _flat_klines(130)
        result = detect_behavior_markers(ks, {})
        assert result.markers == []


# ============================================================
# 2. 低吸信号
# ============================================================


class TestDipBuy:
    def _setup(self):
        """造一根「主力转正 + 长下影 + 回踩 MA20 + 缩量」的 K 线。"""
        ks = _flat_klines(130, close=10.0)
        idx = 120
        ks[idx]["open"] = "9.95"
        ks[idx]["close"] = "9.90"   # 小阴
        ks[idx]["high"] = "10.0"
        ks[idx]["low"] = "9.60"    # 下影 = 9.90-9.60 = 0.30 ≥ 实体 0.05×1.5
        ks[idx]["volume"] = 80000  # 量比 0.8 → 缩量
        d = ks[idx]["date"]
        prev_d = ks[idx - 1]["date"]
        flows = _flows_from([
            _flow(prev_d, net_yi=-0.8, r0_yi=-0.5),
            _flow(d, net_yi=0.4, r0_yi=0.2),
        ])
        return ks, d, flows

    def test_positive(self):
        ks, d, flows = self._setup()
        result = detect_behavior_markers(ks, flows)
        hits = [m for m in result.markers if m.kind == KIND_DIP_BUY]
        assert len(hits) == 1
        m = hits[0]
        assert m.date == d
        assert m.position == "belowBar"
        assert "由" in m.reason and "转" in m.reason
        assert m.metrics["prev_main_net_yi"] == pytest.approx(-0.8)

    def test_negative_when_not_reverting_from_negative(self):
        """前一日主力不是负 → 不产「低吸」(反例)。"""
        ks, d, flows = self._setup()
        flows[d]["__prev__"] = flows[ks[119]["date"]]
        # 把前一日改成正
        flows[ks[119]["date"]] = _flow(
            ks[119]["date"], net_yi=1.0, r0_yi=0.8
        )
        result = detect_behavior_markers(ks, flows)
        assert not [m for m in result.markers if m.kind == KIND_DIP_BUY]


# ============================================================
# 3. 高抛信号
# ============================================================


class TestDistribute:
    def _setup(self):
        """造一根「主力转负 + 长上影 + 近 20 日高位 + 放量」的 K 线。"""
        ks = _flat_klines(130, close=10.0)
        idx = 120
        ks[idx]["open"] = "10.05"
        ks[idx]["close"] = "10.0"   # 小阴
        ks[idx]["high"] = "10.40"   # 上影 = 10.40-10.05 = 0.35 ≥ 实体 0.05×1.5
        ks[idx]["low"] = "9.95"
        ks[idx]["volume"] = 300000  # 量比 3.0 → 放量
        d = ks[idx]["date"]
        flows = _flows_from([
            _flow(ks[idx - 1]["date"], net_yi=1.0, r0_yi=0.8),
            _flow(d, net_yi=-0.6, r0_yi=-0.4),
        ])
        return ks, d, flows

    def test_positive(self):
        ks, d, flows = self._setup()
        result = detect_behavior_markers(ks, flows)
        hits = [m for m in result.markers if m.kind == KIND_DISTRIBUTE]
        assert len(hits) == 1
        m = hits[0]
        assert m.date == d
        assert m.position == "aboveBar"
        assert "距近" in m.reason

    def test_negative_when_not_at_high(self):
        """不在高位(价格远低于窗口高点)→ 不产「高抛」(反例)。"""
        ks, d, flows = self._setup()
        # 把之前的高点抬到 20.0,当前 10.0 → 距高点 50%,超阈值
        for i in range(100, 120):
            ks[i]["close"] = "20.0"
            ks[i]["open"] = "20.0"
            ks[i]["high"] = "20.1"
            ks[i]["low"] = "19.9"
        result = detect_behavior_markers(ks, flows)
        assert not [m for m in result.markers if m.kind == KIND_DISTRIBUTE]


# ============================================================
# 4. 锁仓信号
# ============================================================


class TestLockPosition:
    def test_positive(self):
        """连续 5 日主力净流入 + 横盘 + 缩量 → 产「锁仓」。"""
        ks = _flat_klines(130, close=10.0)
        # 缩量:最后 5 根量减半
        for i in range(125, 130):
            ks[i]["volume"] = 50000
        flows = _flows_from([
            _flow(ks[i]["date"], net_yi=0.3, r0_yi=0.2) for i in range(125, 130)
        ])
        result = detect_behavior_markers(ks, flows)
        hits = [m for m in result.markers if m.kind == KIND_LOCK_POSITION]
        assert hits, "应产出锁仓信号"
        m = hits[-1]
        assert m.date == ks[129]["date"]
        assert m.position == "belowBar"
        assert "连续 5 日" in m.reason
        assert "缩量" in m.reason

    def test_negative_when_flow_breaks(self):
        """其中一天主力转负 → 不产「锁仓」(反例)。"""
        ks = _flat_klines(130, close=10.0)
        for i in range(125, 130):
            ks[i]["volume"] = 50000
        rows = [_flow(ks[i]["date"], net_yi=0.3, r0_yi=0.2) for i in range(125, 130)]
        rows[2] = _flow(ks[127]["date"], net_yi=-0.3, r0_yi=-0.2)
        result = detect_behavior_markers(ks, _flows_from(rows))
        assert not [m for m in result.markers if m.kind == KIND_LOCK_POSITION]


# ============================================================
# 5. 序列长度无关性(计划 §4.1.5 的核心回归点)
# ============================================================


class TestSequenceLengthInvariance:
    def test_same_signals_for_120_and_300_bars(self):
        """同一只票,120 根与 300 根输入 → 历史部分信号完全一致。

        这是「找股页看到信号 → 点进个股页在图上找得到」闭环的前提。
        """
        n = 300
        ks = _flat_klines(n, close=10.0)
        idx = 200
        ks[idx]["open"] = "9.95"
        ks[idx]["close"] = "9.90"
        ks[idx]["high"] = "10.0"
        ks[idx]["low"] = "9.60"
        ks[idx]["volume"] = 80000
        d = ks[idx]["date"]
        flows = _flows_from([
            _flow(ks[idx - 1]["date"], net_yi=-0.8, r0_yi=-0.5),
            _flow(d, net_yi=0.4, r0_yi=0.2),
        ])

        full = detect_behavior_markers(ks, flows)
        short = detect_behavior_markers(ks[-120:], flows)

        full_keys = {(m.kind, m.date) for m in full.markers}
        short_keys = {(m.kind, m.date) for m in short.markers}

        # 120 根版本覆盖的是更晚的区间;两者在**重叠区间**内必须完全一致
        overlap_dates = {d for _, d in short_keys}
        full_overlap = {k for k in full_keys if k[1] in overlap_dates}
        assert full_overlap == short_keys, (
            f"重叠区间信号不一致:\n300根={sorted(full_overlap)}\n120根={sorted(short_keys)}"
        )

    def test_degraded_when_too_few_bars(self):
        """K 线不足 120 根 → 不产出任何标注,并在 degraded 说明。"""
        ks = _flat_klines(60)
        result = detect_behavior_markers(ks, {})
        assert result.markers == []
        assert result.degraded
        assert "120" in result.degraded[0]


# ============================================================
# 6. 日期对齐(计划 §2.2 的核心回归点)
# ============================================================


class TestDateAlignment:
    def test_missing_flow_day_does_not_shift(self):
        """资金流缺某一天 → 该日不产信号,且**不与相邻日错位**。

        如果实现按索引对齐,资金流会整体错位一天 →
        「主力转正」会被判到错误的日期上。
        """
        ks = _flat_klines(130, close=10.0)
        idx = 120
        ks[idx]["open"] = "9.95"
        ks[idx]["close"] = "9.90"
        ks[idx]["high"] = "10.0"
        ks[idx]["low"] = "9.60"
        ks[idx]["volume"] = 80000
        d = ks[idx]["date"]

        # 只有 idx-1 有资金流(idx 当天缺)→ idx 当天**不该**有低吸信号
        flows = _flows_from([
            _flow(ks[idx - 1]["date"], net_yi=-0.8, r0_yi=-0.5),
        ])
        result = detect_behavior_markers(ks, flows)
        assert not [m for m in result.markers if m.kind == KIND_DIP_BUY and m.date == d]

    def test_flows_sorted_descending_still_align(self):
        """资金流降序传入 → 结果与升序传入完全一致。"""
        ks = _flat_klines(130, close=10.0)
        idx = 120
        ks[idx]["open"] = "9.95"
        ks[idx]["close"] = "9.90"
        ks[idx]["high"] = "10.0"
        ks[idx]["low"] = "9.60"
        ks[idx]["volume"] = 80000
        d = ks[idx]["date"]

        rows = [
            _flow(ks[idx - 1]["date"], net_yi=-0.8, r0_yi=-0.5),
            _flow(d, net_yi=0.4, r0_yi=0.2),
        ]
        asc = detect_behavior_markers(ks, _flows_from(rows))
        desc = detect_behavior_markers(ks, _flows_from(list(reversed(rows))))
        assert [(m.kind, m.date) for m in asc.markers] == [
            (m.kind, m.date) for m in desc.markers
        ]
