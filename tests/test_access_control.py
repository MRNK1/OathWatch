"""Guild access-control tests: storage, rules, and message formatting."""
import json
import os

from oathwatch import access_control

WHITELISTED_GUILD = "111111111111111111"
BLACKLISTED_GUILD = "222222222222222222"
PLAIN_GUILD = "333333333333333333"
OWNER_ID = 753862282949165086


class TestStorage:
    def test_file_auto_created_on_first_load(self, isolated_storage):
        assert not os.path.exists(access_control.ACCESS_FILE)
        data = access_control.load_access_control()
        assert os.path.exists(access_control.ACCESS_FILE)
        assert data == {
            "whitelist_enabled": False,
            "whitelist": [],
            "blacklist": {},
        }

    def test_save_is_atomic_and_round_trips(self, isolated_storage):
        access_control.add_whitelist(WHITELISTED_GUILD)
        reloaded = access_control.load_access_control()
        assert WHITELISTED_GUILD in reloaded["whitelist"]

    def test_independent_from_config(self, isolated_storage):
        # Mutating access control must not create or touch config.json.
        access_control.set_whitelist_enabled(True)
        config_path = os.path.join(str(isolated_storage), "config.json")
        assert not os.path.exists(config_path)

    def test_corrupt_file_falls_back_to_defaults(self, isolated_storage):
        with open(access_control.ACCESS_FILE, "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        data = access_control.load_access_control()
        assert data == {
            "whitelist_enabled": False,
            "whitelist": [],
            "blacklist": {},
        }

    def test_non_dict_document_normalizes(self, isolated_storage):
        with open(access_control.ACCESS_FILE, "w", encoding="utf-8") as f:
            json.dump(["not", "a", "dict"], f)
        data = access_control.load_access_control()
        assert data["whitelist_enabled"] is False
        assert data["whitelist"] == []
        assert data["blacklist"] == {}


class TestRules:
    def test_default_state_allows_every_guild(self, isolated_storage):
        assert access_control.is_guild_allowed(PLAIN_GUILD) is True

    def test_blacklist_always_wins(self, isolated_storage):
        access_control.add_whitelist(BLACKLISTED_GUILD)
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam server", OWNER_ID)
        # Even though whitelisted, the blacklist takes precedence.
        assert access_control.is_guild_allowed(BLACKLISTED_GUILD) is False

    def test_whitelist_mode_restricts_to_whitelist(self, isolated_storage):
        access_control.add_whitelist(WHITELISTED_GUILD)
        access_control.set_whitelist_enabled(True)
        assert access_control.is_guild_allowed(WHITELISTED_GUILD) is True
        assert access_control.is_guild_allowed(PLAIN_GUILD) is False

    def test_whitelist_disabled_allows_all_except_blacklist(self, isolated_storage):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam server", OWNER_ID)
        assert access_control.is_guild_allowed(PLAIN_GUILD) is True
        assert access_control.is_guild_allowed(BLACKLISTED_GUILD) is False

    def test_accepts_int_guild_ids(self, isolated_storage):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam", OWNER_ID)
        assert access_control.is_guild_allowed(int(BLACKLISTED_GUILD)) is False


class TestWhitelistMutations:
    def test_add_is_idempotent(self, isolated_storage):
        access_control.add_whitelist(WHITELISTED_GUILD)
        access_control.add_whitelist(WHITELISTED_GUILD)
        assert access_control.get_status()["whitelist"] == [WHITELISTED_GUILD]

    def test_remove_returns_whether_present(self, isolated_storage):
        assert access_control.remove_whitelist(WHITELISTED_GUILD) is False
        access_control.add_whitelist(WHITELISTED_GUILD)
        assert access_control.remove_whitelist(WHITELISTED_GUILD) is True
        assert access_control.get_status()["whitelist"] == []

    def test_enable_disable_persists(self, isolated_storage):
        access_control.set_whitelist_enabled(True)
        assert access_control.get_status()["whitelist_enabled"] is True
        access_control.set_whitelist_enabled(False)
        assert access_control.get_status()["whitelist_enabled"] is False


class TestBlacklistMutations:
    def test_reason_metadata_persists(self, isolated_storage):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam server", OWNER_ID)
        entry = access_control.get_status()["blacklist"][BLACKLISTED_GUILD]
        assert entry["reason"] == "Spam server"
        assert entry["added_by"] == OWNER_ID
        assert isinstance(entry["added_at"], int)

    def test_reasons_survive_reload(self, isolated_storage):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam server", OWNER_ID)
        access_control.load_access_control()  # force re-read from disk
        assert access_control.blocked_reason(BLACKLISTED_GUILD) == "Spam server"

    def test_remove_returns_whether_present(self, isolated_storage):
        assert access_control.remove_blacklist(BLACKLISTED_GUILD) is False
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam", OWNER_ID)
        assert access_control.remove_blacklist(BLACKLISTED_GUILD) is True
        assert access_control.get_status()["blacklist"] == {}


class TestMigration:
    def test_legacy_int_whitelist_and_bare_blacklist(self, isolated_storage):
        # A previous format stored guild ids as ints and blacklist entries
        # as bare strings; normalization must migrate both safely.
        with open(access_control.ACCESS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "whitelist_enabled": True,
                "whitelist": [int(WHITELISTED_GUILD)],
                "blacklist": {BLACKLISTED_GUILD: "legacy bare entry"},
            }, f)

        data = access_control.load_access_control()
        assert data["whitelist"] == [WHITELISTED_GUILD]
        assert data["blacklist"][BLACKLISTED_GUILD] == {
            "reason": "",
            "added_by": None,
            "added_at": None,
        }
        # Migrated document is written back so the next load is a no-op.
        with open(access_control.ACCESS_FILE, encoding="utf-8") as f:
            assert json.load(f) == data


class TestBlockedMessage:
    def test_message_uses_stored_reason(self, isolated_storage):
        access_control.add_blacklist(BLACKLISTED_GUILD, "Spam server", OWNER_ID)
        message = access_control.blocked_message(BLACKLISTED_GUILD)
        assert "This server is currently disabled." in message
        assert "Reason:" in message
        assert "Spam server" in message
        assert "contact the bot owner" in message

    def test_message_fallback_when_no_reason(self, isolated_storage):
        # Whitelist-mode block: no stored reason, message must stay neutral.
        access_control.set_whitelist_enabled(True)
        message = access_control.blocked_message(PLAIN_GUILD)
        assert "This server is currently disabled." in message
        assert "No reason provided." in message

    def test_blocked_reason_none_when_allowed(self, isolated_storage):
        assert access_control.blocked_reason(PLAIN_GUILD) is None
