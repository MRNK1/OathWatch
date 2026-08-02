# OathWatch Roadmap

Phased plan derived from PROJECT_SPEC.md. Status is tracked here as each phase completes.
Phase 1 ✅ Production Stability
Phase 2 ✅ Mayor Board
Phase 3 ✅ Setup System
Phase 4 ✅ Election Board
Phase 5 ✅ Release Infrastructure (docs, startup, lifecycle, tooling, tests, CI)
Phase 6 ✅ Guild Access Control (guild whitelist/blacklist; blocked guilds disabled)

Milestone ✅ v1.0.1 — Election Board UI Polish (support bars, computed percentages, native time display)

Milestone ✅ v1.0.2 — Package restructure (all modules moved into the `oathwatch/` package; no behaviour change)

Milestone ✅ v1.1.0 — Owner System & Reporting (owner-only `/owner` commands; status/log/error channels)

Milestone ✅ Stale-board cleanup (deleted-message self-healing preserved; deleted-channel boards auto-clean after 3 consecutive permanent failures)

Milestone ✅ Final production polish (`/owner health`, `stats`, `version`; slow-refresh detection; per-variable startup validation; `config.backup.json`; shared embed footer/colour scheme; `/setchannel` re-added as the announcement channel; `/owner announce` + announcement history with Confirm/Cancel previews)

Milestone ✅ v1.1.1 — Maintenance release (startup notification fix: fresh / reconnect / restart distinguished; documentation + changelog polish)

## Final Production Polish

- **`/owner health`** — subsystem health embed with an overall Green/Yellow/Red level driven by live state (Discord API + latency, background loop, Hypixel/refresh, configuration, world state, reporting channels, access control, last/next refresh, memory). Ephemeral, owner-guild-scoped.
- **`/owner stats`** — version, uptime, guild totals (total/configured/allowed/blocked), board counts (mayor/election/tracked), refresh metrics (count, average, longest) from the central `runtime.py`.
- **`/owner version`** — version, git commit, Python, discord.py, platform, process start time, uptime.
- **Slow-refresh detection** — a refresh over 10s logs one warning to the log channel (duration, average, guild count, timestamp); all refreshes feed `runtime.record_refresh`.
- **Startup validation** — every env var (required + optional reporting channels) logged with a ✅/⚠ line; non-fatal gaps don't block startup.
- **Config backup** — `config.backup.json` written before each `config.json` save (one rolling atomic backup).
- **Shared embed polish** — `OathWatch v<version>` footer + consistent colour scheme on every embed.
- **Announcement channel** — `/setchannel` now sets `announcement_channel_id` (independent of the `/setup` board channel).
- **Announcements** — `/owner announce` with an interactive Confirm/Cancel preview, per-type embed colours, optional @here/@everyone ping, and an ephemeral delivery summary; failures are reported to the error channel once and never notify users.
- **Announcement history** — `data/announcement_history.json` (auto-created, capped at 20, newest first, sequential `ANN-XXXX`); `/owner announcement history|resend|delete|clear` (clear requires explicit confirmation; corrupt files are quarantined to `*.corrupted.json` and reset, with an error-channel log).
- `runtime.py` (central metrics) and `announcements.py` (broadcast + history + views).
- Tests: 63 new.

## Upcoming Releases

### v1.2 — Quality-of-life improvements
- **`/diagnose`** — a guided troubleshooting command that walks the owner through setup, channels, permissions, API access, and board health in one place.
- **Better setup validation** — clearer, earlier feedback on invalid `/setup` choices and channel types.
- **Improved diagnostics** — richer context in health/error reporting so a problem points at its cause faster.
- **Better status reporting** — more informative status outputs and lifecycle messaging.

### v1.3 — Market update
- **Hypixel Bazaar cache** — a live Bazaar snapshot refreshed on a **30-second** cadence.
- **Bazaar commands** — query prices and moving price points on demand.
- **Market tools** — flip/item tracking helpers on top of the cached data.

### v1.4 — Multi-server architecture
- **Provider system** — a clean seam that lets the bot back onto multiple game servers, not just Hypixel.
- **CraftersMC support** — a second provider implemented on the same interface.
- **Default game selection per Discord server** — each server picks which game it tracks.
- **Unified commands** — one command surface works across all providers.

### v1.5 — Verification system
- **Automatic verification where supported** — linking a player account automatically where the game allows it.
- **Manual verification requests** — a fallback flow for servers/providers without auto-verification.
- **Optional verification** — never forced; unverified users keep existing functionality.

### v1.6 — Experimental OathWatch Guilds
- **Guild creation** and **guild management**.
- **Guild net worth**, **guild statistics**, and **guild leaderboards**.
- **Note:** these are unofficial, **community-managed** guilds until supported by official APIs — clearly labelled as such in-app.

## Future

- **Verified guild migration** — move community guilds to officially verified records once supported APIs become available.
- **Website**.
- **Historical market data**.
- **Support additional SkyBlock servers**.

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

