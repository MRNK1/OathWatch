"""/owner health, stats, and version command tests.

The health embed's overall level is fully deterministic: GREEN only when the
Discord client is connected, the refresh loop is running, a refresh (if any)
succeeded, world state is loaded, reporting channels are set, and at least one
guild is configured. A failed refresh or stopped loop forces RED; a fresh,
unconfigured process forces YELLOW.
"""
import discord
import pytest

from oathwatch import access_control, owner, runtime
from oathwatch.formatting import FOOTER_TEXT
from oathwatch.storage import save_config
from oathwatch.world_state import WORLD_STATE

from .mocks import MockBot, MockGuild, MockInteraction

OWNER_USER_ID = owner.OWNER_USER_ID
OWNER_GUILD_ID = owner.OWNER_GUILD_ID
REPORTING_ENVS = ("BOT_STATUS_CHANNEL_ID", "BOT_LOG_CHANNEL_ID", "BOT_ERROR_CHANNEL_ID")


def _reply(interaction):
    return interaction.replies[0]


def _fields(embed):
    return {f.name: f.value for f in embed.fields}


def _set_healthy_environment(monkeypatch):
    """Configure everything the health embed needs to reach GREEN."""
    monkeypatch.setattr(owner, "_refresh_loop_running", lambda: True)
    for name in REPORTING_ENVS:
        monkeypatch.setenv(name, "1")
    WORLD_STATE["last_updated"] = 1000
    save_config({"guilds": {
        "111": {"channel_id": 1, "notify_enabled": True, "boards": {}},
    }})
    runtime.record_refresh(1.0, ok=True)


class TestHealthCommand:
    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_healthy_state_is_green(self, monkeypatch):
        _set_healthy_environment(monkeypatch)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=MockBot())

        await owner._health(interaction)

        reply = _reply(interaction)
        assert reply["ephemeral"] is True
        embed = reply["embed"]
        assert embed.title == "🩺 OathWatch Health"
        assert embed.color == discord.Color.green()
        assert "GREEN" in embed.description
        assert embed.footer.text == FOOTER_TEXT
        fields = _fields(embed)
        assert fields["Discord API"] == "🟢 Connected"
        assert fields["Background loop"] == "🟢 Running"
        assert fields["Hypixel API / refresh"] == "✅ Last refresh ok"
        assert fields["Configuration"] == "1 guild(s)"
        assert fields["World state"] == "🟢 Loaded"
        assert fields["Reporting channels"] == "🟢 All set"

    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_failed_refresh_forces_red(self, monkeypatch):
        _set_healthy_environment(monkeypatch)
        runtime.record_refresh(2.0, ok=False, error="API request failed")
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=MockBot())

        await owner._health(interaction)

        embed = _reply(interaction)["embed"]
        assert embed.color == discord.Color.red()
        assert "RED" in embed.description
        assert "API request failed" in _fields(embed)["Hypixel API / refresh"]

    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_stopped_loop_forces_red(self, monkeypatch):
        _set_healthy_environment(monkeypatch)
        monkeypatch.setattr(owner, "_refresh_loop_running", lambda: False)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=MockBot())

        await owner._health(interaction)

        embed = _reply(interaction)["embed"]
        assert embed.color == discord.Color.red()
        assert _fields(embed)["Background loop"] == "🔴 Stopped"

    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_fresh_unconfigured_process_is_yellow(self, monkeypatch):
        monkeypatch.setattr(owner, "_refresh_loop_running", lambda: True)
        for name in REPORTING_ENVS:
            monkeypatch.setenv(name, "1")
        # No world state, no configured guilds, and no refresh yet.
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=MockBot())

        await owner._health(interaction)

        embed = _reply(interaction)["embed"]
        assert embed.color == discord.Color.gold()
        assert "YELLOW" in embed.description
        fields = _fields(embed)
        assert fields["Hypixel API / refresh"] == "⏳ No refresh yet this session"
        assert fields["World state"] == "🟡 Not updated yet"

    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_non_owner_denied(self):
        interaction = MockInteraction(1, OWNER_GUILD_ID)
        await owner._health(interaction)
        assert _reply(interaction)["content"] == owner.DENIED_MESSAGE


class TestStatsCommand:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_counts_and_totals(self):
        access_control.add_blacklist("222", "Spam", OWNER_USER_ID)
        save_config({"guilds": {
            "111": {"channel_id": 1, "notify_enabled": True,
                    "boards": {"mayor": {"message_id": 1}}},
            "222": {"channel_id": 2, "notify_enabled": True,
                    "boards": {"mayor": {"message_id": 2},
                              "election": {"message_id": 3}}},
        }})
        runtime.record_refresh(3.0, ok=True)
        runtime.record_refresh(7.0, ok=True)
        bot = MockBot(guilds=[MockGuild(111, "GuildA", object())])
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=bot)

        await owner._stats(interaction)

        reply = _reply(interaction)
        assert reply["ephemeral"] is True
        embed = reply["embed"]
        assert embed.title == "📊 OathWatch Stats"
        assert embed.color == discord.Color.blue()
        fields = _fields(embed)
        assert fields["Version"] == owner.__version__
        assert fields["Guilds (total)"] == "1"
        assert fields["Configured"] == "2"
        assert fields["Allowed"] == "1"
        assert fields["Blocked"] == "1"
        assert fields["Boards — mayor"] == "2"
        assert fields["Boards — election"] == "1"
        assert fields["Boards — tracked"] == "3"
        assert fields["Refreshes since start"] == "2"
        assert fields["Avg refresh"] == "5.0s"
        assert fields["Longest refresh"] == "7.0s"

    @pytest.mark.usefixtures("isolated_storage")
    async def test_non_owner_denied(self):
        interaction = MockInteraction(1, OWNER_GUILD_ID)
        await owner._stats(interaction)
        assert _reply(interaction)["content"] == owner.DENIED_MESSAGE


class TestVersionCommand:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_embed_fields(self):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=MockBot())

        await owner._version(interaction)

        reply = _reply(interaction)
        assert reply["ephemeral"] is True
        embed = reply["embed"]
        assert embed.title == "ℹ️ OathWatch Version"
        fields = _fields(embed)
        assert fields["Version"] == owner.__version__
        assert fields["Python"].count(".") == 2
        assert fields["discord.py"]
        assert fields["Platform"]
        assert fields["Started"].startswith("<t:")
        assert fields["Uptime"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_non_owner_denied(self):
        interaction = MockInteraction(1, OWNER_GUILD_ID)
        await owner._version(interaction)
        assert _reply(interaction)["content"] == owner.DENIED_MESSAGE
