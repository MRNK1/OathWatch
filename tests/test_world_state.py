"""World-state update, election parsing, and validation tests."""
import pytest

from world_state import (
    WORLD_STATE,
    apply_election_data,
    is_election_data_valid,
    normalize_world_state,
)


def _cand(name, votes, percent, perks=None):
    c = {"name": name, "votes": votes, "vote_percent": percent}
    if perks is not None:
        c["perks"] = perks
    return c


def _payload(candidates=None, mayor=None, year=222, last_updated=1720000000000):
    data = {"success": True, "lastUpdated": last_updated}
    data["election"] = (None if candidates is None
                        else {"year": year, "candidates": candidates})
    if mayor is not None:
        data["mayor"] = mayor
    return data


def _payload_current(candidates=None, mayor=None, year=222,
                     last_updated=1720000000000):
    """Build a payload in the current API layout (active election in 'current')."""
    data = {"success": True, "lastUpdated": last_updated}
    data["current"] = (None if candidates is None
                       else {"year": year, "candidates": candidates})
    if mayor is not None:
        data["mayor"] = mayor
    return data


@pytest.mark.usefixtures("reset_world_state")
class TestApplyElectionData:
    def test_full_payload(self):
        data = _payload(
            candidates=[_cand("Aatrox", 100, 30.0,
                              perks=[{"name": "Slayer XP", "description": "25%"}])],
            mayor={"name": "Aatrox", "perks": [],
                   "minister": {"name": "Barry", "perks": []}},
            year=222,
        )
        assert apply_election_data(data) is True
        assert WORLD_STATE["election"]["year"] == 222
        assert len(WORLD_STATE["election"]["candidates"]) == 1
        assert WORLD_STATE["mayor"]["name"] == "Aatrox"
        assert WORLD_STATE["minister"]["name"] == "Barry"

    def test_candidates_sorted_desc_by_percent(self):
        apply_election_data(_payload(candidates=[
            _cand("Low", 10, 10.0), _cand("High", 200, 55.0),
            _cand("Mid", 100, 30.0), _cand("NoPercent", 5, None),
        ], mayor=None))
        names = [c["name"] for c in WORLD_STATE["election"]["candidates"]]
        assert names == ["High", "Mid", "Low", "NoPercent"]

    def test_malformed_candidates_dropped(self):
        apply_election_data(_payload(candidates=[
            _cand("Good", None, None, perks="notalist"), "junk", None,
        ], mayor=None))
        cands = WORLD_STATE["election"]["candidates"]
        assert len(cands) == 1
        assert cands[0]["votes"] is None and cands[0]["vote_percent"] is None
        assert cands[0]["perks"] == []

    def test_no_election_defaults(self):
        apply_election_data(_payload(candidates=None,
                                     mayor={"name": "Aatrox", "perks": []}))
        assert WORLD_STATE["election"]["candidates"] == []
        assert WORLD_STATE["election"]["year"] is None

    def test_returns_true_only_when_changed(self):
        data = _payload(mayor={"name": "Aatrox", "perks": []}, candidates=None)
        assert apply_election_data(data) is True
        assert apply_election_data(data) is False

    def test_missing_mayor_is_safe(self):
        apply_election_data(_payload(candidates=[_cand("Aatrox", 1, 1.0)],
                                     mayor=None))
        assert WORLD_STATE["mayor"]["name"] == "Unknown"
        assert len(WORLD_STATE["election"]["candidates"]) == 1

    def test_current_field_used_for_active_election(self):
        """Current API layout: the active election lives under 'current'."""
        data = _payload_current(
            candidates=[_cand("Diana", 47490, None)],
            mayor={"name": "Diana", "perks": []},
            year=505,
        )
        assert apply_election_data(data) is True
        election = WORLD_STATE["election"]
        assert election["year"] == 505
        assert [c["name"] for c in election["candidates"]] == ["Diana"]

    def test_legacy_election_field_still_supported(self):
        """Older response formats keep working via the 'election' field."""
        apply_election_data(_payload(
            candidates=[_cand("Aatrox", 100, 30.0)], year=222, mayor=None))
        assert WORLD_STATE["election"]["year"] == 222
        assert len(WORLD_STATE["election"]["candidates"]) == 1

    def test_current_takes_precedence_over_legacy_election(self):
        """If both fields exist, 'current' (active) wins over 'election'."""
        data = _payload(candidates=[_cand("Legacy", 10, 10.0)], year=100,
                        mayor=None)
        data["current"] = {"year": 505,
                           "candidates": [_cand("Active", 50, 50.0)]}
        apply_election_data(data)
        election = WORLD_STATE["election"]
        assert election["year"] == 505
        assert [c["name"] for c in election["candidates"]] == ["Active"]

    def test_mayor_election_is_previous_not_active(self):
        """mayor['election'] is the previous election and must be ignored."""
        data = {
            "success": True,
            "lastUpdated": 1720000000000,
            "mayor": {
                "name": "Aatrox",
                "perks": [],
                "election": {"year": 221,
                             "candidates": [_cand("Prev", 1, 1.0)]},
            },
        }
        apply_election_data(data)
        assert WORLD_STATE["election"] == {"year": None, "candidates": []}


class TestValidation:
    def test_accepts_mayor_election_and_both(self):
        assert is_election_data_valid(_payload(
            mayor={"name": "X", "perks": []}, candidates=None))
        assert is_election_data_valid(_payload(
            candidates=[_cand("X", 1, 1.0)], mayor=None))

    def test_accepts_current_layout(self):
        assert is_election_data_valid(_payload_current(
            candidates=[_cand("X", 1, 1.0)], mayor=None))

    def test_rejects_garbage(self):
        for bad in [None, {}, [], "garbage", {"mayor": "string"},
                    {"election": {"candidates": "nope"}},
                    {"current": {"year": 1, "candidates": "nope"}}]:
            assert is_election_data_valid(bad) is False


@pytest.mark.usefixtures("reset_world_state")
class TestNormalize:
    def test_legacy_flat_world_state(self):
        norm = normalize_world_state({
            "mayor": "Scorpius",
            "perks": [{"name": "P", "description": "D"}],
            "minister": "Barry",
        })
        assert norm["mayor"]["name"] == "Scorpius"
        assert norm["minister"]["name"] == "Barry"
        assert norm["election"] == {"year": None, "candidates": []}

    def test_defaults_last_announced_to_persisted_mayor(self):
        norm = normalize_world_state({"mayor": {"name": "Scorpius", "perks": []}})
        assert norm["last_announced"] == "Scorpius"

    def test_round_trip_preserves_election(self):
        apply_election_data(_payload(candidates=[_cand("Aatrox", 5, 5.0)],
                                     year=222, mayor=None))
        norm = normalize_world_state(WORLD_STATE)
        assert norm["election"]["year"] == 222
        assert norm["election"]["candidates"][0]["name"] == "Aatrox"
