"""Consecutive-failure tracking for stale board references.

When a board's update channel is permanently gone (a Discord not-found —
unknown channel / unknown message), every hourly refresh would otherwise fail
and log forever. This module drives the recovery lifecycle:

- a consecutive permanent-failure counter per (guild, board), persisted in
  config.json next to each board entry (the ``failures`` key);
- after ``MAX_CONSECUTIVE_FAILURES`` consecutive permanent failures, the stale
  board reference is removed from config.json (and nothing else);
- any successful update before that threshold resets the counter and emits a
  one-time recovery log.

Transient Discord failures (HTTPException, Forbidden, rate limits, timeouts,
network and Hypixel API failures) never touch the counter and never remove
data — only not-found style errors (the update channel is gone) are permanent.
"""
import time

# A board is declared stale once this many consecutive permanent failures have
# occurred. Self-healing already recovers deleted-message boards, so a counter
# that reaches this threshold means the board can *never* be recovered.
MAX_CONSECUTIVE_FAILURES = 3


def failure_count(board_info) -> int:
    """Consecutive permanent-failure count for a board entry (0 when none)."""
    if isinstance(board_info, dict):
        value = board_info.get("failures")
        if isinstance(value, int) and value > 0:
            return value
    return 0


def record_success(board_info) -> int:
    """Reset a board's counter after a successful update.

    Returns the previous failure count so the caller can log a one-time
    recovery when the board was actually recovering from failures. Safe for
    malformed board entries (non-dicts), which simply report no prior failure.
    """
    previous = failure_count(board_info)
    if isinstance(board_info, dict):
        board_info.pop("failures", None)
    return previous


def record_permanent_failure(boards: dict, board_key: str) -> int:
    """Record one permanent failure for a board; returns its new count.

    When the count reaches ``MAX_CONSECUTIVE_FAILURES`` the board's entry is
    removed from ``boards`` so the caller can persist the cleanup and log the
    final message. Before that, the incremented counter is stored on the
    entry itself. Any board with an existing counter counts as continuing the
    same streak.
    """
    info = boards.get(board_key)
    base = failure_count(info if isinstance(info, dict) else None)
    new_count = base + 1

    if new_count >= MAX_CONSECUTIVE_FAILURES:
        boards.pop(board_key, None)
    elif isinstance(info, dict):
        info["failures"] = new_count
    return new_count


def format_cleanup_message(guild_name, guild_id, board_name, reason, failures) -> str:
    """Build the single final log message for a cleaned-up, irrecoverable board."""
    return "\n\n".join(
        [
            "🧹 Board Cleanup",
            f"Guild:\n{guild_name}",
            f"Guild ID:\n{guild_id}",
            f"Board:\n{board_name}",
            f"Reason:\n{reason}",
            f"Failures:\n{failures} consecutive permanent failures",
            "Action:\nRemoved stale board reference from config.json",
            f"Timestamp:\n<t:{int(time.time())}:F>",
        ]
    )


def format_recovery_message(guild_name, board_name, attempts) -> str:
    """Build the one-time message for a board that recovered before the threshold."""
    return "\n\n".join(
        [
            "✅ Board Recovered",
            f"Guild:\n{guild_name}",
            f"Board:\n{board_name}",
            f"Recovered after:\n{attempts} failed attempts",
            f"Timestamp:\n<t:{int(time.time())}:F>",
        ]
    )
