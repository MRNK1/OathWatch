"""Slow-refresh detection tests for the perform_refresh wrapper.

The wrapper times the pipeline, records the duration via :mod:`runtime`, and
warns to the log channel only when the refresh exceeds the slow threshold.
The threshold is monkeypatched to force each branch deterministically.
"""
import pytest

from oathwatch import refresh, runtime
from oathwatch.refresh import RefreshResult

from .mocks import MockBot


class TestSlowRefreshDetection:
    @pytest.mark.usefixtures("isolated_storage")
    async def test_fast_refresh_records_but_never_warns(self, monkeypatch):
        bot = MockBot()
        logs = []

        async def fake_pipeline(bot):
            return RefreshResult(ok=True, changed=False)

        async def fake_send_log(message):
            logs.append(message)

        monkeypatch.setattr(refresh, "_run_refresh_pipeline", fake_pipeline)
        monkeypatch.setattr(refresh.runtime, "SLOW_REFRESH_THRESHOLD", 1e9)
        monkeypatch.setattr(refresh.reporting, "send_log", fake_send_log)

        await refresh.perform_refresh(bot)

        assert logs == []
        assert runtime.refresh_count() == 1
        assert runtime.last_refresh_ok() is True

    @pytest.mark.usefixtures("isolated_storage")
    async def test_slow_refresh_warns_with_details(self, monkeypatch):
        bot = MockBot()
        logs = []

        async def fake_pipeline(bot):
            return RefreshResult(ok=True, changed=True)

        async def fake_send_log(message):
            logs.append(message)

        monkeypatch.setattr(refresh, "_run_refresh_pipeline", fake_pipeline)
        # A zero threshold makes every refresh "slow" deterministically.
        monkeypatch.setattr(refresh.runtime, "SLOW_REFRESH_THRESHOLD", 0.0)
        monkeypatch.setattr(refresh.reporting, "send_log", fake_send_log)

        await refresh.perform_refresh(bot)

        assert len(logs) == 1
        assert "Slow refresh detected" in logs[0]
        assert "Duration" in logs[0]
        assert "Average" in logs[0]
        assert "Guilds" in logs[0]
        assert "Timestamp" in logs[0]

    @pytest.mark.usefixtures("isolated_storage")
    async def test_failed_refresh_recorded_as_error(self, monkeypatch):
        bot = MockBot()

        async def fake_pipeline(bot):
            return RefreshResult(error="boom")

        async def fake_send_log(message):
            pass

        monkeypatch.setattr(refresh, "_run_refresh_pipeline", fake_pipeline)
        monkeypatch.setattr(refresh.runtime, "SLOW_REFRESH_THRESHOLD", 1e9)
        monkeypatch.setattr(refresh.reporting, "send_log", fake_send_log)

        await refresh.perform_refresh(bot)

        assert runtime.last_refresh_ok() is False
        assert runtime.last_refresh_error() == "boom"
