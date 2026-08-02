"""Setup orchestration for configuring a guild in one step.

Board-agnostic: setup iterates the registered board types (board_registry)
and never hard-codes which boards exist. Adding a future board only requires
registering it — nothing here changes.
"""
import logging
from dataclasses import dataclass

import discord

from . import access_control, reporting
from .board_health import (
    MAX_CONSECUTIVE_FAILURES,
    format_cleanup_message,
    format_recovery_message,
    record_permanent_failure,
    record_success,
)
from .board_registry import UnknownBoardError, all_boards, get_board
from .storage import load_config, save_config

logger = logging.getLogger(__name__)

# Every permanent board failure so far means the update channel is gone, so the
# cleanup log's Reason field is always this value.
CHANNEL_DELETED_REASON = "Channel deleted"


class SetupError(Exception):
    """Raised when a guild cannot be configured (e.g. missing permissions)."""


class BoardPermanentError(SetupError):
    """Raised when a board can never be recovered (its channel is gone).

    Distinct from the transient ``SetupError`` failures: a permanent failure
    means Discord reports the update channel or message as not found, so
    neither self-healing nor a retry can ever bring the board back. Callers
    use this to drive the stale-board cleanup lifecycle.
    """


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
    (message_id, created). Raises SetupError on permission/HTTP failures and
    BoardPermanentError when the update channel is gone (irrecoverable).
    """
    if stored_id:
        try:
            message = await channel.fetch_message(stored_id)
            await message.edit(embed=embed)
            return stored_id, False
        except discord.NotFound:
            # The stored message is gone, but the channel is still live:
            # self-heal by recreating the board below.
            logger.info("Board message %s was deleted; recreating it", stored_id)
        except discord.Forbidden:
            raise SetupError(
                f"I can no longer access the board in {channel.mention}."
            ) from None
        except discord.HTTPException as e:
            raise SetupError(
                f"Failed to update the board in {channel.mention}: {e}"
            ) from e

    try:
        message = await channel.send(embed=embed)
        return message.id, True
    except discord.NotFound:
        # The update channel was deleted mid-flight. Self-healing cannot help,
        # so this is the one permanent failure that drives stale-board cleanup.
        raise BoardPermanentError(
            f"The update channel {channel.mention} no longer exists."
        ) from None
    except discord.Forbidden:
        raise SetupError(
            f"I need **Send Messages** permission in {channel.mention}."
        ) from None
    except discord.HTTPException as e:
        raise SetupError(
            f"Failed to post the board in {channel.mention}: {e}"
        ) from e


async def _delete_orphaned_board(channel, message_id) -> None:
    """Best-effort delete a tracked board message living in another channel.

    Never raises: an already-gone message (NotFound) is expected, and
    Forbidden/HTTP failures are logged so the caller can drop the stale
    reference and continue placing the board in its new channel.
    """
    try:
        message = await channel.fetch_message(message_id)
        await message.delete()
        logger.info(
            "Deleted orphaned board message %s from %s",
            message_id,
            channel.mention,
        )
    except discord.NotFound:
        logger.info("Orphaned board message %s was already deleted", message_id)
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.error(
            "Failed to delete orphaned board message %s: %s", message_id, e
        )


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
    old_channel_id = guild_data.get("channel_id")
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

        # A board tracked in a different channel would be orphaned by this
        # setup. Remove it so a guild never ends up with two boards of the
        # same type. Failures are logged, never raised.
        if stored_id and old_channel_id and old_channel_id != channel.id:
            old_channel = channel.guild.get_channel(old_channel_id)
            if isinstance(old_channel, discord.TextChannel):
                await _delete_orphaned_board(old_channel, stored_id)
            else:
                logger.info(
                    "Old channel %s no longer exists; dropping stale board %s",
                    old_channel_id,
                    stored_id,
                )
            # The stored reference belonged to the old channel; clear it so
            # a later failure never leaves a dangling pointer.
            boards.pop(key, None)
            stored_id = None
            save_config(data)

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
        candidate = bot.get_channel(channel_id)
        if isinstance(candidate, discord.TextChannel):
            channel = candidate

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
            logger.info("Board message %s already gone during unsetup", message_id)
        except Exception as e:
            logger.error("Failed to delete board during unsetup: %s", e)

    note = f" Deleted {len(deleted)} board message(s)." if deleted else ""
    return f"✅ Setup removed for **{guild_name}**.{note}"


@dataclass
class BoardsRefreshResult:
    """Counts for one board-refresh pass (used in the refresh summary)."""

    refreshed: int = 0
    recreated: int = 0


async def update_guild_boards(bot: discord.Client) -> BoardsRefreshResult:
    """Refresh all tracked boards in every configured guild.

    Self-heals boards whose stored message was deleted (channel still live).
    When a board's update channel is permanently gone, a consecutive permanent-
    failure counter is tracked per (guild, board); after
    ``MAX_CONSECUTIVE_FAILURES`` consecutive failures the stale reference is
    removed from config.json and logged once. Any successful update before
    that resets the counter and logs a one-time recovery. Transient failures
    (HTTPException, Forbidden, rate limits, timeouts) never touch the counter
    and never remove data.

    Never raises; each failure is logged and reported to the error channel so
    the hourly loop keeps running. Returns a count of boards edited in place
    vs recreated, which the caller folds into a single refresh summary.
    """
    config = load_config()
    result = BoardsRefreshResult()

    for guild_id, guild_data in config.get("guilds", {}).items():

        if not access_control.is_guild_allowed(guild_id):
            continue  # blocked guild: no board updates, recreation, or self-healing

        channel = bot.get_channel(guild_data.get("channel_id"))
        boards = guild_data.get("boards") or {}

        if not isinstance(channel, discord.TextChannel):
            # The update channel is permanently gone, so every tracked board in
            # this guild can never be recovered. Count one permanent failure per
            # board; on the third consecutive failure the stale reference is
            # removed (the guild's channel config and notification settings are
            # deliberately kept so a re-run of /setup can recover cleanly).
            if boards:
                logger.warning("Channel not found for guild %s", guild_id)
                for board_key in list(boards):
                    await _count_permanent_failure(
                        bot, guild_id, board_key, boards, config
                    )
            continue

        dirty = False
        # Iterate a snapshot: _count_permanent_failure pops a board at the
        # failure threshold, which would otherwise resize the dict under the
        # live iterator and abort the refresh (RuntimeError) before any
        # remaining boards are processed.
        for board_key, board_info in list(boards.items()):

            stored_id = None
            if isinstance(board_info, dict):
                stored_id = board_info.get("message_id")

            try:
                embed = get_board(board_key).build_embed()
            except UnknownBoardError:
                logger.warning(
                    "Unknown board type '%s' in guild %s", board_key, guild_id
                )
                continue

            try:
                new_id, _ = await place_board(channel, embed, stored_id)
            except BoardPermanentError as e:
                logger.error(
                    "Board '%s' in guild %s cannot be recovered: %s",
                    board_key,
                    guild_id,
                    e,
                )
                await _count_permanent_failure(
                    bot, guild_id, board_key, boards, config
                )
                continue
            except SetupError as e:
                logger.error(
                    "Failed to refresh board '%s' in guild %s: %s",
                    board_key,
                    guild_id,
                    e,
                )
                await reporting.report_error(
                    f"Failed to refresh board '{board_key}' in guild {guild_id}",
                    e,
                )
                continue

            # Success (including a self-healed recreation): a board that had
            # been failing is healthy again — reset its counter and log once.
            previous_failures = record_success(board_info)
            if previous_failures:
                await _log_board_recovered(
                    bot, guild_id, board_key, previous_failures
                )
                dirty = True

            if new_id != stored_id:
                # A self-healed recreation also drops any leftover counter.
                guild_data["boards"][board_key] = {"message_id": new_id}
                dirty = True
                result.recreated += 1
            else:
                result.refreshed += 1

        if dirty:
            save_config(config)

    return result


async def _count_permanent_failure(
    bot, guild_id: str, board_key: str, boards: dict, config: dict
) -> None:
    """Record one permanent failure; on failure, remove + log the board.

    Execution order is pinned:

    1. mutate the in-memory ``boards`` dict;
    2. persist it via ``save_config``;
    3. on a failed save — roll the mutation back so memory matches disk,
       report the error, log the deferral, and keep going so remaining
       boards and guilds still process;
    4. on a successful save — never roll back, emit the cleanup log exactly
       once, and keep going.

    Reporting can never undo a persisted change: rollback only lives inside
    the ``except OSError`` branch, which runs only when the save itself
    failed. A report/log-channel failure is contained and logged so it can
    never abort the refresh loop or retract a persisted cleanup.
    """
    entry = boards.get(board_key)
    previous = dict(entry) if isinstance(entry, dict) else entry

    failures = record_permanent_failure(boards, board_key)
    removed = board_key not in boards

    try:
        save_config(config)
    except OSError as e:
        # 3) failed save: roll back so the removal/counter-bump never actually
        # happened, and the next refresh retries the same board. Reporting
        # below stays contained so it cannot abort the loop after the rollback.
        boards[board_key] = previous
        logger.error(
            "Failed to persist board '%s' update in guild %s: %s",
            board_key,
            guild_id,
            e,
        )
        try:
            await reporting.report_error(
                f"Failed to save config for board '{board_key}' in guild {guild_id}",
                e,
            )
        except Exception as report_err:  # noqa: BLE001 - reporting must not abort
            logger.error(
                "Failed to reach the error channel while reporting board '%s' "
                "in guild %s: %s",
                board_key,
                guild_id,
                report_err,
            )
        if removed:
            await _send_cleanup_deferred(bot, guild_id, board_key)
        return

    # 4) save succeeded: the change is persisted. Never roll back after this.
    if failures >= MAX_CONSECUTIVE_FAILURES:
        try:
            await _log_board_cleanup(bot, guild_id, board_key, failures)
        except Exception as cleanup_err:  # noqa: BLE001 - reporting must not abort
            logger.error(
                "Board '%s' cleanup saved but its log failed in guild %s: %s",
                board_key,
                guild_id,
                cleanup_err,
            )


async def _log_board_cleanup(
    bot, guild_id: str, board_key: str, failures: int
) -> None:
    """Send the single final cleanup message for a removed stale board."""
    message = format_cleanup_message(
        _guild_name(bot, guild_id),
        guild_id,
        _board_display_name(board_key),
        CHANNEL_DELETED_REASON,
        failures,
    )
    logger.info("Board cleanup: %s", _one_line(message))
    await reporting.send_log(message)


async def _send_cleanup_deferred(bot, guild_id: str, board_key: str) -> None:
    """Notify that a cleanup could not be persisted and is deferred.

    Logs the notice to the console so it stays visible even if the log
    channel is unreachable. Never raises: a failing send only records the
    error, so the refresh loop keeps running.
    """
    message = "\n\n".join(
        [
            "⚠️ Board Cleanup Deferred",
            f"Guild:\n{_guild_name(bot, guild_id)}",
            f"Board:\n{_board_display_name(board_key)}",
            "Reason:\nCould not save config.json",
            "Action:\nStale board reference will be retried on the next refresh",
        ]
    )
    logger.info("Board cleanup deferred: %s", _one_line(message))
    try:
        await reporting.send_log(message)
    except Exception as e:  # noqa: BLE001 - reporting is never fatal
        logger.error(
            "Could not send deferred cleanup notice for board '%s' in guild %s: %s",
            board_key,
            guild_id,
            e,
        )


async def _log_board_recovered(
    bot, guild_id: str, board_key: str, attempts: int
) -> None:
    """Send the one-time message for a board that recovered before cleanup."""
    message = format_recovery_message(
        _guild_name(bot, guild_id),
        _board_display_name(board_key),
        attempts,
    )
    logger.info("Board recovered: %s", _one_line(message))
    await reporting.send_log(message)


def _guild_name(bot, guild_id: str) -> str:
    """Best-effort guild display name; falls back to the raw id."""
    get_guild = getattr(bot, "get_guild", None)
    if get_guild is not None:
        try:
            guild = get_guild(int(guild_id))
        except (TypeError, ValueError):
            guild = None
        if guild is not None:
            name = getattr(guild, "name", None)
            if name:
                return str(name)
    return str(guild_id)


def _board_display_name(board_key: str) -> str:
    """Registry display name without the trailing ' Board' suffix."""
    try:
        return get_board(board_key).name.removesuffix(" Board")
    except UnknownBoardError:
        return board_key


def _one_line(message: str) -> str:
    """Flatten a multi-line log message for a single console line."""
    return " | ".join(line for line in message.splitlines() if line)
