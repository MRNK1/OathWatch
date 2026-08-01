"""Shared embed-formatting helpers used by every board renderer.

Minecraft format-code stripping, Discord field limits, and perk rendering
are common to all boards (Mayor, Election, future boards). Keeping them in
one module means a new board plugs in by reusing these helpers instead of
duplicating them.
"""
import re

REFRESH_NOTICE = "Data refreshes every hour and may be delayed by up to one hour."

FIELD_LIMIT = 1024


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
