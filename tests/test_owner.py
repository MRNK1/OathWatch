"""Owner-only command group tests.

Covers the security contract: /owner commands are guild-scoped to the owner
guild only (never global, never in public servers), only the owner may
execute them, every reply is ephemeral, and the three command behaviours
(status, refresh, shutdown) work end to end with mocked Discord objects.
"""
import discord
import pytest

from oathwatch import access_control, owner
from oathwatch import bot as bot_module
from oathwatch.refresh import RefreshResult, send_mayor_change_notification
from oathwatch.setup import update_guild_boards
from oathwatch.storage import load_config, save_config

from .mocks import MockBot, MockChannel, MockGuild, MockInteraction

OWNER_USER_ID = owner.OWNER_USER_ID
OWNER_GUILD_ID = owner.OWNER_GUILD_ID
WHITELISTED_GUILD = "111111111111111111"
BLACKLISTED_GUILD = "222222222222222222"
PLAIN_GUILD = "333333333333333333"


class TestGuildScoping:
    def test_owner_group_scoped_to_owner_guild(self):
        assert owner.owner_group._guild_ids == [OWNER_GUILD_ID]

    def test_every_subcommand_is_guild_scoped(self):
        # Subcommands inherit their parent group's guild scope, so the whole
        # /owner group is restricted to the owner guild.
        for command in owner.owner_group.walk_commands():
            assert command.root_parent._guild_ids == [OWNER_GUILD_ID]

    def test_owner_group_registered_only_in_owner_guild(self):
        guild_commands = bot_module.bot.tree.get_commands(
            guild=discord.Object(id=OWNER_GUILD_ID)
        )
        assert owner.owner_group in guild_commands

    def test_global_sync_excludes_owner_group(self):
        # get_commands() with no guild returns only global commands; the
        # guild-scoped /owner group must never appear there.
        global_commands = bot_module.bot.tree.get_commands()
        assert owner.owner_group not in global_commands


class TestPermission:
    async def test_non_owner_denied_ephemeral(self):
        interaction = MockInteraction(user_id=1, guild_id=OWNER_GUILD_ID)
        denied = await owner._deny_non_owner(interaction)
        assert denied is True
        assert interaction.replies[0]["ephemeral"] is True
        assert interaction.replies[0]["content"] == "You do not have permission to use this command."

    async def test_owner_in_public_guild_denied(self):
        interaction = MockInteraction(user_id=OWNER_USER_ID, guild_id=12345)
        denied = await owner._deny_non_owner(interaction)
        assert denied is True

    async def test_owner_allowed(self):
        interaction = MockInteraction(user_id=OWNER_USER_ID, guild_id=OWNER_GUILD_ID)
        denied = await owner._deny_non_owner(interaction)
        assert denied is False
        assert interaction.replies == []

    async def test_owner_guild_only_public_user_denied(self):
        # Someone who is not the owner inside the owner guild is still denied.
        interaction = MockInteraction(user_id=999, guild_id=OWNER_GUILD_ID)
        denied = await owner._deny_non_owner(interaction)
        assert denied is True


class TestBotStatus:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_owner_sees_ephemeral_status(self):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._botstatus(interaction)
        assert interaction.replies[0]["ephemeral"] is True
        assert "OathWatch Status" in interaction.replies[0]["content"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_non_owner_gets_denial(self):
        interaction = MockInteraction(user_id=1, guild_id=OWNER_GUILD_ID)
        await owner._botstatus(interaction)
        assert interaction.replies[0]["content"] == "You do not have permission to use this command."

    def test_uptime_format(self):
        assert owner.format_uptime(5) == "5s"
        assert owner.format_uptime(90) == "1m"
        assert owner.format_uptime(3600) == "1h"
        assert owner.format_uptime(2 * 86400 + 3 * 3600) == "2d 3h"


class TestRefresh:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_manual_refresh_replies_and_logs(self, monkeypatch):
        client = MockBot()
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=client)

        async def fake_refresh(bot):
            assert bot is client
            return RefreshResult(ok=True, changed=True, boards_refreshed=3)

        logged = []

        async def fake_log(message):
            logged.append(message)

        monkeypatch.setattr(owner, "perform_refresh", fake_refresh)
        monkeypatch.setattr(owner.reporting, "send_log", fake_log)

        await owner._refresh(interaction)

        assert interaction.followups[0]["ephemeral"] is True
        assert "data changed" in interaction.followups[0]["content"]
        assert logged == ["🛠️ Manual refresh: data changed · 3 boards refreshed"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_failed_refresh_reports_failure(self, monkeypatch):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        async def fake_refresh(bot):
            return RefreshResult(error="API request failed")

        monkeypatch.setattr(owner, "perform_refresh", fake_refresh)

        await owner._refresh(interaction)

        assert "Refresh failed: API request failed" in interaction.followups[0]["content"]


class TestShutdown:
    async def test_shutdown_replies_ephemeral_and_closes(self):
        client = MockBot()
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=client)
        await owner._shutdown(interaction)
        assert interaction.replies[0]["ephemeral"] is True
        assert "Shutting down" in interaction.replies[0]["content"]
        assert client.closed is True


