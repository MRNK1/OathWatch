"""Shared pytest fixtures.

Every test that touches persistence uses the ``isolated_storage`` fixture,
which redirects all data files to a throwaway temp directory. The real
``data/`` directory is therefore never read or modified by the test suite.
"""
import os

import pytest

import storage
import storage_utils
import world_state
import world_storage

DEFAULT_WORLD_STATE = {
    "mayor": {"name": "Unknown", "perks": []},
    "minister": None,
    "election": {"year": None, "candidates": []},
    "last_updated": "Never",
    "last_announced": "Unknown",
}


@pytest.fixture
def isolated_storage(tmp_path):
    """Redirect all persistence (config + world state) to a temp directory."""
    storage_utils.DATA_DIR = str(tmp_path)
    storage.CONFIG_FILE = os.path.join(str(tmp_path), "config.json")
    world_storage.WORLD_FILE = os.path.join(str(tmp_path), "world_state.json")
    return tmp_path


@pytest.fixture
def reset_world_state():
    """Reset the module-global world-state cache to its defaults."""
    world_state.WORLD_STATE.clear()
    world_state.WORLD_STATE.update(DEFAULT_WORLD_STATE)
    return world_state.WORLD_STATE
