# OathWatch — Complete Engineering Handoff

**Author:** Lead engineer handoff
**Date:** 2026-08-02
**Target reader:** A senior developer taking over the project with **no prior context and without reading git history**.
**Version described:** 1.1.1
**Contract:** Every major change from project inception through the current state is documented below. Nothing is omitted or simplified. This document describes the code as it exists today; it is informational and is **not** a commit.

---

## 1. Executive Summary

OathWatch is a **production-grade Python Discord bot** that tracks the **Hypixel SkyBlock world state** and posts live **Mayor** and **Election** boards to Discord servers. It is a single-owner, self-hosted deployment: one Discord application owned by a specific Discord user, tracking one source of truth (the Hypixel SkyBlock election API), and refreshing it hourly.

The project evolved from a single-file prototype into a **20-module, fully-packaged application** (`oathwatch/`) with the following properties:

- **What it does at a glance:** every hour (and on demand) it fetches the Hypixel SkyBlock election resource, normalizes it into an in-memory world-state cache, persists it to disk (`data/world_state.json`), refreshes each guild's posted board messages in place (self-healing if a user deletes a board), and broadcasts a "Mayor Changed" notification exactly once per mayor across all configured guilds.
- **Reliability engineering:** crash-safe atomic JSON writes, automatic legacy-schema migration, a rolling config backup, self-healing board recreation, consecutive-failure stale-board cleanup, an hourly-loop crash handler that restarts the loop, a global command error handler, and a dedicated error-reporting channel — all so a transient failure can never kill the process or the loop, and a gone-due-to-deletion board stops being logged forever.
- **Operations:** a guild-scoped, owner-only `/owner` command group (status/refresh/shutdown/health/stats/version/announce + whitelist/blacklist/announcement-history), three optional reporting channels (status/log/error) that follow strict content contracts, slow-refresh detection (>10 s → one log warning), and per-variable environment validation at startup.
- **Security model:** all allow/deny decisions for guilds funnel through one module (`access_control.py`); blocked guilds are silently **disabled** (never left, no data modified); all owner commands are guild-scoped so they can never sync into a public server; every non-owner caller and every non-owner button click is denied ephemerally.
- **Quality gate:** 241 automated tests (pytest, green), a clean Ruff linter pass, a clean MyPy type-check pass, and a GitHub Actions CI matrix across Python 3.10 and 3.12. The suite is fully isolated from real `data/` (uses temp directories).

**Bottom line (see §19 for the full verdict):** the codebase is coherent, backward-compatible, well-tested, and **production-ready for its documented single-owner scope**. The only surviving caveats are intentional single-owner hardcodes, an external-API coupling, and a deliberately narrow set of boards (Mayor + Election) — none of which blocks deployment.

---

## 2. Project Achievement Timeline

This is the complete history of how OathWatch reached its current form. Each version/phase is described once; the "Every Source File" (§4) and "Technical Decisions" (§15) sections map these changes onto the modules that exist today.

### Phase 1 — Production Stability
- Moved **blocking network I/O off the event loop** (`asyncio.to_thread`) so the bot stays responsive during API calls.
- **Hardened the hourly loop**: per-step exception guards plus a `@mayor_update_loop.error` handler that restarts the loop instead of letting it die silently.
- Introduced **crash-safe persistence**: atomic writes (temp-file + `os.replace`), an auto-created `data/` directory, and safe defaults for a fresh deploy.
- **Consolidated duplicated world-state update logic** into a single `apply_election_data`.
- Added a **global `@bot.tree.error`** command-error handler.
- Added **structured logging** throughout the API layer.

### Phase 2 — Mayor System Polish
- **Full minister support** (name + perks) with "N/A" when absent.
- **Minecraft format-code stripping** (`§`) on all displayed text.
- Reorganized embed layout, a field-limit truncation guard, a refresh notice, and a UTC-labelled footer (later superseded by native `<t:...>` timestamps in v1.0.1).
- **Duplicate-notification prevention** via a persisted `last_announced` value.
- Graceful handling of deleted boards and missing channels.
- Robust validation of malformed Hypixel responses.
- **Legacy persistence migration** via `normalize_world_state`.

### Phase 3 — Setup System (redesign)
- **One-step `/setup`** replaced the old `/setchannel` + `/board` flow; boards are auto-created. The update-board pair of `/setchannel` was removed as a board-channel setter, then **re-added later as the announcement-channel setter** (Phase "Final Polish").
- Introduced the **board-type registry** (`board_registry.py`) — future boards plug in by registration, with no setup-logic changes.
- **Board-agnostic `setup.py`**: create/update/recreate boards in place, self-healing hourly refresh.
- **Duplicate-board prevention** and deleted-board/channel recovery.
- Automatic config migration (`board_message_id` → `boards` map) — no manual steps.
- `/unsetup` removes a server's configuration and boards.

### Phase 4 — Election System
- Election data parsed into world state: year, all candidates (name, votes, vote-percentage, perks), sorted by highest vote percentage.
- **Election Board embed**: status line ("Election in progress · Year N" or "No election is currently running"), a leading-candidate field, and one field per candidate with vote counts/perks, plus `§`-code stripping and truncation.
- Plugs into the board registry with a single `register_board("election", …)`.
- `/setup` gained `mayor_board` / `election_board` toggles; existing Mayor-only setups are untouched.
- **Validation hardened**: accepts election-only responses (mayor absent on election day), coerces malformed candidates, never crashes a render.
- `apply_election_data` now reports *any* world-state change so boards refresh on vote moves, not only mayor changes.
- Shared render helpers extracted into **`formatting.py`** so both boards render from one source of truth.

### Phase 5 — Release Infrastructure
- **Docs**: `README.md`, `.env.example`, MIT `LICENSE`.
- **Startup**: `main()` entry point with `if __name__ == "__main__"` guard; validates every required env var with clear errors; startup logging (version, data dir, guild count, world state); `bot.py` importable with no env/run side effects.
- **Lifecycle**: `on_guild_remove` removes only a departed guild's config; world state is preserved; failures are logged safely.
- **Tooling**: `pyproject.toml` (Ruff/MyPy/Pytest), `requirements-dev.txt`, GitHub Actions CI (Python 3.10 & 3.12).
- **Tests**: permanent suite (initially 47 tests) all isolated from real `data/`.
- **Type safety**: `WORLD_STATE`/registry annotations, narrowed text-channel types, `raise … from` chaining, fixed Hypixel header typing.

### Phase 6 — Guild Access Control
- **`access_control.py`** — isolated guild whitelist/blacklist; `is_guild_allowed` is the single source of truth for commands, boards, refresh, and notifications. Rule order: **blacklist always wins → whitelist mode restricts to whitelisted → otherwise every guild allowed**.
- Independent persistence (`data/access_control.json`): auto-created, atomic, corrupt-file fallback, automatic schema migration.
- **`/owner whitelist`/`/owner blacklist`** command groups — guild-scoped, owner-only, ephemeral. Blacklist entries store reason/added-by/added-at.
- **Command gate** via a custom `CommandTree.interaction_check` (no per-command edits); blocked guilds get an ephemeral disabled message and every command is dropped — future commands included.
- Blocked guilds are **disabled, never left** (boards/refresh/notifications/setup all skip them; no data modified). The owner guild is exempt from the gate.
- Change logging to the log channel (guild name/id, reason, owner, timestamp).

### v1.0.1 — Election Board UI Polish
- **Discord native timestamps**: "Last Updated" (`<t:...>`) renders in each viewer's timezone; "Next Refresh" (`<t:...:R>`) is relative to the hourly loop.
- **Proportional text progress bars** (10 cells) per candidate, with vote percentages derived from vote counts at render time when the API omits them.
- **Render-time standings** — the leading candidate field and ordering reflect computed support.
- `last_updated` in world state became **unix epoch seconds**; legacy UTC-string values migrate via `normalize_world_state`.
- Board footers reduced to static text; the timestamp line moved into each board's description (Discord does not render `<t:...>` in footers).

### v1.0.2 — Package restructure
- Source modules moved into the **`oathwatch/` package**; the top-level `bot.py` is now a thin launcher preserving `python bot.py` (`python -m oathwatch` also works).
- Relative imports; tests import from `oathwatch.*`.
- Board registration moved to `oathwatch/__init__.py` so boards register on package import.
- `storage_utils` computes `data/` relative to the project root regardless of the import path.
- `__version__` moved to `oathwatch/__init__.py`; bumped to 1.0.2. No behaviour change.

### v1.1.0 — Owner System & Reporting
- **Owner-only `/owner` group** — `botstatus`, `refresh`, `shutdown`. Guild-scoped to the owner guild only; never synced globally; only the owner executes it (ephemeral denial for everyone else); every reply ephemeral.
- **Three optional reporting channels** (`.env`): status/log/error with strict content contracts (see §8).
- `reporting.py` (reusable channel reporting), `refresh.py` (shared refresh pipeline used by loop and `/owner refresh`), `owner.py` (isolated owner functionality).
- Startup-vs-restart detection via a persisted marker (🟢 first launch, 🔄 subsequent); 🔴 shutdown sent on any clean close via an `OathWatchBot.close` override.
- Error reporting wired into: unhandled-event handler, global command-error handler, hourly-loop crash handler, and checkmayor/refresh/setup paths.
- Added **Guild Access Control** underneath the same owner group (the Phase 6 feature, landed together).
- 25 new tests.

