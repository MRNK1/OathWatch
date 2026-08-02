import logging
import os
import shutil

from .storage_utils import DATA_DIR, read_json, write_json_atomic

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# A rolling backup of the previous config, kept so a bot that crashes while
# someone edits config.json can still recover the last good state. Only the
# most recent backup is retained.
BACKUP_FILE = os.path.join(DATA_DIR, "config.backup.json")


def normalize_guild_config(guild_id, guild_data):
    """Coerce one guild entry into the current config schema.

    Migrates legacy entries (a single board_message_id tracking the Mayor
    Board) into the boards map, preserves each board's permanent-failure
    counter, and tolerates hand-edited or invalid data. Idempotent; returns
    a new dict.
    """
    if not isinstance(guild_data, dict):
        guild_data = {}

    normalized = {
        "channel_id": guild_data.get("channel_id"),
        # The per-guild announcement channel (/setchannel). Kept as-is so a
        # guild that configured announcement delivery survives config loads.
        "announcement_channel_id": guild_data.get("announcement_channel_id"),
        "notify_enabled": bool(guild_data.get("notify_enabled", True)),
        "boards": {},
    }

    boards = guild_data.get("boards")
    if isinstance(boards, dict):
        for key, info in boards.items():
            if not (isinstance(info, dict) and info.get("message_id")):
                continue
            entry = {"message_id": info["message_id"]}
            # Preserve the consecutive permanent-failure counter so stale-board
            # tracking survives config loads; malformed values are dropped.
            failures = info.get("failures")
            if isinstance(failures, int) and failures > 0:
                entry["failures"] = failures
            normalized["boards"][key] = entry
    else:
        # Legacy format: one board_message_id tracked the Mayor Board.
        legacy_id = guild_data.get("board_message_id")
        if legacy_id:
            normalized["boards"]["mayor"] = {"message_id": legacy_id}

    return normalized


def normalize_config(data):
    """Coerce a whole loaded config into the current schema."""
    if not isinstance(data, dict):
        data = {}
    guilds = data.get("guilds")
    if not isinstance(guilds, dict):
        guilds = {}
    return {
        "guilds": {
            str(gid): normalize_guild_config(str(gid), guild_data)
            for gid, guild_data in guilds.items()
        }
    }


def load_config():
    """Load guild configuration, normalised, or empty if not present."""
    return normalize_config(read_json(CONFIG_FILE, {"guilds": {}}))


def save_config(data):
    """Persist guild configuration atomically, keeping one rolling backup.

    Before the new config overwrites the current one, the current file is
    copied to ``config.backup.json`` so an earlier good state always survives
    a bot crash or a bad write. Only the most recent backup is kept. Backup
    failures are logged, never raised, so a read-only data dir cannot crash
    the caller.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            shutil.copy2(CONFIG_FILE, BACKUP_FILE)
        except OSError as e:
            logger.warning("Could not create config backup: %s", e)
    write_json_atomic(CONFIG_FILE, data)
