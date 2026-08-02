import os

from .storage_utils import DATA_DIR, read_json, write_json_atomic

WORLD_FILE = os.path.join(DATA_DIR, "world_state.json")


def load_world_state():
    """Load persisted world state, or None if it has never been saved."""
    return read_json(WORLD_FILE, None)


def save_world_state(data):
    """Persist world state atomically."""
    write_json_atomic(WORLD_FILE, data)
