"""决策规则回测闸门

用历史 K 线逐日跑决策器,统计决策信号的实际效果,与「买入并持有」基准对比。
**门槛先定、事后不得下调** —— 不达标就改规则,不得跳过闸门上线。

口径(设计文档 §10.1 / §10.1.1 / §10.2,与父代理 2026-10-21 定稿一致):
- 参考价 P = 信号日**次日**开盘价(信号在收盘后产生,最早次日开盘成交)—— 三类信号统一
- 观察窗口 W = 10 个交易日(entry / exit)、**5 个交易日(stop)**
- 基准臂 = **无条件基准**: 同一只票在回测窗口内**所有可回测日**的
  「次日开盘买入并持有 W 日」同样口径的**平均值**
  (不是信号当天的同一笔交易 —— 那会让「改善」恒等于 0,闸门失去作用)
- 信号臂 = 信号日样本(与基准臂**同一套函数、同一起点**,只是筛选条件不同)
- 胜 = 持有期内最高收盘价 > 买入价 × 1.02
- 平均收益 = 第 W 个交易日收盘价 / 买入价 - 1
- 最大回撤 = 持有期内最低收盘价 / 买入价 - 1

闸门(§10.2,数字不得下调):
1. 样本池股票数 ≥ 30 只
2. 样本池回测窗口 ≥ 120 个交易日 / 只
3. 有效 entry 信号数 ≥ 100 条
4. entry 后 10 日胜率 ≥ 53%
5. entry 超额收益 > 买入并持有基准 + 1.0%
6. exit 后 10 日回撤改善 ≥ 1.0%(无条件基准 − 信号情形)
7. stop 后 5 日回撤改善 ≥ 1.5%(无条件基准 − 信号情形)

第 6/7 条的符号:「无条件基准 − 信号情形」为正 = 信号日之后的跌幅比平时更深
= 止盈/止损信号发出后确实规避了更深的回撤 = 信号有效;
为负 = 信号发出后反而比平时涨得好 = 这批信号没用。

§10.3 迭代(只调规则参数与样本池规模,**不动任何门槛数字**):
- `EntryRule` = 回测侧的 entry 规则参数旋钮(放量确认 / 动能确认)。
  它是**对决策器 entry 信号的附加过滤**,等价于把同一条件写进
  `decision_service.judge_entry` 的 C1 分支 —— 该文件不在本任务可改范围,
  同一条件**必须由父代理同步落到产品代码**,否则结论无法复现到线上。
- 样本池 30 只基池 → 60 只扩池;扩池后无条件基准必须在**同一扩池上重算**
  (否则会把「换个池子」误当成「规则变好」)。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Any

from app.services.decision_service import DecisionContext, MarketContext, build_decision
from app.services.ta_service import compute_indicators

logger = logging.getLogger(__name__)

# ---- 口径常量(§10.1.1) ----
HOLD_DAYS = 10          # entry / exit 的观察窗口(交易日)
STOP_HOLD_DAYS = 5      # stop 的观察窗口(交易日)
MAX_HOLD_DAYS = max(HOLD_DAYS, STOP_HOLD_DAYS)
WIN_THRESHOLD = 0.02    # 胜 = 持有期内最高收盘价 > 买入价 × 1.02
WARMUP_DAYS = 60        # MA60 warmup:前 60 根不算信号日

# ---- 闸门常量(§10.2,先定不得下调) ----
MIN_POOL_CODES = 30        # §10.2「样本池规模」:≥ 30 只股票
MIN_POOL_DAYS = 120        # §10.2「样本池回测窗口」:≥ 120 个交易日 / 只
MIN_ENTRY_SAMPLES = 100    # §10.2「有效 entry 信号数」:≥ 100 条(统计功效下限)
MIN_WIN_RATE = 0.53        # entry 后 10 日胜率 ≥ 53%
MIN_EXCESS_RETURN = 0.01   # entry 超额收益 > 基准 + 1.0%
MIN_EXIT_DD_IMPROVE = 0.01  # exit 后 10 日回撤改善 ≥ 1.0%
MIN_STOP_DD_IMPROVE = 0.015  # stop 后 5 日回撤改善 ≥ 1.5%

# ---- 回测股票池(§10.3 迭代:30 只基池 → 60 只扩池) ----
# (代码, 行业) —— 行业为人工标注,仅用于披露「样本池不集中于单一板块」,不参与闸门判定
# 扩池理由:§10.3 收紧 entry 规则后有效信号数跌破 100 条(统计功效下限),
# 唯一合法出路是把样本池扩到 50–60 只,并在**同一扩池上重算无条件基准**。
POOL_BASE: tuple[tuple[str, str], ...] = (
    ("002185.SZ", "半导体"),
    ("600519.SH", "白酒"),
    ("000001.SZ", "银行"),
    ("002594.SZ", "汽车"),
    ("300750.SZ", "新能源电池"),
    ("600036.SH", "银行"),
    ("000725.SZ", "面板显示"),
    ("002230.SZ", "软件/AI"),
    ("601318.SH", "保险"),
    ("002415.SZ", "安防/消费电子"),
    ("000651.SZ", "家电"),
    ("300059.SZ", "券商"),
    ("600030.SH", "券商"),
    ("002714.SZ", "养殖"),
    ("300760.SZ", "医疗器械"),
    ("688981.SH", "半导体"),
    ("000858.SZ", "白酒"),
    ("600887.SH", "食品"),
    ("601899.SH", "有色金属"),
    ("002352.SZ", "物流"),
    ("300124.SZ", "工业自动化"),
    ("002027.SZ", "传媒"),
    ("600276.SH", "医药"),
    ("601012.SH", "光伏"),
    ("300015.SZ", "医疗服务"),
    ("600009.SH", "机场"),
    ("601166.SH", "银行"),
    ("000568.SZ", "白酒"),
    ("002304.SZ", "白酒"),
    ("603288.SH", "食品"),
)

# 扩池新增 30 只(行业分散:不与基池重复同一板块,新增 12 个行业)
POOL_EXTRA: tuple[tuple[str, str], ...] = (
    ("600028.SH", "石油化工"),
    ("601857.SH", "石油化工"),
    ("600900.SH", "电力"),
    ("600585.SH", "建材"),
    ("601668.SH", "建筑装饰"),
    ("600031.SH", "工程机械"),
    ("600104.SH", "汽车"),
    ("000625.SZ", "汽车"),
    ("601111.SH", "航空运输"),
    ("600029.SH", "航空运输"),
    ("601088.SH", "煤炭"),
    ("600188.SH", "煤炭"),
    ("600309.SH", "化工"),
    ("002129.SZ", "光伏"),
    ("300274.SZ", "光伏设备"),
    ("600703.SH", "半导体"),
    ("002371.SZ", "半导体设备"),
    ("603501.SH", "半导体"),
    ("002475.SZ", "消费电子"),
    ("002241.SZ", "消费电子"),
    ("300014.SZ", "电池"),
    ("002460.SZ", "锂电"),
    ("600941.SH", "通信"),
    ("000063.SZ", "通信"),
    ("600406.SH", "电网设备"),
    ("601688.SH", "券商"),
    ("600660.SH", "汽车零部件"),
    ("000538.SZ", "中药"),
    ("300347.SZ", "医疗服务"),
    ("600600.SH", "食品饮料"),
)

POOL: tuple[tuple[str, str], ...] = POOL_BASE + POOL_EXTRA

DEFAULT_CODES: list[str] = [code for code, _ in POOL]
BASE_CODES: list[str] = [code for code, _ in POOL_BASE]
INDUSTRY: dict[str, str] = dict(POOL)

# 三种持仓上下文(修正 1:build_decision 按 position_status 分派,
# empty→judge_entry / profit→judge_exit / loss→judge_loss_plan)
# cost_basis = 现价 × 系数:0.9 → 浮盈(profit),1.1 → 浮亏(loss)
# 系数只为把持仓状态稳定落到对应分支,**不是策略阈值**,不参与任何动作判定。
CTX_SPECS: tuple[tuple[str, str, int, float | None], ...] = (
    ("entry", "empty", 0, None),
    ("exit", "profit", 100, 0.9),
    ("stop", "loss", 100, 1.1),
)


# ---- §10.3 迭代:entry 规则参数(回测侧旋钮) ----
@dataclass(frozen=True)
class EntryRule:
    """§10.3 迭代用的 entry 规则参数

    只允许调**规则参数**(放量确认阈值、动能确认条件),
    不得改闸门数字、样本池口径、基准口径、下跌通道守卫。

    实现方式:在回测侧对决策器产出的 entry 信号做**附加过滤** ——
    等价于把同一条件写进 `decision_service.judge_entry` 的 C1 分支。
    `decision_service.py` 不在本任务的可改范围内(父代理所有),
    因此同一条件**必须由父代理同步落到产品代码**,否则回测结论无法复现到线上。
    """

    min_volume_ratio: float | None = None   # C1 放量确认:量比 ≥ 阈值
    require_chg5_positive: bool = False     # 5 日涨幅 > 0(短期动能转正确认)


def _entry_rule_ok(ind: dict[str, Any], window: list[dict[str, Any]], rule: EntryRule) -> bool:
    """entry 信号是否满足本轮收紧后的规则参数(缺数据 → 不放行,零编造)"""
    if rule.min_volume_ratio is not None:
        vr = _f((ind.get("volume") or {}).get("ratio"))
        if vr is None or vr < rule.min_volume_ratio:
            return False
    if rule.require_chg5_positive:
        closes = [_f(k.get("close")) for k in window]
        if len(closes) < 6 or any(c is None for c in closes[-6:]):
            return False
        if closes[-1] / closes[-6] - 1 <= 0:
            return False
    return True


def _f(v: Any) -> float | None:
    """安全转 float;None / 非法值 / NaN → None"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _forward_return(
    klines: list[dict[str, Any]], idx: int, hold_days: int = HOLD_DAYS
) -> tuple[float | None, float | None, float | None]:
    """信号日 idx → 次日开盘买入、持有 hold_days 个交易日 → (胜?, 平均收益, 最大回撤)

    - 买入价 = klines[idx+1] 的**开盘价**(信号在收盘后产生,最早次日开盘成交)
    - 持有期 = 买入日起 hold_days 个交易日
    - 胜 = 持有期内最高收盘价 > 买入价 × 1.02
    - 平均收益 = 第 hold_days 个交易日收盘价 / 买入价 - 1
    - 最大回撤 = 持有期内最低收盘价 / 买入价 - 1

    数据不足返回 (None, None, None)(零编造:不拿 0 或默认值顶替)。
    """
    entry_idx = idx + 1
    if entry_idx >= len(klines):
        return None, None, None
    entry = _f(klines[entry_idx].get("open"))
    if entry is None or entry <= 0:
        return None, None, None
    hold = klines[entry_idx: entry_idx + hold_days]
    if len(hold) < hold_days:
        return None, None, None
    closes = [_f(k.get("close")) for k in hold]
    if any(c is None for c in closes):
        return None, None, None
    max_close = max(closes)
    min_close = min(closes)
    last_close = closes[-1]
    is_win = 1.0 if max_close > entry * (1 + WIN_THRESHOLD) else 0.0
    ret = last_close / entry - 1
    dd = min_close / entry - 1
    return is_win, ret, dd


