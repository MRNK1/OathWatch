"""Shared pytest fixtures.

Every test that touches persistence uses the ``isolated_storage`` fixture,
which redirects all data files to a throwaway temp directory. The real
``data/`` directory is therefore never read or modified by the test suite.
"""
import os

import pytest

from oathwatch import (
    access_control,
    announcements,
    reporting,
    runtime,
    storage,
    storage_utils,
    world_state,
    world_storage,
)

DEFAULT_WORLD_STATE = {
    "mayor": {"name": "Unknown", "perks": []},
    "minister": None,
    "election": {"year": None, "candidates": []},
    "last_updated": None,
    "last_announced": "Unknown",
}


@pytest.fixture
def isolated_storage(tmp_path):
    """Redirect all persistence (config + world state + access control) to a temp dir."""
    storage_utils.DATA_DIR = str(tmp_path)
    storage.CONFIG_FILE = os.path.join(str(tmp_path), "config.json")
    storage.BACKUP_FILE = os.path.join(str(tmp_path), "config.backup.json")
    world_storage.WORLD_FILE = os.path.join(str(tmp_path), "world_state.json")
    access_control.ACCESS_FILE = os.path.join(str(tmp_path), "access_control.json")
    announcements.HISTORY_FILE = os.path.join(str(tmp_path), "announcement_history.json")
    announcements.CORRUPTED_FILE = announcements.HISTORY_FILE + ".corrupted.json"
    return tmp_path


@pytest.fixture
def reset_world_state():
    """Reset the module-global world-state cache to its defaults."""
    world_state.WORLD_STATE.clear()
    world_state.WORLD_STATE.update(DEFAULT_WORLD_STATE)
    return world_state.WORLD_STATE


@pytest.fixture(autouse=True)
def _reset_reporting_state():
    """Keep the once-only shutdown guard from leaking between tests."""
    reporting._shutdown_reported = False
    yield


@pytest.fixture(autouse=True)
def _reset_runtime():
    """Keep refresh counters from leaking between tests."""
    runtime.reset()
    yield
