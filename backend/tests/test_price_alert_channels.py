"""到价提醒的渠道路由(规则未指定渠道时 → 跟随全局已启用渠道)。

**回归来源**:`_channels_for` 的注释写着「规则未指定渠道时,跟随全局已启用的渠道」,
实现却硬编码 `return ["console"]` —— 与注释相反。
后果:用户在「通知设置」里把**桌面通知**打开、也点过「测试弹窗」看到能弹,
但到价提醒**永远不会**走桌面渠道,只有后端日志 → 「为什么我电脑上没弹窗?」。

本文件锁住这条语义。
"""
import asyncio
from types import SimpleNamespace

from app.modules.alert.service import price_alert_service


def _alert(channels_json=None):
    """规则行桩(duck typing:只需要 channels_json)。"""
    return SimpleNamespace(channels_json=channels_json)


def _patch_enabled(monkeypatch, channels):
    async def fake_enabled():
        return list(channels)

    monkeypatch.setattr(
        "app.modules.alert.service.notify_service.enabled_channels", fake_enabled
    )


class TestChannelRouting:
    def test_follows_globally_enabled_channels(self, monkeypatch):
        """规则没指定渠道 → 跟随全局已启用渠道(桌面通知开了就要真的走桌面)"""
        _patch_enabled(monkeypatch, ["console", "desktop"])
        got = asyncio.run(price_alert_service._channels_for(_alert()))
        assert got == ["console", "desktop"]

    def test_explicit_channels_win(self, monkeypatch):
        """规则自己指定了渠道 → 以规则为准(不跟全局)"""
        _patch_enabled(monkeypatch, ["console", "desktop"])
        got = asyncio.run(price_alert_service._channels_for(_alert('["bark"]')))
        assert got == ["bark"]

    def test_falls_back_to_console_when_none_enabled(self, monkeypatch):
        """一个渠道都没启用 → 兜底 console(宁可只有日志也不要什么都不发)"""
        _patch_enabled(monkeypatch, [])
        got = asyncio.run(price_alert_service._channels_for(_alert()))
        assert got == ["console"]

    def test_falls_back_to_console_when_read_fails(self, monkeypatch):
        """读配置炸了 → 兜底 console,不能让提醒整条链路崩掉"""

        async def boom():
            raise RuntimeError("配置读不到")

        monkeypatch.setattr(
            "app.modules.alert.service.notify_service.enabled_channels", boom
        )
        got = asyncio.run(price_alert_service._channels_for(_alert()))
        assert got == ["console"]

    def test_broken_json_falls_back(self, monkeypatch):
        """channels_json 坏了 → 不抛,继续按全局渠道走"""
        _patch_enabled(monkeypatch, ["console", "desktop"])
        got = asyncio.run(price_alert_service._channels_for(_alert("不是 JSON")))
        assert got == ["console", "desktop"]


class TestEnabledChannelsAgreesWithPanel:
    """`notify_service.enabled_channels()` 必须与「通知设置」面板显示的一致。

    面板把 console 显示为**默认启用**(没有数据库行也算勾上),
    而 `enabled_channels()` 若只读数据库行 → console 会被漏掉 →
    「面板上勾着的渠道收不到消息」。
    """

    def test_console_counts_as_enabled_without_db_row(self, monkeypatch):
        from app.modules.notify.service import notify_service

        class _Row:
            def __init__(self, channel, enabled):
                self.channel = channel
                self.enabled = enabled

        async def fake_list_all():
            # 只有 desktop 有行;console 没有行(默认启用)
            return [_Row("desktop", True)]

        monkeypatch.setattr(
            "app.modules.notify.config_repository.notify_config_repo.list_all", fake_list_all
        )
        got = asyncio.run(notify_service.enabled_channels())
        assert "console" in got
        assert "desktop" in got

    def test_explicitly_disabled_console_is_excluded(self, monkeypatch):
        from app.modules.notify.service import notify_service

        class _Row:
            def __init__(self, channel, enabled):
                self.channel = channel
                self.enabled = enabled

        async def fake_list_all():
            return [_Row("console", False), _Row("desktop", True)]

        monkeypatch.setattr(
            "app.modules.notify.config_repository.notify_config_repo.list_all", fake_list_all
        )
        got = asyncio.run(notify_service.enabled_channels())
        assert "console" not in got
        assert "desktop" in got
