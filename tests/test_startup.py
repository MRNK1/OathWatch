"""Startup validation and guild-removal lifecycle tests."""
import os

import pytest

from oathwatch import bot, world_storage
from oathwatch.storage import load_config, save_config

from .mocks import MockBot, MockChannel, MockGuild, MockInteraction


def test_get_missing_env_reports_all(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("HYPIXEL_API_KEY", raising=False)
    assert bot.get_missing_env() == ["DISCORD_TOKEN", "HYPIXEL_API_KEY"]


def test_get_missing_env_empty_when_set(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("HYPIXEL_API_KEY", "y")
    assert bot.get_missing_env() == []


def test_validate_env_flags_missing_required(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("HYPIXEL_API_KEY", raising=False)
    report = bot.validate_env()
    assert ("DISCORD_TOKEN", True, False) in report
    assert ("HYPIXEL_API_KEY", True, False) in report


def test_validate_env_marks_present_required(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("HYPIXEL_API_KEY", "y")
    report = bot.validate_env()
    present = {name: present for name, _, present in report}
    assert present["DISCORD_TOKEN"] is True
    assert present["HYPIXEL_API_KEY"] is True
    required = {name for name, required, _ in report if required}
    assert required == {"DISCORD_TOKEN", "HYPIXEL_API_KEY"}


def test_validate_env_includes_optional_reporting_channels(monkeypatch):
    for name in ("BOT_STATUS_CHANNEL_ID", "BOT_LOG_CHANNEL_ID", "BOT_ERROR_CHANNEL_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOT_STATUS_CHANNEL_ID", "1")
    report = bot.validate_env()
    names = [name for name, _, _ in report]
    assert "BOT_STATUS_CHANNEL_ID" in names
    assert "BOT_LOG_CHANNEL_ID" in names
    assert "BOT_ERROR_CHANNEL_ID" in names
    present = {name: present for name, _, present in report}
    assert present["BOT_STATUS_CHANNEL_ID"] is True
    assert present["BOT_LOG_CHANNEL_ID"] is False
    assert present["BOT_ERROR_CHANNEL_ID"] is False


def test_log_env_validation_returns_missing_required(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("HYPIXEL_API_KEY", raising=False)
    assert bot._log_env_validation() == ["DISCORD_TOKEN", "HYPIXEL_API_KEY"]


def test_log_env_validation_empty_when_all_set(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("HYPIXEL_API_KEY", "y")
    assert bot._log_env_validation() == []


def test_main_refuses_to_start_without_env(monkeypatch):
    # Prevent main() from re-reading the real .env file.
    monkeypatch.setattr(bot, "load_dotenv", lambda: None)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("HYPIXEL_API_KEY", raising=False)
    assert bot.main() == 1


def test_main_runs_bot_with_valid_env(isolated_storage, monkeypatch):
    monkeypatch.setattr(bot, "load_dotenv", lambda: None)
    monkeypatch.setenv("DISCORD_TOKEN", "fake-token")
    monkeypatch.setenv("HYPIXEL_API_KEY", "fake-key")

    def fake_run(token):
        assert token == "fake-token"
        raise KeyboardInterrupt  # end main() cleanly after it reaches bot.run

    monkeypatch.setattr(bot.bot, "run", fake_run)
    assert bot.main() == 0


class TestOnGuildRemove:
    async def test_removes_only_departed_guild(self, isolated_storage):
        save_config({"guilds": {
            "1": {"channel_id": 1, "notify_enabled": True, "boards": {}},
            "2": {"channel_id": 2, "notify_enabled": True, "boards": {}},
        }})
        await bot.on_guild_remove(MockGuild(1, "Left", object()))
        cfg = load_config()
        assert "1" not in cfg["guilds"]
        assert "2" in cfg["guilds"]

    async def test_preserves_world_state(self, isolated_storage):
        save_config({"guilds": {
            "1": {"channel_id": 1, "notify_enabled": True, "boards": {}},
        }})
        await bot.on_guild_remove(MockGuild(1, "Left", object()))
        assert not os.path.exists(world_storage.WORLD_FILE)

    async def test_noop_when_guild_not_configured(self, isolated_storage):
        save_config({"guilds": {}})
        await bot.on_guild_remove(MockGuild(1, "NeverConfigured", object()))
        assert load_config() == {"guilds": {}}


class TestSetChannel:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_sets_announcement_channel(self):
        guild = MockGuild(123, "Guild", object())
        channel = MockChannel(500, guild)
        client = MockBot({500: channel})
        save_config({"guilds": {
            "123": {"channel_id": None, "notify_enabled": True, "boards": {}},
        }})
        interaction = MockInteraction(123, 123, client=client, guild=guild)

        await bot.setchannel.callback(interaction, channel)

        assert load_config()["guilds"]["123"]["announcement_channel_id"] == 500
        assert "announcement channel" in interaction.replies[0]["content"].lower()

    @pytest.mark.usefixtures("isolated_storage")
    async def test_rejects_channel_from_other_guild(self):
        guild = MockGuild(123, "Guild", object())
        other = MockGuild(999, "Other", object())
        channel = MockChannel(500, other)
        client = MockBot({500: channel})
        interaction = MockInteraction(123, 123, client=client, guild=guild)

        await bot.setchannel.callback(interaction, channel)

        assert "must be in this server" in interaction.replies[0]["content"]
        assert load_config()["guilds"] == {}