def evaluate_gates(report: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """按设计文档 §10.2 的门槛判定;返回 (是否通过, 每条门槛明细)

    纯函数:不改入参,不改全局状态,可单测。
    """
    gates: list[dict[str, Any]] = []

    codes = report.get("codes") or 0
    gates.append({
        "name": "样本池股票数",
        "target": f"≥ {MIN_POOL_CODES} 只",
        "actual": codes,
        "passed": codes >= MIN_POOL_CODES,
    })

    days = report.get("days") or 0
    gates.append({
        "name": "样本池回测窗口",
        "target": f"≥ {MIN_POOL_DAYS} 个交易日/只",
        "actual": days,
        "passed": days >= MIN_POOL_DAYS,
    })

    samples = report.get("samples") or 0
    gates.append({
        "name": "有效 entry 信号数",
        "target": f"≥ {MIN_ENTRY_SAMPLES} 条",
        "actual": samples,
        "passed": samples >= MIN_ENTRY_SAMPLES,
    })

    entry = report.get("entry") or {}
    wr = _f(entry.get("win_rate"))
    gates.append({
        "name": "entry 后 10 日胜率",
        "target": f"≥ {MIN_WIN_RATE:.0%}",
        "actual": wr,
        "passed": wr is not None and wr >= MIN_WIN_RATE,
    })

    exc = _f(entry.get("avg_return"))
    base = _f(entry.get("baseline_avg_return"))
    excess = None if exc is None or base is None else exc - base
    gates.append({
        "name": "entry 超额收益",
        "target": f"> 基准 + {MIN_EXCESS_RETURN:.1%}",
        "actual": None if excess is None else round(excess, 4),
        "passed": excess is not None and excess > MIN_EXCESS_RETURN,
    })

    # 回撤改善 = 无条件基准 − 信号情形(两臂同窗口可比)
    exit_dd = _f((report.get("exit") or {}).get("avg_drawdown"))
    exit_base = _f((report.get("exit") or {}).get("baseline_avg_drawdown"))
    exit_improve = None if exit_dd is None or exit_base is None else exit_base - exit_dd
    gates.append({
        "name": "exit 后 10 日回撤改善",
        "target": f"≥ {MIN_EXIT_DD_IMPROVE:.1%}",
        "actual": None if exit_improve is None else round(exit_improve, 4),
        "passed": exit_improve is not None and exit_improve >= MIN_EXIT_DD_IMPROVE,
    })

    stop_dd = _f((report.get("stop") or {}).get("avg_drawdown"))
    stop_base = _f((report.get("stop") or {}).get("baseline_avg_drawdown"))
    stop_improve = None if stop_dd is None or stop_base is None else stop_base - stop_dd
    gates.append({
        "name": "stop 后 5 日回撤改善",
        "target": f"≥ {MIN_STOP_DD_IMPROVE:.1%}",
        "actual": None if stop_improve is None else round(stop_improve, 4),
        "passed": stop_improve is not None and stop_improve >= MIN_STOP_DD_IMPROVE,
    })

    return all(g["passed"] for g in gates), gates


async def run_backtest(
    codes: list[str],
    days: int = 120,
    entry_rule: EntryRule | None = None,
) -> dict[str, Any]:
    """对给定股票池逐日跑决策器,产出统计报告(设计文档 §10.1)

    逐日推进,严格无前视偏差:信号日 i 只用 klines[: i+1] 的数据跑判定器,
    前向收益用信号日**次日开盘价**买入后计算(评估用的未来数据,不是判定输入)。

    `entry_rule` 为 §10.3 迭代用的规则参数旋钮(默认不收紧,等价于基线轮)。
    """
    from app.services.kline_service import fetch_klines

    rule = entry_rule or EntryRule()

    # 信号臂累计
    entry_acc = {"wins": 0.0, "n": 0, "ret": 0.0}
    exit_acc = {"n": 0, "dd": 0.0}
    stop_acc = {"n": 0, "dd": 0.0}
    filtered_entry = 0
    # 基准臂累计(无条件基准:全部可回测日)
    uncond_acc = {"n": 0, "ret10": 0.0, "dd10": 0.0, "win10": 0.0, "dd5": 0.0}

    stocks: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    total_signal_days = 0

    for code in codes:
        try:
            klines = await fetch_klines(
                code, period="daily", count=days + MAX_HOLD_DAYS + WARMUP_DAYS
            )
        except Exception as e:  # noqa: BLE001 — 单只失败不中断整池
            logger.warning("回测 %s 取 K 线失败: %s", code, e)
            skipped.append({"code": code, "reason": f"K 线获取失败: {e}"})
            continue

        # 信号日区间:warmup 后,留出前向窗口
        lo = WARMUP_DAYS - 1
        hi = len(klines) - MAX_HOLD_DAYS - 1
        stock_days = max(0, hi - lo)
        # 凑不满回测窗口的票(新股/停牌)直接跳过并记录,不拿别的票凑数
        if stock_days < days:
            skipped.append({
                "code": code,
                "reason": f"K 线仅 {len(klines)} 根,可回测日 {stock_days} < 要求的 {days}",
            })
            continue

        per = {"entry": 0, "exit": 0, "stop": 0}
        for i in range(lo, hi):
            # ---- 基准臂:同一只票、全部可回测日的同样口径 ----
            win10, ret10, dd10 = _forward_return(klines, i, HOLD_DAYS)
            _, _, dd5 = _forward_return(klines, i, STOP_HOLD_DAYS)
            if win10 is not None and ret10 is not None and dd10 is not None and dd5 is not None:
                uncond_acc["n"] += 1
                uncond_acc["ret10"] += ret10
                uncond_acc["dd10"] += dd10
                uncond_acc["win10"] += win10
                uncond_acc["dd5"] += dd5

            # ---- 信号臂:只用 klines[: i+1](无前视) ----
            window = klines[: i + 1]
            try:
                ind = compute_indicators(window)
            except Exception as e:  # noqa: BLE001 — 单日指标失败不中断
                logger.debug("回测 %s 第 %s 日指标计算失败: %s", code, i, e)
                continue

            price = _f(window[-1].get("close"))
            prev_close = _f(window[-2].get("close")) if len(window) >= 2 else None

            for kind, status, shares, cost_factor in CTX_SPECS:
                cost = None if cost_factor is None or price is None else price * cost_factor
                ctx = DecisionContext(
                    stock_code=code,
                    stock_name=None,
                    indicators=ind,
                    klines=window,
                    current_price=price,
                    prev_close=prev_close,
                    cost_basis=cost,
                    shares=shares,
                    position_status=status,
                    env=MarketContext(),
                )
                try:
                    decision = build_decision(ctx)
                except Exception as e:  # noqa: BLE001 — 单次判定失败不中断
                    logger.debug("回测 %s 第 %s 日判定失败(%s): %s", code, i, status, e)
                    continue
                kinds_now = {
                    a.get("kind") for a in decision.get("actions", []) if a.get("status") == "now"
                }
                if kind not in kinds_now:
                    continue
                if kind == "entry":
                    if not _entry_rule_ok(ind, window, rule):
                        filtered_entry += 1
                        continue
                    if win10 is None or ret10 is None:
                        continue
                    entry_acc["wins"] += win10
                    entry_acc["n"] += 1
                    entry_acc["ret"] += ret10
                    per["entry"] += 1
                elif kind == "exit":
                    if dd10 is None:
                        continue
                    exit_acc["n"] += 1
                    exit_acc["dd"] += dd10
                    per["exit"] += 1
                elif kind == "stop":
                    if dd5 is None:
                        continue
                    stop_acc["n"] += 1
                    stop_acc["dd"] += dd5
                    per["stop"] += 1

        total_signal_days += stock_days
        stocks.append({
            "code": code,
            "industry": INDUSTRY.get(code, ""),
            "klines": len(klines),
            "signal_days": stock_days,
            "entry_n": per["entry"],
            "exit_n": per["exit"],
            "stop_n": per["stop"],
        })

    def _avg(total: float, n: int) -> float | None:
        return round(total / n, 4) if n > 0 else None

    entry_n = entry_acc["n"]
    exit_n = exit_acc["n"]
    stop_n = stop_acc["n"]
    u_n = uncond_acc["n"]

    uncond = {
        "n": u_n,
        "avg_return_10": _avg(uncond_acc["ret10"], u_n),
        "avg_drawdown_10": _avg(uncond_acc["dd10"], u_n),
        "win_rate_10": _avg(uncond_acc["win10"], u_n),
        "avg_drawdown_5": _avg(uncond_acc["dd5"], u_n),
    }

    entry_avg_ret = _avg(entry_acc["ret"], entry_n)
    entry_base_ret = uncond["avg_return_10"]
    exit_avg_dd = _avg(exit_acc["dd"], exit_n)
    exit_base_dd = uncond["avg_drawdown_10"]
    stop_avg_dd = _avg(stop_acc["dd"], stop_n)
    stop_base_dd = uncond["avg_drawdown_5"]

    days_actual = min((s["signal_days"] for s in stocks), default=0)

    report: dict[str, Any] = {
        "codes": len(stocks),
        "days": days_actual,
        "samples": entry_n,
        "entry_rule": asdict(rule),
        "entry_filtered": filtered_entry,
        "entry": {
            "n": entry_n,
            "win_rate": _avg(entry_acc["wins"], entry_n),
            "avg_return": entry_avg_ret,
            "baseline_avg_return": entry_base_ret,
            "baseline_win_rate": uncond["win_rate_10"],
            "excess_return": (
                None if entry_avg_ret is None or entry_base_ret is None
                else round(entry_avg_ret - entry_base_ret, 4)
            ),
        },
        "exit": {
            "n": exit_n,
            "avg_drawdown": exit_avg_dd,
            "baseline_avg_drawdown": exit_base_dd,
            "improvement": (
                None if exit_avg_dd is None or exit_base_dd is None
                else round(exit_base_dd - exit_avg_dd, 4)
            ),
        },
        "stop": {
            "n": stop_n,
            "avg_drawdown": stop_avg_dd,
            "baseline_avg_drawdown": stop_base_dd,
            "improvement": (
                None if stop_avg_dd is None or stop_base_dd is None
                else round(stop_base_dd - stop_avg_dd, 4)
            ),
        },
        "unconditional": uncond,
        "signal_rate": {
            "entry": round(entry_n / max(1, total_signal_days), 4),
            "exit": round(exit_n / max(1, total_signal_days), 4),
            "stop": round(stop_n / max(1, total_signal_days), 4),
            "total_signal_days": total_signal_days,
        },
        "stocks": stocks,
        "skipped": skipped,
    }

    passed, gates = evaluate_gates(report)
    report["gates"] = gates
    report["passed"] = passed
    return report


def main() -> None:
    """CLI:python -m app.services.decision_backtest [--pool base|full] [--min-vr 1.5] [--chg5]"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="决策规则回测闸门")
    parser.add_argument("--pool", choices=["base", "full"], default="full",
                        help="base = 30 只基池;full = 60 只扩池")
    parser.add_argument("--codes", nargs="*", default=None, help="显式指定股票代码(覆盖 --pool)")
    parser.add_argument("--days", type=int, default=120, help="每只股票的回测窗口(交易日)")
    parser.add_argument("--min-vr", type=float, default=None,
                        help="C1 放量确认阈值:量比 ≥ 阈值(§10.3 规则参数)")
    parser.add_argument("--chg5", action="store_true",
                        help="要求 5 日涨幅 > 0(§10.3 规则参数)")
    parser.add_argument("--out", default=None, help="报告 JSON 输出路径")
    args = parser.parse_args()

    codes = args.codes or (BASE_CODES if args.pool == "base" else DEFAULT_CODES)
    rule = EntryRule(min_volume_ratio=args.min_vr, require_chg5_positive=args.chg5)
    report = asyncio.run(run_backtest(codes, days=args.days, entry_rule=rule))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"报告已写入 {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
