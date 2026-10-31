"""盘中信号判定(纯函数、零 IO、零 LLM)。

**铁律**:缺数据 → 返回 None,**绝不编数字**。
所有判定都在这里完成,service 层只负责编排(去重 → 通知 → 落库)。

四类信号:
| kind | 名称 | 数据源 |
|---|---|---|
| `velocity_up` / `velocity_down` | 急速拉升 / 急速下跌 | 滚动窗口(2s 帧) |
| `breakout_up` / `breakout_down` | 涨幅突破 / 跌幅突破 | 现价 + 昨收 |
| `t_sell_point` / `t_buyback_point` | 已到 T 卖出点 / T 买回点 | 决策引擎 `t_plan` |
| `grid_sell_point` / `buy_point` | 已到网格卖点 / 网格买点 | 决策引擎 `grid_plan` / `actions` |
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# 判定为"样本不足"的最小帧数(2s 一帧 → 5 帧约 8 秒)
MIN_SAMPLES = 5
# 窗口至少要覆盖目标时长的这个比例才判定(否则样本太稀,涨跌幅不可信)
MIN_SPAN_RATIO = 0.6
# 突破迟滞带(百分点):回落到阈值外这么多才解除"已达突破态"
BREAKOUT_HYSTERESIS = 0.5
# 价位分桶精度(元)—— 指纹按 0.01 元分桶
LEVEL_BUCKET = 0.01


@dataclass(frozen=True, slots=True)
class Signal:
    """一条待推送的盘中信号。"""

    kind: str
    stock_code: str
    stock_name: str | None = None
    # 触发价(到价类有;斜率/突破类为 None)
    level: float | None = None
    # 触发的数值(涨跌幅 % / 窗口内涨跌幅 %)
    value: float | None = None
    title: str = ""
    body: str = ""
    # 去重指纹(同类型 + 同价位只提醒一次)
    fingerprint: str = ""
    # 该信号是否按"价位"去重(到价类为 True;斜率/突破类按冷却窗口去重)
    dedup_by_level: bool = False


@dataclass(frozen=True, slots=True)
class TriggerLevel:
    """一条"到价"触发线(来自决策引擎的**数值**价位)。"""

    kind: str
    level: float
    label: str
    basis: str = ""
    condition: str = ""


def bucket_level(level: float | None) -> str:
    """价位分桶(0.01 元)—— 同一价位用同一指纹。"""
    if level is None:
        return "na"
    return f"{round(float(level) / LEVEL_BUCKET):d}"


def _fmt_pct(value: float) -> str:
    return f"{value:+.2f}"


def _to_float(value) -> float | None:
    """宽松转 float(Decimal / str / None 都能吃);失败返回 None(**不猜**)。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_window(
    window: Sequence[tuple[float, float]], now_ts: float, window_sec: float
) -> list[tuple[float, float]]:
    """截取最近 `window_sec` 秒内的样本(按时间升序)。"""
    cutoff = now_ts - window_sec
    picked: list[tuple[float, float]] = []
    for ts, price in window:
        if ts >= cutoff:
            picked.append((ts, price))
    return picked


def detect_velocity(
    stock_code: str,
    stock_name: str | None,
    window: Sequence[tuple[float, float]],
    *,
    now_ts: float,
    window_sec: float,
    velocity_pct: float,
) -> Signal | None:
    """急速拉升 / 急速下跌。

    Args:
        window: [(ts_epoch, price), ...],按时间升序(可含 window_sec 之前的样本)
        now_ts: 当前时间戳
        window_sec: 判定窗口(秒)
        velocity_pct: 幅度阈值(%)

    样本不足(帧数 < 5 或窗口跨度 < 60% 目标时长)→ 返回 None(**不猜**)。
    """
    if window_sec <= 0 or velocity_pct <= 0:
        return None
    samples = _pick_window(window, now_ts, window_sec)
    if len(samples) < MIN_SAMPLES:
        return None
    ts0, p0 = samples[0]
    ts1, p1 = samples[-1]
    span = ts1 - ts0
    if span < window_sec * MIN_SPAN_RATIO:
        return None
    if p0 <= 0 or p1 <= 0:
        return None

    pct = (p1 / p0 - 1.0) * 100.0
    if abs(pct) < velocity_pct:
        return None

    up = pct > 0
    kind = "velocity_up" if up else "velocity_down"
    name = stock_name or stock_code
    title = f"急速{'拉升' if up else '下跌'} · {stock_code}"
    body = (
        f"{name} {span:.0f} 秒内{'涨' if up else '跌'} {abs(pct):.2f}%"
        f"(阈值 {velocity_pct:.2f}%)\n现价 {p1:.2f}"
    )
    # 斜率类不按价位去重(每次拉升的价位都不一样)→ 交给冷却窗口 + 日限流
    return Signal(
        kind=kind,
        stock_code=stock_code,
        stock_name=stock_name,
        level=None,
        value=pct,
        title=title,
        body=body,
        fingerprint=f"{kind}:{stock_code}",
        dedup_by_level=False,
    )


