# OathWatch

## Vision
OathWatch is a production-quality Discord bot that tracks Hypixel SkyBlock world state.

## Current Features

- Mayor Board
- Minister Support
- Setup Command
- Hourly Updates
- Mayor Notifications
- Multi-server Support
- Persistent Storage

## Planned Features

High Priority
- Election Board

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
Mayor Board embed rendering, Minecraft format-code stripping, and change-notification formatting. Registers the "mayor" board type.

board_registry.py
Board-type registry. Registering a board (key, name, embed builder) makes it usable by the setup system and the hourly update loop — the core setup logic never changes. Future boards (Election, Bazaar) plug in here.

setup.py
Board-agnostic setup orchestration: permission checks, board placement (create/update/recreate), board refresh with self-healing, and config persistence. One /setup command replaces the old /setchannel + /board flow.

storage_utils.py
Shared JSON persistence helpers: data directory creation and atomic writes.

storage.py
Guild configuration. Automatically migrates legacy config schema (board_message_id -> boards) on load.

world_storage.py
World state persistence.

world_state.py
Runtime cache, election-data application, response validation, and state normalisation.

# Coding Standards

- Modular code
- Type hints
- No duplicated logic
- Keep commands small
- Never break existing features
- Always explain architecture changes

Current Phase

1. Polish Mayor Board
2. Setup System
3. GitHub README
4. Website
5. Election Board
6. Bazaar
