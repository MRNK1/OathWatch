"""Mayor Board rendering and change-notification formatting.

All user-facing display text is produced here so formatting rules (Minecraft
format-code stripping, spacing, timezone labels) live in one place. Shared
embed helpers (strip_format_codes, truncate, perks_text) come from
formatting.py so every board renders consistently.
"""
import discord

from board_registry import register_board
from formatting import REFRESH_NOTICE, perks_text, strip_format_codes, truncate
from world_state import WORLD_STATE


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
        value=truncate(perks_text(mayor.get("perks", []))),
        inline=False,
    )
    if minister:
        embed.add_field(
            name="Minister Perks",
            value=truncate(perks_text(minister.get("perks", []))),
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