- One-step `/setup` replaces the `/setchannel` + `/board` flow; boards are auto-created. `/setchannel` was removed as the update-channel setter, then re-added later as the announcement-channel setter (see the Final Production Polish section).
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

### Phase 6 — Guild Access Control

- `access_control.py` — isolated whitelist/blacklist logic; `is_guild_allowed` is the single source of truth for commands, boards, refresh, and notifications. Rules: blacklist always wins, whitelist mode restricts to whitelisted guilds, otherwise every guild is allowed.
- Independent persistence in `data/access_control.json`: auto-created on first use, atomic writes, corrupt-file fallback to defaults, and automatic migration when the schema changes (legacy int ids and bare string blacklist entries migrate silently).
- `/owner whitelist` (enable / disable / status / add / remove / list) and `/owner blacklist` (add with required reason / remove / list) command groups — guild-scoped, owner-only, every reply ephemeral. Blacklist entries store Guild ID, Reason, Added By, and Added Timestamp (rendered as a Discord timestamp in `/owner blacklist list`).
- Command gate via a custom `CommandTree.interaction_check` (no per-command edits): blocked guilds get the ephemeral disabled message and every slash command is dropped — including future commands.
- Blocked guilds are disabled, never left: board creation/updates/recreation, self-healing, notifications, scheduled refreshes, and setup all skip blocked guilds, and no stored data is modified. The owner guild is exempt from the command gate so the control panel can never be locked out.
- Change logging to the log channel: whitelist enabled/disabled, guild added/removed from whitelist, guild added/removed from blacklist (with guild name, guild id, reason, owner, and timestamp).
- Tests: 40 new covering storage/migration, rule precedence, owner whitelist/blacklist commands, the command gate, and blocked-guild feature skips.

### Phase 5 — Release Infrastructure

- Repository: `README.md` (overview, features, screenshots placeholders, install/config/env/commands, architecture, structure, roadmap, dev setup, contributing, license, credits), `.env.example`, MIT `LICENSE`.
- Startup: `main()` entry point with `if __name__ == "__main__"` guard; validates every required env var (`DISCORD_TOKEN`, `HYPIXEL_API_KEY`) with clear error messages; startup logging (version, data dir, guild count, world state); `bot.py` is importable without env/run side effects.
- Lifecycle: `on_guild_remove` removes a departed guild's config only — world state is preserved, active guilds are never touched, failures are logged safely.
- Tooling: `pyproject.toml` (Ruff + MyPy + Pytest config), `requirements-dev.txt`, GitHub Actions CI (lint → type check → tests on Python 3.10 & 3.12).
- Tests: permanent `tests/` suite (47 tests) covering storage, config migration, election parsing, board registry, setup system, world-state updates, formatting, startup validation, and guild-removal lifecycle — all isolated from real `data/`.
- Type safety: `WORLD_STATE`/registry annotations, narrowed text-channel types, `raise … from` chaining, fixed Hypixel header typing.

### v1.1.0 — Owner System & Reporting

- Owner-only `/owner` command group (`botstatus`, `refresh`, `shutdown`), registered ONLY inside the owner guild and never synced globally — it can never appear in a public server.
- Owner permission gate: only the owner user may execute the commands; every other caller gets an ephemeral *"You do not have permission to use this command."* All replies are ephemeral.
- Three optional reporting channels configured via `.env` (`BOT_STATUS_CHANNEL_ID`, `BOT_LOG_CHANNEL_ID`, `BOT_ERROR_CHANNEL_ID`):
  - Status: 🟢 Bot Started / 🔄 Bot Restarted (persisted start marker) / 🔴 Bot Shutdown (sent on any clean close via an `OathWatchBot.close` override).
  - Log: one message per refresh cycle (hourly or manual), setup completed, board recreated (in the refresh summary), configuration changes, version info.
  - Error: unhandled exceptions, command errors, permission failures, Discord HTTP failures, Hypixel API failures, storage failures, board failures — traceback in a code block.
- `reporting.py` (reusable channel reporting), `refresh.py` (shared refresh pipeline used by the loop and `/owner refresh`), `owner.py` (isolated owner functionality).
- Tests: 25 new covering guild-scoping, non-owner denial, owner execution, startup/shutdown/refresh/error logging, and single-message-per-cycle.

### v1.0.1 — Election Board UI Polish

- Discord native timestamps: "Last Updated" (`<t:...>`) renders in each viewer's local timezone; "Next Refresh" (`<t:...:R>`) is relative to the hourly loop.
- Proportional text progress bars (10 cells) for every candidate, with vote percentages derived from vote counts at render time when the API omits them.
- Render-time standings: candidates are re-ranked by computed support so the Leading Candidate field is always accurate.
- `last_updated` in world state now stores unix epoch seconds; legacy UTC-string values migrate automatically via `normalize_world_state`.
