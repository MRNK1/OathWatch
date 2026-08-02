"""Storage and config-migration tests (isolated, temp data dir)."""
import os

import pytest

from oathwatch import storage, storage_utils
from oathwatch.storage import (
    load_config,
    normalize_config,
    normalize_guild_config,
    save_config,
)


@pytest.mark.usefixtures("isolated_storage")
class TestAtomicPersistence:
    def test_write_creates_file_and_data_dir(self, isolated_storage):
        save_config({"guilds": {}})
        assert os.path.exists(storage.CONFIG_FILE)

    def test_round_trip(self, isolated_storage):
        data = {"guilds": {
            "1": {"channel_id": 1, "notify_enabled": True,
                  "boards": {"mayor": {"message_id": 7}}},
        }}
        save_config(data)
        assert load_config() == {"guilds": {
            "1": {"channel_id": 1, "notify_enabled": True,
                  "announcement_channel_id": None,
                  "boards": {"mayor": {"message_id": 7}}},
        }}

    def test_no_tmp_files_left_behind(self, isolated_storage):
        save_config({"guilds": {}})
        leftovers = [f for f in os.listdir(isolated_storage)
                     if f.endswith(".tmp")]
        assert leftovers == []

    def test_read_json_returns_default_when_missing(self, isolated_storage):
        missing = os.path.join(isolated_storage, "nope.json")
        assert storage_utils.read_json(missing, "fallback") == "fallback"


class TestConfigMigration:
    def test_legacy_board_message_id_migrates(self):
        cfg = normalize_guild_config("42", {"channel_id": 777,
                                            "board_message_id": 888,
                                            "notify_enabled": False})
        assert cfg == {"channel_id": 777, "notify_enabled": False,
                       "announcement_channel_id": None,
                       "boards": {"mayor": {"message_id": 888}}}

    def test_legacy_migration_via_load(self, isolated_storage):
        storage_utils.write_json_atomic(
            storage.CONFIG_FILE,
            {"guilds": {"42": {"channel_id": 777, "board_message_id": 888}}},
        )
        cfg = load_config()
        assert cfg["guilds"]["42"]["boards"]["mayor"]["message_id"] == 888
        assert "board_message_id" not in cfg["guilds"]["42"]

    def test_preserves_valid_boards(self):
        cfg = normalize_guild_config("42", {"channel_id": 1,
                                            "notify_enabled": True,
                                            "boards": {"election": {"message_id": 9}}})
        assert cfg["boards"] == {"election": {"message_id": 9}}

    def test_tolerates_invalid_entries(self):
        assert normalize_guild_config("42", None) == {
            "channel_id": None, "notify_enabled": True,
            "announcement_channel_id": None, "boards": {}}
        assert normalize_guild_config("42", {"boards": {"bad": None}})["boards"] == {}
        assert normalize_guild_config(
            "42", {"boards": {"bad": {"message_id": None}}})["boards"] == {}

    def test_preserves_announcement_channel(self):
        cfg = normalize_guild_config("42", {"channel_id": 1,
                                            "notify_enabled": True,
                                            "announcement_channel_id": 555})
        assert cfg["announcement_channel_id"] == 555

    def test_backup_created_then_rolled(self, isolated_storage):
        # The first save has nothing to back up; the second save backs up the
        # first config (Part 7: one rolling config.backup.json).
        assert not os.path.exists(storage.BACKUP_FILE)
        save_config({"guilds": {"1": {"channel_id": 1}}})
        assert not os.path.exists(storage.BACKUP_FILE)
        save_config({"guilds": {"1": {"channel_id": 2}}})
        assert os.path.exists(storage.BACKUP_FILE)
        backup = storage_utils.read_json(storage.BACKUP_FILE, None)
        assert backup["guilds"]["1"]["channel_id"] == 1  # the previous state

    def test_preserves_failure_counter(self):
        cfg = normalize_guild_config("42", {
            "channel_id": 1,
            "notify_enabled": True,
            "boards": {"mayor": {"message_id": 7, "failures": 2}},
        })
        assert cfg["boards"] == {"mayor": {"message_id": 7, "failures": 2}}

    def test_failure_counter_survives_save_reload(self, isolated_storage):
        save_config({"guilds": {
            "1": {"channel_id": 1, "notify_enabled": True,
                  "boards": {"mayor": {"message_id": 7, "failures": 2}}},
        }})
        assert load_config()["guilds"]["1"]["boards"]["mayor"] == {
            "message_id": 7, "failures": 2}

    def test_malformed_failure_counter_dropped(self):
        cfg = normalize_guild_config("42", {
            "channel_id": 1,
            "notify_enabled": True,
            "boards": {"mayor": {"message_id": 7, "failures": "oops"}},
        })
        assert cfg["boards"] == {"mayor": {"message_id": 7}}

    def test_normalize_config_tolerates_garbage(self):
        assert normalize_config(None) == {"guilds": {}}
        assert normalize_config({"guilds": [1, 2]}) == {"guilds": {}}
