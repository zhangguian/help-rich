"""K 线异动行为标注(四信号:主力异动 / 低吸 / 锁仓 / 高抛)。

**定位**:日线级别的**形态回溯标注** —— 回答「历史上某一天出现了什么可观测事实」。

与 `app/modules/signal/engine.py` 是**两回事**,不要混:
- 本模块:日线、逐日回溯、产出标注序列(给 K 线图 + 找股模块)
- `modules/signal/engine.py`:盘中实时、滚动窗口、产出推送(SSE / 桌面通知)

**铁律**(与项目既有判定层一致):
1. **缺数据 → 该信号不产出**,绝不编数字。
2. 每条信号**必须带数值依据**(`reason` 里写清实测值与阈值)。
3. 只用**当日及之前**的数据 → 可回测、可复现。
4. 文案只陈述**已发生的事实**,**不预测涨跌**(项目红线)。

**窗口口径(关键)**:
所有滑动窗口一律取「当日往前 N 根」的**尾窗**,不依赖序列起点。
配合 `BEHAVIOR_MIN_KLINE_COUNT = 120` 的下限 → 同一只票在
K 线图(300 根)与找股模块(120 根)下得出**同一批信号**,
保证「找股页看到信号 → 点进个股页在图上找得到」这一闭环成立。

**资金流与 K 线的对齐**:调用方必须**按日期字典**传入
(见 `behavior_fund_flow_service.align_by_date`),绝不按索引 zip ——
两者排序方向相反(资金流降序 / K 线升序),按索引对齐会整体错位一天。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.core.config import (
    BEHAVIOR_DIP_MAX_MA20_DEVIATION_PCT,
    BEHAVIOR_DIP_MAX_VOLUME_RATIO,
    BEHAVIOR_DIP_MIN_MAIN_NET_YI,
    BEHAVIOR_DIP_MIN_SHADOW_BODY_RATIO,
    BEHAVIOR_DISTRIBUTE_HIGH_WINDOW,
    BEHAVIOR_DISTRIBUTE_MAX_HIGH_DISTANCE_PCT,
    BEHAVIOR_DISTRIBUTE_MAX_MAIN_NET_YI,
    BEHAVIOR_DISTRIBUTE_MIN_SHADOW_BODY_RATIO,
    BEHAVIOR_DISTRIBUTE_MIN_VOLUME_RATIO,
    BEHAVIOR_LOCK_MAX_RANGE_PCT,
    BEHAVIOR_LOCK_MAX_VOLUME_RATIO,
    BEHAVIOR_LOCK_MIN_DAYS,
    BEHAVIOR_LOCK_MIN_TOTAL_NET_YI,
    BEHAVIOR_MA_WINDOW,
    BEHAVIOR_MAIN_FORCE_MIN_CHANGE_PCT,
    BEHAVIOR_MAIN_FORCE_MIN_R0X_RATIO,
    BEHAVIOR_MAIN_FORCE_MIN_VOLUME_RATIO,
    BEHAVIOR_MAIN_FORCE_STRONG_CHANGE_PCT,
    BEHAVIOR_MAIN_FORCE_STRONG_PROGRESS,
    BEHAVIOR_MAIN_FORCE_STRONG_R0_NET_YI,
    BEHAVIOR_MAIN_FORCE_STRONG_R0X_RATIO,
    BEHAVIOR_MAIN_FORCE_STRONG_VOLUME_RATIO,
    BEHAVIOR_MIN_KLINE_COUNT,
)

# ============================================================
# 信号种类与显示元数据
# ============================================================

KIND_MAIN_FORCE_MOVE = "main_force_move"
KIND_DIP_BUY = "dip_buy"
KIND_LOCK_POSITION = "lock_position"
KIND_DISTRIBUTE = "distribute"

#: 四类信号的显示元数据(前后端共用同一套 kind 值)
KIND_META: dict[str, dict[str, str]] = {
    KIND_MAIN_FORCE_MOVE: {
        "label": "主力异动",
        "emoji": "⚡",
        "position": "aboveBar",
        "color": "#f59e0b",
    },
    KIND_DIP_BUY: {
        "label": "低吸信号",
        "emoji": "🔻",
        "position": "belowBar",
        "color": "#22d3ee",
    },
    KIND_LOCK_POSITION: {
        "label": "锁仓信号",
        "emoji": "🔒",
        "position": "belowBar",
        "color": "#a78bfa",
    },
    KIND_DISTRIBUTE: {
        "label": "高抛信号",
        "emoji": "🔺",
        "position": "aboveBar",
        "color": "#f43f5e",
    },
}

#: 找股模块的信号类型顺序(前端分组展示顺序)
KIND_ORDER: tuple[str, ...] = (
    KIND_MAIN_FORCE_MOVE,
    KIND_DIP_BUY,
    KIND_LOCK_POSITION,
    KIND_DISTRIBUTE,
)


# ============================================================
# 数据结构
# ============================================================


@dataclass(frozen=True, slots=True)
class BehaviorMarker:
    """一条异动行为标注点。"""

    kind: str
    date: str          # 对应 K 线日期(YYYY-MM-DD)
    date_index: int    # 在 K 线序列中的下标
    text: str          # 显示文案(含 emoji)
    position: str      # aboveBar / belowBar
    color: str
    reason: str        # 依据文字(带实测数值)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "date": self.date,
            "date_index": self.date_index,
            "text": self.text,
            "position": self.position,
            "color": self.color,
            "reason": self.reason,
            "metrics": self.metrics,
        }


@dataclass(frozen=True, slots=True)
class BehaviorResult:
    """一次判定的完整结论。"""

    markers: list[BehaviorMarker] = field(default_factory=list)
    #: 降级说明(如「K 线不足 120 根」);空表示无降级
    degraded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "behavior_markers": [m.to_dict() for m in self.markers],
            "behavior_degraded": list(self.degraded),
        }


# ============================================================
# 基础工具
# ============================================================


def _f(value: Any) -> float | None:
    """转 float;失败或非有限值一律当无效(与项目其它判定层口径一致)。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _yi(value: float | None) -> float | None:
    """元 → 亿元(资金流接口的单位是元)。"""
    return None if value is None else value / 1e8


