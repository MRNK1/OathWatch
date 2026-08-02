"""Election Board UI-helper and rendering tests.

Covers the render-time vote-percentage fallback, proportional progress bars,
and the board layout that consumes them.
"""
import pytest

from oathwatch import election
from oathwatch.world_state import WORLD_STATE, apply_election_data


def test_effective_percent_uses_api_value():
    assert election._effective_percent({"vote_percent": 45.5}, 100) == 45.5


def test_effective_percent_derived_from_votes():
    cand = {"vote_percent": None, "votes": 25}
    assert election._effective_percent(cand, 100) == 25.0


def test_effective_percent_falls_back_when_api_value_garbage():
    cand = {"vote_percent": "nope", "votes": 25}
    assert election._effective_percent(cand, 100) == 25.0


def test_effective_percent_none_without_data():
    assert election._effective_percent(
        {"vote_percent": None, "votes": None}, 100) is None
    assert election._effective_percent({}, 0) is None


def test_progress_bar_full_and_empty():
    assert election._progress_bar(100) == "█" * 10
    assert election._progress_bar(0) == "░" * 10


def test_progress_bar_half():
    assert election._progress_bar(50) == "█" * 5 + "░" * 5


def test_progress_bar_rounds_and_clamps():
    assert election._progress_bar(45.5) == "█" * 5 + "░" * 5
    assert election._progress_bar(5) == "█" + "░" * 9
    assert election._progress_bar(150) == "█" * 10
    assert election._progress_bar(-5) == "░" * 10
    assert election._progress_bar(None) == "░" * 10


@pytest.mark.usefixtures("reset_world_state")
def test_board_renders_computed_bars():
    apply_election_data({
        "success": True,
        "lastUpdated": 1720000000000,
        "current": {
            "year": 505,
            "candidates": [
                {"name": "Diana", "votes": 50, "perks": []},
                {"name": "Cole", "votes": 25, "perks": []},
            ],
        },
    })
    embed = election.build_election_board_embed()
    assert WORLD_STATE["last_updated"] == 1720000000  # ms -> seconds
    # Fields: Status, Leading Candidate, then one per candidate.
    diana = embed.fields[2]
    assert diana.name == "1. Diana"
    assert "66.67%" in diana.value
    assert "█" in diana.value
    assert "50 votes" in diana.value
    # Native timestamps live in the description (Discord does not render
    # them in footers); the footer is static text only.
    assert "<t:1720000000>" in embed.description
    assert "<t:1720003600:R>" in embed.description
    assert embed.footer.text
    assert "<t:" not in embed.footer.text


@pytest.mark.usefixtures("reset_world_state")
def test_board_sorts_by_computed_percent_when_api_omits_it():
    apply_election_data({
        "success": True,
        "lastUpdated": 1720000000000,
        "current": {
            "year": 505,
            "candidates": [
                {"name": "Low", "votes": 10, "perks": []},
                {"name": "High", "votes": 80, "perks": []},
            ],
        },
    })
    embed = election.build_election_board_embed()
    # API order (Low first) is overridden by computed support at render time.
    assert embed.fields[2].name == "1. High"
    assert "**High**" in embed.fields[1].value
    assert embed.fields[1].name == "Leading Candidate"
