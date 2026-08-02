"""/owner announce and /owner announcement <cmd> command tests.

``_announce`` composes a preview and sends nothing until the owner confirms.
The history subcommands list, resend, delete, and clear (with confirmation)
the stored announcements.
"""
import discord
import pytest

from oathwatch import announcements, owner
from oathwatch.announcements import AnnouncementResult
from oathwatch.storage import save_config

from .mocks import MockBot, MockChannel, MockGuild, MockInteraction

OWNER_USER_ID = owner.OWNER_USER_ID
OWNER_GUILD_ID = owner.OWNER_GUILD_ID


def make_result(delivered=("111",)):
    """A bare AnnouncementResult for seeding history entries."""
    return AnnouncementResult(
        checked=1, delivered=len(delivered), skipped=0, failed=0,
        delivered_guilds=list(delivered), skipped_guilds=[], failed_guilds=[],
    )


def seed_history(n=1):
    for i in range(n):
        announcements.add_history_entry(
            f"Title {i}", "Body", "Update", "No Ping", make_result(), OWNER_USER_ID
        )


class TestAnnounceCommand:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_announce_shows_preview_and_sends_nothing(self):
        guild = MockGuild(111, "GuildA", object())
        channel = MockChannel(500, guild)
        bot = MockBot({500: channel})
        save_config({"guilds": {
            "111": {"channel_id": None, "notify_enabled": True,
                    "announcement_channel_id": 500, "boards": {}},
        }})
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID, client=bot)

        await owner._announce(interaction, "Title", "Body", "Update", "No Ping")

        reply = interaction.replies[0]
        assert reply["ephemeral"] is True
        assert isinstance(reply["view"], announcements.AnnouncementPreviewView)
        assert "preview" in reply["content"].lower()
        assert "Ping: No Ping" in reply["content"]
        assert channel.messages == {}  # nothing delivered yet
        assert reply["embed"].title == "Title"
        assert reply["embed"].description == "Body"
        assert reply["embed"].color == discord.Color.green()

    @pytest.mark.usefixtures("isolated_storage")
    async def test_non_owner_denied(self):
        interaction = MockInteraction(1, OWNER_GUILD_ID)
        await owner._announce(interaction, "T", "M", "Update", "No Ping")
        assert interaction.replies[0]["content"] == owner.DENIED_MESSAGE


class TestAnnouncementHistoryCommand:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_lists_entries_newest_first(self):
        seed_history(3)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await owner._announcement_history(interaction)

        content = interaction.replies[0]["content"]
        assert content.index("ANN-0003") < content.index("ANN-0002")
        assert content.index("ANN-0002") < content.index("ANN-0001")

    @pytest.mark.usefixtures("isolated_storage")
    async def test_empty_history_message(self):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await owner._announcement_history(interaction)

        assert "No announcements" in interaction.replies[0]["content"]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_corrupt_history_reported_to_error_channel(self, monkeypatch):
        with open(announcements.HISTORY_FILE, "w") as f:
            f.write("not json")
        reported = []

        async def fake_report_error(title, exc=None):
            reported.append(title)

        monkeypatch.setattr(owner.reporting, "report_error", fake_report_error)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await owner._announcement_history(interaction)

        assert reported == ["Announcement history file was corrupt and has been reset"]
        assert "No announcements" in interaction.replies[0]["content"]


class TestAnnouncementResendCommand:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_resend_previews_stored_content(self):
        announcements.add_history_entry(
            "Original", "Original body", "Warning", "@here",
            make_result(), OWNER_USER_ID,
        )
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await owner._announcement_resend(interaction, "ANN-0001")

        reply = interaction.replies[0]
        assert isinstance(reply["view"], announcements.AnnouncementPreviewView)
        assert "Resending `ANN-0001`" in reply["content"]
        assert reply["embed"].title == "Original"
        assert reply["embed"].description == "Original body"
        assert reply["embed"].color == discord.Color.red()  # Warning type

    @pytest.mark.usefixtures("isolated_storage")
    async def test_unknown_id_rejected(self):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await owner._announcement_resend(interaction, "ANN-9999")

        assert "No announcement" in interaction.replies[0]["content"]


class TestAnnouncementDeleteCommand:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_delete_removes_entry(self):
        seed_history(1)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await owner._announcement_delete(interaction, "ANN-0001")

        assert "Deleted" in interaction.replies[0]["content"]
        assert announcements.load_history()[0] == []

    @pytest.mark.usefixtures("isolated_storage")
    async def test_delete_unknown_id(self):
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await owner._announcement_delete(interaction, "ANN-9999")

        assert "No announcement" in interaction.replies[0]["content"]


class TestAnnouncementClearCommand:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_clear_requires_confirmation(self):
        seed_history(2)
        interaction = MockInteraction(OWNER_USER_ID, OWNER_GUILD_ID)

        await owner._announcement_clear(interaction)

        reply = interaction.replies[0]
        assert reply["ephemeral"] is True
        assert isinstance(reply["view"], announcements.HistoryClearView)
        assert "Clear announcement history" in reply["content"]
        # Nothing is cleared by merely invoking the command.
        assert len(announcements.load_history()[0]) == 2