class TestStartupReporting:
    """on_ready must sync both scopes and report startup exactly once."""

    async def _run_on_ready(self, monkeypatch, *, restart):
        sync_calls = []

        async def fake_sync(**kwargs):
            sync_calls.append(kwargs)
            return []

        statuses = []
        logs = []

        async def fake_send_status(message):
            statuses.append(message)

        async def fake_send_log(message):
            logs.append(message)

        monkeypatch.setattr(bot_module.bot.tree, "sync", fake_sync)
        monkeypatch.setattr(bot_module.reporting, "send_status", fake_send_status)
        monkeypatch.setattr(bot_module.reporting, "send_log", fake_send_log)
        monkeypatch.setattr(bot_module.reporting, "is_restart", lambda: restart)
        monkeypatch.setattr(bot_module.reporting, "mark_started", lambda: None)
        # Never actually start the hourly loop during a test.
        monkeypatch.setattr(bot_module.mayor_update_loop, "start", lambda: None)

        await bot_module.on_ready()
        return sync_calls, statuses, logs

    @pytest.mark.usefixtures("isolated_storage")
    async def test_fresh_start_reports_started(self, monkeypatch):
        sync_calls, statuses, logs = await self._run_on_ready(monkeypatch, restart=False)
        assert statuses == ["🟢 Bot Started"]
        assert logs == [f"📦 OathWatch v{bot_module.__version__} started"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_restart_reports_restarted(self, monkeypatch):
        _, statuses, _ = await self._run_on_ready(monkeypatch, restart=True)
        assert statuses == ["🔄 Bot Restarted"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_owner_guild_synced_separately(self, monkeypatch):
        sync_calls, _, _ = await self._run_on_ready(monkeypatch, restart=True)
        assert len(sync_calls) == 2
        # First sync is global; second sync targets only the owner guild.
        assert sync_calls[0] == {}
        assert sync_calls[1]["guild"].id == OWNER_GUILD_ID


class TestHourlyLoop:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_success_sends_exactly_one_log(self, monkeypatch):
        logged = []

        async def fake_send_log(message):
            logged.append(message)

        async def fake_refresh(bot):
            return RefreshResult(ok=True, changed=False)

        monkeypatch.setattr(bot_module, "perform_refresh", fake_refresh)
        monkeypatch.setattr(bot_module.reporting, "send_log", fake_send_log)

        await bot_module.mayor_update_loop.coro()

        assert logged == ["🔄 Hourly refresh: data unchanged · 0 boards refreshed"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_failure_sends_no_log(self, monkeypatch):
        logged = []

        async def fake_send_log(message):
            logged.append(message)

        async def fake_refresh(bot):
            return RefreshResult(error="API request failed")

        monkeypatch.setattr(bot_module, "perform_refresh", fake_refresh)
        monkeypatch.setattr(bot_module.reporting, "send_log", fake_send_log)

        await bot_module.mayor_update_loop.coro()

        assert logged == []


class TestWhitelistCommands:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_enable_persists_and_replies_ephemeral(self):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._whitelist_enable(interaction)
        assert access_control.get_status()["whitelist_enabled"] is True
        assert interaction.replies[0]["ephemeral"] is True

    @pytest.mark.usefixtures("isolated_storage")
    async def test_disable_persists(self):
        access_control.set_whitelist_enabled(True)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._whitelist_disable(interaction)
        assert access_control.get_status()["whitelist_enabled"] is False

    @pytest.mark.usefixtures("isolated_storage")
    async def test_status_shows_mode_and_counts(self):
        access_control.set_whitelist_enabled(True)
        access_control.add_whitelist(WHITELISTED_GUILD)
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam", OWNER_USER_ID)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._whitelist_status(interaction)
        content = interaction.replies[0]["content"]
        assert "Enabled" in content
        assert "**Whitelisted Guilds**: 1" in content
        assert "**Blacklisted Guilds**: 1" in content

    @pytest.mark.usefixtures("isolated_storage")
    async def test_add_remove(self):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._whitelist_add(interaction, WHITELISTED_GUILD)
        assert WHITELISTED_GUILD in access_control.get_status()["whitelist"]
        await owner._whitelist_remove(interaction, WHITELISTED_GUILD)
        assert access_control.get_status()["whitelist"] == []

    @pytest.mark.usefixtures("isolated_storage")
    async def test_list(self):
        access_control.add_whitelist(WHITELISTED_GUILD)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._whitelist_list(interaction)
        assert WHITELISTED_GUILD in interaction.replies[0]["content"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_non_owner_cannot_enable(self):
        interaction = MockInteraction(user_id=1, guild_id=OWNER_GUILD_ID)
        await owner._whitelist_enable(interaction)
        assert access_control.get_status()["whitelist_enabled"] is False
        assert interaction.replies[0]["content"] == owner.DENIED_MESSAGE


class TestBlacklistCommands:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_add_stores_reason_metadata(self):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._blacklist_add(interaction, BLACKLISTED_GUILD, "Spam server")
        entry = access_control.get_status()["blacklist"][BLACKLISTED_GUILD]
        assert entry["reason"] == "Spam server"
        assert entry["added_by"] == OWNER_USER_ID
        assert isinstance(entry["added_at"], int)

    @pytest.mark.usefixtures("isolated_storage")
    async def test_remove(self):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam", OWNER_USER_ID)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._blacklist_remove(interaction, BLACKLISTED_GUILD)
        assert access_control.get_status()["blacklist"] == {}

    @pytest.mark.usefixtures("isolated_storage")
    async def test_list_shows_metadata(self):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam server", OWNER_USER_ID)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)
        await owner._blacklist_list(interaction)
        content = interaction.replies[0]["content"]
        assert BLACKLISTED_GUILD in content
        assert "Spam server" in content
        assert "<t:" in content  # Added At rendered as a Discord timestamp

    @pytest.mark.usefixtures("isolated_storage")
    async def test_non_owner_cannot_blacklist(self):
        interaction = MockInteraction(user_id=1, guild_id=OWNER_GUILD_ID)
        await owner._blacklist_add(interaction, BLACKLISTED_GUILD, "Spam")
        assert access_control.get_status()["blacklist"] == {}
        assert interaction.replies[0]["content"] == owner.DENIED_MESSAGE


class TestCommandGate:
    """interaction_check must disable commands in blocked guilds only."""

    @pytest.mark.usefixtures("isolated_storage")
    async def test_blacklisted_guild_gets_disabled_message(self):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam server", OWNER_USER_ID)
        interaction = MockInteraction(user_id=123, guild_id=int(BLACKLISTED_GUILD))
        allowed = await bot_module.bot.tree.interaction_check(interaction)
        assert allowed is False
        reply = interaction.replies[0]
        assert reply["ephemeral"] is True
        assert "This server is currently disabled." in reply["content"]
        assert "Spam server" in reply["content"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_whitelist_mode_blocks_non_whitelisted(self):
        access_control.set_whitelist_enabled(True)
        access_control.add_whitelist(WHITELISTED_GUILD)

        blocked = MockInteraction(user_id=123, guild_id=int(PLAIN_GUILD))
        assert await bot_module.bot.tree.interaction_check(blocked) is False
        assert "No reason provided." in blocked.replies[0]["content"]

        allowed = MockInteraction(user_id=123, guild_id=int(WHITELISTED_GUILD))
        assert await bot_module.bot.tree.interaction_check(allowed) is True
        assert allowed.replies == []

    @pytest.mark.usefixtures("isolated_storage")
    async def test_allowed_guild_passes_through(self):
        interaction = MockInteraction(user_id=123, guild_id=int(PLAIN_GUILD))
        assert await bot_module.bot.tree.interaction_check(interaction) is True
        assert interaction.replies == []

    @pytest.mark.usefixtures("isolated_storage")
    async def test_owner_guild_always_exempt(self):
        interaction = MockInteraction(user_id=123, guild_id=OWNER_GUILD_ID)
        assert await bot_module.bot.tree.interaction_check(interaction) is True

    @pytest.mark.usefixtures("isolated_storage")
    async def test_direct_message_exempt(self):
        interaction = MockInteraction(user_id=123, guild_id=None)
        assert await bot_module.bot.tree.interaction_check(interaction) is True

    @pytest.mark.usefixtures("isolated_storage")
    async def test_autocomplete_in_blocked_guild_dropped_silently(self):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam", OWNER_USER_ID)
        interaction = MockInteraction(user_id=123, guild_id=int(BLACKLISTED_GUILD))
        interaction.type = discord.InteractionType.autocomplete
        assert await bot_module.bot.tree.interaction_check(interaction) is False
        assert interaction.replies == []


class TestBlockedGuildFeatureSkips:
    """Scheduled refresh, board updates, and notifications skip blocked guilds."""

    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_board_updates_skip_blocked_guild(self):
        # A stored message_id pointing at a deleted message forces the
        # self-heal recreation path. The normalization in load_config() keeps
        # it (a truthy id), so update_guild_boards really would recreate the
        # board if the guild were allowed.
        channel = MockChannel(500, MockGuild(int(PLAIN_GUILD), "GuildC", object()))
        bot = MockBot({500: channel})
        save_config({"guilds": {
            PLAIN_GUILD: {
                "channel_id": 500,
                "notify_enabled": True,
                "boards": {"mayor": {"message_id": 501}},
            },
        }})
        access_control.add_blacklist(PLAIN_GUILD, "Spam", OWNER_USER_ID)

        await update_guild_boards(bot)

        assert channel.messages == {}  # blocked guild: nothing posted/recreated
        # The stale reference is left untouched — no data modified.
        assert load_config()["guilds"][PLAIN_GUILD]["boards"] == {
            "mayor": {"message_id": 501}
        }

    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_board_updates_still_work_for_allowed_guild(self):
        channel = MockChannel(500, MockGuild(int(PLAIN_GUILD), "GuildC", object()))
        bot = MockBot({500: channel})
        save_config({"guilds": {
            PLAIN_GUILD: {
                "channel_id": 500,
                "notify_enabled": True,
                "boards": {"mayor": {"message_id": 501}},
            },
        }})

        await update_guild_boards(bot)

        assert len(channel.messages) == 1  # allowed guild: board recreated
        assert load_config()["guilds"][PLAIN_GUILD]["boards"]["mayor"] != {
            "message_id": 501
        }

    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_notifications_skip_blocked_guild(self):
        channel = MockChannel(500, MockGuild(int(PLAIN_GUILD), "GuildC", object()))
        bot = MockBot({500: channel})
        save_config({"guilds": {
            PLAIN_GUILD: {
                "channel_id": 500,
                "notify_enabled": True,
                "boards": {},
            },
        }})
        access_control.add_blacklist(PLAIN_GUILD, "Spam", OWNER_USER_ID)

        await send_mayor_change_notification(bot, "Mayor changed!")

        assert channel.messages == {}

    @pytest.mark.usefixtures("isolated_storage", "reset_world_state")
    async def test_notifications_sent_to_allowed_guild(self):
        channel = MockChannel(500, MockGuild(int(PLAIN_GUILD), "GuildC", object()))
        bot = MockBot({500: channel})
        save_config({"guilds": {
            PLAIN_GUILD: {
                "channel_id": 500,
                "notify_enabled": True,
                "boards": {},
            },
        }})

        await send_mayor_change_notification(bot, "Mayor changed!")

        assert len(channel.messages) == 1