def detect_breakout(
    stock_code: str,
    stock_name: str | None,
    price: float | None,
    prev_close: float | None,
    *,
    up_pct: float,
    down_pct: float,
    state: str | None,
) -> tuple[Signal | None, str | None]:
    """涨幅突破 / 跌幅突破(带迟滞防抖)。

    Returns:
        (信号, 新状态)。状态为 `"up"` / `"down"` / None。
        - 状态为空:进入阈值才触发;
        - 状态为 `"up"`:只有回落到 `up_pct - 0.5` 以下才解除 → 阈值附近不刷屏。
    """
    if price is None or prev_close is None or prev_close <= 0:
        return None, state
    pct = (price / prev_close - 1.0) * 100.0

    if state == "up":
        if pct < up_pct - BREAKOUT_HYSTERESIS:
            state = None  # 回落 → 解除,下次重新突破可以再提醒
        else:
            return None, state
    elif state == "down":
        if pct > down_pct + BREAKOUT_HYSTERESIS:
            state = None
        else:
            return None, state

    name = stock_name or stock_code
    if pct >= up_pct:
        title = f"涨幅突破 · {stock_code}"
        body = (
            f"{name} 现价 {price:.2f},较昨收 {_fmt_pct(pct)}%"
            f"(突破阈值 {up_pct:+.2f}%)\n昨收 {prev_close:.2f}"
        )
        return (
            Signal(
                kind="breakout_up",
                stock_code=stock_code,
                stock_name=stock_name,
                level=None,
                value=pct,
                title=title,
                body=body,
                fingerprint=f"breakout_up:{stock_code}:{up_pct:.2f}",
                dedup_by_level=False,
            ),
            "up",
        )
    if pct <= down_pct:
        title = f"跌幅突破 · {stock_code}"
        body = (
            f"{name} 现价 {price:.2f},较昨收 {_fmt_pct(pct)}%"
            f"(跌破阈值 {down_pct:+.2f}%)\n昨收 {prev_close:.2f}"
        )
        return (
            Signal(
                kind="breakout_down",
                stock_code=stock_code,
                stock_name=stock_name,
                level=None,
                value=pct,
                title=title,
                body=body,
                fingerprint=f"breakout_down:{stock_code}:{down_pct:.2f}",
                dedup_by_level=False,
            ),
            "down",
        )
    return None, state


def detect_level_hits(
    stock_code: str,
    stock_name: str | None,
    price: float | None,
    levels: Sequence[TriggerLevel],
) -> list[Signal]:
    """到价类信号:现价触到决策引擎给的**数值**触发价。

    - 卖点(t_sell_point / grid_sell_point):现价 **≥** 触发价
    - 买点(t_buyback_point / buy_point):现价 **≤** 触发价

    触发价缺失一律跳过 —— **不用文本触发语反推价位**。
    """
    if price is None or price <= 0:
        return []
    name = stock_name or stock_code
    hits: list[Signal] = []
    for lv in levels:
        if lv.level is None:
            continue
        if lv.kind in ("t_sell_point", "grid_sell_point"):
            hit = price >= lv.level
        elif lv.kind in ("t_buyback_point", "buy_point"):
            hit = price <= lv.level
        else:
            continue
        if not hit:
            continue
        body_parts = [f"{name} 现价 {price:.2f},已到{lv.label}(触发价 {lv.level:.2f})"]
        if lv.condition:
            body_parts.append(f"条件:{lv.condition}")
        if lv.basis:
            body_parts.append(f"依据:{lv.basis}")
        hits.append(
            Signal(
                kind=lv.kind,
                stock_code=stock_code,
                stock_name=stock_name,
                level=float(lv.level),
                value=float(price),
                title=f"{lv.label} · {stock_code}",
                body="\n".join(body_parts),
                # 到价类按"同价位当日一次"去重(指纹含价位分桶)
                fingerprint=f"{lv.kind}:{stock_code}:{bucket_level(lv.level)}",
                dedup_by_level=True,
            )
        )
    return hits