def _sma(values: Sequence[float | None], n: int) -> list[float | None]:
    """简单移动平均(与 `ta_service._sma` 同口径:不足 n 项为 None)。"""
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < n:
            out.append(None)
            continue
        window = values[i + 1 - n:i + 1]
        if any(v is None for v in window):
            out.append(None)
            continue
        out.append(sum(window) / n)  # type: ignore[arg-type]
    return out


def _body_and_shadows(
    o: float, h: float, low: float, c: float
) -> tuple[float, float, float]:
    """返回 (实体长度, 上影线长度, 下影线长度)。"""
    body = abs(c - o)
    upper = h - max(c, o)
    lower = min(c, o) - low
    return body, upper, lower


def _fmt_yi(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f} 亿"


def _progress(value: float | None, low: float, high: float) -> float | None:
    """把一个指标映射成「过线进度」。

    - `low` = 判定线(刚够命中) → 进度 0
    - `high` = 强线(算很强) → 进度 1
    - 超出的部分截断在 1(不奖励无限拔高)

    缺值 → 返回 None(调用方跳过该维度,**不编数字**)。
    """
    if value is None:
        return None
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (float(value) - low) / (high - low)))


def main_force_strength_progress(
    r0x_ratio: float | None,
    change_pct: float | None,
    vol_ratio: float | None,
    r0_net_yi: float | None,
) -> tuple[float | None, list[str]]:
    """主力异动的**强度进度**(0~1)与达到强线的维度说明。

    四个维度:资金参与度(主力净占比) / 价格动能(涨跌幅) / 量能(量比) /
    绝对体量(超大单净额)。每个维度算自己的「过线进度」,取**均值** ——
    取均值而不是取最大:取最大会让「只靠一个维度拔尖」的票和
    「四个维度均衡」的票并列,失真。

    ⚠️ **这是强度的单一事实来源**:展示层的「强/一般」等级与打分的
    强度系数都从这里派生 —— 否则会出现「等级写着强、分数却排在
    一般后面」的自相矛盾。

    Returns:
        `(进度均值, 达到强线的维度说明)`;四个维度全缺 → 进度为 None。
    """
    dims: tuple[tuple[str, float | None, float, float], ...] = (
        ("主力占比 {v:.0f}%", r0x_ratio, BEHAVIOR_MAIN_FORCE_MIN_R0X_RATIO,
         BEHAVIOR_MAIN_FORCE_STRONG_R0X_RATIO),
        ("涨幅 {v:.1f}%", change_pct, BEHAVIOR_MAIN_FORCE_MIN_CHANGE_PCT,
         BEHAVIOR_MAIN_FORCE_STRONG_CHANGE_PCT),
        ("量比 {v:.1f}", vol_ratio, BEHAVIOR_MAIN_FORCE_MIN_VOLUME_RATIO,
         BEHAVIOR_MAIN_FORCE_STRONG_VOLUME_RATIO),
        ("超大单净额 {v:.1f} 亿", r0_net_yi, 0.0,
         BEHAVIOR_MAIN_FORCE_STRONG_R0_NET_YI),
    )
    values: list[float] = []
    reached: list[str] = []
    for template, value, low, high in dims:
        p = _progress(value, low, high)
        if p is None:
            continue
        values.append(p)
        if p >= 1.0:
            reached.append(template.format(v=float(value)))
    if not values:
        return None, []
    return sum(values) / len(values), reached


