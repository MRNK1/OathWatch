"""Startup validation and guild-removal lifecycle tests."""
import os

import bot
import world_storage
from storage import load_config, save_config

from .mocks import MockGuild


def test_get_missing_env_reports_all(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("HYPIXEL_API_KEY", raising=False)
    assert bot.get_missing_env() == ["DISCORD_TOKEN", "HYPIXEL_API_KEY"]


def test_get_missing_env_empty_when_set(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("HYPIXEL_API_KEY", "y")
    assert bot.get_missing_env() == []


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
