"""Shared formatting-helper tests."""
from formatting import (
    FIELD_LIMIT,
    REFRESH_NOTICE,
    perks_text,
    strip_format_codes,
    truncate,
)


def test_strip_format_codes():
    assert strip_format_codes("§bAatrox§6!") == "Aatrox!"
    assert strip_format_codes("§x§a§b§c§d§e§fHex") == "Hex"


def test_truncate_keeps_short_text():
    assert truncate("short") == "short"


def test_truncate_clips_to_field_limit():
    out = truncate("x" * 3000)
    assert len(out) == FIELD_LIMIT
    assert out.endswith("…")


def test_perks_text_empty():
    assert perks_text([]) == "No perks this term."
    assert perks_text(None) == "No perks this term."


def test_perks_text_strips_codes():
    out = perks_text([{"name": "§eSlayer XP", "description": "more §6XP"}])
    assert out == "**Slayer XP** — more XP"


def test_perks_text_drops_non_dicts():
    out = perks_text([{"name": "A", "description": "d"}, "junk", None])
    assert "**A** — d" in out


def test_refresh_notice_present():
    assert "hour" in REFRESH_NOTICE
