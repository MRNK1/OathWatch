"""Shared JSON persistence helpers for OathWatch.

Centralises the data directory location, its creation, and atomic writes so
a crash mid-write can never leave a truncated config or world state behind.
"""
import json
import os
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def ensure_data_dir():
    """Create the data directory if it does not exist."""
    os.makedirs(DATA_DIR, exist_ok=True)


def read_json(path, default):
    """Load JSON from path, returning default if the file is missing."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json_atomic(path, data):
    """Write data to path atomically, creating the data directory as needed.

    The payload is written to a temp file in the same directory and renamed
    over the target, so readers never observe a partially written file.
    """
    ensure_data_dir()
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