def _main_force_strength(
    r0x_ratio: float, change_pct: float, vol_ratio: float, r0_net_yi: float
) -> tuple[str, str, float | None]:
    """主力异动的强度等级(与说明、进度分开)。

    **为什么需要分级**:真机实测(2026-10-30 全市场)显示,主力异动命中里
    绝大多数是「刚过线」的(主力占比 65.1%、涨幅 2.01%、量比 1.502),
    真正强势的(占比 85%、涨幅 10%、量比 3.9)反而被淹没在同一条长尾里 ——
    一刀切阈值**看不出谁更强**。

    分级让「命中」再分出层次:找股排序按强度排,用户一眼能看出
    「这只是刚过线」还是「这是强势异动」。

    等级由**强度进度**决定(≥ `BEHAVIOR_MAIN_FORCE_STRONG_PROGRESS` 即为强),
    与打分同源。

    Returns:
        `(等级, 说明, 进度)` —— 等级是干净枚举(`强` / `一般`),
        说明是「哪些维度过了强线」的文字。两者**不要混在一个串里**:
        等级要被当成枚举用(分组、徽标),说明只给人看。
    """
    progress, reached = main_force_strength_progress(
        r0x_ratio, change_pct, vol_ratio, r0_net_yi
    )
    if progress is None:
        return "—", "无强度数据", None
    level = "强" if progress >= BEHAVIOR_MAIN_FORCE_STRONG_PROGRESS else "一般"
    note = "、".join(reached) if reached else "仅刚过判定线"
    return level, note, progress


# ============================================================
# 主入口
# ============================================================


