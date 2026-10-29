"""全市场滚动池(作战计划 v2)单测

覆盖四条主线:
1. **universe 闸门**:板块 / ST / 成交额 三道过滤
2. **次新股判定**:日 K 实际根数 < 60
3. **滚动池记忆**:达到预期→留池、未达预期→累计、连续 3 天→剔除、补位、**幂等**
4. **scope 合并**:截断优先级(先砍池 → 再砍关注 → 持仓永不砍)

判定层全是**纯函数**,所以这里不需要网络与数据库;只有编排层用例才打桩 IO。
"""
from __future__ import annotations

import pytest

from app.core.stock_code import is_main_board
from app.modules.stock_pool.pool_logic import (
    Candidate,
    PoolMember,
    aggregate_stock_status,
    calc_max_drop_pct_5d,
    calc_volume_ratio,
    filter_universe,
    is_new_listing,
    is_st_name,
    select_pool,
)
from app.services.battle_plan_service import _merge_scope, stock_level_fulfillment

EVAL = "2026-10-25"


# ============================================================
# === 1. 板块闸门 ===
# ============================================================


@pytest.mark.parametrize(
    "code",
    [
        "600519.SH", "601398.SH", "603259.SH", "605588.SH",
        "000001.SZ", "001979.SZ", "002415.SZ", "003816.SZ",
        "600519", "sh600519", "sz000001",
    ],
)
def test_main_board_codes_accepted(code: str) -> None:
    assert is_main_board(code) is True


@pytest.mark.parametrize(
    "code",
    [
        "300750.SZ", "301236.SZ",      # 创业板
        "688981.SH", "688111.SH",      # 科创板
        "830799.BJ", "920096.BJ", "430047.BJ",   # 北交所
        "900901.SH", "200011.SZ",      # B 股
        "12345", "", None,             # 非法
    ],
)
def test_non_main_board_codes_rejected(code: str | None) -> None:
    assert is_main_board(code) is False


# ============================================================
# === 2. ST 闸门(前缀判定,不许误杀) ===
# ============================================================


@pytest.mark.parametrize(
    "name", ["ST中安", "*ST海投", "SST前锋", "st华业", "ST 华映", "  ST明诚  "]
)
def test_st_names_detected(name: str) -> None:
    assert is_st_name(name) is True


@pytest.mark.parametrize(
    "name", ["STONE", "STAR", "海特高新", "东方财富", "特变电工", "", None]
)
def test_normal_names_not_flagged_as_st(name: str | None) -> None:
    """⚠️ `"ST" in name.upper()` 会误杀 `STONE` / `STAR` —— 必须收紧为前缀判定。

    同时 `ST中安` 这类「ST + 汉字」必须仍能识别 → 判「后面是不是英文字母」
    时只能用 `isascii()`,不能用 `isalpha()`(汉字的 isalpha() 也是 True)。
    """
    assert is_st_name(name) is False


# ============================================================
# === 3. universe 过滤 ===
# ============================================================


def _row(code: str, name: str = "某某股份", amount: float = 2.0, change: float = 1.0):
    return {
        "code": code, "name": name, "price": 10.0, "change_pct": change,
        "prev_close": 9.9, "amount_yi": amount, "volume": 1000, "limit_pct": 10.0,
    }


def test_filter_universe_applies_all_three_gates() -> None:
    rows = [
        _row("600519.SH"),                  # 主板 → 留
        _row("000001.SZ"),                  # 主板 → 留
        _row("300750.SZ"),                  # 创业板 → 剔
        _row("688981.SH"),                  # 科创板 → 剔
        _row("830799.BJ"),                  # 北交所 → 剔
        _row("600001.SH", name="ST某某"),    # ST → 剔
        _row("600002.SH", amount=0.99),     # 成交额不足 → 剔
        _row("600003.SH", amount=1.0),      # 刚好 1 亿 → 留
    ]
    kept, stats = filter_universe(rows)
    assert [r["code"] for r in kept] == ["600519.SH", "000001.SZ", "600003.SH"]
    assert stats.total == 8
    assert stats.main_board == 5
    assert stats.non_st == 4
    assert stats.after_filters == 3
    assert stats.min_amount_yi == 1.0