### Stale-Board Cleanup (post-v1.1.0)
- **Deleted board message, live channel** → recreated on next refresh (existing self-healing, unchanged).
- **Deleted/irrecoverable update channel** → a consecutive **permanent-failure counter** per (guild, board type) persisted in `config.json`. Transient failures (`HTTPException`, `Forbidden`, rate limits, timeouts, network/Hypixel failures) never touch it.
- After **3 consecutive permanent failures** the stale board reference is removed from config with a single final `🧹 Board Cleanup` log — the guild's channel config and notification settings are kept, and the board is never logged again.
- A recovering board resets its counter and logs a one-time `✅ Board Recovered`.
- `board_health.py` isolates the counter + cleanup/recovery formatters; `BoardPermanentError` in `setup.py` distinguishes an irrecoverable board from transient failures.

### Final Production Polish (shipped in v1.1.1)
- **`/owner health`** — embed with an overall Green/Yellow/Red level and per-subsystem status (Discord API/latency, background loop, Hypixel/refresh, configuration, world state, reporting channels, access control, last/next refresh, memory).
- **`/owner stats`** — version, uptime, guild/board/refresh metrics from a central `runtime.py`.
- **`/owner version`** — version, git commit, Python, discord.py, platform, process start/uptime.
- **Slow-refresh detection** — any refresh over 10 s logs one warning (duration, average, guild count, timestamp); all refreshes feed `runtime.record_refresh`.
- **Startup validation** — every env var (required + optional reporting channels) logged with a ✅/⚠ line; non-fatal gaps don't block startup.
- **Configuration backup** — `config.backup.json` written atomically before each `config.json` save (one rolling backup).
- **Shared embed polish** — `OathWatch v<version>` footer + a consistent colour scheme on every embed.
- **Announcement channel** — `/setchannel` repurposed to set `announcement_channel_id`.
- **Announcements** — `/owner announce` with an interactive Confirm/Cancel preview, per-type embed colours, optional `@here`/`@everyone` ping, and an ephemeral delivery summary; failures reported to the error channel once and never sent to users.
- **Announcement history** — `data/announcement_history.json` (auto-created, capped at 20, newest first, sequential `ANN-XXXX` ids); `/owner announcement history|resend|delete|clear` (clear requires explicit confirmation; corrupt files quarantined to `*.corrupted.json` and reset with an error-channel log).
- `runtime.py` (central metrics) and `announcements.py` (broadcast + history + views).
- 63 new tests (health/stats/version gating, announcement delivery/skip/failure, history ids/cap/corruption, preview/clear views, slow-refresh, runtime metrics, env validation).

### v1.1.1 — Maintenance Release
- **Startup notification fix** — `on_ready` re-fires on a gateway reconnect within the same process; the bot previously reported 🔄 *Bot Restarted* whenever the persisted `.started` marker existed, so a routine reconnect looked like a restart. Lifecycle reporting now flows through `reporting.report_startup()`, which classifies and sends one of three status markers, and the start marker is written exactly once (on the first ever run):
  - 🟢 *Bot Started* — fresh start, no marker.
  - 🔄 *Bot Restarted* — a process relaunch with a previous run's marker.
  - 🔁 *Bot Reconnected* — a gateway reconnect within the same process (never re-marks, never reports a restart).
  - The startup/version log line is lifecycle-aware (`📦 … started` / `🔁 … reconnected`).
- **Documentation & versioning** — version bumped to 1.1.1; CHANGELOG/ROADMAP/README/PROJECT_SPEC/HANDOFF synchronized; the post-v1.1.0 "Unreleased" work was promoted into a proper shipped release (the sections above are now part of v1.1.1, not v1.1.0).
- 4 new regression tests covering the fresh/restart/reconnect classification.

---

## 3. Current Architecture

### 3.1 High-level layout

```
OathWatch/                  (repo root, the git repository)
├── bot.py                  Thin launcher → oathwatch.bot.main (python bot.py)
├── oathwatch/              Application package (ALL application code)
├── tests/                  pytest suite (isolated from data/)
├── data/                   Runtime data (auto-created; git-ignored)
├── requirements.txt        Runtime deps
├── requirements-dev.txt    Dev/CI tooling
├── .env.example            Environment template
├── pyproject.toml          Ruff / mypy / pytest config + build metadata
├── .gitignore
├── PROJECT_SPEC.md, README.md, ROADMAP.md, CHANGELOG.md, AI_RULES.md, LICENSE, HANDOFF.md (this file)
└── .github/workflows/ci.yml  lint → mypy → pytest on Python 3.10 & 3.12
```

### 3.2 Layering / dependency graph (key relationships)

- **Entry points** are thinnest: `oathwatch/__main__.py` and top-level `bot.py` both call `oathwatch.bot.main()`.
- **`oathwatch/bot.py`** is the orchestrator: it owns the Discord client, every user-facing slash command, the hourly loop, and lifecycle. It composes:
  - `reporting` (configure + channel sends)
  - `owner.owner_group` (registered onto the tree)
  - `setup.run_setup/run_unsetup/place_board`, `refresh.perform_refresh`
  - `storage` (config), `world_storage` (world state), `hypixel_api` (network via `asyncio.to_thread`)
  - `board.build_mayor_board_embed` (for the `/board` command)
- **`oathwatch/refresh.py`** runs the shared pipeline and pulls in `hypixel_api`, `world_state`, `world_storage`, `setup.update_guild_boards`, `board.format_notification`, `access_control`, `reporting`, `runtime`.
- **`oathwatch/setup.py`** drives boards via `board_registry` + `board_health`; persists through `storage`.
- **`oathwatch/owner.py`** composes `reporting`, `refresh`, `access_control`, `announcements`, `runtime`, `storage`, `world_state`.
- **Renderers** (`board.py`, `election.py`) read the normalized `WORLD_STATE` and emit embeds using `formatting.py`; they self-register in `board_registry`.
- **Storage**, `storage_utils`, `world_storage`, `access_control`, `reporting`, `runtime` are leaf/low-dependency helpers.

### 3.3 Single-source-of-truth modules (extremely important)

| Responsibility | Single authority | Notes |
| --- | --- | --- |
| Does a guild get to use the bot? | `access_control.is_guild_allowed` | Used by the command gate, `update_guild_boards`, notifications, announcement delivery. |
| Embed formatting rules (`§`-stripping, truncation, perks, timestamps, footer) | `formatting.py` | Both board renderers share it; a new board must reuse it. |
| Which board types exist | `board_registry` | `__init__` imports renderers to trigger registration. |
| One refresh pipeline | `refresh.perform_refresh` | Both the hourly loop and `/owner refresh` call it. |
| Runtime metrics | `oathwatch/runtime.py` | Read by health/stats/version and slow-refresh detection. |
| The bot instance for reporting channels | `reporting.configure(bot)` at boot | Reporting is module-global; configured once. |
| The set of required env vars | `bot.REQUIRED_ENV` | Startup validation reads it; never duplicated elsewhere. |

### 3.4 Where things run

- The bot runs as **one long-lived Python process** (`bot.py`). There is no web server, no database, no message broker. All state is either in-memory (the `WORLD_STATE` dict, the `runtime` module globals) or in flat JSON files under `data/`.
- Blocking work (the Hypixel HTTP request, the git subprocess in `runtime.git_commit`) is kicked off the event loop via `asyncio.to_thread` so the Discord websocket stays responsive.

---

## 4. Every Source File

There are **20 application modules** below `oathwatch/`. For each: module purpose, key public functions/classes, prominent constants, who consumes it, external dependencies, and any notable quirks.

### 4.1 `oathwatch/__init__.py`
- **Purpose:** Python package marker and version/registration hub.
- **Public:** `__version__ = "1.1.1"`.
- **Behaviour:** imports `board` and `election` (with `noqa: F401`) so their module-scope `register_board(...)` calls run on package import, no matter how the package is reached (bot, `python -m`, tests).
- **Consumed by:** every module that reports `__version__`.
- **Quirk:** importing `oathwatch` **registers boards** — a side effect. Tests rely on this.

### 4.2 `oathwatch/__main__.py`
- **Purpose:** support `python -m oathwatch`.
- **Public:** a `if __name__ == "__main__"` guard that calls `sys.exit(oathwatch.bot.main())`.
- **Consumed by:** end users running the module form.

### 4.3 Top-level `bot.py` (launcher)
- **Purpose:** keep the documented `python bot.py` entry point working.
- **Public:** `from .bot import main; sys.exit(main())` under the guard.
- **Consumed by:** operators.

### 4.4 `oathwatch/bot.py` — the Discord client + commands + loop
- **Purpose:** the heart of the bot: connects to Discord, owns all user-facing slash commands, the hourly refresh loop, startup validation, and lifecycle cleanup. It is importable without running.
- **Public / important symbols:**
  - `REQUIRED_ENV = ("DISCORD_TOKEN", "HYPIXEL_API_KEY")`
  - `intents = discord.Intents.default()` (module-level, no privileged intents)
  - `class OathWatchBotTree(app_commands.CommandTree)` — overrides `interaction_check` (see §9). Returns `False` (with an ephemeral blocked message, except for autocomplete) in a blocked guild; `True` for owner guild and DMs.
  - `class OathWatchBot(commands.Bot)` — overrides `close()` to call `reporting.send_shutdown_status()` (🔴) before the real close.
  - `bot` (module instance) with `command_prefix="!"`, `intents`, and `tree_cls=OathWatchTree`.
  - `reporting.configure(bot)` and `bot.tree.add_command(owner.owner_group)` run at import.
  - `on_ready()` — logs online, `sync`s global commands, `sync(guild=owner.OWNER_GUILD)` separately for owner commands, sends the lifecycle status marker (🟢 fresh / 🔄 restart / 🔁 reconnect) via `reporting.report_startup()`, logs a lifecycle-aware version line, and starts `mayor_update_loop`.
  - `on_guild_remove(guild)` — removes the departed guild's config only; never touches the global world state.
  - `on_error(event, *_args, **_kwargs)` — reports application-level event exceptions.
  - Commands: `status`, `testchannel`, `setchannel`, `setup`, `unsetup`, `board`, `checkmayor` (see §6).
  - `async def setup(...)`, `unsetup`, `setchannel`, `board`, `checkmayor`.
  - `@tasks.loop(hours=1) async def mayor_update_loop()` + `mayor_update_loop.error` restart handler.
  - `get_missing_env()` / `validate_env()` / `_log_env_validation()` / `_load_saved_state()` / `main()`.
