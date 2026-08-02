"""Election Board rendering.

Renders the current Hypixel election from the normalized world state
into a Discord embed. Formatting helpers (Minecraft code stripping,
field limits, perk rendering) are shared with the Mayor Board via
formatting.py. The board plugs into the setup system and hourly update
loop purely through registration (board_registry).
"""
import discord

from .board_registry import register_board
from .formatting import (
    FOOTER_TEXT,
    REFRESH_NOTICE,
    perks_text,
    strip_format_codes,
    timestamps_line,
    truncate,
)
from .world_state import WORLD_STATE

# Discord embeds allow 25 fields; Status + Leading Candidate leave room for
# 23 candidate fields. Real elections have ~5-10 candidates, so this is a
# defensive ceiling against a pathological API payload.
MAX_CANDIDATE_FIELDS = 23

# Text progress bars are 10 cells wide — compact enough to render cleanly on
# mobile while still showing proportional support at a glance.
BAR_WIDTH = 10
BAR_FILL = "█"
BAR_EMPTY = "░"


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


def _effective_percent(candidate, total_votes) -> float | None:
    """Resolve a candidate's display percentage.

    Uses the API-provided ``vote_percent`` when present; otherwise derives one
    from the candidate's vote count against the election's total votes. This is
    a render-time fallback only — the parsed world state is left unchanged.
    Returns None when neither value is available.
    """
    pct = candidate.get("vote_percent")
    if pct is not None:
        try:
            return float(pct)
        except (TypeError, ValueError):
            pass
    votes = candidate.get("votes")
    if (isinstance(votes, (int, float))
            and not isinstance(votes, bool)
            and total_votes):
        return votes / total_votes * 100
    return None


def _support_key(candidate, total_votes) -> float:
    """Sort key: effective percentage, with unknown percentages last."""
    pct = _effective_percent(candidate, total_votes)
    return -1.0 if pct is None else pct


def _progress_bar(percent) -> str:
    """Render a proportional text bar of BAR_WIDTH cells for a percentage."""
    if percent is None:
        return BAR_EMPTY * BAR_WIDTH
    filled = min(BAR_WIDTH, max(0, int(percent / 10 + 0.5)))
    return BAR_FILL * filled + BAR_EMPTY * (BAR_WIDTH - filled)


def _total_votes(candidates) -> int:
    """Sum the known vote counts across candidates."""
    total = 0
    for candidate in candidates:
        votes = candidate.get("votes")
        if isinstance(votes, (int, float)) and not isinstance(votes, bool):
            total += int(votes)
    return total


def _candidate_field(candidate, index, total_votes) -> tuple:
    """Build one candidate's (field_name, field_value) pair.

    The field name is the candidate's place and name; the value leads with the
    proportional bar, percentage, and vote count, then the perks. Putting the
    stats on their own line keeps the layout flat and mobile-friendly.
    """
    name = f"{index}. {strip_format_codes(candidate.get('name', 'Unknown'))}"

    pct = _effective_percent(candidate, total_votes)
    stats = []
    if pct is not None:
        stats.append(f"{_progress_bar(pct)} {_format_percent(pct)}%")
    votes = _format_votes(candidate.get("votes"))
    if votes:
        stats.append(f"{votes} votes")

    value = perks_text(candidate.get("perks"))
    if stats:
        value = " · ".join(stats) + "\n\n" + value
    return name, truncate(value)


def build_election_board_embed() -> discord.Embed:
    """Build the Election Board embed from the current world state."""
    election = WORLD_STATE.get("election") or {}
    year = election.get("year")
    candidates = [
        c for c in (election.get("candidates") or []) if isinstance(c, dict)
    ]

    embed = discord.Embed(
        title="🗳️ Election",
        description=(
            f"Current SkyBlock Election\n\n"
            f"{timestamps_line(WORLD_STATE['last_updated'])}"
            f"\n\n_{REFRESH_NOTICE}_"
        ),
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

        total_votes = _total_votes(candidates)
        # The API may omit vote_percent entirely, so standings and the leading
        # candidate must be derived from the computed percentages rather than
        # the parsed order. When vote_percent is present the order is unchanged.
        candidates = sorted(
            candidates, key=lambda c: _support_key(c, total_votes), reverse=True
        )

        leading = candidates[0]
        leading_lines = [
            f"**{strip_format_codes(leading.get('name', 'Unknown'))}**"
        ]
        leading_stats = []
        leading_pct = _effective_percent(leading, total_votes)
        if leading_pct is not None:
            leading_stats.append(
                f"{_progress_bar(leading_pct)} {_format_percent(leading_pct)}%"
            )
        leading_votes = _format_votes(leading.get("votes"))
        if leading_votes:
            leading_stats.append(f"{leading_votes} votes")
        if leading_stats:
            leading_lines.append(" · ".join(leading_stats))
        embed.add_field(
            name="Leading Candidate",
            value="\n".join(leading_lines),
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
            field_name, field_value = _candidate_field(
                candidate, index, total_votes
            )
            embed.add_field(
                name=field_name,
                value=field_value,
                inline=False,
            )

    embed.set_footer(text=FOOTER_TEXT)

    return embed


register_board("election", "Election Board", build_election_board_embed)
