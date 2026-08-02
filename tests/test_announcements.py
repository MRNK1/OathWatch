"""Announcement broadcast, history, and preview/confirm view tests.

``send_announcement`` delivers to every configured announcement channel,
skips blocked/missing channels without aborting, and never notifies users on
failure (one technical log to the error channel instead). History is persisted
to ``data/announcement_history.json`` with sequential ANN-XXXX ids, newest
first, capped at HISTORY_LIMIT, and recovers from corrupt files.
"""
import os

import discord
import pytest

from oathwatch import access_control, announcements, storage_utils
from oathwatch.announcements import AnnouncementResult
from oathwatch.formatting import FOOTER_TEXT
from oathwatch.storage import save_config

from .mocks import MockBot, MockChannel, MockGuild, MockInteraction

OWNER_USER_ID = 100100100100100100
OWNER_GUILD_ID = 200200200200200200
DENIED = "You do not have permission to use this command."


def make_result(delivered=("111",)):
    """A bare AnnouncementResult for history tests (no send happened)."""
    return AnnouncementResult(
        checked=len(delivered),
        delivered=len(delivered),
        skipped=0,
        failed=0,
        delivered_guilds=list(delivered),
        skipped_guilds=[],
        failed_guilds=[],
    )


def announce_config(*announcement_channels):
    """Persist a config where each (guild, channel-id) pair is configured."""
    guilds = {}
    for gid, cid in announcement_channels:
        guilds[str(gid)] = {
            "channel_id": None,
            "notify_enabled": True,
            "announcement_channel_id": cid,
            "boards": {},
        }
    save_config({"guilds": guilds})


def one_guild_channel():
    """A MockBot/channel pair for a single announcement channel."""
    guild = MockGuild(111, "GuildA", object())
    channel = MockChannel(500, guild)
    return MockBot({500: channel}), channel


class TestSendAnnouncement:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_delivers_to_every_configured_channel(self):
        g1 = MockGuild(111, "GuildA", object())
        g2 = MockGuild(222, "GuildB", object())
        c1 = MockChannel(500, g1)
        c2 = MockChannel(501, g2)
        bot = MockBot({500: c1, 501: c2})
        announce_config((111, 500), (222, 501))

        result = await announcements.send_announcement(
            bot, title="Update", message="v2 out now",
            announcement_type="Update", ping_mode="No Ping",
        )

        assert result.checked == 2
        assert result.delivered == 2
        assert result.skipped == 0
        assert result.failed == 0
        assert len(c1.messages) == 1
        assert len(c2.messages) == 1

    @pytest.mark.usefixtures("isolated_storage")
    async def test_ping_mode_becomes_message_content(self):
        bot, channel = one_guild_channel()
        announce_config((111, 500))

        result = await announcements.send_announcement(
            bot, title="T", message="M", announcement_type="Update",
            ping_mode="@everyone",
        )

        assert result.delivered == 1
        msg = next(iter(channel.messages.values()))
        assert msg.content == "@everyone"
        assert msg.last_embed is not None

    @pytest.mark.usefixtures("isolated_storage")
    async def test_guild_without_announcement_channel_skipped(self):
        bot = MockBot()
        announce_config((111, None))

        result = await announcements.send_announcement(
            bot, title="T", message="M", announcement_type="Update",
        )

        assert result.skipped == 1
        assert result.delivered == 0
        assert result.failed == 0

    @pytest.mark.usefixtures("isolated_storage")
    async def test_blocked_guild_skipped(self):
        bot, channel = one_guild_channel()
        announce_config((111, 500))
        access_control.add_blacklist("111", "Spam", OWNER_USER_ID)

        result = await announcements.send_announcement(
            bot, title="T", message="M", announcement_type="Update",
        )

        assert result.skipped == 1
        assert channel.messages == {}

    @pytest.mark.usefixtures("isolated_storage")
    async def test_failure_reported_once_but_never_stops_loop(self, monkeypatch):
        bot, channel = one_guild_channel()
        announce_config((111, 500))

        async def boom(*args, **kwargs):
            raise RuntimeError("network down")

        channel.send = boom  # instance attr shadows the async method

        reported = []

        async def fake_report_error(title, exc):
            reported.append(title)

        monkeypatch.setattr(announcements.reporting, "report_error", fake_report_error)

        result = await announcements.send_announcement(
            bot, title="T", message="M", announcement_type="Update",
        )

        assert result.failed == 1
        assert result.delivered == 0
        assert len(reported) == 1
        assert "Announcement delivery failed" in reported[0]


