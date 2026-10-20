"""通知去重与限流。

两个正交机制:
- **去重(fingerprint)**:同一条告警在冷却窗口内只推一次,避免价格来回
  穿越阈值时反复轰炸。指纹 = (alert_id, 条件签名, 触发时的价格分桶)。
- **限流(日上限)**:每条规则每天最多推 N 条,防止规则写太宽导致刷屏。

状态放在内存(dict),单进程 uvicorn 够用;重启后清零是可接受的
(限流本来就是"别刷屏",重启后重新计一轮无伤大雅)。
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Entry:
    last_fired: float = 0.0
    fired_today: int = 0
    day: str = ""


@dataclass
class NotifyLimiter:
    """线程安全的去重 + 日限流器。"""

    # alert_key -> 状态
    _entries: dict[str, _Entry] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(
        self,
        alert_key: str,
        fingerprint: str,
        cooldown_sec: int = 1800,
        daily_limit: int = 5,
    ) -> tuple[bool, str]:
        """判断是否允许发送。

        Returns:
            (是否允许, 原因)—— 不允许时给出可展示的原因(冷却中 / 今日已达上限)
        """
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        fp = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]

        with self._lock:
            entry = self._entries.get(alert_key)
            if entry is None:
                entry = _Entry()
                self._entries[alert_key] = entry

            if entry.day != today:  # 跨天重置计数
                entry.day = today
                entry.fired_today = 0

            if entry.last_fired and (now - entry.last_fired) < cooldown_sec:
                remain = int(cooldown_sec - (now - entry.last_fired))
                return False, f"冷却中(剩余 {remain}s)"

            if entry.fired_today >= daily_limit:
                return False, f"今日已达上限({daily_limit} 次)"

            entry.last_fired = now
            entry.last_fingerprint = fp  # type: ignore[attr-defined]
            entry.fired_today += 1
            return True, ""

    def reset(self, alert_key: str | None = None) -> None:
        """重置状态(设置页"重置限流"或测试用)。"""
        with self._lock:
            if alert_key is None:
                self._entries.clear()
            else:
                self._entries.pop(alert_key, None)


# 全局单例
limiter = NotifyLimiter()

__all__ = ["NotifyLimiter", "limiter"]
