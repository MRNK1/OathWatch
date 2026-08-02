"""OathWatch bot: Discord client, slash commands, and the hourly update loop.

This module owns the Discord client, every slash command, the hourly
world-state refresh, and lifecycle cleanup. It is importable without running
(no env or network side effects); launch it via the top-level ``bot.py``
launcher, ``python -m oathwatch``, or ``main()`` directly.

Owner-only administration commands live in ``owner`` (guild-scoped, so they
never sync to public servers); status/log/error channel reporting lives in
``reporting``; the shared refresh pipeline lives in ``refresh``.
"""
import asyncio
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from . import __version__, access_control, owner, reporting, storage_utils
from .board import build_mayor_board_embed
from .formatting import last_updated_text
from .hypixel_api import get_election_data
from .refresh import perform_refresh
from .setup import SetupError, place_board, run_setup, run_unsetup
from .storage import load_config, save_config
from .world_state import (
    WORLD_STATE,
    apply_election_data,
    is_election_data_valid,
    normalize_world_state,
)
from .world_storage import load_world_state, save_world_state

logger = logging.getLogger(__name__)

# Every variable required to run the bot, kept in one place so startup
# validation and this list never drift apart. The reporting channel IDs
# (BOT_STATUS/LOG/ERROR_CHANNEL_ID) are optional, not required.
REQUIRED_ENV = ("DISCORD_TOKEN", "HYPIXEL_API_KEY")

intents = discord.Intents.default()


class OathWatchCommandTree(app_commands.CommandTree):
    """Command tree that disables commands inside blocked guilds.

    ``interaction_check`` runs before every slash command, so this single
    gate covers every command — including any future ones — with no
    per-command edits. Users in a blocked guild receive the ephemeral
    disabled message and their command is dropped. The owner guild is
    exempt so the owner control panel can never be locked out.
    """

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        guild_id = interaction.guild_id

        if guild_id is None:
            return True  # direct message: no guild to gate

        if guild_id == owner.OWNER_GUILD_ID:
            return True  # owner controls must always be reachable

        if access_control.is_guild_allowed(guild_id):
            return True

        # Blocked guild: tell the user (only for real command invocations —
        # autocomplete requests cannot carry a message response) and drop it.
        if interaction.type is discord.InteractionType.application_command:
            message = access_control.blocked_message(guild_id)
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        return False


class OathWatchBot(commands.Bot):
    """Bot subclass that reports controlled shutdowns to the status channel.

    Overriding ``close`` means the 🔴 shutdown marker is sent no matter how a
    clean shutdown happens — the /owner shutdown command, a Ctrl+C, or a
    reconnect loop ending. The status send happens before the underlying
    close, while the HTTP session is still usable.
    """

    async def close(self) -> None:
        await reporting.send_shutdown_status()
        await super().close()


bot = OathWatchBot(
    command_prefix="!",
    intents=intents,
    tree_cls=OathWatchCommandTree,
)

# Route channel reporting to this bot instance and register the owner-only
# /owner group. The group is guild-scoped, so it only ever syncs to the
# owner guild and never appears in any public server.
reporting.configure(bot)
bot.tree.add_command(owner.owner_group)


def _get_guild(interaction: discord.Interaction) -> discord.Guild:
    """Resolve a command's guild, rejecting direct-message usage."""
    guild = interaction.guild
    if guild is None:
        raise SetupError("This command can only be used inside a server.")
    return guild

@bot.event
async def on_ready():
    logger.info("%s is online in %d guild(s)", bot.user, len(bot.guilds))

    try:
        synced = await bot.tree.sync()
        logger.info("Synced %d global commands", len(synced))
    except Exception as e:
        logger.error("Failed to sync global commands: %s", e)
        await reporting.report_error("Failed to sync global commands", e)

    # Owner commands are guild-scoped and must never be synced globally, so
    # they are synced separately to the owner guild only.
    try:
        synced = await bot.tree.sync(guild=owner.OWNER_GUILD)
        logger.info("Synced %d owner commands to owner guild", len(synced))
    except Exception as e:
        logger.error("Failed to sync owner commands: %s", e)
        await reporting.report_error("Failed to sync owner commands", e)

    if reporting.is_restart():
        await reporting.send_status("🔄 Bot Restarted")
    else:
        await reporting.send_status("🟢 Bot Started")
        reporting.mark_started()

    await reporting.send_log(f"📦 OathWatch v{__version__} started")

    if not mayor_update_loop.is_running():
        mayor_update_loop.start()

