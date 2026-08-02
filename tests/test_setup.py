"""Setup-system tests using mock Discord objects."""
import discord
import pytest

from oathwatch.board_health import MAX_CONSECUTIVE_FAILURES
from oathwatch.board_registry import UnknownBoardError
from oathwatch.setup import SetupError, run_setup, run_unsetup, update_guild_boards
from oathwatch.storage import load_config, save_config

from .mocks import (
    MockBot,
    MockChannel,
    MockGuild,
    MockMessage,
    MockPerms,
    MockResponse,
)


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
class TestStaleBoardCleanup:
    """Permanent-failure tracking, threshold cleanup, and recovery."""

    def _dead_channel_bot(self, guild_id, guild_name, board_key, message_id):
        """A bot that cannot see the guild's update channel (it was deleted)."""
        guild = MockGuild(int(guild_id), guild_name, object())
        bot = MockBot({})
        bot.get_guild = lambda gid: guild if gid == int(guild_id) else None
        save_config({"guilds": {
            guild_id: {
                "channel_id": int(guild_id),
                "notify_enabled": True,
                "boards": {board_key: {"message_id": message_id}},
            },
        }})
        return bot

    async def test_deleted_channel_increments_per_board(self):
        bot = self._dead_channel_bot("700", "GuildC", "mayor", 1)
        save_config({"guilds": {
            "700": {
                "channel_id": 700,
                "notify_enabled": True,
                "boards": {
                    "mayor": {"message_id": 1},
                    "election": {"message_id": 2},
                },
            },
        }})

        await update_guild_boards(bot)

        boards = load_config()["guilds"]["700"]["boards"]
        # Every tracked board in a dead channel gets its own counter.
        assert boards["mayor"]["failures"] == 1
        assert boards["election"]["failures"] == 1

    async def test_deleted_channel_cleans_up_after_three_failures(self, monkeypatch):
        logs = []
        async def fake_send_log(message):
            logs.append(message)
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", fake_send_log)

        bot = self._dead_channel_bot("700", "Skyblock Hub", "mayor", 1)

        await update_guild_boards(bot)  # failure 1
        assert load_config()["guilds"]["700"]["boards"]["mayor"]["failures"] == 1
        assert logs == []

        await update_guild_boards(bot)  # failure 2
        assert load_config()["guilds"]["700"]["boards"]["mayor"]["failures"] == 2
        assert logs == []

        await update_guild_boards(bot)  # failure 3 -> cleanup

        boards = load_config()["guilds"]["700"]["boards"]
        assert "mayor" not in boards  # only the stale board reference removed
        assert load_config()["guilds"]["700"]["channel_id"] == 700  # guild kept

        assert len(logs) == 1  # exactly one final cleanup message
        msg = logs[0]
        assert "🧹 Board Cleanup" in msg
        assert "Guild:\nSkyblock Hub" in msg
        assert "Guild ID:\n700" in msg
        assert "Board:\nMayor" in msg
        assert "Reason:\nChannel deleted" in msg
        assert "3 consecutive permanent failures" in msg
        assert "Removed stale board reference from config.json" in msg

        # Never logged again: the reference is gone, so nothing to clean up.
        await update_guild_boards(bot)
        assert len(logs) == 1

    async def test_deleted_channel_cleans_two_boards_same_cycle(self, monkeypatch):
        # The dead-channel branch iterates list(boards); two boards reaching
        # the threshold in one pass must both be cleaned, each logged once.
        logs = []
        async def fake_send_log(message):
            logs.append(message)
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", fake_send_log)

        bot = self._dead_channel_bot("1200", "GuildC", "mayor", 1)
        save_config({"guilds": {
            "1200": {
                "channel_id": 1200,
                "notify_enabled": True,
                "boards": {
                    "mayor": {"message_id": 1, "failures": 2},
                    "election": {"message_id": 2, "failures": 2},
                },
            },
        }})

        await update_guild_boards(bot)

        boards = load_config()["guilds"]["1200"]["boards"]
        assert boards == {}  # both stale references removed

        cleanup = [msg for msg in logs if "🧹 Board Cleanup" in msg]
        assert len(cleanup) == 2  # exactly one cleanup message per board
        logged = "".join(cleanup)
        assert "Board:\nMayor" in logged
        assert "Board:\nElection" in logged

    async def test_channel_deleted_mid_send_is_permanent(self, monkeypatch):
        # bot.get_channel still resolves the cached channel object, but the
        # channel is actually gone: Discord answers send() with a NotFound.
        channel = MockChannel(800, MockGuild(800, "GuildC", object()))
        bot = MockBot({800: channel})
        save_config({"guilds": {
            "800": {
                "channel_id": 800,
                "notify_enabled": True,
                "boards": {"mayor": {"message_id": 1}},
            },
        }})

        async def failing_send(*args, **kwargs):
            raise discord.NotFound(MockResponse(404), "channel gone")
        channel.send = failing_send

        await update_guild_boards(bot)

        boards = load_config()["guilds"]["800"]["boards"]
        assert boards["mayor"]["failures"] == 1

    @pytest.mark.parametrize("exc", [
        discord.HTTPException(MockResponse(500), "boom"),
        discord.Forbidden(MockResponse(403), "no access"),
    ])
    async def test_transient_errors_never_increment(self, monkeypatch, exc):
        channel = MockChannel(800, MockGuild(800, "GuildC", object()))
        bot = MockBot({800: channel})
        save_config({"guilds": {
            "800": {
                "channel_id": 800,
                "notify_enabled": True,
                "boards": {"mayor": {"message_id": 1}},
            },
        }})

        message = MockMessage(1, channel=channel)
        channel.messages[1] = message
        async def failing_edit(**kwargs):
            raise exc
        message.edit = failing_edit

        for _ in range(MAX_CONSECUTIVE_FAILURES + 2):
            await update_guild_boards(bot)

        boards = load_config()["guilds"]["800"]["boards"]
        # Transient failures never touch the counter and never remove the board.
        assert boards["mayor"] == {"message_id": 1}

    async def test_two_boards_both_cleaned_in_same_cycle(self, monkeypatch):
        # Two boards both reach the threshold in the SAME refresh cycle.
        # The main board-update loop iterates the live boards dict directly;
        # removing the first stale board mid-iteration must not abort
        # processing of the second, or the second board is never cleaned and
        # the refresh raises. Regression guard for the pop-during-iteration
        # bug (the dead-channel branch uses list(boards) and is fine, but the
        # channel-live path must too).
        logs = []
        async def fake_send_log(message):
            logs.append(message)
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", fake_send_log)

        # Channel object is live, but Discord answers send() with a NotFound
        # (the channel was deleted mid-check): place_board raises
        # BoardPermanentError for both boards.
        channel = MockChannel(900, MockGuild(900, "GuildC", object()))
        async def failing_send(*args, **kwargs):
            raise discord.NotFound(MockResponse(404), "channel gone")
        channel.send = failing_send
        bot = MockBot({900: channel})

        save_config({"guilds": {
            "900": {
                "channel_id": 900,
                "notify_enabled": True,
                "boards": {
                    "mayor": {"message_id": 1, "failures": 2},
                    "election": {"message_id": 2, "failures": 2},
                },
            },
        }})

        # update_guild_boards promises never to raise.
        await update_guild_boards(bot)

        boards = load_config()["guilds"]["900"]["boards"]
        assert boards == {}  # both stale references removed

        cleanup = [msg for msg in logs if "🧹 Board Cleanup" in msg]
        assert len(cleanup) == 2  # exactly one cleanup message per board
        logged = "".join(cleanup)
        assert "Board:\nMayor" in logged
        assert "Board:\nElection" in logged

    async def test_save_failure_defers_cleanup(self, monkeypatch):
        # The board hits the cleanup threshold but save_config raises (disk
        # full, permission error): the pipeline must not abort, the removal
        # must not be persisted, and the board is retried next refresh.
        logs = []
        errors = []
        async def fake_send_log(message):
            logs.append(message)
        async def fake_report_error(title, exc=None):
            errors.append((title, exc))
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", fake_send_log)
        monkeypatch.setattr("oathwatch.setup.reporting.report_error", fake_report_error)

        channel = MockChannel(1000, MockGuild(1000, "GuildC", object()))
        async def failing_send(*args, **kwargs):
            raise discord.NotFound(MockResponse(404), "channel gone")
        channel.send = failing_send
        bot = MockBot({1000: channel})

        save_config({"guilds": {
            "1000": {
                "channel_id": 1000,
                "notify_enabled": True,
                "boards": {"mayor": {"message_id": 1, "failures": 2}},
            },
        }})

        def failing_save(data):
            raise OSError("disk full")
        monkeypatch.setattr("oathwatch.setup.save_config", failing_save)

        # update_guild_boards promises never to raise.
        await update_guild_boards(bot)

        # Disk is untouched: the board stays at its pre-cleanup counter and
        # will be retried on the next refresh.
        boards = load_config()["guilds"]["1000"]["boards"]
        assert boards["mayor"]["failures"] == 2
        assert boards["mayor"]["message_id"] == 1

        # No cleanup message (nothing was persisted), but the failure is
        # reported to the error channel and the deferral is logged.
        assert [msg for msg in logs if "🧹 Board Cleanup" in msg] == []
        assert len(errors) == 1
        assert "mayor" in errors[0][0]
        assert isinstance(errors[0][1], OSError)
        deferred = [msg for msg in logs if "⚠️ Board Cleanup Deferred" in msg]
        assert len(deferred) == 1
        assert "Board:\nMayor" in deferred[0]
        assert "will be retried on the next refresh" in deferred[0]

    async def test_save_failure_does_not_block_remaining_boards(self, monkeypatch):
        # A failed save for the first stale board must not abort processing of
        # the second: election is still counted this cycle even though mayor's
        # cleanup is deferred.
        logs = []
        async def fake_send_log(message):
            logs.append(message)
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", fake_send_log)

        channel = MockChannel(1100, MockGuild(1100, "GuildC", object()))
        async def failing_send(*args, **kwargs):
            raise discord.NotFound(MockResponse(404), "channel gone")
        channel.send = failing_send
        bot = MockBot({1100: channel})

        save_config({"guilds": {
            "1100": {
                "channel_id": 1100,
                "notify_enabled": True,
                "boards": {
                    "mayor": {"message_id": 1, "failures": 2},  # threshold, save fails
                    "election": {"message_id": 2},               # first failure, must count
                },
            },
        }})

        real_save = save_config
        attempts = {"n": 0}
        def flaky_save(data):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise OSError("disk full")
            real_save(data)
        monkeypatch.setattr("oathwatch.setup.save_config", flaky_save)

        await update_guild_boards(bot)

        boards = load_config()["guilds"]["1100"]["boards"]
        # Mayor's cleanup was deferred (still on disk, retried next refresh)...
        assert boards["mayor"]["failures"] == 2
        # ...but election was still processed on this cycle.
        assert boards["election"]["failures"] == 1

        # Exactly one deferral log; nothing was cleaned or double-processed.
        deferred = [msg for msg in logs if "⚠️ Board Cleanup Deferred" in msg]
        assert len(deferred) == 1
        assert [msg for msg in logs if "🧹 Board Cleanup" in msg] == []

    async def test_report_failure_cannot_abort_persisted_cleanup(self, monkeypatch):
        # A log-channel failure that surfaces AFTER a successful save must
        # never abort the refresh nor undo the persisted cleanup: both boards
        # were already removed from config, and that removal stands.
        async def exploding_send_log(message):
            raise RuntimeError("log channel unreachable")
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", exploding_send_log)

        channel = MockChannel(1300, MockGuild(1300, "GuildC", object()))
        async def failing_send(*args, **kwargs):
            raise discord.NotFound(MockResponse(404), "channel gone")
        channel.send = failing_send
        bot = MockBot({1300: channel})

        save_config({"guilds": {
            "1300": {
                "channel_id": 1300,
                "notify_enabled": True,
                "boards": {
                    "mayor": {"message_id": 1, "failures": 2},
                    "election": {"message_id": 2, "failures": 2},
                },
            },
        }})

        # update_guild_boards promises never to raise.
        await update_guild_boards(bot)

        # Both cleanups persisted despite the log-channel explosion.
        boards = load_config()["guilds"]["1300"]["boards"]
        assert boards == {}

    async def test_report_failure_after_rollback_still_recovers(self, monkeypatch):
        # Worst case: the save fails AND the error channel / log channel also
        # throw. The board must still be rolled back to its pre-cleanup state
        # (retried next refresh) and the refresh must not abort.
        async def exploding_report_error(title, exc=None):
            raise RuntimeError("error channel unreachable")
        monkeypatch.setattr(
            "oathwatch.setup.reporting.report_error", exploding_report_error
        )
        async def exploding_send_log(message):
            raise RuntimeError("log channel unreachable")
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", exploding_send_log)

        channel = MockChannel(1400, MockGuild(1400, "GuildC", object()))
        async def failing_send(*args, **kwargs):
            raise discord.NotFound(MockResponse(404), "channel gone")
        channel.send = failing_send
        bot = MockBot({1400: channel})

        save_config({"guilds": {
            "1400": {
                "channel_id": 1400,
                "notify_enabled": True,
                "boards": {"mayor": {"message_id": 1, "failures": 2}},
            },
        }})

        def failing_save(data):
            raise OSError("disk full")
        monkeypatch.setattr("oathwatch.setup.save_config", failing_save)

        # update_guild_boards promises never to raise.
        await update_guild_boards(bot)

        # Rolled back to the pre-cleanup counter; nothing persisted, so the
        # board is retried on the next refresh.
        boards = load_config()["guilds"]["1400"]["boards"]
        assert boards["mayor"]["failures"] == 2
        assert boards["mayor"]["message_id"] == 1

    async def test_recovery_resets_counter_and_logs_once(self, monkeypatch):
        logs = []
        async def fake_send_log(message):
            logs.append(message)
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", fake_send_log)

        bot = self._dead_channel_bot("800", "GuildC", "mayor", 1)

        await update_guild_boards(bot)  # failure 1
        await update_guild_boards(bot)  # failure 2
        assert load_config()["guilds"]["800"]["boards"]["mayor"]["failures"] == 2
        assert logs == []

        # The channel comes back and the board message is live again.
        channel = MockChannel(800, MockGuild(800, "GuildC", object()))
        bot.channels[800] = channel
        channel.messages[1] = MockMessage(1, channel=channel)

        await update_guild_boards(bot)

        boards = load_config()["guilds"]["800"]["boards"]
        assert boards["mayor"] == {"message_id": 1}  # counter reset
        assert len(logs) == 1
        assert "✅ Board Recovered" in logs[0]
        assert "Recovered after:\n2 failed attempts" in logs[0]

        # Healthy next cycle: no repeated recovery message.
        await update_guild_boards(bot)
        assert len(logs) == 1

    async def test_self_healed_recreation_also_recovers(self, monkeypatch):
        logs = []
        async def fake_send_log(message):
            logs.append(message)
        monkeypatch.setattr("oathwatch.setup.reporting.send_log", fake_send_log)

        bot = self._dead_channel_bot("800", "GuildC", "mayor", 1)

        await update_guild_boards(bot)  # failure 1 (channel gone)
        assert load_config()["guilds"]["800"]["boards"]["mayor"]["failures"] == 1

        # Channel returns but the stored board message was deleted: the
        # existing self-healing recreates it, which counts as a success.
        channel = MockChannel(800, MockGuild(800, "GuildC", object()))
        bot.channels[800] = channel

        await update_guild_boards(bot)

        boards = load_config()["guilds"]["800"]["boards"]
        assert boards["mayor"]["message_id"] in channel.messages  # recreated
        assert "failures" not in boards["mayor"]  # counter reset
        assert len(logs) == 1
        assert "✅ Board Recovered" in logs[0]


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