- **Consumers:** every other part.
- **Quirks:** The owner `owner_group` is registered at import time but **synced only to the owner guild**, never globally. The `.env` is loaded in `main()` via `load_dotenv()` — and **also** at the top of `owner.py`, because `owner.py` is imported before `main()` runs and must read `OWNER_USER_ID`/`OWNER_GUILD_ID` at import (missing/invalid values raise a clear `ValueError`).

### 4.5 `oathwatch/hypixel_api.py`
- **Purpose:** all Hypixel HTTP requests.
- **Constants:** `ELECTION_URL = "https://api.hypixel.net/v2/resources/skyblock/election"`, `MAX_RETRIES = 3`, `RETRY_BACKOFF = 2`.
- **Public:** `get_election_data()` — GET the election resource with a 10 s timeout, retrying up to 3 times with exponential backoff on transient failures (429/5xx and network/timeout); raises the last exception otherwise; raises `RuntimeError` after exhausting attempts.
- **Dependencies:** `requests`, `python-dotenv` (`load_dotenv()` at import), and the module-level `API_KEY = os.getenv("HYPIXEL_API_KEY")`.
- **Sync by design**; callers run it in a worker thread via `asyncio.to_thread`.

### 4.6 `oathwatch/board.py` — the **Mayor Board** renderer
- **Purpose:** build the Mayor Board embed and the mayor-change notification text.
- **Public:**
  - `build_mayor_board_embed() -> discord.Embed` — a blue embed titled `📜 OathWatch`, with a description combining `timestamps_line` + the refresh notice, fields: **Mayor** (name), **Sam (name)** (minister name or `N/A`), **Mayor Perks**, and **Minister Perks** when present. Footer = `FOOTER_TEXT`.
  - `format_mayor_change_message(old_mayor, new_mayor) -> str` — `📜 **Mayor Changed!**\n\n**old** ➜ **new**` with `§`-codes stripped.
- **Registers** `"mayor"` → name `"Mayor Board"` builder `build_mayor_board_embed`.
- **Forwards:** `WORLD_STATE` from `world_state`; helpers from `formatting`.
- **Consumers:** the `board` slash command, `refresh` (notification text), and `setup` via the registry.

### 4.7 `oathwatch/election.py` — the **Election Board** renderer
- **Purpose:** render the ongoing election from normalized world state.
- **Constants:** `MAX_CANDIDATE_FIELDS = 23`, `BAR_WIDTH = 10`, `BAR_FILL = "█"`, `BAR_EMPTY = "░"`.
- **Public:** `build_election_board_embed() -> discord.Embed` — title `🗳️ Election`, status field (`Election in progress · Year N` or `No election is currently running`), a `Leading Candidate` field, then one field per candidate (up to 23). Candidates are **re-ranked at render time by computed support** (derived percentage, or computed from vote counts when the API omits it), each field leading with a proportional progress bar, percentage, and vote count, then perks.
- **Private render helpers:** `_format_percent`, `_format_votes`, `_effective_percent`, `_support_key`, `_progress_bar`, `_total_votes`, `_candidate_field`.
- **Registers** `"election"` → `"Election Board"` builder.
- **Consumed:** the `election` board is picked up by the setup system and hourly loop via the registry.

### 4.8 `oathwatch/board_registry.py`
- **Purpose:** the board-type registry.
- **Public:**
  - `class UnknownBoardError(KeyError)` — for an unknown key.
  - `class BoardType` (frozen dataclass) — `key`, `name`, `build_embed: Callable[[], discord.Embed]`.
  - `register_board(key, name, build_embed)` — idempotent; re-registering replaces.
  - `get_board(key) -> BoardType` — raises `UnknownBoardError` on unknown.
  - `all_boards() -> list[BoardType]` — **insertion order** (so the hourly loop / setup iterate in a stable order).
  - `build_board_embed(key) -> discord.Embed`.
- **Consumers:** `setup.py`, `oathwatch/__init__.py` (registration trigger).

### 4.9 `oathwatch/board_health.py`
- **Purpose:** consecutive-failure tracking for stale board references + cleanup/recovery log text.
- **Constant:** `MAX_CONSECUTIVE_FAILURES = 3`.
- **Public:**
  - `failure_count(board_info) -> int` (0 when none / malformed).
  - `record_success(board_info) -> int` — resets the counter, returns the prior count.
  - `record_permanent_failure(boards: dict, board_key: str) -> int` — increments; when it reaches the threshold, pops the board from `boards` (so the caller persists cleanup); otherwise stores the new count on the entry.
  - `format_cleanup_message(guild_name, guild_id, board_name, reason, failures) -> str`.
  - `format_recovery_message(guild_name, board_name, attempts) -> str`.
- **Consumers:** `setup.py` (`update_guild_boards` / `_count_permanent_failure`).
- **Notes:** only *not-found* style errors constitute permanent failure (see `setup.py`); transient errors must never call `record_permanent_failure`.

### 4.10 `oathwatch/setup.py` — setup orchestration
- **Purpose:** one-step server setup/unsetup + the tracked-board refresh cycle. Board-agnostic (iterates registered boards).
- **Constants:** `CHANNEL_DELETED_REASON = "Channel deleted"`.
- **Exceptions:** `class SetupError(Exception)`; `class BoardPermanentError(SetupError)` (irrecoverable board — channel gone).
- **Public functions:**
  - `_missing_permissions(channel) -> list[str]` — checks `send_messages`, `embed_links`, `read_message_history`.
  - `async place_board(channel, embed, stored_id) -> (message_id, new_id_bool)` — edit-in-place if the stored message lives; otherwise recreate (self-heal). `NotFound` → recreate; `BoardPermanentError` when the *channel itself* is gone.
  - `async _delete_orphaned_board(channel, message_id)` — best-effort, never raises.
  - `async run_setup(guild_id, channel, board_keys=None, notify=True) -> str` — for each requested board, computes stored_id (clearing a board tracked in another channel first), places it, persists per-board one at a time (so a partial failure never duplicates). Returns an inline summary.
  - `async run_unsetup(bot, guy_id, guild_name) -> str` — removes config; best-effort deletes board messages.
  - `class BoardsRefreshResult` (dataclass) — `refreshed: int`, `recreated: int`.
  - `async update_guild_boards(bot) -> BoardsRefreshResult` — the per-cycle board refresh: for each configured guild, resolves the update channel, rebuilds each tracked board, self-heals recreated boards, **counts permanent failures for irrecoverable channels**, and reports board errors to the error channel. Returns refreshed/recreated counts for the loop summary.
  - Helpers `_count_permanent_failure`, `_log_board_cleanup`, `_log_board_recovered`, `_guild_name`, `_board_display_name`, `_one_line`.
- **Consumers:** `bot` commands, `refresh._run_refresh_pipeline`, tests.
- **Notes:** `update_board_boards` *never raises* — it logs/reports so the hourly loop survives.

### 4.11 `oathwatch/world_state.py`
- **Purpose:** in-memory world-state cache, election-data application, response validation, normalization.
- **Global:** `WORLD_STATE` dict — keys: `mayor` {name, perks}, `minister` (name + perks or None), `election` {year, candidates}, `last_updated`, `last_announced`.
- **Public functions:**
  - `is_election_data_valid(data) -> bool`.
  - `apply_election_data(data: dict) -> bool` — updates the cache; returns `True` if any displayed state changed.
  - `normalize_world_state(state) -> dict` — coerces persisted/legacy state (including a legacy flat-mayor format and a `last_updated` UTC string) into the current shape.
- **Private coercers:** `_coerce_epoch_seconds`, `_coerce_last_updated`, `_clean_name`, `_coerce_perks`, `_coerce_int`, `_coerce_float`, `_coerce_candidates`, `_coerce_election`, `_get_active_election`.
- **Notes:** `_get_active_election` prefers the current-API `data["current"]` block and falls back to legacy `data["election"]`; the mayor's own unbeneficial `election` field is deliberately ignored (previous election).

### 4.12 `oathwatch/formatting.py` (also referenced in 4.6/4.7) — the shared embed helpers
- **Constants:** `REFRESH_NOTICE`, `FIELD_LIMIT = 1024`, `REFRESH_SECONDS = 3600`, `FOOTER_TEXT = f"OathWatch v{__version__}"`.
- **Public functions:** `last_updated_text(epoch)`, `next_refresh_text(epoch)`, `timestamps_line(epoch)`, `strip_format_codes(text)`, `truncate(text, limit=1024)`, `perks_text(perks)`.
- **Notes:** `strip_format_codes` removes `§*` sequences and any stray `§`. `timestamps_line` is placed in the embed description (not footer) because Discord renders `<t:...>` only in descriptions/fields.

### 4.13 `oathwatch/storage.py`
- **Purpose:** persisted guild configuration with migration.
- **Constants:** `CONFIG_FILE = data/config.json`, `BACKUP_FILE = data/config.backup.json`.
- **Public:**
  - `normalize_guild_config(guild_id, guild_data) -> dict` — migrates legacy `board_message_id` → `boards["mayor"]`; preserves `announcement_channel_id` and the per-board `failures` counter; drops malformed entries.
  - `normalize_config(data) -> dict`.
  - `load_config() -> dict`.
  - `save_config(data)` — backs up the current config to `BACKUP_FILE` (rolling, copy) before an atomic overwrite; backup failures are logged, never raised.