def detect_behavior_markers(
    klines: Sequence[dict[str, Any]],
    flows_by_date: dict[str, dict[str, Any]] | None = None,
    *,
    min_kline_count: int = BEHAVIOR_MIN_KLINE_COUNT,
) -> BehaviorResult:
    """扫描整段日 K,产出四类异动行为标注点。

    Args:
        klines: **升序**的日 K 列表(每项含 date/open/high/low/close/volume)。
        flows_by_date: `{date: 资金流行}` 字典 —— **必须按日期对齐**
            (见模块 docstring)。传 None 或缺某日 → 该日不产出依赖资金的信号。
        min_kline_count: 最少 K 线根数;不足 → 不产出任何标注,并在 degraded 说明。

    Returns:
        `BehaviorResult`;`markers` 按日期升序。
    """
    ks = [k for k in (klines or []) if isinstance(k, dict)]
    flows = flows_by_date or {}

    if len(ks) < min_kline_count:
        return BehaviorResult(
            markers=[],
            degraded=[f"behavior: K 线不足 {min_kline_count} 根(实际 {len(ks)} 根)"],
        )

    closes = [_f(k.get("close")) for k in ks]
    opens = [_f(k.get("open", k.get("close"))) for k in ks]
    highs = [_f(k.get("high")) for k in ks]
    lows = [_f(k.get("low")) for k in ks]
    volumes = [_int(k.get("volume")) for k in ks]
    dates = [str(k.get("date") or "") for k in ks]

    ma20 = _sma(closes, BEHAVIOR_MA_WINDOW)
    vol_ratio = _volume_ratio_series(volumes)

    # 「前一日资金流」由本模块**按日期自行取** —— 不依赖调用方预填 `__prev__`。
    # 理由:调用方若按索引而非按日期取「前一日」,会整体错位一天(静默错误),
    # 所以正确性必须收敛在本模块内部。
    prev_flow_by_date: dict[str, dict[str, Any]] = {}
    for idx in range(1, len(dates)):
        prev_flow = flows.get(dates[idx - 1])
        if prev_flow:
            prev_flow_by_date[dates[idx]] = prev_flow

    markers: list[BehaviorMarker] = []

    for i in range(len(ks)):
        date = dates[i]
        flow = flows.get(date)
        prev_flow = prev_flow_by_date.get(date)
        c, o, h, low = closes[i], opens[i], highs[i], lows[i]
        if c is None or o is None or h is None or low is None:
            continue
        body, upper, lower = _body_and_shadows(o, h, low, c)

        marker = _detect_main_force_move(
            i, date, flow, c, o, vol_ratio[i]
        )
        if marker:
            markers.append(marker)

        marker = _detect_dip_buy(
            i, date, flow, prev_flow, c, o, h, low, body, lower, ma20[i], vol_ratio[i]
        )
        if marker:
            markers.append(marker)

        marker = _detect_distribute(
            i, date, flow, prev_flow, c, o, h, low, body, upper,
            volumes, vol_ratio[i], closes,
        )
        if marker:
            markers.append(marker)

    # 锁仓信号:需要一段连续窗口,单独扫(产出在窗口最后一天)
    markers.extend(_detect_lock_position(ks, flows, dates, closes, volumes))

    markers.sort(key=lambda m: (m.date, m.date_index))
    return BehaviorResult(markers=markers, degraded=[])


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _volume_ratio_series(volumes: Sequence[int]) -> list[float | None]:
    """逐根量比 = 当根成交量 ÷ 前 5 根均量(尾窗,不依赖序列起点)。

    前 5 根(样本不足)→ None(不猜)。
    """
    out: list[float | None] = []
    for i in range(len(volumes)):
        if i < 5:
            out.append(None)
            continue
        base = [v for v in volumes[i - 5:i] if v > 0]
        if not base:
            out.append(None)
            continue
        avg = sum(base) / len(base)
        out.append(float(volumes[i]) / avg if avg > 0 else None)
    return out


# ============================================================
# 1. 主力异动
# ============================================================


def _detect_main_force_move(
    i: int,
    date: str,
    flow: dict[str, Any] | None,
    close: float,
    open_: float,
    vol_ratio: float | None,
) -> BehaviorMarker | None:
    """主力异动:超大单净流入 + 主力占比高 + 上涨 + 放量。"""
    if not flow:
        return None
    r0_net = _yi(_f(flow.get("r0_net")))
    r0x_ratio = _f(flow.get("r0x_ratio"))
    change_pct = _f(flow.get("change_ratio"))
    if change_pct is not None:
        # 接口的 changeratio 是小数(0.0281 = 2.81%)→ 转百分比
        change_pct = change_pct * 100
    if r0_net is None or r0x_ratio is None or change_pct is None or vol_ratio is None:
        return None

    if r0_net <= 0:
        return None
    if r0x_ratio < BEHAVIOR_MAIN_FORCE_MIN_R0X_RATIO:
        return None
    if change_pct < BEHAVIOR_MAIN_FORCE_MIN_CHANGE_PCT:
        return None
    if vol_ratio < BEHAVIOR_MAIN_FORCE_MIN_VOLUME_RATIO:
        return None

    meta = KIND_META[KIND_MAIN_FORCE_MOVE]
    strength_level, strength_note, strength_progress = _main_force_strength(
        r0x_ratio, change_pct, vol_ratio, r0_net
    )
    reason = (
        f"超大单净额 {_fmt_yi(r0_net)}；主力净占比 {r0x_ratio:.1f}%"
        f"(阈值 {BEHAVIOR_MAIN_FORCE_MIN_R0X_RATIO:.0f}%)；"
        f"当日涨跌 {change_pct:+.2f}%(阈值 {BEHAVIOR_MAIN_FORCE_MIN_CHANGE_PCT:.1f}%)；"
        f"量比 {vol_ratio:.2f}(阈值 {BEHAVIOR_MAIN_FORCE_MIN_VOLUME_RATIO:.1f})；"
        f"强度 {strength_level}({strength_note})"
    )
    return BehaviorMarker(
        kind=KIND_MAIN_FORCE_MOVE,
        date=date,
        date_index=i,
        text=f"{meta['emoji']} {meta['label']}",
        position=meta["position"],
        color=meta["color"],
        reason=reason,
        metrics={
            "r0_net_yi": round(r0_net, 3),
            "r0x_ratio": round(r0x_ratio, 2),
            "change_pct": round(change_pct, 2),
            "volume_ratio": round(vol_ratio, 3),
            "strength_level": strength_level,
            "strength_note": strength_note,
            "strength_progress": (
                round(strength_progress, 4) if strength_progress is not None else None
            ),
        },
    )