def test_filter_universe_sorts_by_amount_desc() -> None:
    rows = [_row("600001.SH", amount=1.5), _row("600002.SH", amount=9.0),
            _row("600003.SH", amount=3.0)]
    kept, _stats = filter_universe(rows)
    assert [r["code"] for r in kept] == ["600002.SH", "600003.SH", "600001.SH"]


# ============================================================
# === 4. 次新股 & 量比 ===
# ============================================================


def test_new_listing_threshold_is_60_trading_days() -> None:
    assert is_new_listing(59) is True
    assert is_new_listing(60) is False
    assert is_new_listing(190) is False


def test_volume_ratio_is_same_source() -> None:
    """量比 = 末根成交量 ÷ 前 5 根均量(**同源**:都取自同一份日 K)"""
    ks = [{"volume": v} for v in [100, 100, 100, 100, 100, 300]]
    assert calc_volume_ratio(ks) == pytest.approx(3.0)
    # 只有一根 → 无从判定 → 0,不是编出来的数
    assert calc_volume_ratio([{"volume": 300}]) == 0.0
    assert calc_volume_ratio([]) == 0.0


def test_max_drop_pct_5d() -> None:
    ks = [{"close": c} for c in [10.0, 10.0, 10.0, 10.0, 10.0, 8.0]]
    assert calc_max_drop_pct_5d(ks) == pytest.approx(-20.0)
    assert calc_max_drop_pct_5d([]) == 0.0


# ============================================================
# === 5. 滚动池记忆 ===
# ============================================================


def _member(code: str, streak: int = 0, evaluated: str | None = None,
            status: str | None = None, score: float | None = None) -> PoolMember:
    return PoolMember(
        stock_code=code, stock_name="测试票", miss_streak=streak,
        last_evaluated_on=evaluated, last_status=status, last_score=score,
        joined_on="2026-10-20",
    )


def _select(members, prev=None, cands=None, watch=None, limit=5, threshold=3, evaluated=EVAL):
    return select_pool(
        pool_state=members,
        prev_fulfillment=prev or {},
        ranked_candidates=cands or [],
        watchlist_codes=watch or set(),
        limit=limit,
        miss_threshold=threshold,
        evaluated_on=evaluated,
    )


def test_touched_resets_streak_and_keeps_member() -> None:
    d = _select([_member("600519.SH", streak=2)], prev={"600519.SH": "touched"})
    assert len(d.picks) == 1
    assert d.picks[0].state == "kept"
    assert d.picks[0].miss_streak == 0
    assert "继续关注" in d.picks[0].streak_note
    assert d.dropped == []


def test_executed_also_counts_as_reached() -> None:
    d = _select([_member("600519.SH", streak=2)], prev={"600519.SH": "executed"})
    assert d.picks[0].miss_streak == 0
    assert "已执行" in d.picks[0].streak_note


def test_missed_increments_streak_but_keeps_member() -> None:
    d = _select([_member("600519.SH", streak=1)], prev={"600519.SH": "missed"})
    assert len(d.picks) == 1
    assert d.picks[0].miss_streak == 2
    assert d.dropped == []
    assert "连续 2 天" in d.picks[0].streak_note


def test_three_consecutive_misses_drops_member() -> None:
    d = _select([_member("600519.SH", streak=2)], prev={"600519.SH": "missed"})
    assert d.picks == []
    assert len(d.dropped) == 1
    assert d.dropped[0].stock_code == "600519.SH"
    assert d.dropped[0].miss_streak == 3
    assert "连续 3 天" in d.dropped[0].reason


