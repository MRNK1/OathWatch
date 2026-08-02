# Changelog

## v1.1.1

Maintenance release: promotes the post-v1.1.0 production polish (previously tracked as "Unreleased") into a shipped release, fixes the startup notification mislabeling, and synchronizes all documentation.

### Added

- **Stale-board cleanup** — a board whose update channel is permanently dead stops failing and logging forever:
  - Deleted board message with a live channel → the board is **recreated** on the next refresh (existing self-healing, unchanged).
  - Deleted/irrecoverable update channel → a consecutive **permanent-failure counter** (per guild + board type) is persisted in `config.json`. Transient failures (HTTP errors, permission issues, rate limits, timeouts, network/Hypixel failures) never touch it.
  - After **3 consecutive permanent failures** the stale board reference is removed from `config.json` with a single final `🧹 Board Cleanup` log — the guild's channel config and notification settings are kept, and the board is never logged again.
  - A board that recovers before the threshold resets its counters and logs a one-time `✅ Board Recovered` message.
- `oathwatch/board_health.py` — isolated consecutive-failure counter and cleanup/recovery log formatters; `BoardPermanentError` in `oathwatch/setup.py` distinguishes an irrecoverable board (channel gone) from transient `SetupError` failures.
- **`/owner health`** — live subsystem health as an embed with an overall **Green/Yellow/Red** level (Discord API + latency, background loop, Hypixel/refresh, configuration, world state, reporting channels, access control, last/next refresh, memory usage).
- **`/owner stats`** — version, uptime, guild totals (total/configured/allowed/blocked), board counts (mayor/election/tracked), refresh metrics (count, average, longest), all drawn from a central `oathwatch/runtime.py`.
- **`/owner version`** — version, git commit, Python, discord.py, platform, process start time, uptime.
- **`/owner announce`** — broadcast an announcement to every configured announcement channel via an interactive **Confirm/Cancel preview** (nothing is sent until confirmed). Types: Information, Update, Maintenance, Patch Notes, Warning, Release — each with its own embed colour. Optional ping (`No Ping` / `@here` / `@everyone`). On send the owner sees an ephemeral summary (servers checked/delivered/skipped/failed, duration, timestamp).
- **Announcement history** (`data/announcement_history.json`, auto-created, capped at 20, newest first, sequential `ANN-XXXX` ids) plus `/owner announcement` subcommands:
  - `history` — list ids/titles/types/timestamps and delivered/failed counts.
  - `resend <id>` — previews and re-sends the exact stored content; creates a new history entry.
  - `delete <id>` — removes one entry.
  - `clear` — wipes all history, **with an explicit Confirm/Cancel**.
  - A corrupt history file is moved to `announcement_history.corrupted.json` and a fresh one created; the reset is reported to the error channel.
- **Announcement channel** (`/setchannel` re-added, repurposed) — sets a guild's `announcement_channel_id`, the only target for owner announcements. Independent of the `/setup` update-board channel; stored in `config.json` and preserved through config migration.
- **Slow-refresh detection** — a refresh exceeding 10s logs one `⚠️ Slow refresh detected` message to the log channel with duration, average, guild count, and timestamp.
- **Startup env validation** — every environment variable (required + optional reporting channels) is checked and logged with a ✅/⚠ per variable; the bot still starts on non-fatal (optional) gaps.
- **Configuration backup** — before each `config.json` write, the previous config is saved to `config.backup.json` (one rolling backup, atomic).
- **Shared embed polish** — `OathWatch v<version>` footer on every embed and a consistent colour scheme.
- **Reconnect detection** — a third startup marker, 🔁 *Bot Reconnected*. `on_ready` fires again whenever Discord's gateway reconnects within the same process; the bot now reports a reconnect honestly instead of repeating the restart marker. A fresh first run still reports 🟢 *Bot Started*, and a deliberate process relaunch (a prior run's marker present) still reports 🔄 *Bot Restarted*.
- `oathwatch/runtime.py` — central runtime stats (start time, refresh counters, versions, platform, memory) shared by health/stats/version and slow-refresh detection; `oathwatch/announcements.py` — broadcast + history + preview/confirm views.

### Changed

- `/setchannel` repurposed from update channel to **announcement channel** (it sets `announcement_channel_id`). Legacy `/setup`-based update-board channels and existing configs keep working; no migration needed.
- `update_guild_boards` now tracks per-board consecutive failures, removes irrecoverable board references, and sends exactly one cleanup/recovery message per occurrence.
- Config normalization preserves each board's `failures` counter and the guild's `announcement_channel_id` across loads (malformed values are dropped).
- `save_config` now writes a one-for-one `config.backup.json` before every write.
- Every embed now carries the shared `OathWatch v<version>` footer and a consistent colour scheme.
- Startup lifecycle reporting funnels through a single `reporting.report_startup()` classification (fresh / restart / reconnect). The start marker is written exactly once — on the first ever run — and reconnects neither re-write it nor re-report a restart. The startup log line now says "started" or "reconnected" to match the status marker.

