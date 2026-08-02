"""Shared embed-formatting helpers used by every board renderer.

Minecraft format-code stripping, Discord field limits, and perk rendering
are common to all boards (Mayor, Election, future boards). Keeping them in
one module means a new board plugs in by reusing these helpers instead of
duplicating them.
"""
import re

from . import __version__

REFRESH_NOTICE = "Data refreshes every hour and may be delayed by up to one hour."

FIELD_LIMIT = 1024

# The hourly update loop refreshes once an hour; used for the relative
# "Next refresh" timestamp on every board.
REFRESH_SECONDS = 3600

# Static footer text shared by every board. Every embed in the project carries
# the same footer so branding stays consistent. Discord does not render
# <t:...> timestamps in footers, so the dynamic time information lives in
# each board's description instead (see timestamps_line).
FOOTER_TEXT = f"OathWatch v{__version__}"


def last_updated_text(epoch) -> str:
    """Build a Discord timestamp for the last update.

    Discord renders ``<t:...>`` in each viewer's own timezone, so every viewer
    sees the time in their local time without any UTC formatting on our side.
    """
    if epoch is None:
        return "Never"
    return f"<t:{int(epoch)}>"


def next_refresh_text(epoch) -> str:
    """Build a relative Discord timestamp for the next hourly refresh."""
    if epoch is None:
        return "within an hour"
    return f"<t:{int(epoch) + REFRESH_SECONDS}:R>"


def timestamps_line(epoch) -> str:
    """Build the 'Last updated' / 'Next refresh' status line.

    Discord renders native timestamps only in embed descriptions and fields,
    never in footers, so boards put this line in their description.
    """
    return (f"🕒 Last updated: {last_updated_text(epoch)}"
            f" · ⏭ Next refresh: {next_refresh_text(epoch)}")


def strip_format_codes(text) -> str:
    """Remove Minecraft formatting codes (e.g. §6, §x hex) from a string."""
    return re.sub(r"§.", "", str(text)).replace("§", "")


def truncate(text, limit=FIELD_LIMIT) -> str:
    """Clip text so an embed field value stays within Discord's limit."""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def perks_text(perks) -> str:
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