@pytest.mark.parametrize("status", ["no_data", "n_a", "pending"])
def test_undecided_status_does_not_increment_streak(status: str) -> None:
    """「没判定」不是「没兑现」—— 不因缺数据惩罚股票"""
    d = _select([_member("600519.SH", streak=2)], prev={"600519.SH": status})
    assert len(d.picks) == 1
    assert d.picks[0].miss_streak == 2


def test_missing_record_does_not_increment_streak() -> None:
    d = _select([_member("600519.SH", streak=2)], prev={})
    assert d.picks[0].miss_streak == 2


def test_dropped_slot_is_filled_from_candidates() -> None:
    cands = [Candidate("000001.SZ", "平安银行", 88.0, "量比2.1(放量)")]
    d = _select([_member("600519.SH", streak=2)], prev={"600519.SH": "missed"}, cands=cands)
    assert len(d.picks) == 1
    assert d.picks[0].stock_code == "000001.SZ"
    assert d.picks[0].state == "added"
    assert d.picks[0].miss_streak == 0
    assert "补位" in d.picks[0].streak_note
    assert len(d.dropped) == 1


def test_fill_skips_stocks_already_in_watchlist() -> None:
    """自选单独覆盖,不占池席位 → 补位时必须跳过"""
    cands = [
        Candidate("000001.SZ", "自选票", 95.0, ""),
        Candidate("000002.SZ", "候选票", 70.0, "量比2.0(放量)"),
    ]
    d = _select([], cands=cands, watch={"000001.SZ"}, limit=1)
    assert d.picks[0].stock_code == "000002.SZ"


def test_fill_does_not_re_add_dropped_member_same_day() -> None:
    """当天被剔除的票不该当天又补位回来"""
    cands = [Candidate("600519.SH", "刚被剔的", 99.0, "")]
    d = _select([_member("600519.SH", streak=2)], prev={"600519.SH": "missed"}, cands=cands)
    assert d.picks == []
    assert len(d.dropped) == 1


def test_not_enough_candidates_leaves_slot_and_degrades() -> None:
    d = _select([], cands=[])
    assert d.picks == []
    assert d.degraded is True
    assert any("候选不足" in r for r in d.degraded_reason)


def test_same_day_regeneration_does_not_double_count() -> None:
    """幂等:同一天重复生成日报,连续天数不能从 1 变成 2"""
    m = _member("600519.SH", streak=1, evaluated=EVAL, status="missed")
    d = _select([m], prev={"600519.SH": "missed"})
    assert d.picks[0].miss_streak == 1


def test_next_day_does_count_again() -> None:
    m = _member("600519.SH", streak=1, evaluated="2026-10-24", status="missed")
    d = _select([m], prev={"600519.SH": "missed"}, evaluated="2026-10-25")
    assert d.picks[0].miss_streak == 2


def test_kept_members_sorted_by_current_score() -> None:
    members = [
        _member("600001.SH", score=50.0),
        _member("600002.SH", score=90.0),
    ]
    cands = [Candidate("600002.SH", "高分", 95.0, "")]
    d = _select(members, cands=cands)
    assert [p.stock_code for p in d.picks][:2] == ["600002.SH", "600001.SH"]


# ============================================================
# === 6. 股票级兑现状态聚合 ===
# ============================================================


def test_stock_level_status_priority() -> None:
    assert aggregate_stock_status(["missed", "touched"]) == "touched"
    assert aggregate_stock_status(["missed", "executed"]) == "executed"
    assert aggregate_stock_status(["missed", "missed"]) == "missed"
    assert aggregate_stock_status(["no_data", "n_a"]) == "no_data"
    assert aggregate_stock_status([]) == "n_a"
    assert aggregate_stock_status(None) == "n_a"


def test_stock_level_fulfillment_groups_by_code() -> None:
    checked = [
        {"stock_code": "600519.SH", "fulfillment": "missed"},
        {"stock_code": "600519.SH", "fulfillment": "touched"},
        {"stock_code": "000001.SZ", "fulfillment": "missed"},
    ]
    out = stock_level_fulfillment(checked)
    assert out == {"600519.SH": "touched", "000001.SZ": "missed"}


