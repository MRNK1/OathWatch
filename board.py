"""Mayor Board rendering and change-notification formatting.

All user-facing display text is produced here so formatting rules (Minecraft
format-code stripping, spacing, timezone labels) live in one place.
"""
import re

import discord

from board_registry import register_board
from world_state import WORLD_STATE

REFRESH_NOTICE = "Data refreshes every hour and may be delayed by up to one hour."

FIELD_LIMIT = 1024


def strip_format_codes(text) -> str:
    """Remove Minecraft formatting codes (e.g. §6, §x hex) from a string."""
    return re.sub(r"§.", "", str(text)).replace("§", "")


def _truncate(text, limit=FIELD_LIMIT) -> str:
    """Clip text so an embed field value stays within Discord's limit."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _perks_text(perks) -> str:
    """Render a perk list into field text with formatting codes stripped."""
    if not perks:
        return "No perks this term."

    lines = []
    for perk in perks:
        if not isinstance(perk, dict):
            continue
        name = strip_format_codes(perk.get("name", "Unknown"))
        description = strip_format_codes(perk.get("description", ""))
        if description:
            lines.append(f"**{name}** — {description}")
        else:
            lines.append(f"**{name}**")

    return "\n\n".join(lines) if lines else "No perks this term."


def build_mayor_board_embed() -> discord.Embed:
    """Build the Mayor Board embed from the current world state."""
    mayor = WORLD_STATE["mayor"]
    minister = WORLD_STATE["minister"]

    embed = discord.Embed(
        title="📜 OathWatch",
        description=f"Current SkyBlock World Status\n\n_{REFRESH_NOTICE}_",
        color=discord.Color.blue(),
    )

    embed.add_field(
        name="Mayor",
        value=strip_format_codes(mayor.get("name", "Unknown")),
        inline=True,
    )
    embed.add_field(
        name="Minister",
        value=strip_format_codes(minister["name"]) if minister else "N/A",
        inline=True,
    )
    embed.add_field(
        name="Mayor Perks",
        value=_truncate(_perks_text(mayor.get("perks", []))),
        inline=False,
    )
    if minister:
        embed.add_field(
            name="Minister Perks",
            value=_truncate(_perks_text(minister.get("perks", []))),
            inline=False,
        )

    embed.set_footer(
        text=f"🕒 Last updated: {WORLD_STATE['last_updated']} · Refresh: every hour"
    )

    return embed


def format_mayor_change_message(old_mayor, new_mayor) -> str:
    """Build the mayor-change notification message."""
    old = strip_format_codes(old_mayor)
    new = strip_format_codes(new_mayor)
    return f"📜 **Mayor Changed!**\n\n**{old}** ➜ **{new}**"


register_board("mayor", "Mayor Board", build_mayor_board_embed)
