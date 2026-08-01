import os

from storage_utils import DATA_DIR, read_json, write_json_atomic

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")


def normalize_guild_config(guild_id, guild_data):
    """Coerce one guild entry into the current config schema.

    Migrates legacy entries (a single board_message_id tracking the Mayor
    Board) into the boards map and tolerates hand-edited or invalid data.
    Idempotent; returns a new dict.
    """
    if not isinstance(guild_data, dict):
        guild_data = {}

    normalized = {
        "channel_id": guild_data.get("channel_id"),
        "notify_enabled": bool(guild_data.get("notify_enabled", True)),
        "boards": {},
    }

    boards = guild_data.get("boards")
    if isinstance(boards, dict):
        normalized["boards"] = {
            key: {"message_id": info["message_id"]}
            for key, info in boards.items()
            if isinstance(info, dict) and info.get("message_id")
        }
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
    """Persist guild configuration atomically."""
    write_json_atomic(CONFIG_FILE, data)