# ============================================================
# === 7. scope 合并与截断优先级 ===
# ============================================================


def _wl(code, pos=False):
    return {"stock_code": code, "in_position": pos, "is_favorite": not pos,
            "shares": 0, "avg_cost": 0.0}


def test_merge_scope_cuts_pool_before_favorites() -> None:
    watchlist = [_wl("600001.SH", pos=True), _wl("000001.SZ")]
    picks = [Candidate("000002.SZ"), Candidate("000003.SZ")]
    scope, truncated = _merge_scope(watchlist, picks, max_scope=3)
    assert [s["stock_code"] for s in scope] == ["600001.SH", "000001.SZ", "000002.SZ"]
    assert truncated is True


def test_merge_scope_never_cuts_positions() -> None:
    watchlist = [_wl("600001.SH", pos=True), _wl("600002.SH", pos=True), _wl("000001.SZ")]
    picks = [Candidate("000002.SZ")]
    scope, truncated = _merge_scope(watchlist, picks, max_scope=2)
    codes = [s["stock_code"] for s in scope]
    assert "600001.SH" in codes and "600002.SH" in codes
    assert "000001.SZ" not in codes
    assert truncated is True


def test_merge_scope_dedups_pool_against_watchlist() -> None:
    watchlist = [_wl("600519.SH")]
    picks = [Candidate("600519.SH"), Candidate("000001.SZ")]
    scope, truncated = _merge_scope(watchlist, picks, max_scope=5)
    codes = [s["stock_code"] for s in scope]
    assert codes.count("600519.SH") == 1
    assert "000001.SZ" in codes
    assert truncated is False


def test_merge_scope_exact_limit_is_not_truncated() -> None:
    """恰好等于上限时**不算截断** —— 否则会向用户谎称「砍掉了一些票」"""
    watchlist = [_wl("600001.SH", pos=True), _wl("000001.SZ")]
    scope, truncated = _merge_scope(watchlist, [], max_scope=2)
    assert len(scope) == 2
    assert truncated is False


def test_merge_scope_default_cap_never_squeezes_out_the_pool() -> None:
    """⚠️ 自选很多时,全市场池也不能被挤掉

    用户口径:总覆盖 = 自选数 + 池 5 只(自选全覆盖,池永远有位置)。
    若沿用固定上限 20,自选 17 只时 17+5=22 > 20 → 按「先砍池尾」会把池整个砍没,
    正好违背「全市场永远有位置」这个设计前提。
    """
    watchlist = [_wl(f"6000{i:02d}.SH", pos=True) for i in range(17)]
    picks = [Candidate("000002.SZ"), Candidate("000003.SZ")]
    scope, truncated = _merge_scope(watchlist, picks)
    codes = [s["stock_code"] for s in scope]
    assert "000002.SZ" in codes and "000003.SZ" in codes
    assert len(scope) == 19          # 17 自选 + 2 池
    assert truncated is False


# ============================================================
# === 8. 编排层(打桩 IO) ===
# ============================================================


@pytest.mark.asyncio
async def test_snapshot_unavailable_keeps_existing_pool_and_marks_degraded(monkeypatch):
    """全市场快照挂了 → 池**原样保留**(记忆不能丢),并如实披露降级"""
    from app.data.market_snapshot import MarketSnapshotUnavailable
    from app.modules.stock_pool import service as sp
    from app.modules.stock_pool.repository import stock_pool_repo

    await stock_pool_repo.upsert_members([
        {"stock_code": "600519.SH", "stock_name": "贵州茅台", "active": True,
         "joined_on": "2026-10-20", "miss_streak": 0,
         "last_evaluated_on": "2026-10-24", "last_status": "touched",
         "last_score": 70.0, "last_reason": "继续关注"},
    ])

    async def _boom(*a, **kw):
        raise MarketSnapshotUnavailable("网络不通")

    monkeypatch.setattr(sp, "fetch_market_snapshot", _boom)

    degraded: list[str] = []
    result = await sp.build_market_pool(
        prev_fulfillment={"600519.SH": "touched"},
        watchlist_codes=set(),
        evaluated_on=EVAL,
        degraded=degraded,
    )
    assert [p.stock_code for p in result.decision.picks] == ["600519.SH"]
    assert any("快照" in r for r in degraded), degraded


