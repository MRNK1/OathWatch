"""Owner announcement broadcasting and history.

Announcements are user-facing broadcasts (updates, patch notes, maintenance,
warnings, releases) sent by the owner to every guild that has configured an
announcement channel (``announcement_channel_id``, set with ``/setchannel``).
They are deliberately separate from the error channel contract: an
announcement is never sent to the error channel, and a delivery failure is
reported there (one technical log) without notifying any user.

A broadcast is confirmed first via an interactive preview (Confirm/Cancel)
and, once sent, recorded in ``data/announcement_history.json`` — newest first,
capped at ``HISTORY_LIMIT`` entries — so the owner can review, resend, or
delete past announcements.

Send logic and history persistence live here so the ``/owner`` commands in
``owner`` only orchestrate the interaction.
"""
import logging
import os
import time
from dataclasses import dataclass, field

import discord

from . import __version__, access_control, reporting
from .formatting import FOOTER_TEXT
from .storage import load_config
from .storage_utils import DATA_DIR, read_json, write_json_atomic

logger = logging.getLogger(__name__)

HISTORY_FILE = os.path.join(DATA_DIR, "announcement_history.json")

# Corrupt history files are renamed here so the fresh one can be created
# without losing the corrupt document for later investigation.
CORRUPTED_FILE = HISTORY_FILE + ".corrupted.json"

# Only the most recent announcements are kept; older ones are dropped on save.
HISTORY_LIMIT = 20

# One color per announcement type (Part 8 color scheme, shared by all embeds).
ANNOUNCEMENT_COLORS = {
    "Information": discord.Color.blue(),
    "Update": discord.Color.green(),
    "Maintenance": discord.Color.orange(),
    "Patch Notes": discord.Color.purple(),
    "Warning": discord.Color.red(),
    "Release": discord.Color.gold(),
}

# Discord renders this title emoji prefix; kept as a constant so commands and
# the preview view share the exact same preview headline.
PREVIEW_HEADING = "📣 **Announcement preview** — nothing has been sent yet."


@dataclass
class AnnouncementResult:
    """Outcome of one announcement broadcast."""

    checked: int = 0
    delivered: int = 0
    skipped: int = 0
    failed: int = 0
    duration: float = 0.0
    delivered_guilds: list = field(default_factory=list)
    skipped_guilds: list = field(default_factory=list)
    failed_guilds: list = field(default_factory=list)


