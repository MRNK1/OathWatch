"""Runtime statistics for the bot process.

Centralises process start time, refresh-cycle metrics, git commit info,
memory usage, and platform details so every ``/owner`` command (health,
stats, version) and the slow-refresh detector read from a single source of
truth instead of each tracking its own copy.

The refresh counters are written by :func:`oathwatch.refresh.perform_refresh`
via :func:`record_refresh` and read by the health/stats commands. Nothing here
touches the network or depends on Discord state.
"""
import logging
import os
import platform
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# Wall-clock and monotonic process start times (seconds).
STARTED_AT = time.monotonic()
STARTED_WALL = int(time.time())

# Cumulative refresh metrics, mutated by record_refresh.
_count = 0
_total = 0.0
_longest = 0.0
_last_at = None  # unix epoch seconds, or None before any refresh
_last_ok = True
_last_error = ""

# Project root is used to locate the git repository for the /owner version
# commit hash. Same computation as storage_utils.PROJECT_ROOT.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A refresh is flagged as slow when it exceeds this many seconds.
SLOW_REFRESH_THRESHOLD = 10.0


def record_refresh(duration: float, *, ok: bool, error: str = "") -> None:
    """Record one refresh cycle's duration and outcome.

    ``ok`` reflects whether the refresh produced a ``RefreshResult`` with
    ``ok=True``; ``error`` carries its one-line error string when it did not.
    """
    global _count, _total, _longest, _last_at, _last_ok, _last_error
    _count += 1
    _total += duration
    _longest = max(_longest, duration)
    _last_at = time.time()
    _last_ok = ok
    _last_error = error


def reset() -> None:
    """Reset all counters to their pre-startup defaults (used by tests)."""
    global _count, _total, _longest, _last_at, _last_ok, _last_error
    _count = 0
    _total = 0.0
    _longest = 0.0
    _last_at = None
    _last_ok = True
    _last_error = ""


def refresh_count() -> int:
    """Number of refresh cycles recorded since process start."""
    return _count


def average_refresh() -> float:
    """Average refresh duration in seconds (0.0 before any refresh)."""
    return _total / _count if _count else 0.0


def longest_refresh() -> float:
    """Longest refresh duration in seconds."""
    return _longest


def last_refresh_at() -> float | None:
    """Wall-clock epoch seconds of the most recent refresh, or None."""
    return _last_at


def last_refresh_ok() -> bool:
    """True when the most recent refresh completed successfully."""
    return _last_ok


def last_refresh_error() -> str:
    """One-line error from the most recent failed refresh, or empty."""
    return _last_error


def uptime() -> float:
    """Process uptime in seconds."""
    return time.monotonic() - STARTED_AT


def started_at_epoch() -> int:
    """Wall-clock unix epoch seconds when the process started."""
    return STARTED_WALL


def git_commit() -> str:
    """Best-effort short git commit hash, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=PROJECT_ROOT,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("Could not read git commit: %s", e)
        return "unknown"
    commit = result.stdout.strip()
    return commit or "unknown"


def python_version() -> str:
    """Python interpreter version, e.g. '3.12.4'."""
    return (
        f"{sys.version_info.major}.{sys.version_info.minor}."
        f"{sys.version_info.micro}"
    )


def discord_py_version() -> str:
    """discord.py library version, or 'unknown'."""
    try:
        import discord

        return discord.__version__
    except AttributeError:
        return "unknown"


def platform_info() -> str:
    """Platform identifier, e.g. 'Windows 11'."""
    return f"{platform.system()} {platform.release()}"


def process_memory_mb() -> float | None:
    """Best-effort current process RSS in MB, or None when unavailable.

    Prefers ``resource`` (POSIX) and falls back to ``tracemalloc`` when the
    trace was enabled; without either it reports None (health shows 'N/A').
    Never raises.
    """
    try:
        import resource

        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # type: ignore[attr-defined]
        # ru_maxrss is bytes on macOS and kilobytes on Linux.
        divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
        return raw / divisor
    except (ImportError, AttributeError, OSError):
        pass
    try:
        import tracemalloc

        current, _ = tracemalloc.get_traced_memory()
        if current > 0:
            return current / (1024 * 1024)
    except (RuntimeError, AttributeError):
        pass
    return None