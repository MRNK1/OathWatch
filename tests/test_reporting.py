"""Channel-reporting tests (status / log / error) using mock channels."""
import pytest

from oathwatch import reporting

from .mocks import MockBot, MockChannel, MockGuild


@pytest.fixture
def mock_reporting_channels(monkeypatch):
    """Configure a mock bot whose reporting channels record sends."""
    guild = MockGuild(1, "TestGuild", object())
    status_channel = MockChannel(1001, guild)
    log_channel = MockChannel(1002, guild)
    error_channel = MockChannel(1003, guild)
    bot = MockBot({
        1001: status_channel,
        1002: log_channel,
        1003: error_channel,
    })
    reporting.configure(bot)
    monkeypatch.setenv("BOT_STATUS_CHANNEL_ID", "1001")
    monkeypatch.setenv("BOT_LOG_CHANNEL_ID", "1002")
    monkeypatch.setenv("BOT_ERROR_CHANNEL_ID", "1003")
    return bot


def _contents(channel):
    return [msg.content for msg in channel.messages.values()]


class TestStatusAndLogChannels:
    async def test_status_sends_to_status_channel(self, mock_reporting_channels):
        await reporting.send_status("🟢 Bot Started")
        channel = mock_reporting_channels.channels[1001]
        assert _contents(channel) == ["🟢 Bot Started"]

    async def test_log_sends_to_log_channel(self, mock_reporting_channels):
        await reporting.send_log("Hello log")
        channel = mock_reporting_channels.channels[1002]
        assert _contents(channel) == ["Hello log"]

    async def test_unconfigured_channel_is_silent(self, monkeypatch):
        reporting.configure(MockBot({}))
        monkeypatch.delenv("BOT_LOG_CHANNEL_ID", raising=False)
        # Must not raise and must not touch any channel.
        await reporting.send_log("Nope")

    async def test_missing_channel_is_silent(self, monkeypatch):
        reporting.configure(MockBot({}))
        monkeypatch.setenv("BOT_LOG_CHANNEL_ID", "9999")
        await reporting.send_log("Nope")

    async def test_send_failure_is_tolerated(self, mock_reporting_channels, monkeypatch):
        async def boom(*args, **kwargs):
            raise RuntimeError("send failed")

        monkeypatch.setattr(
            mock_reporting_channels.channels[1002], "send", boom
        )
        await reporting.send_log("Nope")


class TestErrorChannel:
    async def test_error_includes_traceback_block(self, mock_reporting_channels):
        try:
            raise ValueError("boom")
        except ValueError as exc:
            await reporting.report_error("Command failed", exc)
        content = _contents(mock_reporting_channels.channels[1003])[0]
        assert "Command failed" in content
        assert "```" in content
        assert "ValueError: boom" in content

    async def test_error_accepts_exc_info_tuple(self, mock_reporting_channels):
        try:
            raise KeyError("k")
        except KeyError:
            await reporting.report_error("Loop crashed", __import__("sys").exc_info())
        content = _contents(mock_reporting_channels.channels[1003])[0]
        assert "KeyError" in content

    async def test_error_without_exception_omits_traceback(self, mock_reporting_channels):
        await reporting.report_error("Permission denied for user 1 in guild 2")
        content = _contents(mock_reporting_channels.channels[1003])[0]
        assert "Permission denied" in content
        assert "```" not in content


class TestStartMarker:
    def test_first_run_is_start_then_restart(self, isolated_storage):
        assert reporting.is_restart() is False
        reporting.mark_started()
        assert reporting.is_restart() is True

    def test_marker_survives_new_instance(self, isolated_storage):
        reporting.mark_started()
        assert reporting.is_restart() is True


class TestStartupLifecycle:
    """Fresh start vs process restart vs gateway reconnect reporting."""

    async def test_fresh_start_sends_started_and_marks(
        self, isolated_storage, mock_reporting_channels
    ):
        assert await reporting.report_startup() == "fresh"
        channel = mock_reporting_channels.channels[1001]
        assert _contents(channel) == ["🟢 Bot Started"]
        # The marker is written so the next process launch reports a restart.
        assert reporting.is_restart() is True

    async def test_restart_sends_restarted(
        self, isolated_storage, mock_reporting_channels
    ):
        reporting.mark_started()
        assert await reporting.report_startup() == "restart"
        channel = mock_reporting_channels.channels[1001]
        assert _contents(channel) == ["🔄 Bot Restarted"]

    async def test_reconnect_sends_reconnected_not_restarted(
        self, isolated_storage, mock_reporting_channels
    ):
        # First on_ready in the process: marker present -> restart.
        reporting.mark_started()
        assert await reporting.report_startup() == "restart"
        # Gateway reconnect fires on_ready again in the same process: this
        # must be reported as a reconnect, never as a second restart.
        assert await reporting.report_startup() == "reconnect"
        channel = mock_reporting_channels.channels[1001]
        assert _contents(channel) == ["🔄 Bot Restarted", "🔁 Bot Reconnected"]

    async def test_fresh_start_then_reconnect(
        self, isolated_storage, mock_reporting_channels
    ):
        # Even when the marker was just written by the fresh start, the next
        # on_ready in the same process is a reconnect, not a restart.
        assert await reporting.report_startup() == "fresh"
        assert await reporting.report_startup() == "reconnect"
        channel = mock_reporting_channels.channels[1001]
        assert _contents(channel) == ["🟢 Bot Started", "🔁 Bot Reconnected"]


class TestShutdownStatus:
    async def test_shutdown_status_sent_once(self, mock_reporting_channels):
        await reporting.send_shutdown_status()
        await reporting.send_shutdown_status()
        channel = mock_reporting_channels.channels[1001]
        assert _contents(channel) == ["🔴 Bot Shutdown"]