- **Consumers:** almost everything that touches config (bot, setup, owner, refresh, board command).

### 4.14 `oathwatch/storage_utils.py`
- **Purpose:** shared JSON persistence + the data-dir location.
- **Constants:** `PROJECT_ROOT` (parent of the `oathwatch/` package), `DATA_DIR = <project_root>/data`.
- **Public:** `ensure_data_dir()`, `read_json(path, default)` (returns `default` when the file is missing — a *corrupt* JSON raises `ValueError`, which callers catch and handle), `write_json_atomic(path, data)` (temp-file + `os.replace`).
- **Consumers:** every persistence module.

### 4.15 `oathwatch/world_storage.py`
- **Purpose:** world-state persistence.
- **Constants:** `WORLD_FILE = data/world_state.json`.
- **Public:** `load_world_state() -> dict|None`, `save_world_state(data)`.

### 4.16 `oathwatch/access_control.py`
- **Purpose:** isolated guild access control + its own persisted document.
- **Constants:** `ACCESS_FILE = data/access_control.json`; `DEFAULT_ACCESS_CONTROL = {"whitelist_enabled": False, "whitelist": [], "blacklist": {}}`; `BLOCKED_GUILD_MESSAGE`.
- **Public:**
  - `normalize_access_control(data)` (migration: int ids, bare-string blacklist entries),
  - `load_access_control()`, `save_access_control(data)`,
  - `is_guild_allowed(guild_id) -> bool` (blacklist wins → whitelist-mode → allow),
  - `blocked_reason(guild_id)`, `blocked_message(guild_id)`,
  - `get_status() -> dict`,
  - `set_whitelist_enabled(enabled)`,
  - `add_whitelist(id)` / `remove_whitelist(id) -> bool`,
  - `add_blacklist(id, reason, added_by)` / `remove_blacklist(id) -> bool`.
- **Notes:** on a corrupt file it returns safe defaults **without overwriting** the corrupt file on disk. Auto-creates on first use.

### 4.17 `oathwatch/refresh.py`
- **Purpose:** shared refresh pipeline.
- **Data class:** `RefreshResult` — fields `ok, error, changed, mayor_changed, boards_refreshed, boards_recreated`; a `.summary` property producing the one-line log message.
- **Public:**
  - `async send_mayor_change_notification(bot, message)` — to every allowed deployed notify-enabled guild's channel; never raises.
  - `async _run_refresh_pipeline(bot) -> RefreshResult` — fetch (threaded) → validate → apply → persist → refresh boards on a change → announce a mayor change; individual steps log/report and degrade, never raise.
  - `async perform_refresh(bot) -> RefreshResult` — the timed wrapper: times the run, records the duration into `runtime`, and warns on the log channel when exceeding the slow threshold.
- **Consumers:** the hourly loop, and `/owner refresh`.

### 4.18 `oathwatch/reporting.py`
- **Purpose:** status/log/error channel reporting.
- **Constants:** `MAX_MESSAGE_LENGTH = 2000`; channel env-vars `STATUS_CHANNEL_ENV/LOG_CHANNEL_ENV/ERROR_CHANNEL_ENV`; module globals `_bot`, `_shutdown_reported`.
- **Public:**
  - `configure(bot)` (once).
  - `send_status(message)`, `send_log(message)`.
  - `report_error(title, exc=None)` — supports an exception or a `sys.exc_info()` tuple; a code block with the traceback; clipped to fit one message.
  - `is_restart() -> bool`, `mark_started()`, `async report_startup() -> str` (sends the 🟢/🔄/🔁 marker and returns the lifecycle kind: fresh / restart / reconnect), `send_shutdown_status()` (once-guarded).
- **Notes:** every send is best-effort with `_bot is None`/missing channel/send failure handled; never raises. The status/log/error contracts are described fully in §8.

### 4.19 `oathwatch/runtime.py`
- **Purpose:** central runtime metrics for health/stats/version and slow-refresh.
- **Constants:** `STARTED_AT`, `STARTED_WALL`, `PROJECT_ROOT`, `SLOW_REFRESH_THRESHOLD = 10.0`.
- **Module globals:** `_count`, `_total`, `_longest`, `_last_at`, `_last_ok`, `_last_error`.
- **Public functions:** `record_refresh(duration, ok=..., error=...)`, `reset()`, `refresh_count()`, `average_settled()`, `longest_refresh()`, `last_refresh_at()`, `last_refresh_ok()`, `last_refresh_error()`, `uptime()`, `started_at_epoch()`, `git_commit()`, `python_version()`, `discord_py_version()`, `platform_info()`, `process_memory_mb()`.
- **Notes:** `git_commit()` shells out to `git rev-parse --short HEAD` with a 3 s timeout; it runs inline in `/owner version` (a single quick subprocess).

### 4.20 `oathwatch/announcements.py`
- **Purpose:** announcement broadcasting + persistence history + confirm/cancel views.
- **Constants:** `HISTORY_FILE`, `CORRUPTED_FILE`, `HISTORY_LIMIT = 20`, `ANNOUNCEMENT_COLORS`, `PREVIEW_HEADING`.
- **Public:**
  - `class AnnouncementResult` (dataclass) — counts + per-guild sets; `announcement_embed(title, message, type)`.
  - `async send_announcement(bot, *, title, message, announcement_type, ping_mode) -> AnnouncementResult` — to every configured allowed guild's `announcement_channel_id`; skips blocked/missing-channel; failures counted + reported to error channel once; never raises.
  - `_next_id`, `_quarantine_corrupt_history`, `load_history() -> (entries, was_corrupt)` (corrupt file renamed to `*.corrupted.json` and reset), `save_history`, `add_history_entry(...) -> id`, `get_history_entry(id)`, `delete_history_entry(id) -> bool`, `clear_history() -> int`.
  - `format_summary(result, ann_id)`, `format_history_lines(entries)`.
  - `class AnnouncementPreviewView` (Confirm/Cancel, owner re-check on click; Confirm sends + records summary).
  - `class HistoryClearView` (Confirm/Cancel; destructive approved).
- **Consumers:** `owner.py`.

### 4.21 `oathwatch/owner.py` — owner-only commands

#### 4.21.1 Infrastructure
- **Constants:** `OWNER_USER_ID`, `OWNER_GUILD_ID`, and `OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)` are read from the environment at import — `OWNER_USER_ID_ENV`/`OWNER_GUILD_ID_ENV` (`.env`), via `_required_id(env_name, label)`, which raises a clear `ValueError` if a value is missing or not numeric so a misconfigured deployment fails fast. Also `DENIED_MESSAGE` (`"You do not have permission to use this command."`), `ANNOUNCEMENT_EXTRAS`.
- **Groups:** `owner_group` (guild_ids=[OWNER_GUILD_ID]), `whitelist_group`, `blacklist_group`, `announcement_group` — all `parent=owner_group`, so they inherit the owner-guild scope.
- **Security entry points:** `is_owner(interaction)` and `async _deny_non_owner(interaction) -> bool` — rejects anyone who is not the owner **and** not in the owner guild; logs + reports to the error channel, sends the ephemeral `DENIED_MESSAGE`, returns `True`. All owner command functions begin with `if await _deny_non_owner(...): return`.
- `format_uptime(seconds) -> str` (e.g. `5s`, `1m`, `1h`, `2d 3h`).
- `_refresh_loop_running()` — lazily imports `oathwatch.bot.mayor_update_loop` at call time to avoid a circular import at module load.
- `_health_embed`, `_stats_embed`, `_version_embed` — build the health/stats/version embeds (details in §4.20-era-Runtime and §6).

#### 4.21.2 Commands registered
Top-level `/owner` commands:
- `botstatus` → `_botstatus` (ephemeral status summary).
- `refresh` → `_refresh` (manual `perform_refresh`; logs + tells owner).
- `shutdown` → `_shutdown` (replies then `interaction.client.close()`; 🔴 is sent by the inherited `close`).
- `health` → `_health`, `stats` → `_stats`, `version` → `_version`, `announce` → `_announce`.

`/owner whitelist`: `enable`/`disable`/`status`/`add <guild>`/`remove <guild>`/`list`.
`/owner blacklist`: `add <guild> <reason>`/`remove <guild>`/`list`.
`/owner announcement`: `history`/`resend <id>`/`delete <id>`/`clear` (destructive confirm).

All ephemeral; all owner-gated; all guild-scoped to the owner guild.

---

## 5. Data Files

All runtime data lives in `data/` (created automatically; all git-ignored). **Back up `data/`** — it holds config and last-known world state.

### 5.1 `data/config.json`
Guild configuration. Schema:

```json
{
  "guilds": {
    "<discord guild id string>": {
      "channel_id": <int>,                 // the /setup update-board channel
      "announcement_channel_id": <int|null>, // the /setchannel announcement channel
      "notify_enabled": <bool>,
      "boards": {
        "mayor":    { "message_id": <int>, "failures": <int|missing> },
        "election": { "message_id": <int>, "failures": <int|missing> }
      }
    }
  }
}
```
- **Migration:** a legacy `board_message_id` key (which tracked the Mayor Board) auto-migrates to `boards["mayor"]["message_id"]` on load. The transient `failures` counter is preserved; malformed values dropped.
- **Backup:** before each save, the previous file is copied to `config.backup.json` (rolling, one backup).

### 5.2 `config.backup.json`
The immediately-prior `config.json`, kept for manual recovery after a crash/bad edit. Regenerated each save.