### Fixed

- **Startup notification bug** — after a normal connection, a gateway reconnect re-fires `on_ready` in the same process and the bot reported 🔄 *Bot Restarted* even though no restart happened, producing a spurious, confusing status message. Reconnects are now reported as 🔁 *Bot Reconnected* and no longer masquerade as restarts. Fresh launches (🟢) and genuine process restarts (🔄) are unchanged, so existing behaviour is fully preserved.

### Reliability

- **Stale-board cleanup** makes permanent channel loss self-resolving: instead of failing and logging every hour forever, a dead board is removed from config after 3 consecutive permanent failures, while a recovering board resets its counter — operators stop chasing phantom board errors, and transient failures (rate limits, timeouts, network blips) can never trigger a cleanup.
- **Slow-refresh detection** surfaces performance regressions as a single log-channel warning instead of silent degradation.
- **Configuration backup** guarantees a recoverable previous configuration before every `config.json` save.
- **Reconnect classification** removes a source of false status spam on flaky connections and keeps the status channel honest.

### Logging

- One-time, bounded logging replaces repeated per-hour failure spam: `🧹 Board Cleanup` (final removal), `✅ Board Recovered` (counter reset), `⚠️ Slow refresh detected` (per occurrence), and a ✅/⚠ per-variable startup validation report.
- The startup/version log line is lifecycle-aware — `📦 … started` on a fresh start or restart and `🔁 … reconnected` on a gateway reconnect — so the log channel never claims a restart that did not happen.

### Tests

- 67 new test cases: health/stats/version embeds and gating, announcement delivery/skip/failure, history ids/cap/corruption, preview and clear views, slow-refresh detection, runtime metrics, per-variable env validation, `/setchannel`, and the fresh-vs-restart-vs-reconnect startup classification (4 new regression tests for the reconnect fix).

### Documentation

- `CHANGELOG.md` — post-v1.1.0 work promoted from "Unreleased" into this release; full history preserved below.
- `ROADMAP.md` — v1.1.1 milestone added; the forward-looking plan restructured into versioned releases (v1.2–v1.6 + Future).
- `README.md` — roadmap summary and the status-channel contract now include the 🔁 reconnect marker.
- `PROJECT_SPEC.md` — current features and the upcoming-releases list updated to match the roadmap.
- `HANDOFF.md` — timeline, channel contracts, module reference, and release checklist updated to the v1.1.1 state.

### Maintenance

- Version bumped from 1.1.0 to 1.1.1 (`oathwatch/__init__.py`); every version reference across code and docs is consistent.
- The post-v1.1.0 "Unreleased" work is now a shipped, documented release.
- No behaviour outside the documented scope changed; fully backward compatible.

## v1.1.0

### Added

- **Owner-only `/owner` command group** — `botstatus`, `refresh`, and `shutdown`. The group is guild-scoped to the owner guild only and is never synced globally, so it never appears in any public server. Only the owner user may execute it; anyone else receives an ephemeral *"You do not have permission to use this command."* Every reply is ephemeral.
- **Owner reporting channels** (optional, `.env`): `BOT_STATUS_CHANNEL_ID`, `BOT_LOG_CHANNEL_ID`, `BOT_ERROR_CHANNEL_ID`. The bot runs fine when blank.
  - Status channel: only 🟢 Bot Started / 🔄 Bot Restarted / 🔴 Bot Shutdown.
  - Log channel: one operational summary per refresh cycle, plus setup completed, board recreated, configuration changes, and version info — never one message per guild.
  - Error channel: unhandled exceptions, command errors, permission failures, Discord HTTP failures, Hypixel API failures, storage failures, and board failures, each with its traceback in a code block.
- `oathwatch/reporting.py` — reusable status/log/error channel reporting (optional channels, degrades to console logging, never raises).
- `oathwatch/refresh.py` — shared refresh pipeline used by both the hourly loop and `/owner refresh`, so the two never drift apart.
- `oathwatch/owner.py` — all owner functionality isolated in one module.
- Startup vs restart detection via a persisted marker (🟢 first launch, 🔄 subsequent launches); 🔴 is sent on any clean shutdown (command or Ctrl+C) through an `OathWatchBot.close` override.
- Error-channel reporting wired into the unhandled-event handler, the global command-error handler, the hourly-loop crash handler, and the checkmayor/refresh/setup paths.
- Tests: 25 new (reporting channels, owner guild-scoping/permissions, status/refresh/shutdown, startup/shutdown/refresh/error logging, single-message-per-cycle).
- **Guild access control** — `/owner whitelist` (`enable`, `disable`, `status`, `add`, `remove`, `list`) and `/owner blacklist` (`add` with required reason, `remove`, `list`). Guild-scoped to the owner guild only, owner-only, every reply ephemeral. Blacklist entries store Guild ID, Reason, Added By, and Added Timestamp (rendered as a Discord timestamp in `/owner blacklist list`).
- `oathwatch/access_control.py` — isolated whitelist/blacklist logic and `data/access_control.json` persistence: auto-created on first use, atomic writes, corrupt-file fallback to safe defaults, and automatic migration when the schema changes. Rules: blacklist always wins; whitelist mode restricts to whitelisted guilds; otherwise every guild is allowed.
- Blocked-guild behaviour — a custom `CommandTree.interaction_check` disables every slash command in blocked guilds (ephemeral disabled message; the owner guild is always reachable). Board creation/updates/recreation, self-healing, notifications, scheduled refreshes, and `/setup` all skip blocked guilds. The bot never leaves a guild — it simply behaves as disabled, and no stored data is modified.
- Whitelist/blacklist change logging to the log channel (guild name, guild id, reason when applicable, owner, timestamp).
- Tests: 40 new (access-control storage/migration, rule precedence, owner whitelist/blacklist commands, the command gate, and blocked-guild feature skips).