# ============================================================
# 2. 低吸信号
# ============================================================


def _detect_dip_buy(
    i: int,
    date: str,
    flow: dict[str, Any] | None,
    prev_flow: dict[str, Any] | None,
    close: float,
    open_: float,
    high: float,
    low: float,
    body: float,
    lower_shadow: float,
    ma20: float | None,
    vol_ratio: float | None,
) -> BehaviorMarker | None:
    """低吸信号:主力净额由负转正 + 下影线实体 + 回踩 MA20 + 缩量。"""
    if not flow or not isinstance(prev_flow, dict):
        return None
    net_today = _yi(_f(flow.get("net_amount")))
    if net_today is None:
        return None
    net_prev = _yi(_f(prev_flow.get("net_amount")))
    if net_prev is None:
        return None

    # 主力净额由负转正
    if not (net_prev < 0 and net_today > BEHAVIOR_DIP_MIN_MAIN_NET_YI):
        return None

    # 下影线实体:下影 ≥ 实体 × 系数(实体为 0 时只看下影是否够长)
    min_shadow = BEHAVIOR_DIP_MIN_SHADOW_BODY_RATIO * body
    if body > 0 and lower_shadow < min_shadow:
        return None
    if body == 0 and lower_shadow <= 0:
        return None

    # 回踩 MA20
    if ma20 is None or ma20 <= 0:
        return None
    deviation = abs(close - ma20) / ma20 * 100
    if deviation > BEHAVIOR_DIP_MAX_MA20_DEVIATION_PCT:
        return None

    # 缩量或平量
    if vol_ratio is None or vol_ratio > BEHAVIOR_DIP_MAX_VOLUME_RATIO:
        return None

    meta = KIND_META[KIND_DIP_BUY]
    reason = (
        f"主力净额由 {_fmt_yi(net_prev)} 转 {_fmt_yi(net_today)}；"
        f"下影 {lower_shadow:.2f} ≥ 实体 {body:.2f}×{BEHAVIOR_DIP_MIN_SHADOW_BODY_RATIO:.1f}；"
        f"收盘 {close:.2f} 回踩 MA20 {ma20:.2f}(偏离 {deviation:.2f}%，"
        f"阈值 {BEHAVIOR_DIP_MAX_MA20_DEVIATION_PCT:.1f}%)；"
        f"量比 {vol_ratio:.2f}(阈值 ≤{BEHAVIOR_DIP_MAX_VOLUME_RATIO:.1f})"
    )
    return BehaviorMarker(
        kind=KIND_DIP_BUY,
        date=date,
        date_index=i,
        text=f"{meta['emoji']} {meta['label']}",
        position=meta["position"],
        color=meta["color"],
        reason=reason,
        metrics={
            "main_net_yi": round(net_today, 3),
            "prev_main_net_yi": round(net_prev, 3),
            "lower_shadow": round(lower_shadow, 3),
            "body": round(body, 3),
            "ma20": round(ma20, 2),
            "ma20_deviation_pct": round(deviation, 2),
            "volume_ratio": round(vol_ratio, 3),
        },
    )


# ============================================================
# 3. 高抛信号
# ============================================================