### 5.3 `world_state.json`
The normalized, persisted world state (same shape as the `WORLD_STATE` dict):

```json
{
  "mayor":    { "name": "…", "perks": [{"name": "…", "description": "…"}] },
  "minister": null | { "name": "…", "perks": [ … ] },
  "election": { "year": null|int, "candidates": [ {"name": "…", "year":…} ] },
  "last_updated": null|int,   // unix epoch seconds
  "last_announced": "…"
}
```

### 5.4 `access_control.json`
```json
{
  "whitelist_enabled": false,
  "whitelist": ["<guild-id>", "..."],
  "blacklist": {
    "<guild-id>": { "reason": "…", "added_by": <int>, "added_at": <int-unix> }
  }
}
```
- Auto-created on first load; corrupt file → safe defaults (on-disk left in place for investigation); structure changes migrate automatically.

### 5.5 `announcement_history.json`
A list (newest first), capped at 20, each entry:
```json
{
  "id": "ANN-0001",
  "title": "…", "message": "…", "type": "Update",
  "ping_mode": "No Ping",
  "timestamp": <unix>,
  "delivered_servers": [ ... ], "skipped_servers": [ ... ], "failed_servers": [ ... ],
  "owner_id": <int>, "bot_version": "1.1.1"
}
```
On load, if the file is corrupt it is **renamed to `announcement_history.corrupted.json`** and a fresh one starts; the reset is reported to the error channel.

### 5.6 `.started`
A marker file (content `started`) written after the first successful startup; presence distinguishes a first launch (🟢) from a restart (🔄).

### 5.7 Environment / secrets
`app.env` holds real secrets (the discord token + Hypixel key) and is **gitignored and must never be committed or read/printed**. `data/` and `config.backup.json` are likewise gitignored.

---

## 6. Commands

**Legend:** 🔒 = administrator-only (via `app_commands.default_permissions`). The human-facing table in `README.md` mirrors this list. All commands are slash commands.

### 6.1 Global (synced to every guild)

| Command | Synopsis | Args | Access |
| --- | --- | --- | --- |
| `/status` | Checks bot status + latency (`🏰 OathWatch Online · Latency: Nms`). | — | Everyone |
| `/setup` | Configures this server in one step: places the chosen boards, sets the update channel + notify. | `channel: TextChannel` (required), `mayor_board: bool=True`, `election_board: bool=True`, `notify: bool=True` | 🔒 (administrator) |
| `/unsetup` | Removes this server's config and deletes its tracked board messages. | — | 🔒 |
| `/board` | Shows the Mayor Board in the current channel; if the current channel is this guild's update channel, it manages the tracked Mayor Board in place (so `/board` never duplicates). | — | Everyone |
| `/checkmayor` | Fetch + apply the latest election data immediately, then persist. | — | Everyone |
| `/testchannel` | Sends a test message to the configured update channel. | — | 🔒 |
| `/setchannel` | Sets this server's **announcement channel**. Since the current implementation, announcements are delivered to this channel and nowhere else; independent of the `/setup` update-channel. | `channel: TextChannel` | 🔒 |

### 6.2 Owner-only group (`/owner …`, guild-scoped to the owner guild; never global)

These never sync beyond the owner guild. Only the owner (user + guild) may run them; every reply is ephemeral; non-owner callers get an ephemeral denial.

| Command | Synopsis |
| --- | --- |
| `/owner botstatus` | Ephemeral status summary (version, latency, uptime, guilds, configured counts, current mayor, last updated, data dir). |
| `/owner refresh` | Manually run one refresh cycle; reports the one-line outcome (ephemeral followup). |
| `/owner shutdown` | Graceful shutdown; replies then `client.close()` (sends 🔴). |
| `/owner health` | Live health embed with an overall **GREEN/YELLOW/RED** level + per-subsystem rows. |
| `/owner stats` | Aggregated stats embed (guilds, boards, refresh metrics) from `runtime`. |
| `/owner version` | Version / git commit / Python / discord.py / platform / started / uptime embed. |
| `/owner announce <title:str> <message:str> <type:enum> [ping:enum]` | Creates an announcement preview with Confirm/Cancel; nothing is broadcast until confirmed. `type` in `Information|Update|Maintenance|Patch Notes|Warning|Release`; `ping` in `No Ping|@here|@everyone`. |
| `/owner whitelist enable` | Enable whitelist mode. |
| `/owner whitelist disable` | Disable whitelist mode (everything non-blacklisted works again). |
| `/owner whitelist add <guild_id:str>` | Whitelist a guild (idempotent). |
| `/owner whitelist remove <guild_id:str>` | Remove from whitelist (errors if absent). |
| `/owner whitelist status` | Show mode + counts. |
| `/owner whitelist list` | List whitelisted guilds. |
| `/owner blacklist add <guild_id:str> <reason:str>` | Blacklist a guild (reason required). |
| `/owner blacklist remove <guild_id:str>` | Remove from blacklist. |
| `/owner blacklist list` | List blacklisted guilds with reason / added-by / added-at. |
| `/owner announcement history` | List the most recent announcements (newest first). |
| `/owner announcement resend <id:str>` | Preview a stored announcement for a new broadcast. |
| `/owner announcement delete <id:str>` | Delete one history entry. |
| `/owner announcement clear` | Wipe all history (requires a separate Confirm via a button). |

### 6.3 Guild-scoping invariant
Owner commands are scoped by `guild_ids=[OWNER_GUILD_ID]` on the group (and therefore its sub-groups). They are synced in `on_ready` via `bot.tree.sync(guild=OWNER_GUILD)` — **never** the global sync. Verified by tests (`test_owner.py::TestGuildScoping`).

---

## 7. Environment Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `DISCORD_TOKEN` | ✅ | Discord bot token. Must be set or the bot refuses to start (`main()` returns 1 with a clear message). |
| `HYPIXEL_API_KEY` | ✅ | Hypixel key, obtained in-game with `/api`. Sent as the request `API-Key` header when set. Required for startup, though the election endpoint is a public resource. |
| `BOT_STATUS_CHANNEL_ID` | — | Optional status channel (only startup/shutdown markers — see §8). |
| `BOT_LOG_CHANNEL_ID` | — | Optional operational log channel (one summary per refresh + config/setup/version/board-cleanup/access changes — see §8). |
| `BOT_ERROR_CHANNEL_ID` | — | Optional error channel (failures with traceback code-blocks — see §8). |

**Startup validation:** `bot.validate_env()` reports a `(name, required, present)` tuple per known variable; `_log_env_validation()` logs one ✅/⚠ line per variable. Missing required vars → `main()` prints a critical message and returns exit code 1 before connecting. Missing optional vars → a ⚠ warning, startup proceeds. This is independent of the older `get_missing_env()` strict check (still used by tests).

**Example:** copy `.env.example` → `.env` and fill. `.env` is gitignored.

---

## 8. Logging System

