# OathWatch

## Vision
OathWatch is a production-quality Discord bot that tracks Hypixel SkyBlock world state.

## Current Features

- Mayor Board
- Election Board (support bars, computed percentages)
- Minister Support
- Setup Command
- Hourly Updates
- Local-Time Timestamps (Discord native `<t:...>` display)
- Mayor Notifications
- Multi-server Support
- Persistent Storage
- Stale-board cleanup (deleted-channel boards self-clean after 3 consecutive permanent failures; deleted-message self-healing preserved)
- Owner-only `/owner` Commands (botstatus, refresh, shutdown, health, stats, version, announce, whitelist, blacklist, announcement — guild-scoped, never public)
- Status / Log / Error Reporting Channels (optional, `.env`)
- Guild Access Control (guild whitelist/blacklist; blocked guilds are disabled, never left)
- `/owner` Health / Stats / Version (Green/Yellow/Red subsystem health, runtime + board metrics, environment details)
- Announcements (`/owner announce` with Confirm/Cancel preview + delivery summary; `/owner announcement history|resend|delete|clear`)
- Announcement Channel (`/setchannel` sets `announcement_channel_id`)
- Slow-refresh detection (>10s warnings to the log channel)
- Per-variable startup validation (✅/⚠ per env var; optional gaps non-fatal)
- Configuration backup (`config.backup.json` rolling atomic backup before each write)

## Planned Features

High Priority
- (none — Election Board shipped in Phase 4)

Medium Priority
- Bazaar Board
- Event Tracking

Low Priority
- Public API
- Dashboard

# Architecture

All application code lives in the `oathwatch/` package; the top-level `bot.py` is a thin launcher that preserves the `python bot.py` entry point (`python -m oathwatch` works too).

bot.py (top-level launcher)
Thin launcher delegating to `oathwatch.bot.main`. Exists only to keep the documented `python bot.py` entry point working.

oathwatch/bot.py
Main bot entry point. `main()` configures logging, validates the environment, loads persisted state, and runs the bot under an `if __name__ == "__main__"` guard. Owns slash commands, the hourly update loop, and lifecycle cleanup (`on_guild_remove`). Offloads blocking API calls off the event loop via asyncio.to_thread. A custom `CommandTree.interaction_check` disables every command inside blocked guilds (ephemeral disabled message; owner guild always reachable).

oathwatch/hypixel_api.py
Handles all API requests. Sync by design; callers run it in a worker thread.

oathwatch/board.py
Mayor Board embed rendering and change-notification formatting. Registers the "mayor" board type.

oathwatch/election.py
Election Board embed rendering: election status, all candidates ranked by support with proportional text progress bars, vote percentages, vote counts, candidate perks, and the current leading candidate. Computes vote percentages from vote counts at render time when the API omits them. Registers the "election" board type. Renders from the normalized election data in world_state.py.

