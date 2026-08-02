"""Owner-only administration commands.

The ``/owner`` command group is registered ONLY inside the owner guild and
only the owner user may execute it. It is guild-scoped (``guild_ids`` on the
group) so it never syncs to public servers and never appears outside the
owner guild. Every reply is ephemeral; any non-owner caller receives a single
ephemeral denial.

All owner functionality is isolated here — the bot module only imports the
group to register it and reuses the shared reporting/refresh helpers.
"""
import logging
import os
import time
from typing import Literal

import discord
from discord import app_commands
from dotenv import load_dotenv

from . import (
    __version__,
    access_control,
    announcements,
    reporting,
    runtime,
    storage_utils,
)
from .formatting import FOOTER_TEXT, last_updated_text, next_refresh_text
from .refresh import perform_refresh
from .storage import load_config
from .world_state import WORLD_STATE

logger = logging.getLogger(__name__)

# The owner's Discord IDs are configuration, never source: they come from the
# environment (.env). load_dotenv is called here at import so these are correct
# no matter when this module is first imported (bot.main()'s later call is
# idempotent). A missing or malformed value fails fast at startup instead of
# silently registering the owner group in the wrong guild.
load_dotenv()

OWNER_USER_ID_ENV = "OWNER_USER_ID"
OWNER_GUILD_ID_ENV = "OWNER_GUILD_ID"


def _required_id(env_name: str, label: str) -> int:
    """Read a required Discord ID from the environment.

    Raises ValueError with an actionable message when the variable is unset or
    not a numeric Discord ID.
    """
    raw = (os.getenv(env_name) or "").strip()
    if not raw:
        raise ValueError(
            f"Missing owner configuration: set {env_name} in .env "
            f"(the {label} Discord ID)."
        )
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"Invalid {label} Discord ID in {env_name}: expected a numeric "
            f"ID, got {raw!r}."
        ) from None


OWNER_USER_ID = _required_id(OWNER_USER_ID_ENV, "owner user")
OWNER_GUILD_ID = _required_id(OWNER_GUILD_ID_ENV, "owner guild")
OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)

DENIED_MESSAGE = "You do not have permission to use this command."

# Process start time, used for the uptime shown in /owner botstatus.
STARTED_AT = time.monotonic()

owner_group = app_commands.Group(
    name="owner",
    description="Owner-only administration commands",
    guild_ids=[OWNER_GUILD_ID],
)

# Nested sub-groups. Group(parent=...) auto-registers them under /owner, so
# they inherit the owner guild's scope and never sync globally.
whitelist_group = app_commands.Group(
    name="whitelist",
    description="Whitelist mode and whitelisted guilds",
    parent=owner_group,
)

blacklist_group = app_commands.Group(
    name="blacklist",
    description="Blacklisted guilds",
    parent=owner_group,
)

announcement_group = app_commands.Group(
    name="announcement",
    description="Announcement history and management",
    parent=owner_group,
)


def is_owner(interaction) -> bool:
    """True if the caller is the owner executing inside the owner guild."""
    return (
        interaction.user.id == OWNER_USER_ID
        and interaction.guild_id == OWNER_GUILD_ID
    )


async def _deny_non_owner(interaction) -> bool:
    """Reject a non-owner caller. Returns True when the caller was denied."""
    if is_owner(interaction):
        return False

    logger.warning(
        "Owner command denied for user %s in guild %s",
        interaction.user.id,
        interaction.guild_id,
    )
    await reporting.report_error(
        f"Owner command permission denied (user {interaction.user.id}, "
        f"guild {interaction.guild_id})"
    )

    if interaction.response.is_done():
        await interaction.followup.send(DENIED_MESSAGE, ephemeral=True)
    else:
        await interaction.response.send_message(DENIED_MESSAGE, ephemeral=True)
    return True