@pytest.mark.asyncio
async def test_market_pool_ranks_candidates_and_skips_excluded_boards(monkeypatch):
    """Stage A/B:板块 / ST 被排除,主板票按 4 因子分排序后进池"""
    from app.modules.stock_pool import service as sp
    from app.services import kline_service

    rows = [
        _row("600519.SH", "贵州茅台", amount=12.0, change=4.0),
        _row("000001.SZ", "平安银行", amount=8.0, change=2.0),
        _row("300750.SZ", "宁德时代", amount=30.0, change=5.0),
        _row("600001.SH", "ST某某", amount=5.0, change=1.0),
    ]

    async def _snap(*a, **kw):
        return rows

    async def _flows(*a, **kw):
        return [{"category": "hangye_ZC39", "name": "计算机、通信和其他", "netamount_yi": 5.0}]

    async def _members(nodes):
        return {"600519.SH": "hangye_ZC39", "000001.SZ": "hangye_ZC39"}

    async def _k(code, period="daily", count=60):
        return [
            {"date": f"2026-09-{(i % 28) + 1:02d}", "close": 10.0 + i * 0.01,
             "high": 10.5, "low": 9.5, "volume": 100 if i < 59 else 300}
            for i in range(60)
        ]

    monkeypatch.setattr(sp, "fetch_market_snapshot", _snap)
    monkeypatch.setattr(sp, "get_sector_fund_flow", _flows)
    monkeypatch.setattr(sp, "fetch_sector_members", _members)
    monkeypatch.setattr(kline_service, "fetch_klines", _k)

    degraded: list[str] = []
    result = await sp.build_market_pool(
        prev_fulfillment={}, watchlist_codes=set(), evaluated_on=EVAL, degraded=degraded,
    )
    codes = [p.stock_code for p in result.decision.picks]
    assert "300750.SZ" not in codes     # 创业板被 universe 闸门剔掉
    assert "600001.SH" not in codes     # ST 被剔掉
    assert codes == ["600519.SH", "000001.SZ"]
    assert result.universe.total == 4
    assert result.universe.after_filters == 2


@pytest.mark.asyncio
async def test_pool_state_round_trip(monkeypatch):
    """池状态落库 → 读回,`miss_streak` 与 `active` 要原样保真"""
    from app.modules.stock_pool.repository import stock_pool_repo

    await stock_pool_repo.upsert_members([
        {"stock_code": "600519.SH", "stock_name": "贵州茅台", "active": True,
         "joined_on": "2026-10-20", "miss_streak": 2,
         "last_evaluated_on": "2026-10-24", "last_status": "missed",
         "last_score": 61.5, "last_reason": "继续关注"},
        {"stock_code": "000001.SZ", "stock_name": "平安银行", "active": False,
         "joined_on": "2026-10-20", "miss_streak": 3,
         "last_evaluated_on": "2026-10-24", "last_status": "missed",
         "last_score": None, "last_reason": "连续 3 天未达预期,已剔除出池"},
    ])
    active = await stock_pool_repo.list_members(active_only=True)
    assert [m["stock_code"] for m in active] == ["600519.SH"]
    assert active[0]["miss_streak"] == 2
    assert active[0]["last_score"] == 61.5

    every = await stock_pool_repo.list_members(active_only=False)
    assert len(every) == 2
    dropped = [m for m in every if not m["active"]][0]
    assert dropped["stock_code"] == "000001.SZ"
    assert dropped["miss_streak"] == 3
