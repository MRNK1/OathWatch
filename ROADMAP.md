# OathWatch Roadmap

Phased plan derived from PROJECT_SPEC.md. Status is tracked here as each phase completes.
Phase 1 ✅ Production Stability
Phase 2 ✅ Mayor Board
Phase 3 ✅ Setup System

Phase 3.5
Documentation & Release Infrastructure

Phase 4
Election Board

Phase 5
Public API

Phase 6
Website

Phase 7
Bazaar

Phase 8
Release Candidate

Phase 9
v1.0
## Completed Phases

### Phase 1 — Production Stability

- Blocking I/O off the event loop (`asyncio.to_thread`).
- Hourly loop hardened: per-step guards + `@mayor_update_loop.error` restart handler.
- Crash-safe persistence: atomic writes, auto-created data directory, fresh-deploy defaults.
- Duplicated world-state update logic consolidated into `apply_election_data`.
- Global `@bot.tree.error` handler.
- Structured logging throughout the API layer.

### Phase 2 — Mayor System Polish

- Full Minister support (name + perks) with "N/A" when absent.
- Minecraft format-code (§) stripping on all displayed text.
- Reorganized embed layout, truncation guard, refresh notice, UTC-labelled footer.
- Duplicate notification prevention via persisted `last_announced`.
- Graceful handling of deleted boards and missing channels.
- Robust validation of malformed Hypixel responses.
- Legacy world-state migration via `normalize_world_state`.

### Phase 3 — Setup System (redesign)

- One-step `/setup` replaces the `/setchannel` + `/board` flow; boards are auto-created.
- Board-type registry (`board_registry.py`): future boards plug in via registration, no setup rewrites.
- Board-agnostic `setup.py`: create/update/recreate boards in place, self-healing hourly refresh.
- Duplicate-board prevention; deleted board/channel recovery; permission failures surface clearly.
- Automatic config migration (`board_message_id` → `boards`) — no manual steps.
- `/unsetup` removes a server's configuration and boards.
