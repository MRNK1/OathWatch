"""Shared formatting-helper tests."""
from oathwatch.formatting import (
    FIELD_LIMIT,
    REFRESH_NOTICE,
    last_updated_text,
    next_refresh_text,
    perks_text,
    strip_format_codes,
    timestamps_line,
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


def test_last_updated_text_local_timestamp():
    assert last_updated_text(1720000000) == "<t:1720000000>"


def test_last_updated_text_none():
    assert last_updated_text(None) == "Never"


def test_next_refresh_text_relative():
    assert next_refresh_text(1720000000) == "<t:1720003600:R>"


def test_next_refresh_text_none():
    assert next_refresh_text(None) == "within an hour"


def test_timestamps_line_combines_both():
    assert timestamps_line(1720000000) == \
        "🕒 Last updated: <t:1720000000> · ⏭ Next refresh: <t:1720003600:R>"


def test_timestamps_line_unknown():
    assert "Never" in timestamps_line(None)
    assert "within an hour" in timestamps_line(None)