class TestAnnouncementEmbed:
    def test_color_per_type(self):
        expected = {
            "Information": discord.Color.blue(),
            "Update": discord.Color.green(),
            "Maintenance": discord.Color.orange(),
            "Patch Notes": discord.Color.purple(),
            "Warning": discord.Color.red(),
            "Release": discord.Color.gold(),
        }
        for ann_type, color in expected.items():
            embed = announcements.announcement_embed("T", "M", ann_type)
            assert embed.color == color, ann_type
            assert embed.footer.text == FOOTER_TEXT

    def test_unknown_type_falls_back_to_blue(self):
        embed = announcements.announcement_embed("T", "M", "Whatever")
        assert embed.color == discord.Color.blue()


class TestHistory:
    @pytest.mark.usefixtures("isolated_storage")
    def test_history_file_auto_created_on_first_add(self):
        assert not os.path.exists(announcements.HISTORY_FILE)
        ann_id = announcements.add_history_entry(
            "T", "M", "Update", "No Ping", make_result(), OWNER_USER_ID
        )
        assert os.path.exists(announcements.HISTORY_FILE)
        assert ann_id == "ANN-0001"

    @pytest.mark.usefixtures("isolated_storage")
    def test_ids_increment_sequentially(self):
        for _ in range(3):
            announcements.add_history_entry("T", "M", "Update", "No Ping", make_result(), OWNER_USER_ID)
        assert announcements.get_history_entry("ANN-0001") is not None
        assert announcements.get_history_entry("ANN-0003") is not None
        assert announcements.get_history_entry("ANN-0004") is None

    @pytest.mark.usefixtures("isolated_storage")
    def test_load_is_newest_first(self):
        for i in range(3):
            announcements.add_history_entry(f"Title {i}", "M", "Update", "No Ping", make_result(), OWNER_USER_ID)
        entries, was_corrupt = announcements.load_history()
        assert was_corrupt is False
        assert [e["id"] for e in entries] == ["ANN-0003", "ANN-0002", "ANN-0001"]

    @pytest.mark.usefixtures("isolated_storage")
    def test_history_capped_at_limit_dropping_oldest(self):
        for i in range(announcements.HISTORY_LIMIT + 5):
            announcements.add_history_entry(f"Title {i}", "M", "Update", "No Ping", make_result(), OWNER_USER_ID)
        entries, _ = announcements.load_history()
        assert len(entries) == announcements.HISTORY_LIMIT
        ids = [e["id"] for e in entries]
        assert "ANN-0001" not in ids  # oldest dropped
        assert f"ANN-{announcements.HISTORY_LIMIT + 5:04d}" in ids  # newest kept

    @pytest.mark.usefixtures("isolated_storage")
    def test_entry_records_all_fields(self):
        result = AnnouncementResult(
            checked=1, delivered=1, skipped=0, failed=0,
            delivered_guilds=["111"], skipped_guilds=[], failed_guilds=[],
        )
        ann_id = announcements.add_history_entry(
            "Patch", "Fixed the bug", "Patch Notes", "@here", result, OWNER_USER_ID
        )
        entry = announcements.get_history_entry(ann_id)
        assert entry["id"] == "ANN-0001"
        assert entry["title"] == "Patch"
        assert entry["message"] == "Fixed the bug"
        assert entry["type"] == "Patch Notes"
        assert entry["ping_mode"] == "@here"
        assert entry["delivered_servers"] == ["111"]
        assert entry["skipped_servers"] == []
        assert entry["failed_servers"] == []
        assert entry["owner_id"] == OWNER_USER_ID
        assert isinstance(entry["timestamp"], int)

    @pytest.mark.usefixtures("isolated_storage")
    def test_delete_returns_presence(self):
        announcements.add_history_entry("T", "M", "Update", "No Ping", make_result(), OWNER_USER_ID)
        assert announcements.delete_history_entry("ANN-0001") is True
        assert announcements.delete_history_entry("ANN-0001") is False
        assert announcements.load_history()[0] == []

    @pytest.mark.usefixtures("isolated_storage")
    def test_clear_removes_all(self):
        for _ in range(2):
            announcements.add_history_entry("T", "M", "Update", "No Ping", make_result(), OWNER_USER_ID)
        removed = announcements.clear_history()
        assert removed == 2
        assert announcements.load_history()[0] == []

    @pytest.mark.usefixtures("isolated_storage")
    def test_corrupt_file_quarantined_and_reset(self):
        with open(announcements.HISTORY_FILE, "w") as f:
            f.write("{not json!!!")
        entries, was_corrupt = announcements.load_history()
        assert was_corrupt is True
        assert entries == []
        assert os.path.exists(announcements.CORRUPTED_FILE)
        # A fresh history can be created and used again.
        entries, was_corrupt = announcements.load_history()
        assert was_corrupt is False

    @pytest.mark.usefixtures("isolated_storage")
    def test_non_list_history_quarantined(self):
        storage_utils.write_json_atomic(announcements.HISTORY_FILE, {"not": "a list"})
        entries, was_corrupt = announcements.load_history()
        assert was_corrupt is True
        assert entries == []


