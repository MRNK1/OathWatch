# OathWatch Roadmap

Phased plan derived from PROJECT_SPEC.md. Status is tracked here as each phase completes.
Phase 1 ✅ Production Stability
Phase 2 ✅ Mayor Board
Phase 3 ✅ Setup System
Phase 4 ✅ Election Board
Phase 5 ✅ Release Infrastructure (docs, startup, lifecycle, tooling, tests, CI)

Phase 6
Public API

Phase 7
Website

Phase 8
Bazaar

Phase 9
Release Candidate

Phase 10
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

### Phase 4 — Election System

- Election data parsed into world state: year, all candidates (name, votes, vote percentage, perks), sorted by highest vote percentage.
- Election Board embed: status ("Election in progress · Year N" or "No election is currently running"), leading candidate, one field per candidate with vote counts and perks, §-code stripping, field-limit truncation, footer with Last Updated + refresh interval.
- Plugs into the existing board registry via a single `register_board("election", …)` call — no setup-logic changes.
- `/setup` now takes `mayor_board` / `election_board` options; existing Mayor-only setups are untouched and keep working.
- Validation hardened: accepts election-only responses (mayor absent on election day), coerces malformed candidates (non-dicts dropped, missing votes/percent → "N/A"), never crashes.
- `apply_election_data` now reports *any* world-state change so boards refresh when votes move, not just on mayor changes.
- Shared render helpers (`strip_format_codes`, `truncate`, `perks_text`, refresh notice) extracted into `formatting.py` — both boards render from one source of truth.

### Phase 5 — Release Infrastructure

- Repository: `README.md` (overview, features, screenshots placeholders, install/config/env/commands, architecture, structure, roadmap, dev setup, contributing, license, credits), `.env.example`, MIT `LICENSE`.
- Startup: `main()` entry point with `if __name__ == "__main__"` guard; validates every required env var (`DISCORD_TOKEN`, `HYPIXEL_API_KEY`) with clear error messages; startup logging (version, data dir, guild count, world state); `bot.py` is importable without env/run side effects.
- Lifecycle: `on_guild_remove` removes a departed guild's config only — world state is preserved, active guilds are never touched, failures are logged safely.
- Tooling: `pyproject.toml` (Ruff + MyPy + Pytest config), `requirements-dev.txt`, GitHub Actions CI (lint → type check → tests on Python 3.10 & 3.12).
- Tests: permanent `tests/` suite (47 tests) covering storage, config migration, election parsing, board registry, setup system, world-state updates, formatting, startup validation, and guild-removal lifecycle — all isolated from real `data/`.
- Type safety: `WORLD_STATE`/registry annotations, narrowed text-channel types, `raise … from` chaining, fixed Hypixel header typing.
