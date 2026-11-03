"""做T建议价的三档阶梯(纯函数,无 IO)。

为什么要分档:
  一个建议价只能回答「现在这个价做不做」。真实做T要的是**梯度**:
  价到一档就该动手(怕错过,幅度小),价到三档是这波最舒服的位置(赚最多,可能要等)。
  所以每条挂单给三档,每档都带「按这档成交之后的摊薄成本线」——
  一眼看出「做到哪一档,成本能被拉低多少」。

方向(必须分清,不能一味价高):
  反T(先卖后买):基准 = 不亏本接回线,三档价格**往下**走
                 —— 越等接回越便宜,幅度越大越难成交。
  正T(先买后卖):基准 = 买入均价,三档价格**往上**走
                 —— 越等卖得越贵,幅度越大越难成交。
  两边都是「一档贴线最好成交、三档幅度最大」,但价格方向相反。

幅度为什么是 1% / 2% / 3%:
  0.5% 只够覆盖双边手续费(接回 10 万块也就省 500 块),谈不上「做T的收益」——
  忙活一趟基本白做,还得一直盯着盘面。1% 起才有意义,3% 是这波能做到的舒服位置。
  口径集中在这一个常量里,改它不改结构。

预警线(提前提醒,见 `build_pre_alert`):
  到价才响 = 没有操作空间 —— 价格可能直接穿过去。所以每条挂单再给一条**预警线**:
  生效到价线朝**基准线方向**再退 `PRE_ALERT_OFFSET`。反T 往上(接回更容易够到),
  正T 往下(卖出更容易够到)。默认 1% 时预警线≈基准线,语义是
  「价格回到成本/不亏本线了,准备动手」。
  预警线是**相对生效到价线**算的 —— 用户把到价提醒改到二档,预警线跟着走。

成本口径:摊薄(券商口径)。摊薄总额 = 净投入,买入即增加、卖出按成交价回收。
  反T接回 → 净投入增加、股数增加;正T卖出 → 净投入减少、股数减少。
  没有持仓行或算完股数为 0 → 成本字段留 null(不编数字)。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.modules.portfolio.t_pairing import DIRECTION_FORWARD

# 三档幅度(相对基准线)。改这里就改了三档建议价。
TIER_OFFSETS: tuple[Decimal, ...] = (
    Decimal("0.01"),
    Decimal("0.02"),
    Decimal("0.03"),
)

# 预警线相对**生效到价线**再退多少(朝基准线方向)。
# 1% 时预警线≈基准线 —— 「价格回到成本/不亏本线就提醒准备」。
PRE_ALERT_OFFSET = Decimal("0.01")

# 每档的标签与提示语
TIER_LABELS: tuple[str, ...] = ("一档", "二档", "三档")
TIER_HINTS: tuple[str, ...] = (
    "贴线,最容易成交 —— 先把这单做掉",
    "幅度与成交概率折中",
    "幅度最大,可能要等行情",
)


@dataclass(frozen=True)
class TierSpec:
    """一档的定义:相对基准线的幅度。"""

    tier: int
    offset: Decimal
    label: str
    hint: str


TIER_SPECS: tuple[TierSpec, ...] = tuple(
    TierSpec(
        tier=i + 1,
        offset=TIER_OFFSETS[i],
        label=TIER_LABELS[i],
        hint=TIER_HINTS[i],
    )
    for i in range(len(TIER_OFFSETS))
)


class TTier(BaseModel):
    """一档建议价 + 按这一档成交之后的成本线。"""

    # 档位号(1/2/3)
    tier: int
    # 档位名(一档/二档/三档)
    label: str
    # 这一档的价格
    price: float
    # 相对基准线的幅度(0.01 = 1%)
    offset_pct: float
    # 当前成本线(摊薄成本价,券商口径);没有持仓时为 null
    cost_before: float | None = None
    # 按这一档成交之后的成本线;算不出来时为 null
    cost_after: float | None = None
    # 这一档的取舍说明
    hint: str = ""


def tier_factor(direction: str, offset: Decimal) -> Decimal:
    """档位价格 = 基准线 × (1 ∓ 幅度)。

    反T 往下(接回更便宜),正T 往上(卖得更贵)—— 方向相反,不能一味价高。
    """
    if direction == DIRECTION_FORWARD:
        return Decimal("1") + offset
    return Decimal("1") - offset


def build_tiers(
    base: Decimal,
    direction: str,
    *,
    shares: int,
    total_cost: Decimal | None = None,
    position_shares: int = 0,
) -> list[TTier]:
    """算出三档建议价 + 每档成交后的成本前→后。

    base: 基准线(反T=不亏本接回线,正T=买入加权均价)。
    shares: 这条挂单的股数。
    total_cost: 当前持仓的摊薄总额(净投入);None = 没有持仓行 → 成本留 null。
    position_shares: 当前持仓股数。
    """
    base = Decimal(base).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    tiers: list[TTier] = []

    cost_before: float | None = None
    if total_cost is not None and position_shares > 0:
        cost_before = float(
            (total_cost / position_shares).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        )

    for spec in TIER_SPECS:
        price = (base * tier_factor(direction, spec.offset)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
        cost_after: float | None = None
        if total_cost is not None and position_shares > 0:
            if direction == DIRECTION_FORWARD:
                # 正T卖出:按成交价回收净投入,股数减少
                new_total = total_cost - price * shares
                new_shares = position_shares - shares
            else:
                # 反T接回:净投入增加,股数增加
                new_total = total_cost + price * shares
                new_shares = position_shares + shares
            if new_shares > 0:
                cost_after = float(
                    (new_total / new_shares).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                )
        tiers.append(
            TTier(
                tier=spec.tier,
                label=spec.label,
                price=float(price),
                offset_pct=float(spec.offset),
                cost_before=cost_before,
                cost_after=cost_after,
                hint=spec.hint,
            )
        )
    return tiers


class TPreAlert(BaseModel):
    """预警线:到价之前的「准备区」边界 + 还差多远。"""

    # 预警线价格
    price: float
    # 相对生效到价线的提前幅度(0.01 = 1%)
    offset_pct: float
    # 距到价线还差百分之几(**绝对值**,正数);现价未知 → null
    distance_pct: float | None = None
    # 现价是否已经越过到价线(反T:已跌穿;正T:已涨穿)
    reached: bool = False
    # 现价是否已经进入预警区(该准备了)
    in_pre_zone: bool = False
    # 一句话说明
    hint: str = ""


def build_pre_alert(
    trigger_price: Decimal | float,
    direction: str,
    *,
    current_price: float | None = None,
    offset: Decimal = PRE_ALERT_OFFSET,
) -> TPreAlert:
    """算预警线 + 还差多远。

    预警线 = 生效到价线朝**基准线方向**再退 `offset`:
      - 反T(往下接回):预警线**高于**到价线 → 条件 `price <= 预警线` 更容易先满足;
      - 正T(往上卖出):预警线**低于**到价线 → 条件 `price >= 预警线` 更容易先满足。

    `trigger_price` 是**当前生效**的到价线(用户在二档就按二档算)——
    预警线永远比到价线早一步,不会反客为主。
    """
    trigger = Decimal(str(trigger_price)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    # 反T 往上退、正T 往下退 —— 方向相反,不能一味价高
    factor = (
        Decimal("1") - offset if direction == DIRECTION_FORWARD else Decimal("1") + offset
    )
    pre = (trigger * factor).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    distance_pct: float | None = None
    reached = False
    in_pre_zone = False
    if current_price is not None and current_price > 0:
        cur = Decimal(str(current_price))
        # 还差多少:到价线与现价的差距占现价的百分比(**绝对值**)。
        # 方向交给 `reached` 表达 —— 反T 是「还要跌」,正T 是「还要涨」,
        # 用带符号的百分比会让人误读方向。
        distance_pct = float(
            (abs(trigger - cur) / cur * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        reached = (
            cur >= trigger if direction == DIRECTION_FORWARD else cur <= trigger
        )
        in_pre_zone = (
            cur >= pre if direction == DIRECTION_FORWARD else cur <= pre
        )

    return TPreAlert(
        price=float(pre),
        offset_pct=float(offset),
        distance_pct=distance_pct,
        reached=reached,
        in_pre_zone=in_pre_zone,
        hint=(
            "价格回到这条线就该准备 —— 再走一段就到成交价"
            if not reached
            else "已经越过成交价"
        ),
    )
