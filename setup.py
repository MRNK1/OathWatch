"""Setup orchestration for configuring a guild in one step.

Board-agnostic: setup iterates the registered board types (board_registry)
and never hard-codes which boards exist. Adding a future board only requires
registering it — nothing here changes.
"""
import logging

import discord

import board  # noqa: F401  (registers the Mayor Board on import)
from board_registry import UnknownBoardError, all_boards, get_board
from storage import load_config, save_config

logger = logging.getLogger(__name__)


class SetupError(Exception):
    """Raised when a guild cannot be configured (e.g. missing permissions)."""


def _missing_permissions(channel: discord.TextChannel) -> list:
    """Return the permission names the bot lacks in the given channel."""
    bot_member = channel.guild.me
    if bot_member is None:
        raise SetupError(
            "Could not verify the bot's permissions in that channel. Try again."
        )

    channel_perms = channel.permissions_for(bot_member)

    missing = []
    for perm_name in ("send_messages", "embed_links", "read_message_history"):
        if not getattr(channel_perms, perm_name):
            missing.append(perm_name.replace("_", " ").title())
    return missing


async def place_board(channel: discord.TextChannel, embed, stored_id):
    """Post or update a board message in a channel.

    If stored_id points to a live message it is edited in place; if it was
    deleted (or is absent), a new message is created. Returns
    (message_id, created). Raises SetupError on permission/HTTP failures.
    """
    if stored_id:
        try:
            message = await channel.fetch_message(stored_id)
            await message.edit(embed=embed)
            return stored_id, False
        except discord.NotFound:
            logger.info(f"Board message {stored_id} was deleted; recreating it")
        except discord.Forbidden:
            raise SetupError(f"I can no longer access the board in {channel.mention}.")
        except discord.HTTPException as e:
            raise SetupError(f"Failed to update the board in {channel.mention}: {e}")

    try:
        message = await channel.send(embed=embed)
        return message.id, True
    except discord.Forbidden:
        raise SetupError(f"I need **Send Messages** permission in {channel.mention}.")
    except discord.HTTPException as e:
        raise SetupError(f"Failed to post the board in {channel.mention}: {e}")


async def run_setup(
    guild_id: str,
    channel: discord.TextChannel,
    board_keys: list = None,
    notify: bool = True,
) -> str:
    """Configure a guild: place/refresh each requested board and persist config.

    board_keys defaults to every registered board. Boards are saved one at a
    time so a partial failure never creates a duplicate and a later retry
    resumes cleanly. Returns a confirmation summary.
    """
    if board_keys is None:
        board_keys = [board.key for board in all_boards()]

    missing = _missing_permissions(channel)
    if missing:
        raise SetupError(
            f"I need **{', '.join(missing)}** permission in {channel.mention}."
        )

    data = load_config()
    guild_data = data["guilds"].setdefault(guild_id, {})
    guild_data["channel_id"] = channel.id
    guild_data["notify_enabled"] = bool(notify)
    boards = guild_data.setdefault("boards", {})
    save_config(data)

    placed = []
    for key in board_keys:
        board_type = get_board(key)
        stored_id = None
        info = boards.get(key)
        if isinstance(info, dict):
            stored_id = info.get("message_id")

        embed = board_type.build_embed()
        message_id, created = await place_board(channel, embed, stored_id)

        boards[key] = {"message_id": message_id}
        save_config(data)
        placed.append((board_type.name, created))

    lines = [
        f"✅ Setup complete for **{channel.guild.name}**.",
        f"- Updates channel: {channel.mention}",
        f"- Mayor change notifications: {'on' if notify else 'off'}",
    ]
    for name, created in placed:
        action = "created" if created else "updated"
        lines.append(f"- {name}: {action}.")
    return "\n".join(lines)


async def run_unsetup(bot: discord.Client, guild_id: str, guild_name: str) -> str:
    """Remove a guild's configuration and best-effort delete its boards."""
    data = load_config()
    guild_data = data.get("guilds", {}).pop(guild_id, None)
    save_config(data)

    if not guild_data:
        return f"ℹ️ **{guild_name}** was not configured."

    channel = None
    channel_id = guild_data.get("channel_id")
    if channel_id:
        channel = bot.get_channel(channel_id)

    deleted = []
    for board_info in (guild_data.get("boards") or {}).values():
        message_id = board_info.get("message_id") if isinstance(board_info, dict) else None
        if not channel or not message_id:
            continue
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
            deleted.append(message_id)
        except discord.NotFound:
            logger.info(f"Board message {message_id} already gone during unsetup")
        except Exception as e:
            logger.error(f"Failed to delete board during unsetup: {e}")

    note = f" Deleted {len(deleted)} board message(s)." if deleted else ""
    return f"✅ Setup removed for **{guild_name}**.{note}"


async def update_guild_boards(bot: discord.Client):
    """Refresh all tracked boards in every configured guild.

    Self-heals boards whose stored message was deleted. Never raises; each
    failure is logged so the hourly loop keeps running.
    """
    config = load_config()

    for guild_id, guild_data in config.get("guilds", {}).items():

        channel = bot.get_channel(
            guild_data.get("channel_id")
        )

        if not channel:
            logger.warning(
                f"Channel not found for guild {guild_id}"
            )
            continue

        for board_key, board_info in (guild_data.get("boards") or {}).items():

            stored_id = None
            if isinstance(board_info, dict):
                stored_id = board_info.get("message_id")

            try:
                embed = get_board(board_key).build_embed()
            except UnknownBoardError:
                logger.warning(
                    f"Unknown board type '{board_key}' in guild {guild_id}"
                )
                continue

            try:
                new_id, _ = await place_board(channel, embed, stored_id)
            except SetupError as e:
                logger.error(
                    f"Failed to refresh board '{board_key}' in guild {guild_id}: {e}"
                )
                continue

            if new_id != stored_id:
                guild_data["boards"][board_key] = {"message_id": new_id}
                save_config(config)