def _detect_distribute(
    i: int,
    date: str,
    flow: dict[str, Any] | None,
    prev_flow: dict[str, Any] | None,
    close: float,
    open_: float,
    high: float,
    low: float,
    body: float,
    upper_shadow: float,
    volumes: Sequence[int],
    vol_ratio: float | None,
    closes: Sequence[float | None],
) -> BehaviorMarker | None:
    """高抛信号:主力净额由正转负 + 上影冲高回落 + 近 M 日高位 + 放量。"""
    if not flow or not isinstance(prev_flow, dict):
        return None
    net_today = _yi(_f(flow.get("net_amount")))
    if net_today is None:
        return None
    net_prev = _yi(_f(prev_flow.get("net_amount")))
    if net_prev is None:
        return None

    if not (net_prev > 0 and net_today < BEHAVIOR_DISTRIBUTE_MAX_MAIN_NET_YI):
        return None

    # 上影冲高回落
    min_shadow = BEHAVIOR_DISTRIBUTE_MIN_SHADOW_BODY_RATIO * body
    if body > 0 and upper_shadow < min_shadow:
        return None
    if body == 0 and upper_shadow <= 0:
        return None

    # 近 M 日高位(尾窗)
    window = closes[max(0, i - BEHAVIOR_DISTRIBUTE_HIGH_WINDOW + 1):i + 1]
    valid = [v for v in window if v is not None]
    if len(valid) < 5:
        return None
    window_high = max(valid)
    if window_high <= 0:
        return None
    distance = (window_high - close) / window_high * 100
    if distance > BEHAVIOR_DISTRIBUTE_MAX_HIGH_DISTANCE_PCT:
        return None

    # 放量
    if vol_ratio is None or vol_ratio < BEHAVIOR_DISTRIBUTE_MIN_VOLUME_RATIO:
        return None

    meta = KIND_META[KIND_DISTRIBUTE]
    reason = (
        f"主力净额由 {_fmt_yi(net_prev)} 转 {_fmt_yi(net_today)}；"
        f"上影 {upper_shadow:.2f} ≥ 实体 {body:.2f}×{BEHAVIOR_DISTRIBUTE_MIN_SHADOW_BODY_RATIO:.1f}；"
        f"收盘 {close:.2f} 距近 {BEHAVIOR_DISTRIBUTE_HIGH_WINDOW} 日高 {window_high:.2f} "
        f"仅 {distance:.2f}%(阈值 ≤{BEHAVIOR_DISTRIBUTE_MAX_HIGH_DISTANCE_PCT:.0f}%)；"
        f"量比 {vol_ratio:.2f}(阈值 {BEHAVIOR_DISTRIBUTE_MIN_VOLUME_RATIO:.1f})"
    )
    return BehaviorMarker(
        kind=KIND_DISTRIBUTE,
        date=date,
        date_index=i,
        text=f"{meta['emoji']} {meta['label']}",
        position=meta["position"],
        color=meta["color"],
        reason=reason,
        metrics={
            "main_net_yi": round(net_today, 3),
            "prev_main_net_yi": round(net_prev, 3),
            "upper_shadow": round(upper_shadow, 3),
            "body": round(body, 3),
            "window_high": round(window_high, 2),
            "high_distance_pct": round(distance, 2),
            "volume_ratio": round(vol_ratio, 3),
        },
    )


# ============================================================
# 4. 锁仓信号
# ============================================================