@bot.event
async def on_guild_remove(guild: discord.Guild):
    """Remove configuration for a guild the bot just left.

    World state is global (not per-guild) and is deliberately left intact.
    Only the departed guild's config entry is removed, so active guilds are
    never touched. Failures are logged so the removal can never crash the
    event loop.
    """
    guild_id = str(guild.id)
    data = load_config()

    if guild_id not in data.get("guilds", {}):
        return

    data["guilds"].pop(guild_id, None)

    try:
        save_config(data)
        logger.info(
            "Removed configuration for guild %s (%s)", guild_id, guild.name
        )
        await reporting.send_log(
            f"🗑️ Guild {guild.name} ({guild_id}) left; configuration removed"
        )
    except Exception as e:
        logger.error(
            "Failed to remove configuration for guild %s: %s", guild_id, e
        )

@bot.event
async def on_error(event, *_args, **_kwargs):
    """Report unhandled exceptions raised by other events."""
    logger.error("Unhandled error in event %s", event, exc_info=True)
    await reporting.report_error(f"Unhandled error in event '{event}'", sys.exc_info())

@bot.tree.command(name="status", description="Check bot status")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"🏰 OathWatch Online\nLatency: {round(bot.latency * 1000)}ms"
    )

@bot.tree.command(name="testchannel", description="Send a test message")
@app_commands.default_permissions(administrator=True)
async def testchannel(interaction: discord.Interaction):
    data = load_config()

    guild_id = str(_get_guild(interaction).id)

    if guild_id not in data.get("guilds", {}):
        await interaction.response.send_message(
            "❌ No channel configured."
        )
        return

    channel_id = data["guilds"][guild_id]["channel_id"]
    channel = bot.get_channel(channel_id)

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Channel not found."
        )
        return

    await channel.send("📜 OathWatch test message.")

    await interaction.response.send_message(
        "✅ Test message sent."
    )

