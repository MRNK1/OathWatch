"""Guild access control: whitelist and blacklist logic, fully isolated.

All guild allow/deny decisions flow through this one module so commands,
board updates, refresh cycles, and notifications share a single source of
truth. The bot never leaves a guild; a blocked guild is simply disabled.

Rules (blacklist ALWAYS wins):
1. If a guild is blacklisted it is never allowed.
2. If whitelist mode is enabled, a guild is allowed only when whitelisted.
3. If whitelist mode is disabled, every guild except blacklisted ones is
   allowed.

Persistence lives in ``data/access_control.json``, independent from
``config.json``. The file is auto-created on first use, written atomically
(never corrupted), and normalized on load so a future structure change
migrates silently instead of breaking.
"""
import copy
import logging
import os
import time
from typing import Any

from .storage_utils import DATA_DIR, read_json, write_json_atomic

logger = logging.getLogger(__name__)

ACCESS_FILE = os.path.join(DATA_DIR, "access_control.json")

DEFAULT_ACCESS_CONTROL = {
    "whitelist_enabled": False,
    "whitelist": [],
    "blacklist": {},
}

# The exact wording shown to a user running a command inside a blocked guild.
# Internal implementation details must never leak into this message.
BLOCKED_GUILD_MESSAGE = (
    "This server is currently disabled.\n\n"
    "Reason:\n{reason}\n\n"
    "If you believe this is a mistake, please contact the bot owner."
)


def _coerce_int(value):
    """Coerce a value to an int, returning None when it cannot be parsed."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_access_control(data):
    """Normalize/ migrate a persisted access-control document.

    Guarantees the three schema keys with the correct types, drops malformed
    entries, and coerces every guild id to a string. Any unrecognized keys
    are ignored so newer documents written by a future version still load.
    """
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_ACCESS_CONTROL)

    normalized: dict[str, Any] = {
        "whitelist_enabled": bool(data.get("whitelist_enabled", False)),
        "whitelist": [],
        "blacklist": {},
    }

    whitelist = data.get("whitelist", [])
    if isinstance(whitelist, list):
        for guild_id in whitelist:
            guild_key = str(guild_id)
            if guild_key not in normalized["whitelist"]:
                normalized["whitelist"].append(guild_key)

    blacklist = data.get("blacklist", {})
    if isinstance(blacklist, dict):
        for guild_id, raw_entry in blacklist.items():
            guild_key = str(guild_id)
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            # A bare entry has no reason metadata; keep it as an empty
            # record rather than dropping the block silently.
            normalized["blacklist"][guild_key] = {
                "reason": entry.get("reason") if isinstance(entry.get("reason"), str) else "",
                "added_by": _coerce_int(entry.get("added_by")),
                "added_at": _coerce_int(entry.get("added_at")),
            }

    return normalized


def load_access_control():
    """Load access control, auto-creating or migrating the file if needed."""
    try:
        raw = read_json(ACCESS_FILE, None)
    except (ValueError, OSError):
        # Corrupt or unreadable document: fall back to the safe defaults
        # without overwriting the on-disk file so it can be investigated.
        logger.warning("Access control file is corrupt; using defaults")
        return copy.deepcopy(DEFAULT_ACCESS_CONTROL)

    if raw is None:
        # First ever load: create the file with defaults so the document
        # exists on disk (auto-create requirement).
        data = copy.deepcopy(DEFAULT_ACCESS_CONTROL)
        save_access_control(data)
        return data

    normalized = normalize_access_control(raw)
    if normalized != raw:
        # Structure changed since it was written (e.g. a future migration):
        # persist the normalized shape so the next load is a clean no-op.
        save_access_control(normalized)
    return normalized


def save_access_control(data):
    """Persist access control atomically (crash-safe, never corrupt)."""
    write_json_atomic(ACCESS_FILE, data)


def _update(mutator):
    """Shared load → mutate → save path for every mutation."""
    data = load_access_control()
    result = mutator(data)
    save_access_control(data)
    return result


def is_guild_allowed(guild_id) -> bool:
    """True when a guild may use the bot (see module rules)."""
    key = str(guild_id)
    data = load_access_control()

    # Blacklist always wins.
    if key in data["blacklist"]:
        return False

    if data["whitelist_enabled"]:
        return key in data["whitelist"]

    return True


def blocked_reason(guild_id):
    """Stored blacklist reason for a guild, or None when not blacklisted."""
    key = str(guild_id)
    data = load_access_control()
    entry = data["blacklist"].get(key)
    if not entry:
        return None
    return entry.get("reason") or None


def blocked_message(guild_id) -> str:
    """The exact ephemeral message for a blocked guild's users."""
    reason = blocked_reason(guild_id) or "No reason provided."
    return BLOCKED_GUILD_MESSAGE.format(reason=reason)


def get_status() -> dict:
    """Snapshot for the /owner whitelist status command."""
    data = load_access_control()
    return {
        "whitelist_enabled": data["whitelist_enabled"],
        "whitelist": list(data["whitelist"]),
        "blacklist": copy.deepcopy(data["blacklist"]),
    }


def set_whitelist_enabled(enabled: bool) -> None:
    """Turn whitelist mode on or off."""
    def mutate(data):
        data["whitelist_enabled"] = bool(enabled)
    _update(mutate)


def add_whitelist(guild_id) -> None:
    """Add a guild to the whitelist (idempotent)."""
    def mutate(data):
        key = str(guild_id)
        if key not in data["whitelist"]:
            data["whitelist"].append(key)
    _update(mutate)


def remove_whitelist(guild_id) -> bool:
    """Remove a guild from the whitelist; returns True if it was present."""
    def mutate(data):
        key = str(guild_id)
        if key in data["whitelist"]:
            data["whitelist"].remove(key)
            return True
        return False
    return _update(mutate)


def add_blacklist(guild_id, reason: str, added_by: int) -> None:
    """Add or update a blacklist entry with reason and audit metadata."""
    def mutate(data):
        data["blacklist"][str(guild_id)] = {
            "reason": reason,
            "added_by": _coerce_int(added_by),
            "added_at": _coerce_int(time.time()),
        }
    _update(mutate)


def remove_blacklist(guild_id) -> bool:
    """Remove a blacklist entry; returns True if it was present."""
    def mutate(data):
        key = str(guild_id)
        if key in data["blacklist"]:
            data["blacklist"].pop(key)
            return True
        return False
    return _update(mutate)
