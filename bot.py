import asyncio
import logging
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import storage_utils
from board import build_mayor_board_embed, format_mayor_change_message
from hypixel_api import get_election_data
from setup import SetupError, place_board, run_setup, run_unsetup, update_guild_boards
from storage import load_config, save_config
from world_state import (
    WORLD_STATE,
    apply_election_data,
    is_election_data_valid,
    normalize_world_state,
)
from world_storage import load_world_state, save_world_state

__version__ = "0.5.0"

logger = logging.getLogger(__name__)

# Every variable required to run the bot, kept in one place so startup
# validation and this list never drift apart.
REQUIRED_ENV = ("DISCORD_TOKEN", "HYPIXEL_API_KEY")

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


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
        logger.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

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
    except Exception as e:
        logger.error(
            "Failed to remove configuration for guild %s: %s", guild_id, e
        )

@bot.tree.command(name="status", description="Check bot status")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"🏰 OathWatch Online\nLatency: {round(bot.latency * 1000)}ms"
    )

@bot.tree.command(name="setchannel", description="Set update channel")
@app_commands.default_permissions(administrator=True)
async def setchannel(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):
    data = load_config()

    guild_id = str(_get_guild(interaction).id)

    guild_data = data["guilds"].setdefault(guild_id, {})
    guild_data["channel_id"] = channel.id

    save_config(data)

    await interaction.response.send_message(
        f"✅ Update channel set to {channel.mention}"
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

    summary = await run_setup(
        str(_get_guild(interaction).id),
        channel,
        board_keys=board_keys,
        notify=notify,
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
        logger.error(f"Failed to fetch election data: {e}")
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

    original = getattr(error, "original", None)
    if isinstance(original, SetupError):
        message = str(original)
    else:
        message = "❌ Something went wrong. Please try again later."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def send_mayor_change_notification(message):
    """Send a mayor-change message to every configured guild channel."""
    config = load_config()

    for guild_id, guild_data in config.get("guilds", {}).items():

        if not guild_data.get("notify_enabled", True):
            continue

        channel = bot.get_channel(
            guild_data.get("channel_id")
        )

        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                f"Channel not found for guild {guild_id}"
            )
            continue

        try:
            await channel.send(message)
        except Exception as e:
            logger.error(
                f"Failed to send mayor change notification to {guild_id}: {e}"
            )


@tasks.loop(hours=1)
async def mayor_update_loop():

    try:
        data = await asyncio.to_thread(get_election_data)
    except Exception as e:
        logger.error(f"Failed to fetch election data: {e}")
        return

    if not is_election_data_valid(data):
        logger.warning("Invalid response from Hypixel API in update loop")
        return

    try:
        changed = apply_election_data(data)
    except Exception as e:
        logger.error(f"Failed to apply election data: {e}")
        return

    try:
        save_world_state(WORLD_STATE)
    except Exception as e:
        logger.error(f"Failed to persist world state: {e}")

    if changed:
        await update_guild_boards(bot)

    if WORLD_STATE["last_announced"] != WORLD_STATE["mayor"]["name"]:
        logger.info(
            f"Mayor changed: {WORLD_STATE['last_announced']} -> "
            f"{WORLD_STATE['mayor']['name']}"
        )

        message = format_mayor_change_message(
            WORLD_STATE["last_announced"],
            WORLD_STATE["mayor"]["name"]
        )

        await send_mayor_change_notification(message)

        WORLD_STATE["last_announced"] = WORLD_STATE["mayor"]["name"]

        try:
            save_world_state(WORLD_STATE)
        except Exception as e:
            logger.error(f"Failed to persist world state: {e}")

@mayor_update_loop.error  # type: ignore[type-var]
async def on_mayor_update_loop_error(error):
    """Last-resort safety net so the hourly loop can never die silently."""
    logger.error(
        "mayor_update_loop crashed, restarting: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )
    mayor_update_loop.restart()


def get_missing_env() -> list:
    """Names of required environment variables that are unset or blank."""
    return [name for name in REQUIRED_ENV if not os.getenv(name)]


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

    missing = get_missing_env()
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
        WORLD_STATE["last_updated"],
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