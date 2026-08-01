"""Setup-system tests using mock Discord objects."""
import discord
import pytest

from board_registry import UnknownBoardError
from setup import SetupError, run_setup, run_unsetup, update_guild_boards
from storage import load_config

from .mocks import MockBot, MockChannel, MockGuild, MockPerms, MockResponse


@pytest.mark.usefixtures("isolated_storage", "reset_world_state")
class TestRunSetup:
    async def test_places_requested_boards(self):
        channel = MockChannel(10, MockGuild(1, "TestGuild", object()))
        summary = await run_setup("1", channel,
                                  board_keys=["mayor", "election"],
                                  notify=True)
        cfg = load_config()
        assert set(cfg["guilds"]["1"]["boards"]) == {"mayor", "election"}
        assert len(channel.messages) == 2
        assert "Mayor Board" in summary
        assert "Election Board" in summary

    async def test_mayor_only(self):
        channel = MockChannel(11, MockGuild(1, "TestGuild", object()))
        await run_setup("1", channel, board_keys=["mayor"], notify=True)
        cfg = load_config()
        assert set(cfg["guilds"]["1"]["boards"]) == {"mayor"}

    async def test_repeat_setup_updates_in_place(self):
        channel = MockChannel(12, MockGuild(1, "TestGuild", object()))
        await run_setup("1", channel,
                        board_keys=["mayor", "election"], notify=True)
        first = load_config()
        await run_setup("1", channel,
                        board_keys=["mayor", "election"], notify=True)
        second = load_config()
        assert first["guilds"]["1"]["boards"] == second["guilds"]["1"]["boards"]
        assert len(channel.messages) == 2  # no duplicates

    async def test_unknown_board_key_raises(self):
        channel = MockChannel(13, MockGuild(1, "TestGuild", object()))
        with pytest.raises(UnknownBoardError):
            await run_setup("1", channel, board_keys=["nope"], notify=True)

    async def test_missing_permissions_raise(self):
        guild = MockGuild(1, "TestGuild", object())
        channel = MockChannel(14, guild, perms=MockPerms(
            send_messages=False, embed_links=False, read_message_history=False))
        with pytest.raises(SetupError) as exc:
            await run_setup("1", channel, board_keys=["mayor"], notify=True)
        assert "Send Messages" in str(exc.value)

    async def test_move_board_to_another_channel(self):
        guild = MockGuild(1, "GuildB", object())
        old_channel = MockChannel(31, guild)
        new_channel = MockChannel(32, guild)
        guild.channels = {31: old_channel, 32: new_channel}

        await run_setup("1", old_channel,
                        board_keys=["mayor", "election"], notify=True)
        old_ids = {k: v["message_id"]
                   for k, v in load_config()["guilds"]["1"]["boards"].items()}
        assert len(old_channel.messages) == 2

        await run_setup("1", new_channel,
                        board_keys=["mayor", "election"], notify=True)

        cfg = load_config()["guilds"]["1"]
        assert cfg["channel_id"] == 32
        assert len(old_channel.messages) == 0  # orphans removed
        assert len(new_channel.messages) == 2
        for key in ("mayor", "election"):
            new_id = cfg["boards"][key]["message_id"]
            assert new_id != old_ids[key]
            assert new_id in new_channel.messages

    async def test_move_when_old_board_already_deleted(self):
        guild = MockGuild(1, "GuildC", object())
        old_channel = MockChannel(33, guild)
        new_channel = MockChannel(34, guild)
        guild.channels = {33: old_channel, 34: new_channel}

        await run_setup("1", old_channel, board_keys=["mayor"], notify=True)
        old_id = load_config()["guilds"]["1"]["boards"]["mayor"]["message_id"]
        del old_channel.messages[old_id]  # a user already deleted the board

        await run_setup("1", new_channel, board_keys=["mayor"], notify=True)

        cfg = load_config()["guilds"]["1"]
        new_id = cfg["boards"]["mayor"]["message_id"]
        assert new_id != old_id
        assert cfg["channel_id"] == 34
        assert new_id in new_channel.messages
        assert len(new_channel.messages) == 1

    @pytest.mark.parametrize("exc", [
        discord.Forbidden(MockResponse(403), "no access"),
        discord.HTTPException(MockResponse(500), "boom"),
    ])
    async def test_move_when_old_board_delete_fails(self, exc):
        guild = MockGuild(1, "GuildD", object())
        old_channel = MockChannel(35, guild)
        new_channel = MockChannel(36, guild)
        guild.channels = {35: old_channel, 36: new_channel}

        await run_setup("1", old_channel, board_keys=["mayor"], notify=True)
        old_id = load_config()["guilds"]["1"]["boards"]["mayor"]["message_id"]

        async def failing_fetch(msg_id):
            raise exc
        old_channel.fetch_message = failing_fetch

        await run_setup("1", new_channel, board_keys=["mayor"], notify=True)

        cfg = load_config()["guilds"]["1"]
        new_id = cfg["boards"]["mayor"]["message_id"]
        assert new_id != old_id
        assert new_id in new_channel.messages
        # The undeletable orphan stays behind but is no longer tracked.
        assert old_id in old_channel.messages
        assert old_id not in cfg["boards"]["mayor"].values()

    async def test_repeated_setup_after_move_keeps_single_board(self):
        guild = MockGuild(1, "GuildE", object())
        old_channel = MockChannel(37, guild)
        new_channel = MockChannel(38, guild)
        guild.channels = {37: old_channel, 38: new_channel}

        await run_setup("1", old_channel,
                        board_keys=["mayor", "election"], notify=True)
        await run_setup("1", new_channel,
                        board_keys=["mayor", "election"], notify=True)
        await run_setup("1", new_channel,
                        board_keys=["mayor", "election"], notify=True)

        cfg = load_config()["guilds"]["1"]
        assert len(old_channel.messages) == 0
        assert len(new_channel.messages) == 2
        # exactly one tracked message per board type, no duplicates
        assert len(cfg["boards"]) == 2
        assert len({v["message_id"] for v in cfg["boards"].values()}) == 2


@pytest.mark.usefixtures("isolated_storage", "reset_world_state")
class TestUpdateGuildBoards:
    async def test_recreates_deleted_board(self):
        channel = MockChannel(20, MockGuild(301, "GuildC", object()))
        bot = MockBot({20: channel})
        await run_setup("301", channel,
                        board_keys=["mayor", "election"], notify=True)
        old_id = load_config()["guilds"]["301"]["boards"]["election"]["message_id"]
        del channel.messages[old_id]  # a user deleted the board

        await update_guild_boards(bot)

        new_id = load_config()["guilds"]["301"]["boards"]["election"]["message_id"]
        assert new_id != old_id
        assert new_id in channel.messages


@pytest.mark.usefixtures("isolated_storage", "reset_world_state")
class TestUnsetup:
    async def test_removes_config_and_deletes_boards(self):
        channel = MockChannel(30, MockGuild(101, "GuildA", object()))
        bot = MockBot({30: channel})
        await run_setup("101", channel,
                        board_keys=["mayor", "election"], notify=True)
        await run_unsetup(bot, "101", "GuildA")
        cfg = load_config()
        assert "101" not in cfg["guilds"]
        assert len(channel.messages) == 0

    async def test_noop_when_not_configured(self):
        summary = await run_unsetup(MockBot(), "999", "Ghost Guild")
        assert "was not configured" in summary