def format_uptime(seconds: float) -> str:
    """Format a duration in seconds as a compact human string."""
    seconds = int(seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _status_text(interaction) -> str:
    """Build the ephemeral status summary for the owner."""
    client = interaction.client
    guilds = len(client.guilds) if hasattr(client, "guilds") else 0
    latency = client.latency if hasattr(client, "latency") else 0
    configured = len(load_config().get("guilds", {}))
    mayor = WORLD_STATE["mayor"]["name"]

    return "\n".join([
        "🛠️ **OathWatch Status**",
        f"Version: {__version__}",
        f"Latency: {round(latency * 1000)}ms",
        f"Uptime: {format_uptime(time.monotonic() - STARTED_AT)}",
        f"Guilds: {guilds}",
        f"Configured guilds: {configured}",
        f"Mayor: {mayor}",
        f"Last updated: {last_updated_text(WORLD_STATE['last_updated'])}",
        f"Data directory: {storage_utils.DATA_DIR}",
    ])


async def _botstatus(interaction: discord.Interaction) -> None:
    """Show the owner a live status summary."""
    if await _deny_non_owner(interaction):
        return
    await interaction.response.send_message(_status_text(interaction), ephemeral=True)


async def _refresh(interaction: discord.Interaction) -> None:
    """Manually run one refresh cycle and report the outcome."""
    if await _deny_non_owner(interaction):
        return

    await interaction.response.defer(ephemeral=True)

    result = await perform_refresh(interaction.client)

    if result.ok:
        await reporting.send_log(f"🛠️ Manual refresh: {result.summary}")
        await interaction.followup.send(f"✅ {result.summary}", ephemeral=True)
    else:
        await interaction.followup.send(
            f"❌ Refresh failed: {result.error}", ephemeral=True
        )


async def _shutdown(interaction: discord.Interaction) -> None:
    """Gracefully shut the bot down (🔴 status is sent by bot.close)."""
    if await _deny_non_owner(interaction):
        return

    await interaction.response.send_message("🔴 Shutting down...", ephemeral=True)
    await interaction.client.close()


async def _log_access_change(interaction, action: str, guild_id=None, reason=None) -> None:
    """Log a whitelist/blacklist change (guild name, id, reason, owner, time)."""
    guild_name = "all guilds"
    if guild_id is not None and str(guild_id).isdigit():
        client = interaction.client
        guild = client.get_guild(int(guild_id)) if hasattr(client, "get_guild") else None
        guild_name = getattr(guild, "name", None) or str(guild_id)

    parts = [f"🛡️ {action} — {guild_name} ({guild_id or '—'})"]
    if reason:
        parts.append(f"Reason: {reason}")
    parts.append(f"Owner: {OWNER_USER_ID}")
    parts.append(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

    line = " · ".join(parts)
    logger.info("Access control change: %s", line)
    await reporting.send_log(line)


async def _whitelist_enable(interaction: discord.Interaction) -> None:
    """Enable whitelist mode: only whitelisted guilds stay active."""
    if await _deny_non_owner(interaction):
        return
    access_control.set_whitelist_enabled(True)
    await _log_access_change(interaction, "Whitelist enabled")
    await interaction.response.send_message("✅ Whitelist mode enabled.", ephemeral=True)


async def _whitelist_disable(interaction: discord.Interaction) -> None:
    """Disable whitelist mode: every non-blacklisted guild is active again."""
    if await _deny_non_owner(interaction):
        return
    access_control.set_whitelist_enabled(False)
    await _log_access_change(interaction, "Whitelist disabled")
    await interaction.response.send_message("✅ Whitelist mode disabled.", ephemeral=True)


async def _whitelist_status(interaction: discord.Interaction) -> None:
    """Show whitelist mode and counts."""
    if await _deny_non_owner(interaction):
        return
    status = access_control.get_status()
    mode = "Enabled" if status["whitelist_enabled"] else "Disabled"
    await interaction.response.send_message(
        "\n".join([
            "🛡️ **Whitelist Mode**",
            mode,
            "",
            f"**Whitelisted Guilds**: {len(status['whitelist'])}",
            f"**Blacklisted Guilds**: {len(status['blacklist'])}",
        ]),
        ephemeral=True,
    )


async def _whitelist_add(interaction: discord.Interaction, guild_id: str) -> None:
    """Add a guild to the whitelist."""
    if await _deny_non_owner(interaction):
        return
    access_control.add_whitelist(guild_id)
    await _log_access_change(interaction, "Guild added to whitelist", guild_id=guild_id)
    await interaction.response.send_message(
        f"✅ Guild `{guild_id}` added to the whitelist.", ephemeral=True
    )


async def _whitelist_remove(interaction: discord.Interaction, guild_id: str) -> None:
    """Remove a guild from the whitelist."""
    if await _deny_non_owner(interaction):
        return
    if not access_control.remove_whitelist(guild_id):
        await interaction.response.send_message(
            f"❌ Guild `{guild_id}` is not in the whitelist.", ephemeral=True
        )
        return
    await _log_access_change(interaction, "Guild removed from whitelist", guild_id=guild_id)
    await interaction.response.send_message(
        f"✅ Guild `{guild_id}` removed from the whitelist.", ephemeral=True
    )


async def _whitelist_list(interaction: discord.Interaction) -> None:
    """List all whitelisted guilds."""
    if await _deny_non_owner(interaction):
        return
    whitelist = access_control.get_status()["whitelist"]
    if not whitelist:
        await interaction.response.send_message(
            "📋 No whitelisted guilds.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        "📋 **Whitelisted Guilds**\n" + "\n".join(f"- `{guild}`" for guild in whitelist),
        ephemeral=True,
    )


async def _blacklist_add(interaction: discord.Interaction, guild_id: str, reason: str) -> None:
    """Blacklist a guild with a required reason."""
    if await _deny_non_owner(interaction):
        return
    access_control.add_blacklist(guild_id, reason, OWNER_USER_ID)
    await _log_access_change(interaction, "Guild added to blacklist", guild_id, reason)
    await interaction.response.send_message(
        f"✅ Guild `{guild_id}` blacklisted.", ephemeral=True
    )


async def _blacklist_remove(interaction: discord.Interaction, guild_id: str) -> None:
    """Remove a guild from the blacklist."""
    if await _deny_non_owner(interaction):
        return
    if not access_control.remove_blacklist(guild_id):
        await interaction.response.send_message(
            f"❌ Guild `{guild_id}` is not blacklisted.", ephemeral=True
        )
        return
    await _log_access_change(interaction, "Guild removed from blacklist", guild_id=guild_id)
    await interaction.response.send_message(
        f"✅ Guild `{guild_id}` removed from the blacklist.", ephemeral=True
    )


async def _blacklist_list(interaction: discord.Interaction) -> None:
    """List all blacklisted guilds with reason and audit metadata."""
    if await _deny_non_owner(interaction):
        return
    blacklist = access_control.get_status()["blacklist"]
    if not blacklist:
        await interaction.response.send_message(
            "📋 No blacklisted guilds.", ephemeral=True
        )
        return

    lines = []
    for guild_id, entry in blacklist.items():
        added_by = entry.get("added_by") or "—"
        added_at = entry.get("added_at")
        added_at_text = f"<t:{added_at}:F>" if added_at else "—"
        lines.append(
            f"**{guild_id}**\n"
            f"Reason: {entry.get('reason') or '—'}\n"
            f"Added by: `{added_by}` · Added at: {added_at_text}"
        )
    await interaction.response.send_message(
        "📋 **Blacklisted Guilds**\n\n" + "\n\n".join(lines),
        ephemeral=True,
    )


def _refresh_loop_running() -> bool:
    """True when the hourly refresh loop is currently running.

    Imported lazily so the owner module never depends on the bot module at
    import time (bot.py imports owner.py); at command-execution time the bot
    is always fully loaded.
    """
    try:
        from .bot import mayor_update_loop

        return bool(mayor_update_loop.is_running())
    except Exception:  # noqa: BLE001 - health reporting must never crash
        return False


def _health_embed(interaction: discord.Interaction) -> discord.Embed:
    """Build the /owner health embed with an overall GREEN/YELLOW/RED level."""
    client = interaction.client
    latency_ms = round(client.latency * 1000) if hasattr(client, "latency") else 0
    discord_ok = bool(getattr(client, "is_ready", lambda: True)())
    loop_ok = _refresh_loop_running()

    attempted = runtime.refresh_count() > 0
    refresh_ok = runtime.last_refresh_ok()
    refresh_error = runtime.last_refresh_error()

    config = load_config()
    configured = len(config.get("guilds", {}))
    world_loaded = bool(WORLD_STATE["last_updated"])

    reporting_ok = all(
        os.getenv(name)
        for name in (
            reporting.STATUS_CHANNEL_ENV,
            reporting.LOG_CHANNEL_ENV,
            reporting.ERROR_CHANNEL_ENV,
        )
    )

    ac = access_control.get_status()
    ac_mode = "whitelist on" if ac["whitelist_enabled"] else "open"
    ac_text = f"{len(ac['whitelist'])} whitelisted · {len(ac['blacklist'])} blacklisted"

    memory = runtime.process_memory_mb()
    memory_text = f"{memory:.1f} MB" if memory is not None else "N/A"

    last_at = runtime.last_refresh_at()
    last_refresh_text = f"<t:{int(last_at)}:R>" if last_at else "Never"

    if not discord_ok or not loop_ok or (attempted and not refresh_ok):
        level, color = "RED", discord.Color.red()
    elif not world_loaded or not reporting_ok or configured == 0:
        level, color = "YELLOW", discord.Color.gold()
    else:
        level, color = "GREEN", discord.Color.green()

    if attempted:
        refresh_field = (
            "✅ Last refresh ok" if refresh_ok else f"❌ {refresh_error or 'failed'}"
        )
    else:
        refresh_field = "⏳ No refresh yet this session"

    embed = discord.Embed(
        title="🩺 OathWatch Health",
        description=f"Overall: **{level}**",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Discord API",
        value="🟢 Connected" if discord_ok else "🔴 Disconnected",
        inline=True,
    )
    embed.add_field(name="Latency", value=f"{latency_ms}ms", inline=True)
    embed.add_field(
        name="Background loop",
        value="🟢 Running" if loop_ok else "🔴 Stopped",
        inline=True,
    )
    embed.add_field(name="Hypixel API / refresh", value=refresh_field, inline=False)
    embed.add_field(name="Configuration", value=f"{configured} guild(s)", inline=True)
    embed.add_field(
        name="World state",
        value="🟢 Loaded" if world_loaded else "🟡 Not updated yet",
        inline=True,
    )
    embed.add_field(
        name="Reporting channels",
        value="🟢 All set" if reporting_ok else "🟡 Some missing",
        inline=True,
    )
    embed.add_field(name="Access control", value=f"{ac_mode} · {ac_text}", inline=True)
    embed.add_field(name="Last refresh", value=last_refresh_text, inline=True)
    embed.add_field(
        name="Next refresh",
        value=next_refresh_text(WORLD_STATE["last_updated"]),
        inline=True,
    )
    embed.add_field(name="Memory usage", value=memory_text, inline=True)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def _stats_embed(interaction: discord.Interaction) -> discord.Embed:
    """Build the /owner stats embed from runtime and config data."""
    client = interaction.client
    guilds = load_config().get("guilds", {})
    total_guilds = len(client.guilds) if hasattr(client, "guilds") else 0
    allowed = sum(1 for gid in guilds if access_control.is_guild_allowed(gid))
    blocked = len(guilds) - allowed
    boards = [g.get("boards") or {} for g in guilds.values()]
    mayor_boards = sum(1 for b in boards if "mayor" in b)
    election_boards = sum(1 for b in boards if "election" in b)
    board_total = sum(len(b) for b in boards)

    embed = discord.Embed(
        title="📊 OathWatch Stats",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Version", value=__version__, inline=True)
    embed.add_field(name="Uptime", value=format_uptime(runtime.uptime()), inline=True)
    embed.add_field(name="Guilds (total)", value=total_guilds, inline=True)
    embed.add_field(name="Configured", value=len(guilds), inline=True)
    embed.add_field(name="Allowed", value=allowed, inline=True)
    embed.add_field(name="Blocked", value=blocked, inline=True)
    embed.add_field(name="Boards — mayor", value=mayor_boards, inline=True)
    embed.add_field(name="Boards — election", value=election_boards, inline=True)
    embed.add_field(name="Boards — tracked", value=board_total, inline=True)
    embed.add_field(name="Refreshes since start", value=runtime.refresh_count(), inline=True)
    embed.add_field(name="Avg refresh", value=f"{runtime.average_refresh():.1f}s", inline=True)
    embed.add_field(name="Longest refresh", value=f"{runtime.longest_refresh():.1f}s", inline=True)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def _version_embed(interaction: discord.Interaction) -> discord.Embed:
    """Build the /owner version embed."""
    embed = discord.Embed(
        title="ℹ️ OathWatch Version",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Version", value=__version__, inline=True)
    embed.add_field(name="Git commit", value=runtime.git_commit(), inline=True)
    embed.add_field(name="Python", value=runtime.python_version(), inline=True)
    embed.add_field(name="discord.py", value=runtime.discord_py_version(), inline=True)
    embed.add_field(name="Platform", value=runtime.platform_info(), inline=True)
    embed.add_field(name="Started", value=f"<t:{runtime.started_at_epoch()}:F>", inline=True)
    embed.add_field(name="Uptime", value=format_uptime(runtime.uptime()), inline=True)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


async def _health(interaction: discord.Interaction) -> None:
    """Show the owner a live health report (overall level + subsystem status)."""
    if await _deny_non_owner(interaction):
        return
    await interaction.response.send_message(
        embed=_health_embed(interaction), ephemeral=True
    )


async def _stats(interaction: discord.Interaction) -> None:
    """Show the owner runtime and usage statistics."""
    if await _deny_non_owner(interaction):
        return
    await interaction.response.send_message(
        embed=_stats_embed(interaction), ephemeral=True
    )


async def _version(interaction: discord.Interaction) -> None:
    """Show the owner version and environment details."""
    if await _deny_non_owner(interaction):
        return
    await interaction.response.send_message(
        embed=_version_embed(interaction), ephemeral=True
    )


async def _announce(
    interaction: discord.Interaction,
    title: str,
    message: str,
    type: Literal["Information", "Update", "Maintenance", "Patch Notes", "Warning", "Release"],
    ping: Literal["No Ping", "@here", "@everyone"] = "No Ping",
) -> None:
    """Compose an announcement; nothing is sent until the owner confirms."""
    if await _deny_non_owner(interaction):
        return

    view = announcements.AnnouncementPreviewView(
        interaction.client,
        title=title,
        message=message,
        announcement_type=type,
        ping_mode=ping,
        owner_id=OWNER_USER_ID,
    )
    embed = announcements.announcement_embed(title, message, type)
    await interaction.response.send_message(
        content=f"{announcements.PREVIEW_HEADING}\nPing: {ping}",
        embed=embed,
        view=view,
        ephemeral=True,
    )


async def _announcement_history(interaction: discord.Interaction) -> None:
    """List the most recent announcements (newest first)."""
    if await _deny_non_owner(interaction):
        return

    entries, was_corrupt = announcements.load_history()
    if was_corrupt:
        await reporting.report_error(
            "Announcement history file was corrupt and has been reset"
        )

    if not entries:
        await interaction.response.send_message(
            "📋 No announcements in history.", ephemeral=True
        )
        return

    header = "📋 **Announcement History**"
    lines = []
    used = len(header)
    for line in announcements.format_history_lines(entries):
        if used + len(line) + 4 > 2000:
            break
        lines.append(line)
        used += len(line)
    await interaction.response.send_message(
        header + "\n" + "\n".join(lines), ephemeral=True
    )


async def _announcement_resend(interaction: discord.Interaction, ann_id: str) -> None:
    """Re-send a stored announcement after showing a fresh preview."""
    if await _deny_non_owner(interaction):
        return

    entry = announcements.get_history_entry(ann_id)
    if not entry:
        await interaction.response.send_message(
            f"❌ No announcement with id `{ann_id}`.", ephemeral=True
        )
        return

    title = str(entry.get("title") or "Untitled")
    message = str(entry.get("message") or "")
    announcement_type = str(entry.get("type") or "Information")
    ping_mode = str(entry.get("ping_mode") or "No Ping")

    view = announcements.AnnouncementPreviewView(
        interaction.client,
        title=title,
        message=message,
        announcement_type=announcement_type,
        ping_mode=ping_mode,
        owner_id=OWNER_USER_ID,
    )
    embed = announcements.announcement_embed(title, message, announcement_type)
    await interaction.response.send_message(
        content=f"{announcements.PREVIEW_HEADING}\nResending `{ann_id}` · Ping: {ping_mode}",
        embed=embed,
        view=view,
        ephemeral=True,
    )


async def _announcement_delete(interaction: discord.Interaction, ann_id: str) -> None:
    """Delete one announcement from history."""
    if await _deny_non_owner(interaction):
        return

    if announcements.delete_history_entry(ann_id):
        await interaction.response.send_message(
            f"✅ Deleted `{ann_id}` from history.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❌ No announcement with id `{ann_id}`.", ephemeral=True
        )


async def _announcement_clear(interaction: discord.Interaction) -> None:
    """Clear the entire announcement history (needs explicit confirmation)."""
    if await _deny_non_owner(interaction):
        return

    view = announcements.HistoryClearView(owner_id=OWNER_USER_ID)
    await interaction.response.send_message(
        "🗑️ **Clear announcement history?** This removes every saved "
        "announcement and cannot be undone.",
        view=view,
        ephemeral=True,
    )


# Register the commands under the /owner group.
owner_group.command(name="botstatus", description="Show bot status")(_botstatus)
owner_group.command(name="refresh", description="Manually refresh world data")(_refresh)
owner_group.command(name="shutdown", description="Shut the bot down")(_shutdown)
owner_group.command(name="health", description="Show a live health report")(_health)
owner_group.command(name="stats", description="Show runtime and usage statistics")(_stats)
owner_group.command(name="version", description="Show version and environment details")(_version)
owner_group.command(
    name="announce",
    description="Broadcast an announcement to every announcement channel",
)(_announce)

whitelist_group.command(name="enable", description="Enable whitelist mode")(_whitelist_enable)
whitelist_group.command(name="disable", description="Disable whitelist mode")(_whitelist_disable)
whitelist_group.command(name="status", description="Show whitelist status")(_whitelist_status)
whitelist_group.command(name="add", description="Add a guild to the whitelist")(_whitelist_add)
whitelist_group.command(name="remove", description="Remove a guild from the whitelist")(_whitelist_remove)
whitelist_group.command(name="list", description="List whitelisted guilds")(_whitelist_list)

blacklist_group.command(name="add", description="Blacklist a guild with a reason")(_blacklist_add)
blacklist_group.command(name="remove", description="Remove a guild from the blacklist")(_blacklist_remove)
blacklist_group.command(name="list", description="List blacklisted guilds")(_blacklist_list)

announcement_group.command(
    name="history", description="List recent announcements"
)(_announcement_history)
announcement_group.command(
    name="resend", description="Re-send a stored announcement"
)(_announcement_resend)
announcement_group.command(
    name="delete", description="Delete an announcement from history"
)(_announcement_delete)
announcement_group.command(
    name="clear", description="Clear the entire announcement history"
)(_announcement_clear)
