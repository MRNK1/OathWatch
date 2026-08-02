"""Reusable world-state refresh shared by the hourly loop and /owner refresh.

The hourly loop and the manual owner command run the exact same pipeline
(fetch → validate → apply → persist → refresh boards → announce a mayor
change) so there is no duplicated refresh logic. Each refresh produces a
single RefreshResult whose one-line summary becomes exactly one message in
the log channel — never one per guild.

Failures are reported to the error channel and logged, never raised, so a
single bad guild or API hiccup cannot kill the cycle.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

import discord

from . import access_control, reporting, runtime
from .board import format_mayor_change_message
from .hypixel_api import get_election_data
from .setup import update_guild_boards
from .storage import load_config
from .world_state import (
    WORLD_STATE,
    apply_election_data,
    is_election_data_valid,
)
from .world_storage import save_world_state

logger = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    """Outcome of one refresh cycle."""

    ok: bool = False
    error: str = ""
    changed: bool = False
    mayor_changed: bool = False
    boards_refreshed: int = 0
    boards_recreated: int = 0

    @property
    def summary(self) -> str:
        """One-line summary for the log channel and owner reply."""
        parts = ["data changed" if self.changed else "data unchanged"]
        parts.append(f"{self.boards_refreshed} boards refreshed")
        if self.boards_recreated:
            parts.append(f"{self.boards_recreated} recreated")
        if self.mayor_changed:
            parts.append("mayor changed")
        return " · ".join(parts)


async def send_mayor_change_notification(bot, message) -> None:
    """Send a mayor-change message to every configured guild channel."""
    config = load_config()

    for guild_id, guild_data in config.get("guilds", {}).items():

        if not access_control.is_guild_allowed(guild_id):
            continue  # blocked guild: never send notifications

        if not guild_data.get("notify_enabled", True):
            continue

        channel = bot.get_channel(guild_data.get("channel_id"))

        if not isinstance(channel, discord.TextChannel):
            logger.warning("Channel not found for guild %s", guild_id)
            continue

        try:
            await channel.send(message)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Failed to send mayor change notification to %s: %s",
                guild_id,
                e,
            )
            await reporting.report_error(
                f"Mayor-change notification failed for guild {guild_id}", e
            )


async def _run_refresh_pipeline(bot) -> RefreshResult:
    """Execute one refresh cycle and return its outcome. Never raises."""
    try:
        data = await asyncio.to_thread(get_election_data)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to fetch election data: %s", e)
        await reporting.report_error("Hypixel API request failed", e)
        return RefreshResult(error="API request failed")

    if not is_election_data_valid(data):
        logger.warning("Invalid response from Hypixel API in update loop")
        return RefreshResult(error="invalid API response")

    try:
        changed = apply_election_data(data)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to apply election data: %s", e)
        await reporting.report_error("Failed to apply election data", e)
        return RefreshResult(error="failed to apply election data")

    try:
        save_world_state(WORLD_STATE)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to persist world state: %s", e)
        await reporting.report_error("Failed to persist world state", e)

    result = RefreshResult(ok=True, changed=changed)

    if changed:
        boards = await update_guild_boards(bot)
        result.boards_refreshed = boards.refreshed
        result.boards_recreated = boards.recreated

    if WORLD_STATE["last_announced"] != WORLD_STATE["mayor"]["name"]:
        logger.info(
            "Mayor changed: %s -> %s",
            WORLD_STATE["last_announced"],
            WORLD_STATE["mayor"]["name"],
        )

        message = format_mayor_change_message(
            WORLD_STATE["last_announced"],
            WORLD_STATE["mayor"]["name"],
        )

        await send_mayor_change_notification(bot, message)

        WORLD_STATE["last_announced"] = WORLD_STATE["mayor"]["name"]
        result.mayor_changed = True

        try:
            save_world_state(WORLD_STATE)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to persist world state: %s", e)
            await reporting.report_error("Failed to persist world state", e)

    return result


async def perform_refresh(bot) -> RefreshResult:
    """Run one timed refresh cycle; log to the Log channel when it is slow.

    Times the pipeline, records the duration and outcome in :mod:`runtime`
    so the ``/owner`` health/stats commands can report them, and warns on
    the Log channel when a refresh exceeds the slow threshold. Never raises.
    """
    started = time.monotonic()
    result = await _run_refresh_pipeline(bot)
    duration = time.monotonic() - started

    runtime.record_refresh(duration, ok=result.ok, error=result.error)

    if duration > runtime.SLOW_REFRESH_THRESHOLD:
        logger.warning("Slow refresh detected: %.1fs", duration)
        await reporting.send_log(
            "⚠️ **Slow refresh detected**\n"
            f"Duration: {duration:.1f}s\n"
            f"Average: {runtime.average_refresh():.1f}s\n"
            f"Guilds: {len(load_config().get('guilds', {}))}\n"
            f"Timestamp: <t:{int(time.time())}:F>"
        )

    return result