def _detect_lock_position(
    ks: Sequence[dict[str, Any]],
    flows: dict[str, dict[str, Any]],
    dates: Sequence[str],
    closes: Sequence[float | None],
    volumes: Sequence[int],
) -> list[BehaviorMarker]:
    """锁仓信号:连续 N 日主力净流入 + 期间横盘 + 期间缩量。

    「进易出难」:钱在持续进,股价却横着不动 → 主力锁仓。

    标注落在**窗口最后一天**(信号成立的那一刻)。
    """
    out: list[BehaviorMarker] = []
    n = len(ks)
    win = BEHAVIOR_LOCK_MIN_DAYS

    for end in range(win - 1, n):
        window_dates = dates[end - win + 1:end + 1]
        window_flows = [flows.get(d) for d in window_dates]
        if any(f is None for f in window_flows):
            continue

        nets = [_yi(_f(f.get("net_amount"))) for f in window_flows]  # type: ignore[union-attr]
        if any(v is None for v in nets):
            continue
        # 连续为正
        if not all(v > 0 for v in nets):  # type: ignore[operator]
            continue
        total_net = sum(nets)  # type: ignore[arg-type]
        if total_net < BEHAVIOR_LOCK_MIN_TOTAL_NET_YI:
            continue

        window_closes = [closes[end - win + 1:end + 1]]
        valid_closes = [v for v in window_closes[0] if v is not None]
        if len(valid_closes) < win:
            continue
        lo, hi = min(valid_closes), max(valid_closes)
        if lo <= 0:
            continue
        price_range = (hi - lo) / lo * 100
        if price_range > BEHAVIOR_LOCK_MAX_RANGE_PCT:
            continue

        # 期间缩量:窗口均量 ÷ 窗口前的 5 日均量
        prior = [v for v in volumes[end - win - 5:end - win] if v > 0]
        if not prior:
            continue
        prior_avg = sum(prior) / len(prior)
        window_vol = [v for v in volumes[end - win + 1:end + 1] if v > 0]
        if not window_vol or prior_avg <= 0:
            continue
        win_avg = sum(window_vol) / len(window_vol)
        vol_shrink = win_avg / prior_avg
        if vol_shrink > BEHAVIOR_LOCK_MAX_VOLUME_RATIO:
            continue

        meta = KIND_META[KIND_LOCK_POSITION]
        reason = (
            f"连续 {win} 日主力净流入为正，累计 {_fmt_yi(total_net)}"
            f"(阈值 {BEHAVIOR_LOCK_MIN_TOTAL_NET_YI:.1f} 亿)；"
            f"期间股价振幅 {price_range:.2f}%(阈值 ≤{BEHAVIOR_LOCK_MAX_RANGE_PCT:.0f}%，横盘)；"
            f"期间均量为前 5 日均量的 {vol_shrink:.2f} 倍"
            f"(阈值 ≤{BEHAVIOR_LOCK_MAX_VOLUME_RATIO:.1f}，缩量)"
        )
        out.append(
            BehaviorMarker(
                kind=KIND_LOCK_POSITION,
                date=dates[end],
                date_index=end,
                text=f"{meta['emoji']} {meta['label']}",
                position=meta["position"],
                color=meta["color"],
                reason=reason,
                metrics={
                    "days": win,
                    "total_main_net_yi": round(total_net, 3),
                    "price_range_pct": round(price_range, 2),
                    "volume_shrink_ratio": round(vol_shrink, 3),
                },
            )
        )
    return out


# ============================================================
# 统一窗口过滤(闸 2 完备闸)
#
# **为什么要有这个**:找股路径与 K 线路径曾经各写各的过滤 ——
# 一个按「日历天 60」、另一个按「K 线根数 120 根(= 168 日历天)」,
# **单位都不同** → 61% 的信号「找股页列出来了、K 线上找不到」(实测 405/663 条)。
#
# 把过滤收敛到**这三个纯函数**,两条路径调用同一实现,
# 一致性问题就从「靠人记住两边写对」变成「物理保证」。
#
# **单位**:一律按**日历天**。用户看到的时间语义是「3 个月前」,
# 按 K 线根数换算会出现「120 根 ≈ 168 天」这种歧义。
# ============================================================


def marker_date(marker: BehaviorMarker) -> date | None:
    """标注的日期 → `date`;不可解析 → None(**不编数字**)。"""
    raw = str(getattr(marker, "date", "") or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def filter_markers_by_window(
    markers: Sequence[BehaviorMarker],
    base_date: date,
    lookback_days: int,
) -> list[BehaviorMarker]:
    """按**日历天**过滤标注,只保留 `base_date - lookback_days` 之后(含端点)的。

    - 保留输入顺序(调用方已按日期升序)。
    - 日期不可解析的标注 → **丢弃**(无法判断是否在窗口内,不猜)。
    - `lookback_days <= 0` → 原样返回(不做过滤)。
    """
    if not markers:
        return []
    if lookback_days <= 0:
        return list(markers)
    threshold = base_date - timedelta(days=lookback_days)
    out: list[BehaviorMarker] = []
    for m in markers:
        d = marker_date(m)
        if d is None:
            continue
        if d >= threshold:
            out.append(m)
    return out


def base_date_from_klines(items: Sequence[dict[str, Any]]) -> date | None:
    """K 线序列的**末根日期**作为基准日;取不到 → None(不编数字)。"""
    if not items:
        return None
    raw = str(items[-1].get("date") or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


__all__ = [
    "KIND_DISTRIBUTE",
    "KIND_DIP_BUY",
    "KIND_LOCK_POSITION",
    "KIND_MAIN_FORCE_MOVE",
    "KIND_META",
    "KIND_ORDER",
    "BehaviorMarker",
    "BehaviorResult",
    "base_date_from_klines",
    "detect_behavior_markers",
    "filter_markers_by_window",
    "marker_date",
]