### Changed

- The hourly loop now delegates to `perform_refresh` and sends exactly one log-channel summary per cycle on success.
- `update_guild_boards` returns refreshed/recreated counts for the refresh summary and reports board failures to the error channel.
- `/setup`, `/unsetup`, and `/setchannel` log configuration changes to the log channel; a leaving guild's config removal is logged too.
- Board updates and mayor-change notifications now consult `is_guild_allowed` and skip blocked guilds without touching stored data.
- Version bumped to 1.1.0.

## v1.0.2

### Changed

- Source modules moved into the `oathwatch/` package; the top-level `bot.py` is now a thin launcher preserving the `python bot.py` entry point (`python -m oathwatch` works too).
- Intra-package imports converted to relative imports; tests now import from `oathwatch.*`.
- Board registration moved to `oathwatch/__init__.py`, so boards are registered whenever the package is imported.
- `storage_utils` now computes the data directory relative to the project root, so `data/` stays put regardless of import path.
- `__version__` moved to `oathwatch/__init__.py`; version bumped to 1.0.2.
- Logging standardised on lazy `%`-style formatting; added the missing bot-module docstring.

### Fixed

- None — structural cleanup only. Runtime behaviour, config schema, and board output are unchanged.

## v1.0.1

### Added

- Proportional text progress bars for every election candidate
- Vote percentages derived from vote counts at render time when the API omits them
- Discord native timestamps (`<t:...>`) for "Last Updated" (rendered in each viewer's local timezone) and "Next Refresh" (`<t:...:R>`, relative)
- Render-time standings so the leading candidate and ordering reflect computed support
- Board footers reduced to static text; the timestamp line lives in each board's description because Discord does not render `<t:...>` in footers

### Changed

- `WORLD_STATE["last_updated"]` is now unix epoch seconds; legacy UTC-string values from older persisted state migrate automatically
- Election Board candidate fields lead with the support bar, percentage, and vote count before the perks
- Version bumped to 1.0.1

### Fixed

- Leading Candidate now reflects the actual top candidate when the API omits vote percentages

## v0.5.0

### Added

- `main()` entry point with `if __name__ == "__main__"` guard
- Startup validation for every required env var (`DISCORD_TOKEN`, `HYPIXEL_API_KEY`) with clear errors
- `on_guild_remove` config cleanup (departed guild only; world state preserved)
- README.md, .env.example, MIT LICENSE
- pyproject.toml (Ruff / MyPy / Pytest), requirements-dev.txt, GitHub Actions CI
- Automated test suite (`tests/`, 47 tests) — isolated from real project data

### Changed

- `bot.py` is now importable without env or run side effects; startup logs version, data dir, and guild count
- Channel access narrowed to text channels (`isinstance` guards) in setup and bot
- Hypixel API key header only sent when set; typed `last_error` accumulation
- `WORLD_STATE` and board registry annotated as `dict` for MyPy
- Ruff-clean: modernized `Callable` import, `raise … from` exception chaining, removed redundant file-mode arg

### Fixed

- Hypixel API key typing made safe when unset

## v0.4.0

### Added

- Election Board (status, leading candidate, all candidates with vote counts/percentages and perks)
- /setup board selection: `mayor_board` and `election_board` options
- Election data in world state (year + candidates sorted by vote %)
- formatting.py shared render helpers (used by both boards)

### Changed

- /setup places only the boards the admin selects; existing Mayor-only setups keep working
- apply_election_data now returns whether any world state changed (boards refresh on vote moves)
- is_election_data_valid accepts election-only responses (mayor may be absent on election day)
- Malformed candidates are coerced defensively instead of crashing renders

### Fixed

- None — Phase 4 was additive; no regressions observed.

## v0.3.0

### Added

- /setup
- Board registry
- Automatic board recovery

### Changed

- Config migration
- Better setup flow

### Fixed

- Duplicate boards
- setchannel overwrite bug