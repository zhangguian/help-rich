"""做T挂单的到价提醒自动管理。

为什么自动建:
  做T挂单最怕「价格到了没人盯着」。清单里每一条未闭合的做T腿都应该有一个到价提醒:
    反T(先卖后买)→ 跌到接回价提醒接回  → 条件 `price <= X`
    正T(先买后卖)→ 涨到卖出价提醒卖出  → 条件 `price >= X`
  方向必须跟T的方向一致 —— 反T用 <=、正T用 >=,反了就是「涨了提醒你接回、跌了提醒你卖出」。

怎么标记「这条是系统自动建的」:
  PriceAlert 没有 source / metadata 字段,只能用 name 前缀 `[做T]` 标记。
  只对带前缀的提醒做自动停用 —— 用户手工建的提醒一律不碰。

同步时机:
  GET /api/t-reminders/pending 里做(幂等)—— 打开页面即对齐,不用用户点「建提醒」。
  挂单接回/卖出后自动从清单消失 → 对应的自动提醒自动**停用**(不是删除:
  保留触发历史,将来在价格提醒页还能看到这条做过什么)。

自动提醒落在**哪一档**:
  新建的提醒建在**一档** —— 一档是最容易成交、也最该「先把这单做掉」的那一档,
  它是行动信号,不是最优价。二/三档是「愿意多等一会儿换更好价」的选择。
  **用户把自动提醒改到二档/三档,系统认**(不会被拉回一档)——
  三档摆在那里就是为了让人选,系统不该替用户改主意。
  只有当提醒的价格**不落在当前任何一档**上时(基准线变了,或被改成了档位外的自定义价),
  才把这条提醒**就地**改回一档(不新建、不停用,避免留下口径打架的旧提醒)。

  一句话:**有提醒就复用,提醒的档位由用户定;提醒跟不上了才拉回一档。**

预警提醒(到价之前的「准备区」):
  到价才响 = 没有操作空间 —— 价格可能直接穿过去。所以每条挂单**另外**建一条预警提醒:
  条件是 `price <= 预警线`(反T)/ `price >= 预警线`(正T),预警线 = 生效到价线朝基准线
  方向再退 1%(见 `t_pricing.build_pre_alert`)。

  预警提醒是**一次性**的(条件树顶层 `once: true`)—— 命中后 alert 服务自动停用它:
  进过一次准备区就不该反复提醒。价格**离开**预警区之后,清单同步会把它**重新武装**,
  这样「价格又回来了」还能再提醒一次。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.logging import logger
from app.modules.portfolio.t_pairing import DIRECTION_FORWARD
from app.modules.portfolio.t_pricing import build_pre_alert

# 自动提醒的 name 前缀 —— 认这个前缀的才归系统管
AUTO_ALERT_PREFIX = "[做T]"
# 预警提醒的 name 前缀(与上面的前缀**不重叠**:"[做T·预警]" 不是 "[做T]" 的前缀)
PRE_ALERT_PREFIX = "[做T·预警]"
# 预警提醒的 kind(进 SSE 负载,前端据此显示「预警」徽章)
PRE_ALERT_KIND = "pre_alert"

# 价格匹配容差(3 位小数的最小报价单位)
_PRICE_TOLERANCE = 0.005

# 自动提醒的限流:10 分钟冷却、一天最多 3 次 —— 反复触达没有意义,人盯不过来
_AUTO_COOLDOWN_SEC = 600
_AUTO_DAILY_LIMIT = 3


@dataclass
class AutoAlertSyncStats:
    """一次同步的结果(给接口返回,让前端知道系统动了什么)。"""

    created: int = 0
    disabled: int = 0
    linked: int = 0
    realigned: int = 0
    # 预警提醒:新建 / 重新武装 / 因挂单消失而停用
    pre_created: int = 0
    pre_rearmed: int = 0
    pre_disabled: int = 0
    # 预警线被就地改掉的条数
    pre_realigned: int = 0


@dataclass
class _Candidate:
    """候选提醒的匹配结果。"""

    alert: dict[str, Any]
    price: float
    tier: int | None = None
    auto: bool = False


def _is_auto(alert: dict[str, Any]) -> bool:
    """这条是不是系统自动建的(到价提醒或预警提醒)。"""
    name = alert.get("name") or ""
    return name.startswith(AUTO_ALERT_PREFIX) or name.startswith(PRE_ALERT_PREFIX)


def _is_pre(alert: dict[str, Any]) -> bool:
    """这条是不是**预警**提醒。"""
    return (alert.get("name") or "").startswith(PRE_ALERT_PREFIX)


def _iter_price_leaves(node: Any):
    """递归找出条件树里所有 `price` 叶子。

    自动提醒是平铺结构,手工提醒可能嵌套 —— 递归一层都不漏。
    """
    if not isinstance(node, dict):
        return
    for leaf in node.get("conditions") or []:
        if not isinstance(leaf, dict):
            continue
        if leaf.get("metric") == "price" and leaf.get("value") is not None:
            yield leaf
        else:
            yield from _iter_price_leaves(leaf)


def _ops_of(direction: str) -> tuple[str, ...]:
    """该方向认可的比较符。"""
    if direction == DIRECTION_FORWARD:
        return (">=", ">")
    return ("<=", "<")


def _op_of(direction: str) -> str:
    """建提醒时用的比较符(取最保守的那个)。"""
    return ">=" if direction == DIRECTION_FORWARD else "<="


def _tier_of(price: float, tier_prices: list[Decimal]) -> int | None:
    """这个价格落在第几档;不在任何一档上 → None。"""
    for i, p in enumerate(tier_prices):
        if abs(price - float(p)) <= _PRICE_TOLERANCE:
            return i + 1
    return None


def _find(
    alerts: list[dict[str, Any]],
    code: str,
    direction: str,
    candidates: list[tuple[Decimal, int | None]],
    *,
    exclude_ids: set[int] | None = None,
    exclude_auto: bool = False,
) -> _Candidate | None:
    """在提醒里找第一条命中「同标的 + 同方向 + 价格命中候选价」的启用提醒。

    candidates: [(价格, 档位号 or None)] —— 档位号为 None 表示这是基准线而不是某一档。
    exclude_auto: True 时跳过系统自动建的提醒(用于「用户手工提醒」那一栏)。
    """
    ops = _ops_of(direction)
    for a in alerts:
        if a.get("stock_code") != code or not a.get("enabled"):
            continue
        if exclude_ids and a.get("id") in exclude_ids:
            continue
        auto = _is_auto(a)
        if exclude_auto and auto:
            continue
        for leaf in _iter_price_leaves(a.get("conditions") or {}):
            if leaf.get("op") not in ops:
                continue
            val = leaf.get("value")
            if val is None:
                continue
            fval = float(val)
            for price, tier in candidates:
                if abs(fval - float(price)) <= _PRICE_TOLERANCE:
                    return _Candidate(alert=a, price=fval, tier=tier, auto=auto)
    return None


def _auto_alerts_for(
    alerts: list[dict[str, Any]], code: str, direction: str
) -> list[_Candidate]:
    """该标的该方向的**启用自动提醒**(任意价格都算)。

    用来认领「已经存在的自动提醒」—— 不管它当前落在哪一档。
    **预警提醒不在这里** —— 它有独立的生命周期(一次性 + 重新武装)。
    """
    ops = _ops_of(direction)
    out: list[_Candidate] = []
    for a in alerts:
        if not _is_auto(a) or not a.get("enabled"):
            continue
        if _is_pre(a):
            continue
        if a.get("stock_code") != code:
            continue
        for leaf in _iter_price_leaves(a.get("conditions") or {}):
            if leaf.get("op") in ops and leaf.get("value") is not None:
                out.append(_Candidate(alert=a, price=float(leaf["value"]), auto=True))
                break
    return out


def _pre_alerts_for(
    alerts: list[dict[str, Any]], code: str, direction: str
) -> list[dict[str, Any]]:
    """该标的该方向的**预警提醒**(不管启用与否)。

    停用状态也要找出来 —— 停用说明「已经预警过一次」,
    要靠它判断价格离开预警区后该不该**重新武装**。
    """
    ops = _ops_of(direction)
    out: list[dict[str, Any]] = []
    for a in alerts:
        if not _is_pre(a):
            continue
        if a.get("stock_code") != code:
            continue
        for leaf in _iter_price_leaves(a.get("conditions") or {}):
            if leaf.get("op") in ops and leaf.get("value") is not None:
                out.append(a)
                break
    return out


def _pre_price_of(alert: dict[str, Any]) -> float | None:
    """预警提醒当前挂着的预警线价格。"""
    for leaf in _iter_price_leaves(alert.get("conditions") or {}):
        if leaf.get("metric") == "price" and leaf.get("value") is not None:
            return float(leaf["value"])
    return None


def _action_label(direction: str) -> str:
    return "正T卖出" if direction == DIRECTION_FORWARD else "反T接回"


def _conditions_for(direction: str, price: float) -> dict:
    return {
        "op": "and",
        "conditions": [{"metric": "price", "op": _op_of(direction), "value": price}],
    }


def _pre_conditions_for(direction: str, price: float) -> dict:
    """预警提醒的条件树。

    顶层两个标记(引擎不认识,只透传):
    - `kind: "pre_alert"` → 前端显示「预警」徽章,不再显示涨跌色徽章;
    - `once: true`      → **一次性**:命中后 alert 服务自动停用它。
    """
    return {
        "op": "and",
        "kind": PRE_ALERT_KIND,
        "once": True,
        "conditions": [{"metric": "price", "op": _op_of(direction), "value": price}],
    }


async def _realign(
    alert: dict[str, Any], direction: str, price: float
) -> bool:
    """把一条自动提醒的价格**就地**改掉(不新建、不停用)。"""
    from app.modules.alert.service import price_alert_service

    try:
        await price_alert_service.update(
            int(alert["id"]), conditions=_conditions_for(direction, price)
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[t-alerts] 对齐自动提醒价格失败 {alert.get('id')}: {e}")
        return False


async def _realign_pre(
    alert: dict[str, Any], direction: str, price: float
) -> bool:
    """把预警提醒的预警线**就地**改掉(保留 kind / once 标记)。"""
    from app.modules.alert.service import price_alert_service

    try:
        await price_alert_service.update(
            int(alert["id"]), conditions=_pre_conditions_for(direction, price)
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[t-alerts] 对齐预警线失败 {alert.get('id')}: {e}")
        return False


async def _rearm(
    alert: dict[str, Any], direction: str, price: float
) -> bool:
    """**重新武装**一条已经预警过的提醒(价格已离开预警区)。

    「一次性」不等于「一辈子只提醒一次」—— 价格离开预警区之后又回来,
    还应该再提醒一次。所以这里把它重新启用,并把预警线对齐到当前值。
    """
    from app.modules.alert.service import price_alert_service

    try:
        await price_alert_service.update(
            int(alert["id"]),
            enabled=True,
            conditions=_pre_conditions_for(direction, price),
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[t-alerts] 重新武装预警提醒失败 {alert.get('id')}: {e}")
        return False


async def sync_auto_alerts(items: list[Any]) -> AutoAlertSyncStats:
    """把每条挂单的到价提醒对齐到当前建议价。

    幂等:重复调用不会重复建提醒 —— 已存在的提醒会被复用。

    副作用:
      1. 没有提醒的挂单 → 建一条自动提醒(一档价);
      2. 已有自动提醒但价格不在当前任一档上 → **就地**改回一档;
      3. 挂单已经消失(接回/卖出) → 对应的自动提醒停用。
    """
    from app.modules.alert.service import price_alert_service

    stats = AutoAlertSyncStats()
    try:
        alerts = await price_alert_service.list_alerts()
    except Exception as e:  # noqa: BLE001 — 提醒读不到不该拖垮清单
        logger.warning(f"[t-alerts] 读取到价提醒失败,跳过自动同步: {e}")
        return stats

    auto_ids = {a.get("id") for a in alerts if _is_auto(a)}
    used_ids: set[int] = set()

    for it in items:
        tiers = list(getattr(it, "tiers", None) or [])
        if not tiers:
            continue
        code = it.stock_code
        direction = it.direction
        tier1 = tiers[0]
        tier_prices = [Decimal(str(t.price)) for t in tiers]

        adopted: _Candidate | None = None
        autos = _auto_alerts_for(alerts, code, direction)
        if autos:
            # 已有自动提醒(list_alerts 按 id 倒序 → 最新的在前)
            cand = autos[0]
            tier_no = _tier_of(cand.price, tier_prices)
            if tier_no is None:
                # 不在任何一档上(基准变了 / 被改成档位外的自定义价)→ 就地拉回一档
                if await _realign(cand.alert, direction, tier1.price):
                    cand.price = tier1.price
                    tier_no = 1
                    stats.realigned += 1
                else:
                    tier_no = None
            cand.tier = tier_no
            adopted = cand
        else:
            # 没有自动提醒 → 先看用户手工建的那条是否正好在一档价(别重复建)
            manual_hit = _find(
                alerts,
                code,
                direction,
                [(Decimal(str(tier1.price)), 1)],
                exclude_auto=True,
            )
            if manual_hit is not None:
                adopted = manual_hit
            else:
                try:
                    alert_id = await price_alert_service.create(
                        stock_code=code,
                        conditions=_conditions_for(direction, tier1.price),
                        name=(
                            f"{AUTO_ALERT_PREFIX}{it.stock_name or it.stock_code} "
                            f"{_action_label(direction)}"
                        ),
                        cooldown_sec=_AUTO_COOLDOWN_SEC,
                        daily_limit=_AUTO_DAILY_LIMIT,
                    )
                except Exception as e:  # noqa: BLE001 — 建提醒失败不该拖垮清单
                    logger.warning(f"[t-alerts] 自动建提醒失败 {code}: {e}")
                    continue
                adopted = _Candidate(
                    alert={"id": alert_id}, price=tier1.price, tier=1, auto=True
                )
                stats.created += 1

        it.alert_id = adopted.alert.get("id")
        it.alert_price = adopted.price
        it.alert_tier = adopted.tier
        it.alert_auto = adopted.auto
        used_ids.add(int(adopted.alert.get("id")))
        stats.linked += 1

        # ---- 预警提醒:到价之前先给一次「准备」信号 ----
        # 预警线基于**生效到价线**(用户在二档就按二档算),朝基准线方向再退 1%。
        trigger_price = adopted.price if adopted.price is not None else tier1.price
        pre = build_pre_alert(
            trigger_price,
            direction,
            current_price=getattr(it, "current_price", None),
        )
        it.pre_alert_price = pre.price
        it.pre_alert_distance_pct = pre.distance_pct
        it.pre_alert_reached = pre.reached
        it.pre_alert_in_zone = pre.in_pre_zone

        pres = _pre_alerts_for(alerts, code, direction)
        pre_alert = pres[0] if pres else None
        if pre_alert is None:
            try:
                pre_id = await price_alert_service.create(
                    stock_code=code,
                    conditions=_pre_conditions_for(direction, pre.price),
                    name=(
                        f"{PRE_ALERT_PREFIX}{it.stock_name or it.stock_code} "
                        f"{_action_label(direction)}预警"
                    ),
                    cooldown_sec=_AUTO_COOLDOWN_SEC,
                    daily_limit=_AUTO_DAILY_LIMIT,
                )
            except Exception as e:  # noqa: BLE001 — 建提醒失败不该拖垮清单
                logger.warning(f"[t-alerts] 自动建预警提醒失败 {code}: {e}")
            else:
                it.pre_alert_id = pre_id
                it.pre_alert_fired = False
                stats.pre_created += 1
                used_ids.add(int(pre_id))
        else:
            pre_id = int(pre_alert.get("id"))
            it.pre_alert_id = pre_id
            used_ids.add(pre_id)
            enabled = bool(pre_alert.get("enabled"))
            it.pre_alert_fired = not enabled
            old_pre = _pre_price_of(pre_alert)
            if enabled:
                # 预警线跟着「生效到价线」走 —— 到价线改了,预警线跟着改
                if (
                    old_pre is None or abs(old_pre - pre.price) > _PRICE_TOLERANCE
                ) and await _realign_pre(pre_alert, direction, pre.price):
                    stats.pre_realigned += 1
            else:
                # 已经预警过(一次性提醒命中后自动停用):
                # 现价**离开**了预警区 → 重新武装,下次再进区还会提醒
                # 现价未知(distance_pct is None)→ 保持停用,不做任何动作
                if (
                    pre.distance_pct is not None
                    and not pre.in_pre_zone
                    and await _rearm(pre_alert, direction, pre.price)
                ):
                    it.pre_alert_fired = False
                    stats.pre_rearmed += 1

        # 用户自己建的提醒(同标的 + 同方向):基准线或任一档位命中都算
        # 排除系统自动建的 —— 自动提醒归「到价提醒」那一栏管,这里只放用户手工的
        manual = _find(
            alerts,
            code,
            direction,
            [
                (Decimal(str(it.price)), None),
                *[(Decimal(str(t.price)), t.tier) for t in tiers],
            ],
            exclude_ids={int(it.alert_id)} if it.alert_id else None,
            exclude_auto=True,
        )
        if manual is not None:
            it.manual_alert_id = manual.alert.get("id")
            it.manual_alert_price = manual.price

    # 挂单已经消失(接回 / 卖出)→ 对应的自动提醒停用(不是删除)
    for a in alerts:
        aid = a.get("id")
        if aid not in auto_ids or aid in used_ids:
            continue
        if not a.get("enabled"):
            continue
        try:
            await price_alert_service.update(int(aid), enabled=False)
            if _is_pre(a):
                stats.pre_disabled += 1
            else:
                stats.disabled += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[t-alerts] 停用自动提醒失败 {aid}: {e}")

    return stats
