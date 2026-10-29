"""全市场选股与滚动池的**纯函数**层(作战计划 v2)

设计约束(与项目既有判定层一致):
- **零 IO、零 LLM、零 DB** —— 输入全是已取好的数据,输出是决策
- **缺数据 → None / 降级**,绝不编数字
- 每个函数都能被单测钉死

三个层次:
1. universe 闸门:`filter_universe` —— 快照级 O(N) 过滤
2. 指标:`calc_volume_ratio` / `calc_consecutive_up_days` / `calc_max_drop_pct_5d`
3. 池记忆:`select_pool` —— 带幂等键的滚动池选择
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from app.core.config import (
    POOL_LIMIT,
    POOL_MIN_AMOUNT_YI,
    POOL_MISS_THRESHOLD,
    POOL_NEW_LISTING_TRADING_DAYS,
)
from app.core.stock_code import is_main_board

# 达成预期 = 触及或执行(用户口径:触及即算)
STATUS_MET = ("touched", "executed")
# 未达预期 = 当日没碰到触发位
STATUS_MISS = "missed"
# 不计入连续天数(没数据 / 不适用 / 还没判)
STATUS_NEUTRAL = ("no_data", "n_a", "pending")


# ============================================================
# === 1. universe 闸门 ===
# ============================================================


def is_st_name(name: str | None) -> bool:
    """是否 ST / *ST / SST 风险警示股(**前缀**判定)

    ⚠️ 为什么不用 `"ST" in name.upper()`:
    那会把名字里含 "ST" 的普通票一起误杀(如 `STONE` / `STAR`)。
    真实 ST 股的名字形态是**前缀**:`STxx` / `*STxx` / `SSTxx`。

    ⚠️ 为什么"ST 后面接汉字"要放过:
    `ST中安` 是真实 ST 股名。`"中".isalpha()` 在 Python 里是 True,
    若用 `isalpha()` 判"后面是不是英文字母"会漏判 → 必须用 `isascii()`。
    """
    if not name:
        return False
    n = str(name).strip().upper().replace(" ", "").lstrip("*")
    if n.startswith("SST"):
        n = n[1:]  # SST → ST
    if not n.startswith("ST"):
        return False
    rest = n[2:]
    # 后面接**ASCII 字母** → 不是风险警示标记(STONE / STAR)
    return not (rest and rest[0].isascii() and rest[0].isalpha())


@dataclass(frozen=True)
class UniverseStats:
    """universe 各级过滤的通过量(出参给前端看口径)"""

    total: int = 0          # 快照全量
    main_board: int = 0     # 过了板块闸门
    non_st: int = 0         # 再过了 ST 闸门
    after_filters: int = 0  # 再过了成交额闸门 = 最终候选数
    min_amount_yi: float = POOL_MIN_AMOUNT_YI

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "main_board": self.main_board,
            "non_st": self.non_st,
            "after_filters": self.after_filters,
            "min_amount_yi": self.min_amount_yi,
        }


def _f(v: Any) -> float | None:
    """转 float;非有限值一律当无效(与项目其它判定层口径一致)"""
    try:
        if v is None:
            return None
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def filter_universe(
    rows: list[dict[str, Any]] | None,
    min_amount_yi: float = POOL_MIN_AMOUNT_YI,
) -> tuple[list[dict[str, Any]], UniverseStats]:
    """快照级 universe 过滤 + 按成交额降序排序(纯函数)

    三道闸门(顺序即成本从低到高):
    1. **板块**:只留沪深主板(排除北交所 / 创业板 / 科创板)
    2. **ST**:剔除 ST / *ST / SST
    3. **成交额**:`amount_yi >= min_amount_yi`(默认 1 亿)

    返回 `(候选列表, 统计)`;候选已按成交额降序排好。
    """
    total = len(rows or [])
    main_board = 0
    non_st = 0
    kept: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if not is_main_board(str(r.get("code") or "")):
            continue
        main_board += 1
        if is_st_name(r.get("name")):
            continue
        non_st += 1
        amount = _f(r.get("amount_yi"))
        if amount is None or amount < min_amount_yi:
            continue
        kept.append(r)

    stats = UniverseStats(
        total=total,
        main_board=main_board,
        non_st=non_st,
        after_filters=len(kept),
        min_amount_yi=min_amount_yi,
    )
    kept.sort(key=lambda r: (_f(r.get("amount_yi")) or 0.0), reverse=True)
    return kept, stats


# ============================================================
# === 2. K 线派生指标(与 screener 同源口径的本地实现) ===
# ============================================================


def calc_volume_ratio(klines: list[dict[str, Any]] | None) -> float:
    """量比 = 最新一根成交量 ÷ 前 5 根均量(**同源**)

    ⚠️ **同源**是刻意的:screener 用「腾讯 quote 的当日量 ÷ 新浪 K 线近 5 日均量」,
    跨源 —— 两者单位一旦不一致就会算出假量比。本模块统一取**同一份日 K**。

    ⚠️ 盘中生成时,日 K 的最后一根还是**上一交易日**(收盘后才写入当日 bar),
    此时量比是「上一交易日量 ÷ 其前 5 日均量」,不是「当日量比」。
    """
    vols: list[int] = []
    for k in klines or []:
        if not isinstance(k, dict):
            continue
        try:
            vols.append(int(k.get("volume") or 0))
        except (TypeError, ValueError):
            vols.append(0)
    if len(vols) < 2:
        return 0.0
    base = [v for v in vols[-6:-1] if v > 0]
    if not base:
        return 0.0
    avg = sum(base) / len(base)
    if avg <= 0:
        return 0.0
    return float(vols[-1]) / avg


def calc_consecutive_up_days(klines: list[dict[str, Any]] | None) -> int:
    """连续上涨天数(从最新一根往回数,close > 前一根 close 才算)"""
    ks = [k for k in (klines or []) if isinstance(k, dict)]
    if len(ks) < 2:
        return 0
    days = 0
    for i in range(len(ks) - 1, 0, -1):
        cur = _f(ks[i].get("close"))
        prev = _f(ks[i - 1].get("close"))
        if cur is None or prev is None or cur <= prev:
            break
        days += 1
    return days


def calc_max_drop_pct_5d(klines: list[dict[str, Any]] | None) -> float:
    """近 5 日最大跌幅(%,负数表示下跌)—— 避雷过滤用"""
    ks = [k for k in (klines or []) if isinstance(k, dict)]
    if len(ks) < 6:
        return 0.0
    last5 = ks[-5:]
    base = _f(last5[0].get("close"))
    cur = _f(last5[-1].get("close"))
    if base is None or cur is None or base <= 0:
        return 0.0
    return (cur / base - 1) * 100


def is_new_listing(
    kline_count: int,
    threshold: int = POOL_NEW_LISTING_TRADING_DAYS,
) -> bool:
    """是否次新股(上市不足 threshold 个交易日)

    判定依据 = 日 K 的**实际根数**:新浪返回的是「上市以来全部日 K」,
    不足 threshold 根即上市不足 threshold 个交易日。

    ⚠️ K 线缓存不会破坏这个判定:缓存里存的是**实际根数**
    (新股最多存 40 根,不会被"请求 60 根"撑成 60)。
    """
    return int(kline_count or 0) < threshold


# ============================================================
# === 3. 滚动池(带记忆的选股) ===
# ============================================================


@dataclass(frozen=True)
class PoolMember:
    """池成员状态(来自 `battle_plan_pool` 表)"""

    stock_code: str
    stock_name: str | None = None
    miss_streak: int = 0
    last_evaluated_on: str | None = None
    last_status: str | None = None
    last_score: float | None = None
    joined_on: str = ""


@dataclass(frozen=True)
class Candidate:
    """精排候选(Stage B 的 4 因子结果)"""

    stock_code: str
    stock_name: str | None = None
    score: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class PoolPick:
    """池内选中的一只(含给用户看的原因)"""

    stock_code: str
    stock_name: str | None
    state: str            # kept(保留) | added(新补位)
    score: float | None
    reason: str
    miss_streak: int
    last_status: str | None
    streak_note: str


@dataclass(frozen=True)
class DroppedPick:
    """被剔除的一只"""

    stock_code: str
    stock_name: str | None
    miss_streak: int
    reason: str


@dataclass(frozen=True)
class PoolDecision:
    """一次选池的完整结论"""

    picks: list[PoolPick]
    dropped: list[DroppedPick]
    members: list[dict[str, Any]]   # 落库用的最终状态
    candidates_considered: int = 0
    degraded: bool = False
    degraded_reason: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        """给 `meta.pool` 用的出参"""
        return {
            "limit": POOL_LIMIT,
            "members": [
                {
                    "stock_code": p.stock_code,
                    "stock_name": p.stock_name,
                    "score": p.score,
                    "reason": p.reason,
                    "state": p.state,
                    "miss_streak": p.miss_streak,
                    "last_status": p.last_status,
                    "streak_note": p.streak_note,
                }
                for p in self.picks
            ],
            "dropped": [
                {
                    "stock_code": d.stock_code,
                    "stock_name": d.stock_name,
                    "miss_streak": d.miss_streak,
                    "reason": d.reason,
                }
                for d in self.dropped
            ],
            "candidates_considered": self.candidates_considered,
        }


def _streak_note(status: str | None, miss_streak: int) -> str:
    """给人看的「这只为什么还在池里」"""
    if status == "executed":
        return "昨日已执行 → 继续关注"
    if status == "touched":
        return "昨日已触及触发位 → 继续关注"
    if status == STATUS_MISS:
        return f"昨日未达预期(连续 {miss_streak} 天)"
    if status == "no_data":
        return "昨日未判定 → 不计入连续天数"
    if status == "n_a":
        return "昨日不适用 → 不计入连续天数"
    if status == "pending":
        return "昨日尚未判定 → 不计入连续天数"
    return "昨日无预案记录 → 不计入连续天数"


def select_pool(
    pool_state: list[PoolMember] | None,
    prev_fulfillment: dict[str, str] | None = None,
    ranked_candidates: list[Candidate] | None = None,
    watchlist_codes: set[str] | None = None,
    limit: int = POOL_LIMIT,
    miss_threshold: int = POOL_MISS_THRESHOLD,
    evaluated_on: str = "",
) -> PoolDecision:
    """滚动池选择(**纯函数** —— 这是整个滚动池的记忆核心)

    规则(顺序即语义):

    1. **更新连续未达预期天数**(`miss_streak`)
       - `touched` / `executed` → 归零(达到预期 → 继续关注)
       - `missed` → +1
       - `no_data` / `n_a` / `pending` / 无记录 → **不变**
         (不因缺数据惩罚股票 —— 「没判定」不是「没兑现」)
    2. **剔除**:`miss_streak >= miss_threshold` → 移出池
    3. **占席**:保留成员按当前得分降序,最多占 `limit` 席
    4. **补位**:空席从 `ranked_candidates` 取,跳过
       ①已在池 ②本次被剔除的 ③**已在自选**的(自选单独覆盖,不重复占席)
    5. **席位不足**:如实披露,不硬凑、不放宽排除规则

    **幂等**:`evaluated_on` 是幂等键 —— 若某成员的 `last_evaluated_on` 已等于
    它,说明今天已经判过,本次**不重复累计** `miss_streak`
    (同一天重复生成日报,连续天数不会从 3 变成 4)。
    """
    members_in = list(pool_state or [])
    prev = dict(prev_fulfillment or {})
    cands = list(ranked_candidates or [])
    watch = set(watchlist_codes or ())

    score_by_code = {c.stock_code: c.score for c in cands}
    name_by_code = {c.stock_code: c.stock_name for c in cands}

    # ---- 1. 更新计数(幂等) ----
    updated: list[tuple[PoolMember, str | None]] = []
    for m in members_in:
        if evaluated_on and m.last_evaluated_on == evaluated_on:
            # 今天已判过 → 原样保留,不重复累计
            updated.append((m, m.last_status))
            continue
        status = prev.get(m.stock_code)
        streak = m.miss_streak
        if status in STATUS_MET:
            streak = 0
        elif status == STATUS_MISS:
            streak = streak + 1
        updated.append((replace(m, miss_streak=streak), status))

    # ---- 2. 剔除 ----
    kept: list[tuple[PoolMember, str | None]] = []
    dropped: list[DroppedPick] = []
    for m, status in updated:
        if m.miss_streak >= miss_threshold:
            dropped.append(
                DroppedPick(
                    stock_code=m.stock_code,
                    stock_name=m.stock_name,
                    miss_streak=m.miss_streak,
                    reason=f"连续 {m.miss_streak} 天未达预期,已剔除出池",
                )
            )
        else:
            kept.append((m, status))

    # ---- 3. 占席(按当前得分降序;同分保持原顺序 —— sort 稳定) ----
    kept.sort(
        key=lambda pair: (
            score_by_code.get(pair[0].stock_code, pair[0].last_score or 0.0),
            pair[0].stock_code,
        ),
        reverse=True,
    )
    kept = kept[:limit]

    # ---- 4. 补位 ----
    picked_codes = {m.stock_code for m, _ in kept}
    dropped_codes = {d.stock_code for d in dropped}
    fills: list[Candidate] = []
    for c in cands:
        if len(kept) + len(fills) >= limit:
            break
        if c.stock_code in picked_codes or c.stock_code in dropped_codes:
            continue
        if c.stock_code in watch:
            continue  # 自选单独覆盖,不重复占席
        fills.append(c)

    # ---- 5. 组装 ----
    picks: list[PoolPick] = []
    for m, status in kept:
        score = score_by_code.get(m.stock_code, m.last_score)
        picks.append(
            PoolPick(
                stock_code=m.stock_code,
                stock_name=m.stock_name or name_by_code.get(m.stock_code),
                state="kept",
                score=score,
                reason=_member_reason(m, score),
                miss_streak=m.miss_streak,
                last_status=status,
                streak_note=_streak_note(status, m.miss_streak),
            )
        )
    for c in fills:
        picks.append(
            PoolPick(
                stock_code=c.stock_code,
                stock_name=c.stock_name,
                state="added",
                score=c.score,
                reason=c.reason or f"全市场 4 因子分 {c.score:.1f}",
                miss_streak=0,
                last_status=None,
                streak_note=f"新补位 · 全市场 4 因子分 {c.score:.1f}",
            )
        )

    # ---- 6. 落库用的最终状态 ----
    out_members: list[dict[str, Any]] = []
    for p in picks:
        out_members.append(
            {
                "stock_code": p.stock_code,
                "stock_name": p.stock_name,
                "active": True,
                "joined_on": evaluated_on,
                "miss_streak": p.miss_streak,
                "last_evaluated_on": evaluated_on,
                "last_status": p.last_status,
                "last_score": p.score,
                "last_reason": p.reason,
            }
        )
    for d in dropped:
        out_members.append(
            {
                "stock_code": d.stock_code,
                "stock_name": d.stock_name,
                "active": False,
                "joined_on": "",
                "miss_streak": d.miss_streak,
                "last_evaluated_on": evaluated_on,
                "last_status": STATUS_MISS,
                "last_score": None,
                "last_reason": d.reason,
            }
        )

    # ---- 7. 席位不足 → 如实披露 ----
    degraded = False
    degraded_reason: list[str] = []
    if len(picks) < limit:
        degraded = True
        degraded_reason.append(
            f"全市场可用候选不足,滚动池实际 {len(picks)} 只(上限 {limit} 只)"
        )

    return PoolDecision(
        picks=picks,
        dropped=dropped,
        members=out_members,
        candidates_considered=len(cands),
        degraded=degraded,
        degraded_reason=degraded_reason,
    )


def _member_reason(m: PoolMember, score: float | None) -> str:
    """保留成员的入选理由"""
    if score is not None:
        return f"继续关注 · 上次 4 因子分 {score:.1f}"
    return "继续关注"


def aggregate_stock_status(statuses: list[str] | None) -> str:
    """多条预案的兑现状态 → **股票级**状态(滚动池按股票判定,不是按条)

    口径(用户选「触及即算达到预期」):
    - 有 `executed` → `executed`(按计划操作了)
    - 有 `touched`  → `touched`(价格触及了,算达到预期)
    - 有 `missed`   → `missed`(有该达到的没达到)
    - 有 `no_data`  → `no_data`(没判定,不计入连续天数)
    - 其余          → `n_a`(不计入统计)

    为什么「有 touched 就盖过 missed」:一只票有多条预案时,只要有一条
    触及了,这只票当天就**有**达到预期的动作 —— 用户选的口径是「触及即算」。
    逐条判会让「3 条里触及 1 条」的票被当成完全没达预期,连续 3 天就被剔,
    剔掉的却是「其实动过手」的票。

    ⚠️ `no_data` 不参与抢占优先级之外的惩罚:只有当一只票**所有**条目都
    没判定时,才落到 `no_data`(不累计连续天数)。
    """
    if not statuses:
        return "n_a"
    order = ("executed", "touched", "missed", "no_data")
    for key in order:
        if key in statuses:
            return key
    return "n_a"


__all__ = [
    "STATUS_MET",
    "STATUS_MISS",
    "STATUS_NEUTRAL",
    "Candidate",
    "DroppedPick",
    "PoolDecision",
    "PoolMember",
    "PoolPick",
    "UniverseStats",
    "aggregate_stock_status",
    "calc_consecutive_up_days",
    "calc_max_drop_pct_5d",
    "calc_volume_ratio",
    "filter_universe",
    "is_new_listing",
    "is_st_name",
    "select_pool",
]
