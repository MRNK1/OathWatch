"""Runtime world-state cache and Hypixel election data handling.

Holds the current SkyBlock world state and provides the logic to apply new
election data to it. Persisted state is normalised so legacy flat files from
earlier versions keep working.
"""
from datetime import datetime, timezone

WORLD_STATE = {
    "mayor": {"name": "Unknown", "perks": []},
    "minister": None,  # {"name": ..., "perks": [...]} or None when absent
    "election": {
        "year": None,  # int (election year) or None when no election is running
        "candidates": [],  # sorted by vote_percent, highest first
    },
    "last_updated": "Never",
    # Last mayor name already announced to guilds, used to prevent duplicate
    # change notifications across restarts.
    "last_announced": "Unknown",
}


def format_timestamp(epoch_ms) -> str:
    """Format an epoch-milliseconds timestamp as UTC, or 'Never' if invalid."""
    if epoch_ms in (None, 0, ""):
        return "Never"
    try:
        ts = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError, TypeError):
        return "Never"
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def _clean_name(value, default="Unknown") -> str:
    """Return value as a non-empty string, or default if missing/blank."""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _coerce_perks(perks) -> list:
    """Coerce raw API perks into a list of {name, description} dicts."""
    if not isinstance(perks, list):
        return []
    result = []
    for perk in perks:
        if not isinstance(perk, dict):
            continue
        result.append({
            "name": _clean_name(perk.get("name")),
            "description": str(perk.get("description", "")),
        })
    return result


def _coerce_int(value):
    """Return value as an int, or None if it is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _coerce_float(value):
    """Return value as a float, or None if it is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _coerce_candidates(candidates) -> list:
    """Normalize a raw candidate list, sorted by vote percent (highest first).

    Tolerates malformed entries (non-dicts are dropped) so a bad API payload
    can never crash a board render.
    """
    if not isinstance(candidates, list):
        return []
    result = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        result.append({
            "name": _clean_name(candidate.get("name")),
            "votes": _coerce_int(candidate.get("votes")),
            "vote_percent": _coerce_float(candidate.get("vote_percent")),
            "perks": _coerce_perks(candidate.get("perks")),
        })
    result.sort(
        key=lambda c: c["vote_percent"] if c["vote_percent"] is not None else -1.0,
        reverse=True,
    )
    return result


def _coerce_election(election) -> dict:
    """Coerce a raw/persisted election entry into {year, candidates}."""
    if not isinstance(election, dict):
        return {"year": None, "candidates": []}
    year = election.get("year")
    return {
        "year": _coerce_int(year),
        "candidates": _coerce_candidates(election.get("candidates")),
    }


def is_election_data_valid(data) -> bool:
    """True if data looks like a usable Hypixel election response.

    Accepts a response with a current mayor, an ongoing election (with
    candidates), or both. The mayor may be absent while an election decides
    the next one.
    """
    if not isinstance(data, dict):
        return False
    election = data.get("election")
    has_election = (
        isinstance(election, dict)
        and isinstance(election.get("candidates"), list)
    )
    return isinstance(data.get("mayor"), dict) or has_election


def apply_election_data(data: dict) -> bool:
    """Update WORLD_STATE from Hypixel election data.

    Callers must validate data with is_election_data_valid first.
    Returns True if any displayed world state changed (mayor, minister, or
    election candidates), so the hourly loop knows to refresh the boards.
    """
    changed = False

    mayor = data.get("mayor")
    if isinstance(mayor, dict):
        old_mayor = WORLD_STATE["mayor"]["name"]
        WORLD_STATE["mayor"] = {
            "name": _clean_name(mayor.get("name")),
            "perks": _coerce_perks(mayor.get("perks")),
        }

        minister = mayor.get("minister")
        if isinstance(minister, dict):
            WORLD_STATE["minister"] = {
                "name": _clean_name(minister.get("name")),
                "perks": _coerce_perks(minister.get("perks")),
            }
        else:
            WORLD_STATE["minister"] = None

        changed = WORLD_STATE["mayor"]["name"] != old_mayor

    election = data.get("election")
    new_election = _coerce_election(election)
    if new_election != WORLD_STATE["election"]:
        changed = True
    WORLD_STATE["election"] = new_election

    WORLD_STATE["last_updated"] = format_timestamp(data.get("lastUpdated"))

    return changed


def normalize_world_state(state) -> dict:
    """Coerce any persisted/legacy world state into the current shape."""
    state = state or {}

    mayor = state.get("mayor")
    if isinstance(mayor, dict):
        mayor_entry = {
            "name": _clean_name(mayor.get("name")),
            "perks": _coerce_perks(mayor.get("perks")),
        }
    elif isinstance(mayor, str):
        # Legacy flat format: the mayor was a plain name, perks were top-level.
        mayor_entry = {
            "name": _clean_name(mayor),
            "perks": _coerce_perks(state.get("perks")),
        }
    else:
        mayor_entry = {"name": "Unknown", "perks": []}

    minister = state.get("minister")
    if isinstance(minister, dict):
        minister_entry = {
            "name": _clean_name(minister.get("name")),
            "perks": _coerce_perks(minister.get("perks")),
        }
    elif isinstance(minister, str) and minister and minister != "Unknown":
        # Legacy flat format: the minister was a plain name.
        minister_entry = {"name": _clean_name(minister), "perks": []}
    else:
        minister_entry = None

    last_announced = state.get("last_announced")
    if not isinstance(last_announced, str) or not last_announced:
        # Default to the persisted mayor so an upgrade does not re-announce it.
        last_announced = mayor_entry["name"]

    return {
        "mayor": mayor_entry,
        "minister": minister_entry,
        "election": _coerce_election(state.get("election")),
        "last_updated": str(state.get("last_updated", "Never")),
        "last_announced": last_announced,
    }