def announcement_embed(title: str, message: str, announcement_type: str) -> discord.Embed:
    """Build the announcement embed: type color, body, and the shared footer.

    Patch Notes intentionally render the message as raw markdown — embed
    descriptions support it — so multi-line patch notes keep their formatting.
    """
    embed = discord.Embed(
        title=title,
        description=message,
        color=ANNOUNCEMENT_COLORS.get(
            announcement_type, discord.Color.blue()
        ),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


async def send_announcement(
    bot,
    *,
    title: str,
    message: str,
    announcement_type: str,
    ping_mode: str = "No Ping",
) -> AnnouncementResult:
    """Broadcast an announcement to every configured announcement channel.

    Each guild's ``announcement_channel_id`` is resolved and the embed is
    posted (with an optional @here/@everyone ping as the message content).
    Blocked guilds, guilds without an announcement channel, and guilds whose
    channel is missing are skipped; a failed send is counted and reported to
    the error channel once. Failures never notify users and never retry, and
    the loop always continues to the remaining guilds. Never raises.
    """
    config = load_config()
    result = AnnouncementResult()
    result.checked = len(config.get("guilds", {}))
    started = time.monotonic()

    for guild_id, guild_data in config.get("guilds", {}).items():

        if not access_control.is_guild_allowed(guild_id):
            result.skipped += 1
            result.skipped_guilds.append(guild_id)
            continue

        channel = bot.get_channel(guild_data.get("announcement_channel_id"))
        if not isinstance(channel, discord.TextChannel):
            result.skipped += 1
            result.skipped_guilds.append(guild_id)
            continue

        try:
            await channel.send(
                content=ping_mode if ping_mode != "No Ping" else None,
                embed=announcement_embed(title, message, announcement_type),
            )
            result.delivered += 1
            result.delivered_guilds.append(guild_id)
        except Exception as e:  # noqa: BLE001 - never let one guild kill the loop
            result.failed += 1
            result.failed_guilds.append(guild_id)
            logger.error("Failed to send announcement to guild %s: %s", guild_id, e)
            await reporting.report_error(
                f"Announcement delivery failed for guild {guild_id}", e
            )

    result.duration = time.monotonic() - started
    return result


def _next_id(entries: list) -> str:
    """Next sequential human-readable id (ANN-0001 style), never a UUID."""
    highest = 0
    for entry in entries:
        ann_id = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(ann_id, str) and ann_id.startswith("ANN-"):
            try:
                highest = max(highest, int(ann_id[len("ANN-"):]))
            except ValueError:
                continue
    return f"ANN-{highest + 1:04d}"


def _quarantine_corrupt_history() -> None:
    """Move a corrupt history file aside so a fresh one can be created."""
    try:
        if os.path.exists(HISTORY_FILE):
            os.replace(HISTORY_FILE, CORRUPTED_FILE)
        logger.warning("Moved corrupt announcement history to %s", CORRUPTED_FILE)
    except OSError as e:
        logger.error("Could not quarantine corrupt history: %s", e)


def load_history() -> tuple:
    """Load history entries, newest first. Returns (entries, was_corrupt).

    A corrupt or unreadable file never crashes the caller: it is renamed to
    ``announcement_history.corrupted.json``, a fresh history is started, and
    ``was_corrupt`` is set so the command can report it to the error channel.
    """
    try:
        raw = read_json(HISTORY_FILE, None)
    except (ValueError, OSError):
        logger.exception("Announcement history file is corrupt")
        _quarantine_corrupt_history()
        return [], True

    if raw is None:
        return [], False

    if not isinstance(raw, list):
        _quarantine_corrupt_history()
        return [], True

    return [entry for entry in raw if isinstance(entry, dict)], False


def save_history(entries: list) -> None:
    """Persist history (newest first), capped at HISTORY_LIMIT."""
    write_json_atomic(HISTORY_FILE, entries[:HISTORY_LIMIT])


def add_history_entry(
    title: str,
    message: str,
    announcement_type: str,
    ping_mode: str,
    result: AnnouncementResult,
    owner_id: int,
) -> str:
    """Record a sent announcement at the front of history; returns its id."""
    entries, _ = load_history()
    ann_id = _next_id(entries)
    entry = {
        "id": ann_id,
        "title": title,
        "message": message,
        "type": announcement_type,
        "ping_mode": ping_mode,
        "timestamp": int(time.time()),
        "delivered_servers": list(result.delivered_guilds),
        "skipped_servers": list(result.skipped_guilds),
        "failed_servers": list(result.failed_guilds),
        "owner_id": owner_id,
        "bot_version": __version__,
    }
    entries.insert(0, entry)
    save_history(entries)
    return ann_id


def get_history_entry(ann_id: str) -> dict | None:
    """Return one history entry by id, or None when not found."""
    entries, _ = load_history()
    for entry in entries:
        if entry.get("id") == ann_id:
            return entry
    return None


def delete_history_entry(ann_id: str) -> bool:
    """Remove one history entry; returns True if it was present."""
    entries, _ = load_history()
    remaining = [e for e in entries if e.get("id") != ann_id]
    if len(remaining) == len(entries):
        return False
    save_history(remaining)
    return True


def clear_history() -> int:
    """Remove every history entry; returns how many were removed."""
    entries, _ = load_history()
    save_history([])
    return len(entries)


class AnnouncementPreviewView(discord.ui.View):
    """Confirm/Cancel buttons for an announcement preview.

    Nothing is broadcast until the owner clicks Confirm. Both buttons re-check
    the owner so a stale view opened by someone else cannot be driven. On
    Confirm the announcement is sent, recorded in history, and the preview
    message is replaced with the ephemeral delivery summary. On Cancel the
    preview message is replaced with a cancellation note.
    """

    def __init__(
        self,
        bot,
        *,
        title: str,
        message: str,
        announcement_type: str,
        ping_mode: str,
        owner_id: int,
    ):
        super().__init__(timeout=300)
        self.bot = bot
        self.title = title
        self.message = message
        self.announcement_type = announcement_type
        self.ping_mode = ping_mode
        self.owner_id = owner_id

    async def _verify_owner(self, interaction) -> bool:
        """Reject a non-owner click; returns True when the click is allowed."""
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "You do not have permission to use this command.", ephemeral=True
        )
        return False

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button) -> None:
        """Send the announcement and replace the preview with a summary."""
        if not await self._verify_owner(interaction):
            return
        result = await send_announcement(
            self.bot,
            title=self.title,
            message=self.message,
            announcement_type=self.announcement_type,
            ping_mode=self.ping_mode,
        )
        ann_id = add_history_entry(
            self.title,
            self.message,
            self.announcement_type,
            self.ping_mode,
            result,
            self.owner_id,
        )
        summary = format_summary(result, ann_id)
        logger.info("Announcement %s sent (%d delivered)", ann_id, result.delivered)
        await interaction.response.edit_message(content=summary, embed=None, view=None)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button) -> None:
        """Abandon the preview without sending anything."""
        if not await self._verify_owner(interaction):
            return
        logger.info("Announcement preview cancelled by %s", interaction.user.id)
        await interaction.response.edit_message(
            content="❌ Announcement cancelled.", embed=None, view=None
        )


