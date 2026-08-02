"""Runtime metric tests (refresh counters, versions, platform info).

The autouse ``_reset_runtime`` fixture in conftest clears every counter
between tests, so these assert against a known-fresh baseline.
"""
from oathwatch import runtime


class TestRefreshMetrics:
    def test_fresh_defaults(self):
        assert runtime.refresh_count() == 0
        assert runtime.average_refresh() == 0.0
        assert runtime.longest_refresh() == 0.0
        assert runtime.last_refresh_at() is None
        assert runtime.last_refresh_ok() is True
        assert runtime.last_refresh_error() == ""

    def test_record_refresh_updates_metrics(self):
        runtime.record_refresh(5.0, ok=True)
        runtime.record_refresh(15.0, ok=False, error="API request failed")
        assert runtime.refresh_count() == 2
        assert runtime.average_refresh() == 10.0
        assert runtime.longest_refresh() == 15.0
        assert runtime.last_refresh_at() is not None
        assert runtime.last_refresh_ok() is False
        assert runtime.last_refresh_error() == "API request failed"

    def test_average_before_any_refresh_is_zero(self):
        assert runtime.average_refresh() == 0.0

    def test_reset_clears_everything(self):
        runtime.record_refresh(5.0, ok=True)
        runtime.reset()
        assert runtime.refresh_count() == 0
        assert runtime.last_refresh_at() is None
        assert runtime.last_refresh_ok() is True
        assert runtime.last_refresh_error() == ""


class TestUptime:
    def test_uptime_is_positive(self):
        assert runtime.uptime() > 0

    def test_started_at_epoch_is_recent_timestamp(self):
        assert isinstance(runtime.started_at_epoch(), int)
        assert runtime.started_at_epoch() > 1_000_000_000


class TestVersionInfo:
    def test_python_version_is_three_parts(self):
        parts = runtime.python_version().split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_git_commit_short_or_unknown(self):
        commit = runtime.git_commit()
        assert commit == "unknown" or len(commit) in (7, 40)

    def test_discord_py_version_not_unknown(self):
        # The library is installed in this environment.
        assert runtime.discord_py_version() != "unknown"

    def test_platform_info(self):
        assert runtime.platform_info()


class TestMemory:
    def test_memory_is_none_or_positive(self):
        mem = runtime.process_memory_mb()
        assert mem is None or mem > 0