@bot.tree.command(name="setchannel", description="Set this server's announcement channel")
@app_commands.default_permissions(administrator=True)
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set the per-guild announcement channel (stored as announcement_channel_id).

    Replaces the legacy update-channel role of this command: announcements
    (updates, patch notes, maintenance, warnings) are delivered to this
    channel and nowhere else. The update board channel is still chosen by
    ``/setup``; the two are independent.
    """
    if channel.guild.id != _get_guild(interaction).id:
        await interaction.response.send_message(
            "❌ The channel must be in this server."
        )
        return

    guild_id = str(_get_guild(interaction).id)
    data = load_config()
    guild_data = data["guilds"].setdefault(guild_id, {})
    guild_data["announcement_channel_id"] = channel.id
    save_config(data)

    await reporting.send_log(
        f"📣 Announcement channel set to #{channel.name} in {channel.guild.name}"
    )
    await interaction.response.send_message(
        f"✅ Announcement channel set to {channel.mention}."
    )


@bot.tree.command(name="setup", description="Configure this server in one step")
@app_commands.default_permissions(administrator=True)
async def setup(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    mayor_board: bool = True,
    election_board: bool = True,
    notify: bool = True,
):
    if channel.guild.id != _get_guild(interaction).id:
        await interaction.response.send_message(
            "❌ The channel must be in this server."
        )
        return

    # The board choices live here (the UI), not in run_setup: setup stays
    # board-agnostic and simply places whatever keys it is given.
    board_keys = []
    if mayor_board:
        board_keys.append("mayor")
    if election_board:
        board_keys.append("election")
    if not board_keys:
        await interaction.response.send_message(
            "❌ Select at least one board to set up."
        )
        return

    await interaction.response.defer()

    guild = _get_guild(interaction)

    summary = await run_setup(
        str(guild.id),
        channel,
        board_keys=board_keys,
        notify=notify,
    )

    await reporting.send_log(
        f"✅ Setup completed for guild {guild.name} ({len(board_keys)} boards)"
    )

    await interaction.followup.send(summary)

@bot.tree.command(name="unsetup", description="Remove this server's configuration")
@app_commands.default_permissions(administrator=True)
async def unsetup(interaction: discord.Interaction):
    guild = _get_guild(interaction)
    summary = await run_unsetup(
        bot,
        str(guild.id),
        guild.name,
    )
    await reporting.send_log(
        f"🗑️ Setup removed for guild {guild.name} ({guild.id})"
    )
    await interaction.response.send_message(summary)

@bot.tree.command(name="board", description="Show OathWatch board")
async def board(interaction: discord.Interaction):

    embed = build_mayor_board_embed()

    data = load_config()

    guild_id = str(_get_guild(interaction).id)

    guild_data = data.get("guilds", {}).get(guild_id)

    if guild_data:
        channel = bot.get_channel(guild_data.get("channel_id"))

        if isinstance(channel, discord.TextChannel) and channel.id == interaction.channel_id:
            # In the configured update channel: manage the tracked Mayor
            # Board in place so /board never creates duplicates.
            stored_id = None
            board_info = (guild_data.get("boards") or {}).get("mayor")
            if isinstance(board_info, dict):
                stored_id = board_info.get("message_id")

            new_id, _ = await place_board(channel, embed, stored_id)

            if new_id != stored_id:
                guild_data.setdefault("boards", {})["mayor"] = {
                    "message_id": new_id
                }
                save_config(data)

            await interaction.response.send_message(
                "✅ Mayor Board updated in this channel."
            )
            return

    await interaction.response.send_message(embed=embed)

    if not guild_data:
        await interaction.followup.send(
            "❌ No channel configured. Run `/setup` first."
        )

@bot.tree.command(name="checkmayor", description="Update mayor data")
async def checkmayor(interaction: discord.Interaction):

    try:
        data = await asyncio.to_thread(get_election_data)
    except Exception as e:
        logger.error("Failed to fetch election data: %s", e)
        await reporting.report_error("Hypixel API request failed", e)
        await interaction.response.send_message(
            "❌ Could not fetch data from the Hypixel API. Please try again later."
        )
        return

    if not is_election_data_valid(data):
        await interaction.response.send_message(
            "❌ Invalid response from the Hypixel API."
        )
        return

    apply_election_data(data)

    save_world_state(WORLD_STATE)

    await interaction.response.send_message(
        "✅ World state updated."
    )

@bot.tree.error
async def on_tree_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    logger.error(
        "Command %s failed: %s",
        interaction.command.name if interaction.command else "?",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )

    await reporting.report_error(
        f"Command '{interaction.command.name if interaction.command else '?'}' failed",
        error,
    )

    original = getattr(error, "original", None)
    if isinstance(original, SetupError):
        message = str(original)
    else:
        message = "❌ Something went wrong. Please try again later."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@tasks.loop(hours=1)
async def mayor_update_loop():
    result = await perform_refresh(bot)
    if result.ok:
        await reporting.send_log(f"🔄 Hourly refresh: {result.summary}")

@mayor_update_loop.error  # type: ignore[type-var]
async def on_mayor_update_loop_error(error):
    """Last-resort safety net so the hourly loop can never die silently."""
    logger.error(
        "mayor_update_loop crashed, restarting: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )
    await reporting.report_error("Hourly update loop crashed; restarting", error)
    mayor_update_loop.restart()


def get_missing_env() -> list:
    """Names of required environment variables that are unset or blank."""
    return [name for name in REQUIRED_ENV if not os.getenv(name)]


def validate_env() -> list:
    """Per-variable validation report for the startup banner.

    Returns ``(name, required, present)`` tuples for every known variable.
    Reporting channel IDs are optional, so a missing one is a ⚠ (warning),
    never fatal. Kept independent of ``get_missing_env`` so the old strict
    check (still used by tests) and the new per-variable report never drift.
    """
    names = list(REQUIRED_ENV) + [
        reporting.STATUS_CHANNEL_ENV,
        reporting.LOG_CHANNEL_ENV,
        reporting.ERROR_CHANNEL_ENV,
    ]
    return [
        (name, name in REQUIRED_ENV, bool(os.getenv(name)))
        for name in names
    ]


def _log_env_validation() -> list:
    """Log one ✅/⚠ line per variable; returns the missing-required names."""
    missing_required = []
    for name, required, present in validate_env():
        if present:
            logger.info("✅ %s configured", name)
        elif required:
            logger.warning("⚠ %s missing (required)", name)
            missing_required.append(name)
        else:
            logger.info("⚠ %s not configured (optional)", name)
    return missing_required


def _load_saved_state() -> None:
    """Merge persisted world state into the runtime cache if present."""
    saved = load_world_state()
    if saved:
        WORLD_STATE.update(normalize_world_state(saved))


def main() -> int:
    """Configure logging, validate the environment, and run the bot.

    Returns an exit code so a fresh deployment can fail fast with a clear
    message instead of crashing mid-import.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_dotenv()

    missing = _log_env_validation()
    if missing:
        logger.critical(
            "Missing required environment variable(s): %s",
            ", ".join(missing),
        )
        logger.critical(
            "Copy .env.example to .env and fill in every value, then restart."
        )
        return 1

    _load_saved_state()

    # Present — get_missing_env() returned above already guaranteed this.
    token = os.environ["DISCORD_TOKEN"]

    logger.info("Starting OathWatch %s", __version__)
    logger.info("Data directory: %s", storage_utils.DATA_DIR)
    logger.info(
        "Configured guilds: %d",
        len(load_config().get("guilds", {})),
    )
    logger.info(
        "World state: mayor=%s, last_updated=%s",
        WORLD_STATE["mayor"]["name"],
        last_updated_text(WORLD_STATE["last_updated"]),
    )

    try:
        bot.run(token)
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    except Exception as e:
        logger.critical("Fatal error while running: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
