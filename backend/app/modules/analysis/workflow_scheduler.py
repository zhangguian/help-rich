"""三段式 Agent 调度器(阶段4 · 阶段 T2 改造)

时间窗(交易日):
- 08:30–08:59  → 盘前简报
- 11:30–11:59  → 盘中复盘(上午收盘)
- 14:00–14:29  → 盘中复盘(下午盘初)
- 16:00–16:59  → 盘后复盘提示

**交易日判定**(阶段 T1):用 `core/trading_calendar`(上证指数真实日 K 的日期集合),
法定节假日不跑。数据源故障回落工作日时**仍然跑**,但记 warning,且产出里带
`estimated` 标记 —— 绝不静默假装是准确交易日。

---

## ⚠️ 2026-10-27 修复:单窗口失败不再杀死调度器

**事故**:11:30 档因「今日作战计划还没生成」抛 `IntradayReviewError` →
异常直接冲出 `start_workflow_scheduler` 的 `while` 循环 →
**调度器当场死亡**(日志:`Task exception was never retrieved`) →
当天后续所有窗口(含 14:00 那档)再也没人跑 → 当天两档复盘全空 →
前端面板只能显示「下一次盘中复盘 11:30」,用户完全看不到复盘内容。

**现在**:

1. 单窗口失败只记日志,**继续跑后面的窗口**(调度器不再被单个窗口带走)。
2. 失败的那档在**补跑有效期内**继续重试(默认 5 分钟一次),
   **成功才**写入 `_fired` —— 失败不再等于「今天这档放弃了」。
3. 下一档触发时,会先把之前没成功的档**按时间顺序补上**
   (例:14:00 触发时,先把 11:30 补掉,再跑 14:00)。
4. **推送失败不重试** —— 产出已经落库,重推会重复发消息给用户;
   只有**产出失败**才重试(那时什么也没发出去,重试安全)。
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime

from app.core.logging import logger

# (kind, hour, minute, end_minute)
TIME_WINDOWS = [
    ("premarket", 8, 30, 59),
    ("intraday_am", 11, 30, 59),
    ("intraday_pm", 14, 0, 29),
    ("postmarket", 16, 0, 59),
]

SLOT_LABEL = {
    "premarket": "08:30",
    "intraday_am": "11:30",
    "intraday_pm": "14:00",
    "postmarket": "16:00",
}

# 盘中窗口 → 复盘档位(阶段 T2:盘中主产出改为「盘中复盘」)
REVIEW_SLOT = {
    "intraday_am": "11:30",
    "intraday_pm": "14:00",
}

# 每档的**补跑截止时刻**(当天,小时:分钟)
#
# 过了这个点就不再补跑 —— 下午三点补一份上午的复盘没什么意义。
# 盘中两档的截止点刻意错开:
#   11:30 档 → 截止 14:29(下一档触发之前)
#   14:00 档 → 截止 15:59(收盘之后)
# 这样 14:00 那一轮既能补 11:30,也能跑 14:00。
RETRY_DEADLINE = {
    "premarket": (9, 29),
    "intraday_am": (14, 29),
    "intraday_pm": (15, 59),
    "postmarket": (23, 59),
}

# 同一档两次尝试的最小间隔(分钟)—— 调度器每 60s 醒一次,
# 不设间隔的话一个必然失败的档(比如作战计划还没生成)会每分钟炸一次日志。
RETRY_INTERVAL_MIN = 5

# 已**成功**产出的窗口(当天)。失败的不写进来 —— 所以还能补跑。
_fired: set[str] = set()
# 每档最后一次尝试的时刻(用于重试间隔)
_last_attempt: dict[str, datetime] = {}
# 已经打过完整堆栈的失败(同一档只打一次,后续只打一行)
_failed_logged: set[str] = set()
# 「交易日判定含推算」的 warning 每天只打一次(调度器每 60s 醒一次,别刷屏)
_trading_warned_day: str | None = None


def _window_key(kind: str, now: datetime) -> str:
    return f"{now.date().isoformat()}:{kind}"


async def _is_trading_day(d: date) -> bool:
    """交易日判定(真实日 K 集合;数据源故障回落工作日 + warning)"""
    global _trading_warned_day

    from app.services.trading_calendar_service import ensure_trading_calendar
    from app.core.trading_calendar import is_trading_day, trading_days_hint

    await ensure_trading_calendar()
    hint = trading_days_hint()
    if hint.get("estimated") and _trading_warned_day != d.isoformat():
        _trading_warned_day = d.isoformat()
        logger.warning(
            f"[workflow] 交易日判定含推算(source={hint.get('source')}, "
            f"estimated=True): 今日按工作日处理,产出里会带 estimated 标记"
        )
    return is_trading_day(d)


async def due_windows(now: datetime) -> list[str]:
    """返回此刻应触发(或应补跑)的窗口 kind 列表,**按时间顺序**。

    规则(每档独立判断):
    - 触发时刻已过(`now >= 触发时刻`);
    - 今天还没**成功**产出过;
    - 还没过该档的补跑截止时刻;
    - 距上次尝试至少 `RETRY_INTERVAL_MIN` 分钟。

    ⚠️ 本函数**不**标记「已跑」—— 标记只发生在产出成功之后
    (见 `start_workflow_scheduler`)。否则失败一次就等于当天放弃。
    """
    if not await _is_trading_day(now.date()):
        return []
    out: list[str] = []
    for kind, hour, minute, _end in TIME_WINDOWS:
        key = _window_key(kind, now)
        if key in _fired:
            continue
        trigger = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < trigger:
            continue  # 还没到点
        dl_hour, dl_minute = RETRY_DEADLINE[kind]
        deadline = now.replace(hour=dl_hour, minute=dl_minute, second=0, microsecond=0)
        if now > deadline:
            continue  # 过了补跑截止,放弃这一档
        last = _last_attempt.get(key)
        if last is not None:
            elapsed_min = (now - last).total_seconds() / 60
            if elapsed_min < RETRY_INTERVAL_MIN:
                continue  # 离上次失败还没到重试间隔
        out.append(kind)
    return out


def reset_fired() -> None:
    """清空已触发记录(单测用)。"""
    _fired.clear()
    _last_attempt.clear()
    _failed_logged.clear()


def mark_attempt(kind: str, now: datetime, ok: bool) -> None:
    """记录一次尝试的结果。

    - **成功** → 写 `_fired`:这档今天不用再跑了(幂等)
    - **失败** → 只写 `_last_attempt`:等重试间隔到了还能再试

    ⚠️ 用循环里的 `now` 而不是 `datetime.now()`,是为了让「重试间隔」
    的判断跟 `due_windows` 用的是同一个时间基准(否则测试不可复现)。
    """
    key = _window_key(kind, now)
    _last_attempt[key] = now
    if ok:
        _fired.add(key)
    _prune_to_today(now)


def _prune_to_today(now: datetime) -> None:
    """只保留当天的记录。

    ⚠️ 三份状态的键都带日期前缀,但**没人删旧键** —— 常驻进程跑一年
    会攒下上千条过期键(几百 KB)。判定只看今天,所以旧键纯属垃圾。
    """
    prefix = f"{now.date().isoformat()}:"
    for stale in [k for k in _fired if not k.startswith(prefix)]:
        _fired.discard(stale)
    for stale in [k for k in _failed_logged if not k.startswith(prefix)]:
        _failed_logged.discard(stale)
    for stale in [k for k in _last_attempt if not k.startswith(prefix)]:
        _last_attempt.pop(stale, None)


async def _run_window(kind: str) -> bool:
    """跑一个窗口。

    返回值 = **产出是否成功**:
    - `True`  产出已落库(推送失败也算 —— 产出在,不重复推)
    - `False` 产出失败(没落库、没推送)→ 允许按重试间隔再试

    任何异常都在这里被吃掉 —— 绝不让它冲出调度器主循环。
    """
    # ⚠️ key 要**按天隔离**:否则第一天失败打了堆栈,第二天同一档失败
    # 只剩一行 warning,第二天真出问题时反而看不到原因。
    key = _window_key(kind, datetime.now())
    try:
        if kind == "premarket":
            from app.modules.analysis.workflow import workflow_agent_service

            result = await workflow_agent_service.run_premarket()
            try:
                await workflow_agent_service.dispatch(result)
            except Exception as e:  # noqa: BLE001 — 推送失败不重试(产出已生成,重推=重复打扰)
                logger.warning(f"[workflow] premarket 推送失败(产出已生成,不重试): {e}")
            logger.info(f"[workflow] {kind} 完成({SLOT_LABEL.get(kind, kind)})")
            return True

        if kind in REVIEW_SLOT:
            from app.modules.analysis.intraday_review import (
                dispatch_intraday_review,
                has_review,
                run_intraday_review,
            )
            from app.services.trading_calendar_service import trading_day_meta

            slot = REVIEW_SLOT[kind]
            # ⚠️ 已经产出过 → 跳过(**不重跑、不重推**)。
            # 调度器的「已跑」标记只在内存里,后端一重启就忘了 ——
            # 不查库的话,重启会把还在补跑窗口内的档再产出一次、再推一次。
            # 推送不可撤回,重复推就是重复打扰用户。数据库才是事实来源。
            if await has_review(date.today().isoformat(), slot):
                logger.info(f"[workflow] {kind} 今日已产出({slot}),跳过(不重复推送)")
                return True

            meta = await trading_day_meta()
            # ⚠️ 只有这一段失败才算「产出失败」→ 可重试。
            # (失败原因最常见:当日作战计划还没生成 → 用户补上计划后应当能补跑)
            payload = await run_intraday_review(slot, trading_day=meta)
            try:
                await dispatch_intraday_review(payload)
            except Exception as e:  # noqa: BLE001 — 同上,推送失败不重试
                logger.warning(f"[workflow] {kind} 推送失败(产出已生成,不重试): {e}")
            logger.info(
                f"[workflow] {kind} 完成({SLOT_LABEL.get(kind, kind)}): "
                f"动作 {len(payload.get('actions') or [])} 条"
            )
            return True

        # postmarket:盘后由选股调度器 + 复盘模块覆盖,这里不重复跑
        return True
    except Exception as e:  # noqa: BLE001 — 产出失败:记日志 + 允许重试
        if key not in _failed_logged:
            _failed_logged.add(key)
            logger.exception(
                f"[workflow] {kind} 产出失败(将于补跑有效期内重试): {e}"
            )
        else:
            logger.warning(
                f"[workflow] {kind} 产出失败(将于补跑有效期内重试): {e}"
            )
        return False


async def start_workflow_scheduler(interval_sec: int = 60) -> None:
    """常驻调度循环。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # 测试环境不启动

    logger.info(f"[workflow] 三段式 Agent 调度器启动,间隔 {interval_sec}s")
    try:
        while True:
            now = datetime.now()
            try:
                for kind in await due_windows(now):
                    ok = await _run_window(kind)
                    mark_attempt(kind, now, ok)
            except Exception as e:  # noqa: BLE001 — 连 due_windows 都不能带死调度器
                logger.exception(f"[workflow] 调度轮次异常(已忽略,继续下一轮): {e}")
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("[workflow] 调度器已停止")
        raise


__all__ = [
    "RETRY_DEADLINE",
    "RETRY_INTERVAL_MIN",
    "REVIEW_SLOT",
    "SLOT_LABEL",
    "TIME_WINDOWS",
    "due_windows",
    "mark_attempt",
    "reset_fired",
    "start_workflow_scheduler",
]
