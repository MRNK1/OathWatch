"""Channel reporting for status, operational logs, and errors.

All messages to the three configured Discord channels (status, log, error)
flow through this one module so owner commands, the hourly loop, and every
error handler reuse a single path. Channel IDs are read from the environment
(``.env``) and are optional: when a channel is unset, missing, or a send
fails, reporting degrades silently to console logging and never crashes the
caller.

Channel contracts (see .env.example):
- Status channel: only the startup/shutdown markers (🟢/🔄/🔴).
- Log channel: one operational summary per refresh cycle, plus setup and
  configuration changes and version info — never one message per guild.
- Error channel: failures with their traceback inside a code block.
"""
import logging
import os
import traceback

from . import storage_utils
from .formatting import truncate

logger = logging.getLogger(__name__)

# Discord caps message content at 2000 characters; tracebacks are clipped so
# the whole report fits one message.
MAX_MESSAGE_LENGTH = 2000

# Environment variable names for each channel; kept together so docs and code
# never drift.
STATUS_CHANNEL_ENV = "BOT_STATUS_CHANNEL_ID"
LOG_CHANNEL_ENV = "BOT_LOG_CHANNEL_ID"
ERROR_CHANNEL_ENV = "BOT_ERROR_CHANNEL_ID"

# The bot instance used to resolve channels, set once at startup.
_bot = None

# Guards against duplicate shutdown markers (close may be called more than
# once, e.g. by the shutdown command and again by the run loop).
_shutdown_reported = False


def configure(bot) -> None:
    """Point reporting at the running bot instance (set once at startup)."""
    global _bot
    _bot = bot


def _channel_id(env_name) -> int | None:
    """Parse a channel ID from the environment, or None when unset/invalid."""
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s channel ID: %r", env_name, raw)
        return None


def _get_channel(env_name):
    """Resolve a configured channel, or None when unset or not found."""
    channel_id = _channel_id(env_name)
    if channel_id is None or _bot is None:
        return None
    channel = _bot.get_channel(channel_id)
    if channel is None:
        logger.warning("Channel %s (%s) not found", env_name, channel_id)
        return None
    return channel


async def _send_message(env_name, content) -> None:
    """Best-effort send a message to a configured channel. Never raises."""
    channel = _get_channel(env_name)
    if channel is None:
        return
    try:
        await channel.send(content)
    except Exception as e:  # noqa: BLE001 - reporting must never raise
        logger.error("Failed to send message to %s channel: %s", env_name, e)


def _format_traceback(exc) -> str:
    """Render an exception (or exc_info tuple) as clipped code-block text."""
    if isinstance(exc, tuple):
        exc_type, exc_value, exc_tb = exc
    else:
        exc_type = type(exc)
        exc_value = exc
        exc_tb = exc.__traceback__
    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip()


async def send_status(message) -> None:
    """Send a status-channel message (startup/shutdown markers)."""
    await _send_message(STATUS_CHANNEL_ENV, message)


async def send_log(message) -> None:
    """Send an operational log message (one per refresh cycle etc.)."""
    await _send_message(LOG_CHANNEL_ENV, message)


async def report_error(title, exc=None) -> None:
    """Report an error to the error channel, traceback in a code block.

    ``exc`` may be an exception instance or a ``sys.exc_info()`` tuple. When
    omitted only the title is sent (used for non-exception failures such as
    permission denials).
    """
    channel = _get_channel(ERROR_CHANNEL_ENV)
    if channel is None:
        return

    content = f"❌ **{title}**"
    if exc is not None:
        body = _format_traceback(exc)
        # Keep the whole message within Discord's content limit.
        budget = MAX_MESSAGE_LENGTH - len(content) - 8
        content += "\n```\n" + truncate(body, budget) + "\n```"

    try:
        await channel.send(content)
    except Exception as e:  # noqa: BLE001 - reporting must never raise
        logger.error("Failed to send error report to error channel: %s", e)


def _start_marker() -> str:
    """Path of the persisted marker that distinguishes first run from restart."""
    return os.path.join(storage_utils.DATA_DIR, ".started")


def is_restart() -> bool:
    """True if the bot has run before (first run reports 'Bot Started')."""
    return os.path.exists(_start_marker())


def mark_started() -> None:
    """Persist a marker so the next launch is reported as a restart."""
    try:
        os.makedirs(storage_utils.DATA_DIR, exist_ok=True)
        with open(_start_marker(), "w", encoding="utf-8") as f:
            f.write("started")
    except OSError as e:
        logger.warning("Could not write start marker: %s", e)


async def send_shutdown_status() -> None:
    """Send the 🔴 shutdown marker once; later calls are no-ops."""
    global _shutdown_reported
    if _shutdown_reported:
        return
    await send_status("🔴 Bot Shutdown")
    _shutdown_reported = True
