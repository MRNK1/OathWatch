# OathWatch

## Vision
OathWatch is a production-quality Discord bot that tracks Hypixel SkyBlock world state.

## Current Features

- Mayor Board
- Election Board
- Minister Support
- Setup Command
- Hourly Updates
- Mayor Notifications
- Multi-server Support
- Persistent Storage

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

bot.py
Main bot entry point. Offloads blocking API calls off the event loop via asyncio.to_thread.

hypixel_api.py
Handles all API requests. Sync by design; callers run it in a worker thread.

board.py
Mayor Board embed rendering and change-notification formatting. Registers the "mayor" board type.

election.py
Election Board embed rendering: election status, all candidates sorted by vote percentage, vote counts, candidate perks, and the current leading candidate. Registers the "election" board type. Renders from the normalized election data in world_state.py.

formatting.py
Shared embed-formatting helpers used by every board renderer: Minecraft format-code stripping (strip_format_codes), Discord field-limit clipping (truncate), perk-list rendering (perks_text), and the shared refresh notice. Keeps board rendering consistent without duplicating logic.

board_registry.py
Board-type registry. Registering a board (key, name, embed builder) makes it usable by the setup system and the hourly update loop — the core setup logic never changes. Future boards (Bazaar, Event) plug in here.

setup.py
Board-agnostic setup orchestration: permission checks, board placement (create/update/recreate), board refresh with self-healing, and config persistence. One /setup command replaces the old /setchannel + /board flow. The /setup command passes the admin's board choices (mayor/election) as board keys — setup itself never hard-codes which boards exist.

storage_utils.py
Shared JSON persistence helpers: data directory creation and atomic writes.

storage.py
Guild configuration. Automatically migrates legacy config schema (board_message_id -> boards) on load.

world_storage.py
World state persistence.

world_state.py
Runtime cache, election-data application, response validation, and state normalisation. Holds the mayor, minister, and ongoing election (year + candidates sorted by vote percentage); validates API responses and coerces malformed payloads so boards never crash.

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

Upcoming
- GitHub README
- Website
- Bazaar
- Public API
- Dashboard