oathwatch/formatting.py
Shared embed-formatting helpers used by every board renderer: Minecraft format-code stripping (strip_format_codes), Discord field-limit clipping (truncate), perk-list rendering (perks_text), the shared refresh notice, and Discord native timestamps for "Last updated" (last_updated_text, shown in each viewer's local time) and "Next refresh" (next_refresh_text, relative). Keeps board rendering consistent without duplicating logic.

oathwatch/board_registry.py
Board-type registry. Registering a board (key, name, embed builder) makes it usable by the setup system and the hourly update loop — the core setup logic never changes. Future boards (Bazaar, Event) plug in here. Boards are registered when the package is imported (oathwatch/__init__.py).

oathwatch/board_health.py
Stale-board health: consecutive permanent-failure tracking per (guild, board) and cleanup/recovery log formatters. Only not-found errors (the update channel is gone) increment the counter; transient failures (HTTPException, Forbidden, timeouts, network/Hypixel API failures) never touch it. After MAX_CONSECUTIVE_FAILURES the stale reference is removed from config.json with one final log; any successful update before that resets the counter with a one-time recovery message.

oathwatch/setup.py
Board-agnostic setup orchestration: permission checks, board placement (create/update/recreate), board refresh with self-healing, and config persistence. One /setup command replaces the old /setchannel + /board flow. The /setup command passes the admin's board choices (mayor/election) as board keys — setup itself never hard-codes which boards exist.

oathwatch/storage_utils.py
Shared JSON persistence helpers: data directory creation and atomic writes. Computes the data directory relative to the project root, so `data/` stays at the repository root.

oathwatch/storage.py
Guild configuration. Automatically migrates legacy config schema (board_message_id -> boards) on load.

oathwatch/access_control.py
Guild access control: whitelist/blacklist rules, fully isolated. `is_guild_allowed` is the single source of truth used by commands, board updates, refresh cycles, and notifications (blacklist always wins; whitelist mode restricts to whitelisted guilds; otherwise every guild is allowed). Persisted independently in `data/access_control.json` — auto-created on first use, atomic writes, corrupt-file fallback, and automatic migration when the structure changes. The bot never leaves a blocked guild; it simply behaves as disabled.

oathwatch/world_storage.py
World state persistence.

oathwatch/owner.py
Owner-only administration. The /owner command group (botstatus, refresh, shutdown, health, stats, version, announce, whitelist, blacklist, announcement) is guild-scoped to the owner guild only (never global, never in public servers), only the owner user may execute it (ephemeral denial for everyone else), and every reply is ephemeral. Health/stats/version embeds draw from runtime.py; announce/announcement delegate to announcements.py; whitelist/blacklist state lives in access_control.py. Reuses reporting.py and refresh.py.

oathwatch/runtime.py
Central runtime metrics shared by health/stats/version and slow-refresh detection: process start time and uptime, refresh counter/average/longest (recorded via record_refresh), last-refresh result/error/timestamp, and version info (git commit, Python, discord.py, platform) plus process memory.

oathwatch/announcements.py
Announcement broadcasting and history. send_announcement delivers a composed embed to every configured announcement channel and returns an AnnouncementResult (checked/delivered/skipped/failed); announcement_embed applies per-type colours. History persists to data/announcement_history.json (auto-created, capped at 20, newest first, sequential ANN-XXXX ids; corrupt files are quarantined to *.corrupted.json and reset). AnnouncementPreviewView and HistoryClearView provide the interactive Confirm/Cancel flows.

oathwatch/reporting.py
Reusable status/log/error channel reporting. Reads BOT_STATUS_CHANNEL_ID / BOT_LOG_CHANNEL_ID / BOT_ERROR_CHANNEL_ID from .env (all optional); degrades to console logging and never raises. Owns the 🟢/🔄 start marker and the once-only 🔴 shutdown guard.

oathwatch/refresh.py
Shared refresh pipeline (fetch → validate → apply → persist → refresh boards → announce mayor change) used by both the hourly loop and /owner refresh, so the two never drift apart. Returns a RefreshResult whose one-line summary becomes exactly one log-channel message per cycle. Board refreshes and change notifications skip blocked guilds.

oathwatch/world_state.py
Runtime cache, election-data application, response validation, and state normalisation. Holds the mayor, minister, and ongoing election (year + candidates sorted by vote percentage); validates API responses and coerces malformed payloads so boards never crash.

# Tooling

- pyproject.toml — Ruff (lint), MyPy (type check), and Pytest (test) configuration.
- tests/ — automated suite covering storage, config migration, access control, election parsing, the board registry, the setup system, world-state updates, formatting, startup validation, owner commands (incl. health/stats/version, announcements, announcement history), slow-refresh detection, and lifecycle cleanup. All tests redirect persistence to a temp directory and never touch real project data.
- .github/workflows/ci.yml — runs lint, type check, and tests on every push/PR.
- requirements-dev.txt — development dependencies (pytest, ruff, mypy).

# Coding Standards

- Modular code
- Type hints
- No duplicated logic
- Keep commands small
- Never break existing features
- Always explain architecture changes

Current Phase

Completed
1. Polish Mayor Board
2. Setup System
3. Election Board
4. Release Infrastructure (README, .env.example, LICENSE, startup/lifecycle hardening, tooling, tests, CI)
5. Owner System & Reporting (owner-only /owner commands; status/log/error channels)
6. Guild Access Control (guild whitelist/blacklist; blocked guilds are disabled, never left)
7. Final Production Polish (/owner health|stats|version, announcements + history, slow-refresh detection, per-variable env validation, config backup, shared embed polish, /setchannel as announcement channel)

Upcoming
- Website
- Bazaar
- Public API
- Dashboard