Everything emitted to the three optional channels goes through `reporting.py`. The three channels have **strict, non-overlapping contracts** (documented in `.env.example` and `reporting.py`'s docstring and enforced by tests). If an optional channel is unset/missing/a-send-fails, reporting **degrades silently to console logging and never raises**.

### 8.1 Status channel (`BOT_STATUS_CHANNEL_ID`)
**What it receives — only these four markers:**
- 🟢 `Bot Started` — the first launch after a fresh `data/` (no `.started` marker).
- 🔄 `Bot Restarted` — a process relaunch with a previous run's marker present.
- 🔁 `Bot Reconnected` — a gateway reconnect within the same process (a later `on_ready`; never re-marks startup).
- 🔴 `Bot Shutdown` — sent once on any clean close (command or Ctrl+C) via the `OathWatchBot.close` override; the once-only guard (`_shutdown_reported`) prevents duplicates.

**What must NEVER be sent there:** operational logs, error tracebacks, announcements, board summaries, or anything else.

### 8.2 Log channel (`BOT_LOG_CHANNEL_ID`)
**What it receives — operational signal, one per event:**
- One summary per refresh (hourly or manual): `🔄 Hourly refresh: <summary>` / `🛠️ Manual refresh: <summary>` — exactly one per cycle, never one per guild.
- Setup/unsetup/setchannel config changes.
- `⚙️` guild-left config removal.
- Lifecycle-aware version line at startup — `📦 OathWatch v1.1.1 started` on a fresh start/restart and `🔁 OathWatch v1.1.1 reconnected` on a gateway reconnect.
- ⚠️ Slow-refresh detected (duration, average, guild count, timestamp).
- Access-control changes (whitelist/blacklist enable/add/remove with reason/owner/timestamp).
- **Board lifecycle**: a single `🧹 Board Cleanup` when a stale board is removed and a single `✅ Board Recovered` on recovery (one per occurrence).

**What must NEVER be sent there:** error tracebacks, exceptions, per-guild board churn, raw Hypixel API responses, announcements.

### 8.3 Error channel (`BOT_ERROR_CHANNEL_ID`)
**What it receives — failures with their traceback in a code block:**
- Unhandled event errors (`on_error`).
- Command errors (global `on_tree_error`).
- Owner command permission denials.
- Hypixel API request failures.
- Failed "apply election data", "persist world state".
- Board refresh failures, announcement delivery failures.
- Corrupt-history resets.
- Hourly-loop crashes (`mayor_update_loop.error`).

`report_error(title, exc=None)` puts the traceback in a fenced code block clipped to fit one 2000-char message. When `exc` is omitted, only the `❌ **<title>**` line is sent (used e.g. for permission denials).

**What must never be sent there:** operational logs, status markers, or user-facing announcements. Announcements are broadcast only to guild announcement channels, never the error channel.

---

## 9. Access Control

All guild-allow/deny decisions flow through `access_control.py`, with `is_guild_allowed(guild_id)` as the **single source of truth** used by:
- the command gate (`OathWatchingCommandTree.interaction_check`),
- `setup.update_board_boards` (board update/recreate/self-heal),
- `refresh.send_mayor_change_notification`,
- `announcements.send_announcement`,
- `owner._stats` (allowed/blocked counts).

### 9.1 The rules (`is_guild_allowed`)
1. **Blacklist wins**: if the guild id appears in `blacklist`, it is never allowed.
2. **Whitelist mode**: if `whitelist_enabled` and not in exactly `whitelist` → not allowed.
3. **Otherwise**: every guild not blacklisted is allowed.

### 9.2 The command gate
`OathWatchTree.interaction_check(interaction)` runs before **every** slash command/app command. Logic:
- DM (`guild_id is None`) → allowed.
- Owner guild → allowed (the owner control panel can never be locked out).
- `is_guild_allowed` → allowed.
- Blocked guild:
  - If the interaction is a **real command** (not autocomplete) → send the ephemeral `blocked_message` and return `False`.
  - If it is **autocomplete** → silently return `False` (autocomplete cannot carry a message). 

This gate covers all current and future commands with zero per-command edits.

### 9.3 Feature skips (blocked guilds are disabled, never left)
Scheduled refresh, board updates/recreation/self-healing, notifications, `/setup`-driven updates, and announcements all call `is_guild_allowed` and **skip a blocked guild** without touching its stored data. The bot never leaves a blocked server.

### 9.4 Persistence & migration
State lives only in `data/access_control.json`, separate from `config.json`. Auto-created on first use; atomic writes; corrupt file → safe defaults (without destroying the file); older schemas (int ids, bare-string blacklist entries) migrate silently on load.

### 9.5 Ownership of changes
Only the owner can mutate whitelist/blacklist via `/owner`, and every such change is logged to the log channel. Blacklist `add` requires a reason and stores `added_by`/`added_at`.

---

## 10. Board System

### 10.1 What a board is
A board is anything that renders world data into a `discord.Embed`. Everything about a board is captured by a `BoardType` in the registry: a `key`, a display `name`, and an embedded builder.

### 10.2 Registered boards
- `mayor` → `"Mayor Board"` → `board.build_Mayor_board_embed` (blue, `📜 OathWatch`).
- `election` → `"Election Board"` → `election.build_election_board_embed` (orange, `🗳️ Election`).

### 10.3 Registry mechanics
- Registered in tag-scope of each renderer module.
- Registration happens on `oathwatch` package import (`__init__` imports the renderers with `noqa F401`).
- `get_board` raises `UnknownBoardError` for unknown keys; setup treats that by **skipping** (warns) so a legacy config with a once-valid board never breaks a refresh.
- Insertion order matters → stable ordering in `/setup` listing and the hourly loop.

### 10.4 Setup places boards (they never hard-code which exist)
`run_setup` iterates the `board_keys` it is given (which the `/setup` command builds from its checkboxes) and calls `get_board(key).build_embed()` — setup logic doesn't change when boards are added.

### 10.5 Lifecycle: place / refresh / self-heal / stale-cleanup
- **Place:** `place_board(channel, embed, stored_id)` → edit in place if `stored_id` exists; else create. `NotFound` → recreate (self-heal).
- **Refresh cycle:** `update_guild_boards(bot)` recreates any board whose message was deleted and reports refreshed/recreated counts into the loop summary.
- **Permanent failure** (channel itself is gone): `board_health` tracks a per-(guild, board) consecutive counter, persisted as `failures` in the config. After `MAX_CONSECUTIVE_FAILURES = 3` the stale reference is removed from config and a single cleanup log is sent; the guild's channel/notify config is kept. Transient errors (`HTTPException`, `Forbidden`, rate limits, timeouts) never touch the counter. A recovering board resets it and logs once.

### 10.6 `/board` command special case
If invoked *in* the guild's configured update channel, `/board` updates the tracked Mayor Board in place (via `place_board`) instead of just showing a one-off embed, so repeated `/board` cannot create duplicates.

---

## 11. Refresh System

### 11.1 The single pipeline (`refresh.py`)
Both the **hourly loop** and **`/owner refresh`** call `perform_refresh(bot)`, which times `_run_refresh_pipeline`:

1. Fetch election data (`get_election_data`) in a worker thread.
2. Validate with `is_election_data_valid` (rejects garbage).
3. Apply with `apply_election_data` (returns whether any displayed world state changed).
4. Persist world state (`save_world_state`) — best-effort, logged.
5. If changed: `update_guild_boards` to refresh/recreate every allowed guild's boards.
6. If the current mayor used to differ from `last_announced`, send `format_mayor_change_message` to every enabled+allowed guild and record the new `last_announced`, persisted.
7. Produce a `RefreshResult` whose `.summary` is **the one log line** for the cycle.

Failures at any step are logged (and where appropriate sent to the error channel) and the pipeline **continues/de-fails gracefully** — it never damages the caller or the loop.

### 11.2 The hourly loop
`@tasks.loop(hours=1) async` `mayor_update_loop()` calls `perform_refresh` and sends `🔄 Hourly refresh: <summary>` only on **success**; failures are handled by the `.error` handler which logs + restarts the loop.

### 11.3 Slow-refresh detection
If a cycle takes longer than `SLOW_REFRESH_THRESHOLD = 10.0` s, `perform_refresh` sends one `⚠️ Slow refresh detected` message with duration, average, guild count, and timestamp. All refreshes feed `runtime.record_refresh`.

### 11.4 Why exactly one log per cycle
The design deliberately produces a **single summary message** per cycle rather than one per guild — this keeps the log channel low-noise. Board/error noise goes only to the error channel/console.

---

## 12. Announcement System

Announcements are owner-initiated, user-facing broadcasts to each server's **announcement channel** (`announcement_channel_id`, set via `/setchannel`).

### 12.1 Flow
1. `/owner announce` (or `/owner announcement resend <id>`) composes an `announcement_embed` and shows an **ephemeral preview** with a Confirm/Cancel view. **Nothing is sent until Confirm.**
2. On **Confirm**, `send_announcement` iterates the configured guilds, skipping (a) blocked guilds, (b) guilds without an `announcement_channel_id`, (c) missing channels. It posts the embed with an optional `@here`/`@everyone` ping as the message content.
3. Results are counted; the preview message is replaced with the ephemeral summary (`Servers checked/delivered/skipped/failed`, duration, timestamp).
4. A history entry is created; failures are reported to the error channel once (**never** broadcast to users).
5. On **Cancel**, the preview is replaced with `❌ Announcement cancelled.`

### 12.2 History
- Stored in `data/announcement_history.json`, newest first, capped at `HISTORY_LIMIT=20`, sequential `ANN-0001`-style ids.
- Commands: `list` (newest first, delivery/failure counts, character-bounded to 2000), `resend <id>` (fresh preview of the stored content; a new history entry is created on send), `delete <id>`, `clear` (a separate `HistoryClearView` confirm; destructive).
- Corrupt files: auto-quarantined to `announcement_history.corrupted.json` and reset; the reset is reported to the error channel.
- Both views **re-verify the owner** on every click so a stale view opened by someone else can't be driven.

### 12.3 Types & colours
`Information` (blue), `Update` (green), `Maintenance` (orange), `Patch Notes` (purple), `Warning` (red), `Release` (gold). Patch Notes renders the body as markdown (multi-line).

---

## 13. Testing

### 13.1 Suite summary
- **241 test cases**, all **green** (`pytest`). Additionally `ruff check .` is clean and `mypy .` is clean.
- **Isolation:** every test that touches persistence uses the `isolated_storage` fixture (conftest) which repoints `DATA_DIR`, `CONFIG_FILE`, `BACKUP_FILE`, `WORLD_FILE`, `ACCESS_FILE`, `HISTORY_FILE`, `CORRUPTED_FILE` to a per-test temp dir. The real `data/` is never read or modified by tests.
- **Metrics hygiene:** an autouse `_reset_runtime` clears `runtime` counters; an autouse `_reset_reporting_state` resets the once-only shutdown guard.

### 13.2 Mocks (`tests/mocks.py`)
Fake Discord objects that mirror the library API closely (production-identical `isinstance` for text channels via subclassing of `discord.TextChannel`):
- `MockResponse` (for constructing `discord.NotFound`/`Forbidden`/`HTTPException`).
- `MockMessage` (edit/delete; records edits).
- `MockPerms`, `MockGuild` (get_channel), `MockChannel` (subclasses `discord.TextChannel`; holds messages; `send`/`fetch_message`; raises `NotFound` for missing; global message counter mirrors Discord's global ids).
- `MockBot` (get_channel/get_guild/is_ready/close).
- `MockInteractionResponse`/`MockFollowup`/`MockInteraction` (records replies/followups/edits for owner-command and view-callback assertions).

### 13.3 Coverage by test file
| Test file | Covers |
| --- | --- |
| `test_access_control.py` | Storage/migration, rule precedence, whitelist/blacklist mutations, blocked-message. |
| `test_announcements.py` | Delivery/skip/failure, embed, history ids/cap/corruption, preview & clear views. |
| `test_announcement_cmd.py` | Owner announce/resend/delete/clear behaviours + preview composition. |
| `test_board_health.py` | Counter arithmetic + cleanup/recovery message format. |
| `test_board_registry.py` | Registration, retrieval, embed building, unknown-key error, adding a board. |
| `test_election.py` | Render-time percentage fallback, progress bars, election board layout/ordering/embed. |
| `test_formatting.py` | `§`-strip, truncation, perks, timestamps, refresh notice. |
| `test_owner.py` | Guild-scoping/registration, owner-permission gate, botstatus/refresh/shutdown, startup reporting, hourly-loop logging, whitelist/blacklist commands, command gate, blocked-guild feature skips. |
| `test_owner_health.py` | health/stats/version embeds + GREEN/YELLOW/ RED logic + owner gating. |
| `test_refresh.py` | Slow-refresh detection branches; refresh-error recording. |
| `test_reporting.py` | Status/log/error channel sends, degraded channels, start marker, fresh/restart/reconnect lifecycle, shutdown once-guard. |
| `test_runtime.py` | Refresh metrics, uptime, version info, memory. |
| `test_setup.py` | run_setup placement/move/repeat, permission errors, update_board self-heal, stale-board cleanup lifecycle, unsetup. |
| `test_storage.py` | Atomic persistence, no tmp leftovers, legacy migration, failure-counter persistence, backup creation. |
| `test_world_state.py` | apply_election_data changes, candidate sorting/coercion, valid/invalid validation, normalisation/legacy migration. |
| `test_startup.py` | Requirement that import/launch validation behaves (version, env) — startup path. |

### 13.4 How to run
```bash
pip install -r requirements-dev.txt
pytest            # tests (isolated)
ruff check .       # lint
mypy .             # type check
```

---

## 14. Documentation

- **`README.md`** — public-facing overview: features, screenshots placeholder, installation, configuration/env tables, command tables, architecture overview, project structure, roadmap summary, development setup, contributing (incl. a "Adding a board" walkthrough), license, credits.
- **`PROJECT_SPEC.md`** — vision, current/planned features, architecture (module-by-module narrative), tooling, coding standards, current phase. Must be updated when a major feature lands (AI_RULES.md mandates it).
- **`ROADMAP.md`** — phased plan + milestone tracker.
- **`CHANGELOG.md`** — versioned change log.
- **`.env.example`** — the environment template + the channel-contrast prose.
- **`AI_RULES.md`** — the engineering rules that shaped the project (never rewrite working code, backward compat, modularity, explain-before-code, update PROJECT_SPEC on major features, autonomy guidelines).
- **`LICENSE`** — MIT.
- **`HANDOFF.md`** — this document.

---

## 15. Technical Decisions

Each decision below notes the choice, why, the alternatives weighed, and the tradeoff taken.

### 15.1 Flat JSON files instead of a DB
- **Why:** a handful of tiny config documents, no relational need, crash-safe single-DB by atomic writes + backups; zero infra; trivially inspectable by an admin; no auth surface.
- **Alternatives:** SQLite/Postgres/Redis. Rejected: overkill for a single low-frequency self-hosted bot.
- **Tradeoff:** no concurrent writers; a single writer process is assumed. Atomic write + rolling backup (config) mitigate the write-crash risk. Hand-edits risk schema drift, mitigated by normalization on load.

### 15.2 Module-global mutable state (`WORLD_STATE`, `runtime` counters)
- **Why:** a single-process bot that needs a consistent in-memory view shared by renderers and commands; avoids threading the state through every call.
- **Tradeoff:** test interference — mitigated by `reset_world_state`/`_reset_runtime` autouse fixtures. Not thread-safe across `asyncio.to_thread` boundaries, but Discord calls and the loop co-ordinated single-loop.

### 15.3 A custom `CommandTree.interaction_check` as the access gate
- **Why:** covers *every* command (present and future) with one function; the owner guild is exempt so the control panel survives a (self) block.
- **Alternatives:** per-command `disabled` checks (unmaintainable), relying on channel overrides (leaky).
- **Tradeoff:** the gate runs the allow/deny decision on every interaction (TL → `load_access_control`).

### 15.4 Guild-scoped owner commands
- **Why:** `/owner` must never appear in a public server. `guild_ids` scoping + a separate owner-guild `sync` achieves it.
- **Tradeoff:** `OWNER_GUILD_ID` and `OWNER_USER_ID` are read from the environment at import (single-owner assumption; no delegation). See §16.

### 15.5 A shared refresh pipeline (`refresh.py`) used by both the loop and `/owner refresh`
- **Why:** the loop and manual refresh must never drift into different logic (a classic divergence source). One `RefreshResult` → one log line.
- **Tradeoff:** none (pure consolidation). 

### 15.6 Threaded blocking I/O (`asyncio.to_thread`) for Hypixel HTTP
- **Why:** `requests` is synchronous; running it inside the event loop would stall the websocket/heartbeat.
- **Alternatives:** `httpx` (async) or `aiohttp`. 
- **Tradeoff (chosen):** keeps the API client dead-simple (`requests`); the 10 s timeout bounds blocking. `time.sleep` in the retry loop runs in the worker thread, not the loop.

### 15.7 Self-healing + permanent-failure stale cleanup
- **Why:** two distinct failure modes: a deleted board message (recoverable → self-heal) vs a deleted channel (irrecoverable). A naive logger would log forever; a naive removal would destroy config on the first transient hiccup. A consecutive-permanent-fail counter (only for not-found) balances both.
- **Tradeoff:** 3 cycles (≈3 h) before a stale channel reference is dropped (deliberate patience).

### 15.8 Discord native timestamps in descriptions, not footers
- **Why:** Discord does not render `<t:...>` in footers; it does in fields/descriptions. Placing them in the description makes "Last Updated" render in each viewer's local timezone.
- **Tradeoff:** footers stay static. 

### 15.9 The owner-recheck on every announcement view click
- **Why:** a stale preview message with buttons could otherwise be driven by someone else; each click re-verifies the owner.
- **Tradeoff:** minor extra callback.

### 15.10 Per-variable env validation vs a single "missing anything" gate
- **Why:** operator-friendly; optional reporting channels are not fatal, so you only learn exactly what's missing.
- **Tradeoff:** two code paths (`get_missing_env` strict for tests vs `validate_env` per-var) — deliberately kept separate and documented so they never drift.

### 15.11 A rolling `config.backup.json` before each write
- **Why:** the highest-value artifact (guild config) gets a crash-safety net without a journaling system.
- **Tradeoff:** an ever-present second file; safe-by-copy (previous state).

### 15.12 Single-owner hardcodes
- **Why:** this is a private, single-owner deployment; solving the multi-owner problem was unnecessary and would add RBAC surface.
- **Tradeoff:** not a multi-tenant product; changing owner/guild requires editing `owner.py` + re-sync (documented in §16).

---

## 16. Known Issues, Limitations & Intentional Choices

### 16.1 Intentional limitations
- **Single owner, single owner-guild, ids from configuration.** `OWNER_USER_ID`/`OWNER_GUILD_ID` come from the environment (`OWNER_USER_ID`/`OWNER_GUILD_ID` in `.env`), read in `owner.py`. Multi-owner or owner-profile config is out of scope. **Impact:** to reassign owner, change the `.env` values, re-sync, and restart; access-control does not support delegation.
- **Only two measures boards** (Mayor + Election). Bazaar, Event, etc. are planned (out of scope).
- **Single global world state**, shared across guilds (correct for a global election; not per-guild/named state). 

### 16.2 External-API coupling
- **One Hypixel resource** (`.../skyblock/election`). Shape is normalized and validated; if Hypixel changes the schema, `is_election_data_valid`/`apply_election_data`/`normalize_world_state` carry the schema (they already tolerate `current` vs `election` layouts). Any schema change must be tested against a new payload.
- **Public resource** requires the API key only optionally; the key is still required at startup (a deploy-time assertion). Rate-limit: the retry handles 429/5xx only.

### 16.3 Reliability acknowledgments
- **Local runtime memory metrics** (`process_memory_mb`) are *best-effort*: uses `resource` on POSIX, falls back to `tracemalloc` (only accurate if tracing was enabled), else reports `None` (health shows "N/A"). Not a complete memory profile.
- The slow-refresh threshold is a constant (10 s), not configurable.
- `SHUTDOWN` status is sent only on clean close (not on a hard kill/OOM).
- The refresh runs on a `tasks.loop(hours=1)`; the "Next refresh" hint on boards is a hardcoded 1-hour assumption (`REFRESH_SECONDS=3600`).

### 16.4 Discords/permissions
- Only default `intents` (no message-content or privileged intents needed — the bot uses slash commands and reactions).
- `send_message`/`embed_links`/`read_message_history` are prerequisites in a guild's update channel; `/setup` surfaces which are missing.
- Global `/owner` announce pinging `@everyone` requires appropriate member permissions in that channel (failure → counted as failed, reported to error channel, never retried).

### 16.5 Data considerations
- **Config/worlds are hand-editable** but schema-normalized on load; a malformed `config.json` (not just a missing file) — e.g. invalid JSON — is NOT auto-healed by `read_json` and would propagate to callers; `normalize_config` coerces most shapes, and the rolling backup enables manual recovery. This is the deliberate "tolerant read" tradeoff.
- **Backups per config only** (not world-state/access/history). Intentional: those are re-derivable or lower value.
- **Announcement content is user-provided and stored verbatim** in history (subject to Discord's content rules).

---

## 17. Final Regression Review

A systematic audit with the requested lens. Result: **no blocking defects; several notes and one deliberate-maintenance caveat.**

### 17.1 Dead code / unused imports
- Review passes: the codebase is Ruff-clean (`select` includes `F` pyflakes), so unused imports would be flagged. All `# noqa` instances are intentional (e.g. `from . import board, election  # noqa F401` registering boards; `noqa BLE001` on deliberately-broad exception handlers in reporting/refresh/announcements).
- **Assignment note (not dead code):** in `refresh.py`, `import asyncio` etc. are used. `bot.py`'s `_args`/`_kwargs` in `on_error` are intentionally named with underscores/leading underscore to signal intentional unused.

### 17.2 Unused imports
- None survive lint. Verified repo-wide.

### 17.3 Duplicate logic
- The suite consolidates: refresh pipeline (loop ↔ manual) in `refresh.py`; embed format in `formatting.py`; persistence atomically in `storage_utils`; access-control in one module; metrics in `runtime`; announcement send+history in `announcements.py`. Two small near-duplications deliberately kept separate for clarity: `get_missing_env` (strict) vs `validate_env` (verbose) — documented in §15.

### 17.4 Circular dependencies
- One intentional lazy import: `owner._refresh_loop_running` imports `oathwatch.bot.mayor_update_loop` **at call time** to break the import-cycle `bot → owner` (bot also imports owner). The only documented cycle; handled correctly.

### 17.5 Hidden bugs
- No reachable exception paths that are not guarded: the hourly loop, the board refresh, the refresh pipeline, reporting, announcements, and unsetup all degrade to log/report rather than raise into the loop. The `/checkmayor` command surfaces a friendly error.

### 17.6 Edge cases
- Empty `data/` (fresh deploy) → defaults everywhere.
- Missing/corrupt `access_control` / history → fallback/quarantine.
- Election-day payloads (mayor absent) → board shows the running election and an "election in progress"/"no mayor".
- Deleted board message → self-heal; deleted channel → stale-counter → cleanup.
- Hand-edited boards with an unknown key → `update_board_boards` warns and skips (does not crash).
- `/board` in the configured channel → in-place update, no duplicates.

### 17.7 Race conditions
- `update_board_boards` runs on the event loop; interactions are sequential re: board placement. No multi-process writer exists. Board message edits across separate commands are serialized by the single loop's await order.
- The `send_shutdown_status` once-only guard makes the 🔴 safe against double-close.

### 17.8 Data corruption
- Atomic writes prevent truncation; config has a rolling backup; history renames corrupt files; access-control falls back to safe defaults. The only unhandled gap is hand-corrupt `config.json` (invalid JSON → not caught by the generic `read_json` default) — see 16.5; tolerable for a single-writer bot, and `normalize_config` does coerce dict/None regardless.

### 17.9 Discord API issues
- Uses currentish `discord.py` 2.x (requirements allow 2.0–<3.0). If a 3.x ships and is installed, verify `app_commands`/`tasks`/`ui.View` compatibility before upgrading; the current suite pins/installs a 2.x.
- `isinstance(channel, discord.TextChannel)` guards prevent using non-text channels as update/announcement channels.

### 17.10 Hypixel API issues
- A single heavyweight endpoint; retries only on 429/5xx (the common transient). Non-retryable (e.g. 4xx) raise immediately.
- Schema: tolerant of both `current` and legacy `election` layouts and omits values.

### 17.11 Backward compatibility
- Legacy `world_state.json` flat formats were currently migrated; legacy `config.json` `board_message_id` migrate; legacy access-control listener schemas migrate; the `election` (legacy) and `current` layouts are both read. Boards/schema have been kept load-compatible across versions.

### 17.12 Performance
- Operations per hour are tiny (one HTTP call + per-guild per-board embed/edit). The only notable cost is `git_commit()` at `/owner version` (a ≤3 s subprocess), invoked once per request. No hot paths.

### 17.13 Memory
- In-memory state is small (a handful of dicts). No unbounded growth: stale-board cleanup prevents runaway failure lists; history capped at 20. Process memory is reported best-effort (may be `N/A` on some platforms).

### 17.14 Security
- Secrets (`DISCORD_TOKEN`, `HYPIXEL_API_KEY`) are read from `.env`, never logged, gitignored. The app never sends secrets to channels. Owner commands never sync globally. Permission denials are ephemeral (minimal info, no internal leaked). Announcement delivery is owner-gated; a blocked guild is not sent announcements. Message content uses `app_commands.default_permissions` for admin-flagging routes. **Note:** Hypixel payload text is stripped of `§` format codes before display (display hygiene; payload text is treated as untrusted).
- **Not** a multi-tenant secure service: owner identity is a hardcoded user id; anyone who controls the `.env`/data directory can surge the bot.

### 17.15 Missing tests
- No test for the actual Hypixel network (by design — no CI dependency on the live API); payloads are hand-built in tests.
- No test that the global sync includes owner commands (by design they must not); the owner gating and separate owner-guild sync behaviour are covered in `test_owner.py`.
- No end-to-end "boot the real client" test (would need a token) — covered by mock-based tests.

### 17.16 Doc / version inconsistencies
- `__version__ = "1.1.1"` in `__init__.py` matches README/ROADMAP/CHANGELOG. Naming is consistent across config/docs. CI runs 3.10 + 3.12, while the local environment is 3.14 (fine).

### 17.17 Concurrency saves in the event loop
- Writes happen in awaited sequence and only from the loop; `asyncio.to_thread` is used for the network call only, not for writes.

**Summary:** no blocking finding. The two items to keep on the radar are (a) the intentional owner/go./API coupling, and (b) the note that a *malformed* (vs missing) `config.json` is not self-healed — backed up by `config.backup.json` for manual recovery.

---

## 18. Release Checklist (for shipping a change / releasing a version)

Use this every release.

1. **Code gate**
   - [ ] `ruff check .` clean.
   - [ ] `mypy .` clean.
   - [ ] `pytest` → **241 passed** (or green on your change).
   - [ ] No `print()` debugging left; use `logging`.
2. **Schema/data compat**
   - [ ] Verify any persisted file format change has a `normalize*`/migration path and that callers that read it tolerate missing/None.
   - [ ] If `config.json`'s structure changes, keep the rolling `config.backup.json` behaviour; validate normalization tests.
   - [ ] If world-state shape changes, extend `normalize_world_state` + its tests.
3. **Versioning**
   - [ ] Bump `__version__` in `oathwatch/__init__`.
   - [ ] Add entries to `CHANGELOG.md` and `ROADMAP.md`; update `README.md` if user-visible; update `PROJECT_SPEC.md` if a major feature (per AI_RULES.md).
   - [ ] Confirm `FOOTER_TEXT` (derives from `__version__`) renders the new version, if you change it.
4. **Environment**
   - [ ] Update `.env.example` for any new env vars (keep the ✅/⚠ validation in `bot` in sync with `REQUIRED_ENV`).
   - [ ] Verify startup validation and non-fatal-vs-fatal channels behave.
5. **Access control**
   - [ ] If you add any command, confirm it goes through the `interaction_check` gate and, if it's owner-only, into the guild-scoped group.
   - [ ] If you add behaviour to boards/refresh/announcements, make sure it consults `is_guild_allowed` for blocked-guild skips.
6. **The `data/` safety**
   - [ ] Backups exist for anything important (config has backups; world-state/history/access-control are derivable).
   - [ ] Ensure the test suite's `isolated_storage` still points to a temp dir (never real `data/`).
7. **Entry points**
   - [ ] `python bot.py` and `python -m oathwatch` both boot.
   - [ ] `on_ready` syncs global + owner-command channels correctly.
8. **Docs**
   - [ ] README command/env tables agree with the actual command list.
   - [ ] `.env.example` matches reported/required variables.
9. **CI**
   - [ ] GitHub Actions passes on both Python 3.10 and 3.12.
10. **Deployment (“release the bot”)**
    - [ ] Copy `.env.example` → `.env`, fill secrets.
    - [ ] Invite the bot with the `bot` + `applications.commands` scopes (Send Messages, Embed Links, Read Message History).
    - [ ] Run `/setup`, verify `data/` is created and boards appear.
    - [ ] Test `/owner` (owner guild only) and a `/checkmayor`.
    - [ ] Confirm the three reporting channels (if set) receive the right messages.
    - [ ] Shut down gracefully and confirm 🔴 in the status channel.

---

## 19. Final Verdict

**Production-ready for the documented scope of this project (a single-owner, self-hosted bot tracking the Mayor and Election boards).**

### Justification
- **Correctness & reliability:** the refresh pipeline, board placement/self-healing, stale cleanup, and persistent/atomic storage are all objectively fallback and guard-correct; the hourly loop cannot die silently (error handler restarts) and cannot be killed by a single bad guild (each failure logs/reports separately).
- **Style & type:** Ruff + mypy + pytest all green; a coherent, modular architecture.
- **Security & ops:** access control has one source of truth; blocked guilds are disabled, never harmed; owner commands never sync globally; ephemeral replies; no secrets logged; optional reporting channels with strict contracts; env validation fails fast.
- **Extensibility:** the board registry lets a new board (Bazaar, Event) be added (a new module + a register call) without touching setup or refresh.
- **Discoverability:** this document should give a new engineer the full map.

### What would *prevent* unconditional production readiness (not bugs — deliberate scope limits)
1. It is **not** a multi-tenant/multi-owner product: owner ids are constants; there's no human RBAC.
2. It couples to **one third-party API endpoint**; a schema/endpoint change on Hypixel's side requires a tested bump.
3. Only two boards and a handful of commands — by design.
4. A *malformed* `config.json` (valid JSON but wrong structure) is not auto-healed (stack: `read_json` returns the default only on a missing file; a wrong-but-valid file is coerced by `normalize_config`); manual recovery via the rolling backup is supported.

### The single caveat to flag to a new maintainer
**Any change to persistence schemas, access-control behavior, or the set of commands must keep the "single point-of-truth" modules (§3.2) and the channel contracts (§8) intact**, or the integration tests (which would then fail) plus the migration paths would be at risk. Preserve backward compatibility exactly as AI_RULES.md and the test suite expect.

---

*End of handoff. Version 1.1.1. This document was written to inform a handover and was **not committed**.*