def format_summary(result: AnnouncementResult, ann_id: str) -> str:
    """Build the ephemeral delivery summary shown after a confirmed send."""
    return "\n".join([
        f"✅ **Announcement {ann_id} sent**",
        f"Servers checked: {result.checked}",
        f"Delivered: {result.delivered}",
        f"Skipped: {result.skipped}",
        f"Failed: {result.failed}",
        f"Duration: {result.duration:.2f}s",
        f"Timestamp: <t:{int(time.time())}:F>",
    ])


def format_history_lines(entries: list) -> list:
    """Render history entries as display lines (newest first).

    Each line shows the id, title, type, timestamp, and delivery/failure
    counts so the owner can see the outcome of every past announcement.
    """
    lines = []
    for entry in entries:
        title = str(entry.get("title") or "Untitled")
        ann_type = str(entry.get("type") or "Information")
        timestamp = entry.get("timestamp")
        ts = f"<t:{int(timestamp)}:F>" if isinstance(timestamp, int) else "—"
        delivered = entry.get("delivered_servers")
        failed = entry.get("failed_servers")
        delivered_n = len(delivered) if isinstance(delivered, list) else 0
        failed_n = len(failed) if isinstance(failed, list) else 0
        lines.append(
            f"**{entry.get('id')}** {title} · {ann_type} · {ts} · "
            f"Delivered {delivered_n} · Failed {failed_n}"
        )
    return lines


class HistoryClearView(discord.ui.View):
    """Confirm/Cancel buttons for wiping the entire announcement history.

    Clearing is destructive and irreversible, so it needs an explicit owner
    confirmation; nothing is removed until Confirm is pressed.
    """

    def __init__(self, owner_id: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id

    async def _verify_owner(self, interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "You do not have permission to use this command.", ephemeral=True
        )
        return False

    @discord.ui.button(label="✅ Confirm clear", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button) -> None:
        """Wipe history and replace the confirmation prompt with the outcome."""
        if not await self._verify_owner(interaction):
            return
        count = clear_history()
        logger.info("Announcement history cleared (%d entries) by %s", count, interaction.user.id)
        await interaction.response.edit_message(
            content=f"✅ Cleared {count} announcement(s) from history.",
            embed=None,
            view=None,
        )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button) -> None:
        """Abandon the clear without removing anything."""
        if not await self._verify_owner(interaction):
            return
        await interaction.response.edit_message(
            content="❌ History clear cancelled.", embed=None, view=None
        )
