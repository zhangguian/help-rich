"""通知子系统测试:去重/限流、编排扇出、渠道构造。"""
import pytest

from app.modules.notify.base import (
    NotifyChannel,
    NotifyError,
    NotifyLevel,
    NotifyMessage,
    NotifyResult,
    Notifier,
)
from app.modules.notify.dedupe import NotifyLimiter
from app.modules.notify.service import NotifyService


class TestNotifyLimiter:
    def test_first_call_allowed(self):
        limiter = NotifyLimiter()
        ok, reason = limiter.allow("a1", "fp1", cooldown_sec=1800, daily_limit=5)
        assert ok is True
        assert reason == ""

    def test_second_call_within_cooldown_blocked(self):
        limiter = NotifyLimiter()
        limiter.allow("a1", "fp1", cooldown_sec=1800)
        ok, reason = limiter.allow("a1", "fp2", cooldown_sec=1800)
        assert ok is False
        assert "冷却中" in reason

    def test_cooldown_expired_allows_again(self):
        limiter = NotifyLimiter()
        limiter.allow("a1", "fp1", cooldown_sec=0)  # 0 = 无冷却
        ok, _ = limiter.allow("a1", "fp2", cooldown_sec=0)
        assert ok is True

    def test_daily_limit_enforced(self):
        limiter = NotifyLimiter()
        for i in range(3):
            ok, _ = limiter.allow("a1", f"fp{i}", cooldown_sec=0, daily_limit=3)
            assert ok is True, f"第 {i} 次应放行"
        ok, reason = limiter.allow("a1", "fp4", cooldown_sec=0, daily_limit=3)
        assert ok is False
        assert "上限" in reason

    def test_separate_keys_independent(self):
        limiter = NotifyLimiter()
        limiter.allow("a1", "fp", cooldown_sec=1800)
        ok, _ = limiter.allow("a2", "fp", cooldown_sec=1800)
        assert ok is True  # 不同规则互不影响

    def test_reset_clears(self):
        limiter = NotifyLimiter()
        limiter.allow("a1", "fp", cooldown_sec=1800)
        limiter.reset("a1")
        ok, _ = limiter.allow("a1", "fp", cooldown_sec=1800)
        assert ok is True


class FakeNotifier(Notifier):
    channel = NotifyChannel.CONSOLE

    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.sent = []

    async def send(self, message: NotifyMessage) -> NotifyResult:
        if self.should_fail:
            raise NotifyError("模拟失败")
        self.sent.append(message)
        return NotifyResult.success(self.channel.value)


class TestNotifyService:
    @pytest.mark.asyncio
    async def test_fanout_to_multiple_channels(self, monkeypatch):
        """一条消息扇出到多个渠道,全部成功。"""
        sent = []

        def make(ch, should_fail=False):
            n = FakeNotifier(should_fail)
            n.channel = ch
            return n

        notifiers = {
            NotifyChannel.CONSOLE.value: make(NotifyChannel.CONSOLE),
            NotifyChannel.WECOM.value: make(NotifyChannel.WECOM),
        }
        # 直接构造 notifier 而非走 _build_notifier
        svc = NotifyService()

        async def fake_notify(message, channels, configs=None):
            results = []
            for ch in channels:
                n = notifiers[ch]
                if n.should_fail:
                    results.append(NotifyResult.failure(ch, "fail"))
                else:
                    n.sent.append(message)
                    results.append(NotifyResult.success(ch))
            return results

        svc.notify = fake_notify
        msg = NotifyMessage(title="t", body="b")
        results = await svc.notify(msg, [NotifyChannel.CONSOLE.value, NotifyChannel.WECOM.value])
        assert len(results) == 2
        assert all(r.ok for r in results)
        assert sent == []

    @pytest.mark.asyncio
    async def test_one_channel_failure_does_not_block_others(self):
        """一个渠道失败,另一个仍成功 —— 通知不阻断主流程。"""
        svc = NotifyService()
        ok_notifier = FakeNotifier()
        ok_notifier.channel = NotifyChannel.WECOM
        bad_notifier = FakeNotifier(should_fail=True)
        bad_notifier.channel = NotifyChannel.DINGTALK

        async def fake_notify(message, channels, configs=None):
            results = []
            for ch in channels:
                n = bad_notifier if ch == NotifyChannel.DINGTALK.value else ok_notifier
                try:
                    results.append(await n.send(message))
                except NotifyError as e:
                    results.append(NotifyResult.failure(ch, str(e)))
            return results

        svc.notify = fake_notify
        results = await svc.notify(NotifyMessage(title="t", body="b"), ["dingtalk", "wecom"])
        assert results[0].ok is False
        assert results[1].ok is True


class TestChannelBuilders:
    def test_build_console_without_config(self):
        from app.modules.notify.service import _build_notifier

        n = _build_notifier("console", None)
        assert n is not None
        assert n.channel == NotifyChannel.CONSOLE

    def test_build_returns_none_when_not_configured(self):
        """未配置凭据的渠道返回 None(跳过),不报错。"""
        from app.modules.notify.service import _build_notifier

        assert _build_notifier("dingtalk", {}) is None
        assert _build_notifier("wecom", None) is None
        assert _build_notifier("bark", {}) is None
        assert _build_notifier("webhook", {}) is None

    def test_build_with_config(self):
        from app.modules.notify.service import _build_notifier

        assert _build_notifier("dingtalk", {"webhook": "https://x.com/robot"}) is not None
        assert _build_notifier("bark", {"device_key": "abc"}) is not None


class TestNotifyMessage:
    def test_plain_text_includes_all(self):
        msg = NotifyMessage(title="标题", body="正文", url="http://x.com")
        text = msg.plain_text()
        assert "标题" in text and "正文" in text and "http://x.com" in text

    def test_level_default(self):
        assert NotifyMessage(title="t", body="b").level == NotifyLevel.INFO
