"""Unit tests for the stale-board failure counter (oathwatch/board_health.py).

These cover the counter arithmetic and log-message formatting in isolation;
the lifecycle integration (how update_guild_boards drives the counter) lives
in test_setup.py.
"""
from oathwatch.board_health import (
    MAX_CONSECUTIVE_FAILURES,
    failure_count,
    format_cleanup_message,
    format_recovery_message,
    record_permanent_failure,
    record_success,
)


class TestFailureCount:
    def test_defaults_to_zero(self):
        assert failure_count(None) == 0
        assert failure_count({}) == 0
        assert failure_count("not-a-dict") == 0

    def test_reads_persisted_counter(self):
        assert failure_count({"message_id": 1, "failures": 2}) == 2

    def test_ignores_malformed_values(self):
        assert failure_count({"failures": "oops"}) == 0
        assert failure_count({"failures": -3}) == 0
        assert failure_count({"failures": 0}) == 0


class TestRecordSuccess:
    def test_resets_counter_and_reports_previous(self):
        info = {"message_id": 1, "failures": 2}
        assert record_success(info) == 2
        assert info == {"message_id": 1}

    def test_clean_board_returns_zero(self):
        info = {"message_id": 1}
        assert record_success(info) == 0
        assert info == {"message_id": 1}

    def test_non_dict_is_safe(self):
        assert record_success(None) == 0
        assert record_success("junk") == 0


class TestRecordPermanentFailure:
    def test_increments_counter_before_threshold(self):
        boards = {"mayor": {"message_id": 1}}
        assert record_permanent_failure(boards, "mayor") == 1
        assert boards["mayor"] == {"message_id": 1, "failures": 1}

        assert record_permanent_failure(boards, "mayor") == 2
        assert boards["mayor"] == {"message_id": 1, "failures": 2}

    def test_removes_board_at_threshold(self):
        boards = {"mayor": {"message_id": 1, "failures": 2}}
        assert record_permanent_failure(boards, "mayor") == MAX_CONSECUTIVE_FAILURES
        assert "mayor" not in boards

    def test_threshold_removes_only_that_board(self):
        boards = {
            "mayor": {"message_id": 1, "failures": 2},
            "election": {"message_id": 2},
        }
        record_permanent_failure(boards, "mayor")
        assert "mayor" not in boards
        assert boards["election"] == {"message_id": 2}

    def test_malformed_entry_does_not_crash(self):
        boards = {"mayor": "not-a-dict"}
        assert record_permanent_failure(boards, "mayor") == 1
        assert "mayor" in boards


class TestMessageFormats:
    def test_cleanup_message_contains_fields(self):
        msg = format_cleanup_message(
            "Skyblock Hub", "123456789", "Mayor", "Channel deleted", 3
        )
        assert "🧹 Board Cleanup" in msg
        assert "Guild:\nSkyblock Hub" in msg
        assert "Guild ID:\n123456789" in msg
        assert "Board:\nMayor" in msg
        assert "Reason:\nChannel deleted" in msg
        assert "3 consecutive permanent failures" in msg
        assert "Removed stale board reference from config.json" in msg
        assert "<t:" in msg  # Discord native timestamp

    def test_recovery_message_contains_fields(self):
        msg = format_recovery_message("Skyblock Hub", "Election", 2)
        assert "✅ Board Recovered" in msg
        assert "Guild:\nSkyblock Hub" in msg
        assert "Board:\nElection" in msg
        assert "Recovered after:\n2 failed attempts" in msg
        assert "<t:" in msg
