"""Election Board rendering.

Renders the current Hypixel election from the normalized world state
into a Discord embed. Formatting helpers (Minecraft code stripping,
field limits, perk rendering) are shared with the Mayor Board via
formatting.py. The board plugs into the setup system and hourly update
loop purely through registration (board_registry).
"""
import discord

from board_registry import register_board
from formatting import REFRESH_NOTICE, perks_text, strip_format_codes, truncate
from world_state import WORLD_STATE

# Discord embeds allow 25 fields; Status + Leading Candidate leave room for
# 23 candidate fields. Real elections have ~5-10 candidates, so this is a
# defensive ceiling against a pathological API payload.
MAX_CANDIDATE_FIELDS = 23


def _format_percent(value) -> str:
    """Format a vote percentage with up to two decimals, or '' when unknown."""
    if value is None:
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{num:.2f}".rstrip("0").rstrip(".")


def _format_votes(value) -> str:
    """Format a vote count with thousands separators, or '' when unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return f"{int(value):,}"


def _candidate_header(candidate, index) -> str:
    """Build a candidate field name, e.g. '1. Aatrox — 25.75% (128,795 votes)'."""
    parts = [strip_format_codes(candidate.get("name", "Unknown"))]
    percent = _format_percent(candidate.get("vote_percent"))
    votes = _format_votes(candidate.get("votes"))
    if percent:
        parts.append(f"{percent}%")
    if votes:
        parts.append(f"({votes} votes)")
    return f"{index}. " + " — ".join(parts)


def build_election_board_embed() -> discord.Embed:
    """Build the Election Board embed from the current world state."""
    election = WORLD_STATE.get("election") or {}
    year = election.get("year")
    candidates = [
        c for c in (election.get("candidates") or []) if isinstance(c, dict)
    ]

    embed = discord.Embed(
        title="🗳️ Election",
        description=f"Current SkyBlock Election\n\n_{REFRESH_NOTICE}_",
        color=discord.Color.orange(),
    )

    if not candidates:
        embed.add_field(
            name="Status",
            value="No election is currently running.",
            inline=False,
        )
    else:
        status_parts = ["Election in progress"]
        if year is not None:
            status_parts.append(f"Year {year}")
        embed.add_field(
            name="Status",
            value=" · ".join(status_parts),
            inline=True,
        )

        leading = candidates[0]
        leading_value = f"**{strip_format_codes(leading.get('name', 'Unknown'))}**"
        percent = _format_percent(leading.get("vote_percent"))
        if percent:
            leading_value += f" — {percent}%"
        embed.add_field(
            name="Leading Candidate",
            value=leading_value,
            inline=True,
        )

        shown = 0
        for index, candidate in enumerate(candidates, start=1):
            if shown >= MAX_CANDIDATE_FIELDS:
                remaining = len(candidates) - shown
                embed.add_field(
                    name=f"… and {remaining} more",
                    value="More candidates are listed on the official election page.",
                    inline=False,
                )
                break
            shown += 1
            embed.add_field(
                name=_candidate_header(candidate, index),
                value=truncate(perks_text(candidate.get("perks"))),
                inline=False,
            )

    embed.set_footer(
        text=f"🕒 Last updated: {WORLD_STATE['last_updated']} · Refresh: every hour"
    )

    return embed


register_board("election", "Election Board", build_election_board_embed)