class TestFormatting:
    def test_format_summary_lists_every_count(self):
        result = AnnouncementResult(
            checked=3, delivered=1, skipped=1, failed=1, duration=0.5
        )
        text = announcements.format_summary(result, "ANN-0001")
        assert "ANN-0001" in text
        assert "Servers checked: 3" in text
        assert "Delivered: 1" in text
        assert "Skipped: 1" in text
        assert "Failed: 1" in text
        assert "0.50s" in text

    def test_format_history_lines(self):
        lines = announcements.format_history_lines([
            {"id": "ANN-0001", "title": "Patch", "type": "Update",
             "timestamp": 1700000000, "delivered_servers": ["111"],
             "failed_servers": ["222"]},
        ])
        assert len(lines) == 1
        assert "ANN-0001" in lines[0]
        assert "Patch" in lines[0]
        assert "Delivered 1" in lines[0]
        assert "Failed 1" in lines[0]


class TestAnnouncementPreviewView:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_confirm_sends_and_records_history(self):
        bot, channel = one_guild_channel()
        announce_config((111, 500))
        view = announcements.AnnouncementPreviewView(
            bot, title="Hi", message="Body", announcement_type="Update",
            ping_mode="No Ping", owner_id=OWNER_USER_ID,
        )
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=bot)

        await view.children[0].callback(interaction)

        assert len(channel.messages) == 1
        assert interaction.edits[0]["view"] is None
        assert "ANN-0001" in interaction.edits[0]["content"]
        entries, _ = announcements.load_history()
        assert entries[0]["title"] == "Hi"

    @pytest.mark.usefixtures("isolated_storage")
    async def test_cancel_sends_nothing(self):
        bot, channel = one_guild_channel()
        view = announcements.AnnouncementPreviewView(
            bot, title="Hi", message="Body", announcement_type="Update",
            ping_mode="No Ping", owner_id=OWNER_USER_ID,
        )
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=bot)

        await view.children[1].callback(interaction)

        assert channel.messages == {}
        assert interaction.edits[0]["content"] == "❌ Announcement cancelled."
        assert announcements.load_history()[0] == []

    @pytest.mark.usefixtures("isolated_storage")
    async def test_non_owner_cannot_confirm(self):
        bot, channel = one_guild_channel()
        announce_config((111, 500))
        view = announcements.AnnouncementPreviewView(
            bot, title="Hi", message="Body", announcement_type="Update",
            ping_mode="No Ping", owner_id=OWNER_USER_ID,
        )
        interaction = MockInteraction(1, OWNER_GUILD_ID, client=bot)

        await view.children[0].callback(interaction)

        assert channel.messages == {}
        assert interaction.replies[0]["content"] == DENIED
        assert announcements.load_history()[0] == []


class TestHistoryClearView:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_confirm_clears_history(self):
        announcements.add_history_entry("T", "M", "Update", "No Ping", make_result(), OWNER_USER_ID)
        view = announcements.HistoryClearView(owner_id=OWNER_USER_ID)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await view.children[0].callback(interaction)

        assert announcements.load_history()[0] == []
        assert interaction.edits[0]["view"] is None
        assert "Cleared 1" in interaction.edits[0]["content"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_cancel_keeps_history(self):
        announcements.add_history_entry("T", "M", "Update", "No Ping", make_result(), OWNER_USER_ID)
        view = announcements.HistoryClearView(owner_id=OWNER_USER_ID)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await view.children[1].callback(interaction)

        assert len(announcements.load_history()[0]) == 1
        assert "cancelled" in interaction.edits[0]["content"].lower()