def extract_trigger_levels(decision: dict | None) -> list[TriggerLevel]:
    """从决策卡里抽出「到价」触发线(全部取**数值**,绝不解析文本触发语)。

    来源(与决策卡 100% 同源 —— 同一个 `judge_t_plan` / `judge_grid_plan`):
    - `t_plan.suitable` → `t_high`(T 卖出点) / `t_low`(T 买回点)
    - `grid_plan.suitable` → `range_low`(网格买点) / `range_high`(网格卖点)
    - `actions[]` 中 `kind == "add"` 且 `price` 是数值且 `status == "armed"` → 加仓买点

    `suitable=False` 时**不产出触发线**(不替用户编一个价位),
    原因由 `extract_unsuitable_notes` 原样带出给前端看。
    """
    if not isinstance(decision, dict):
        return []
    levels: list[TriggerLevel] = []

    t_plan = decision.get("t_plan")
    if isinstance(t_plan, dict) and t_plan.get("suitable"):
        t_high = _to_float(t_plan.get("t_high"))
        t_low = _to_float(t_plan.get("t_low"))
        if t_high is not None:
            levels.append(
                TriggerLevel(
                    kind="t_sell_point",
                    level=t_high,
                    label="T 卖出点",
                    condition=str(t_plan.get("sell_trigger") or ""),
                )
            )
        if t_low is not None:
            levels.append(
                TriggerLevel(
                    kind="t_buyback_point",
                    level=t_low,
                    label="T 买回点",
                    condition=str(t_plan.get("buyback_trigger") or ""),
                )
            )

    grid_plan = decision.get("grid_plan")
    if isinstance(grid_plan, dict) and grid_plan.get("suitable"):
        range_low = _to_float(grid_plan.get("range_low"))
        range_high = _to_float(grid_plan.get("range_high"))
        grid_reason = str(grid_plan.get("reason") or "")
        if range_low is not None:
            levels.append(
                TriggerLevel(
                    kind="buy_point",
                    level=range_low,
                    label="网格买点",
                    condition=grid_reason,
                )
            )
        if range_high is not None:
            levels.append(
                TriggerLevel(
                    kind="grid_sell_point",
                    level=range_high,
                    label="网格卖点",
                    condition=grid_reason,
                )
            )

    actions = decision.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            # 只取「加仓」口径:持仓股的 entry 是空仓建仓口径,与「持仓股」不符
            if action.get("kind") != "add":
                continue
            if action.get("status") != "armed":
                continue
            price = _to_float(action.get("price"))
            if price is None:
                continue
            basis = action.get("basis")
            basis_text = " / ".join(str(b) for b in basis) if isinstance(basis, list) else ""
            levels.append(
                TriggerLevel(
                    kind="buy_point",
                    level=price,
                    label=str(action.get("label") or "加仓买点"),
                    condition=str(action.get("condition") or ""),
                    basis=basis_text,
                )
            )
    return levels


def extract_unsuitable_notes(decision: dict | None) -> list[str]:
    """抽出「今天这只票不适合做T/做网格」的原文原因(前端可见)。

    **不替用户编价位** —— 只把决策引擎自己给的原因原样带出来。
    """
    if not isinstance(decision, dict):
        return []
    notes: list[str] = []
    for key in ("t_plan", "grid_plan"):
        plan = decision.get(key)
        if not isinstance(plan, dict) or plan.get("suitable"):
            continue
        reasons = plan.get("unsuitable_signals")
        if isinstance(reasons, list):
            for reason in reasons:
                text = str(reason).strip()
                if text:
                    notes.append(f"{key}: {text}")
        reason = plan.get("reason")
        if reason:
            text = str(reason).strip()
            if text and text not in notes:
                notes.append(f"{key}: {text}")
    return notes


__all__ = [
    "BREAKOUT_HYSTERESIS",
    "LEVEL_BUCKET",
    "MIN_SAMPLES",
    "MIN_SPAN_RATIO",
    "Signal",
    "TriggerLevel",
    "bucket_level",
    "detect_breakout",
    "detect_level_hits",
    "detect_velocity",
    "extract_trigger_levels",
    "extract_unsuitable_notes",
]
