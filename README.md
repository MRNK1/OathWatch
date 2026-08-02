# OathWatch

OathWatch is a production-quality Discord bot that tracks Hypixel SkyBlock world state. It posts live **Mayor** and **Election** boards to your server, announces mayor changes, and refreshes every hour — all configured with a single `/setup` command.

> 🚧 **Public beta** — the bot is feature-complete for its current boards. See the [Roadmap](#roadmap) for what is planned next.

## Invite OathWatch

Invite OathWatch to your Discord server:

**Invite Link:**
https://discord.com/oauth2/authorize?client_id=1533208250529484951&permissions=2251801961294848&integration_type=0&scope=bot

## Features

- 🏰 **Mayor Board** — current mayor, minister, and their perks, updated hourly.
- 🗳️ **Election Board** — election status, every candidate ranked by support with proportional progress bars, vote percentages, vote counts, and candidate perks.
- 🕒 **Native time display** — Last Updated renders in each viewer's local timezone, with a relative "Next Refresh" countdown, using Discord timestamps.
- 📣 **Mayor change notifications** — announced once per mayor across all configured servers (no duplicates, even across restarts).
- 🛠️ **One-step setup** — `/setup` creates and manages every board in place; `/unsetup` removes them.
- 🔁 **Self-healing boards** — deleted board messages are recreated automatically on the next hourly refresh.
- 🧹 **Stale-board cleanup** — a board whose update channel is permanently gone is removed from config after 3 consecutive permanent failures, with a single cleanup log instead of logging forever; transient errors never touch the counter, and a board that recovers resets it (with a one-time recovery log).
- 🧹 **Clean lifecycle** — configuration is removed when the bot leaves a server.
- 👥 **Multi-server support** — independent boards and settings per server.
- 💾 **Persistent storage** — atomic, crash-safe writes with automatic legacy-config migration and a rolling `config.backup.json` before every write.
- 🩺 **Owner health / stats / version** — `/owner health` (overall Green/Yellow/Red level with per-subsystem status), `/owner stats` (guild/board/refresh metrics), and `/owner version` (environment details) — owner-only, never visible in public servers.
- 📢 **Announcements** — `/owner announce` broadcasts to every server's announcement channel via an interactive Confirm/Cancel preview, with a full delivery summary; past announcements can be listed, resent, or deleted (`/owner announcement`).
- 🚦 **Slow-refresh detection** — any refresh over 10s logs one warning to the log channel with duration, average, guild count, and timestamp.
- ✅ **Per-variable startup validation** — every environment variable is checked at launch (✅/⚠ per variable); optional gaps log a warning without blocking startup.

## Screenshots

> Coming soon — Mayor Board and Election Board embeds will be shown here once the public beta is live.

## Installation

Requires **Python 3.10+**.

```bash
# Clone the repository
git clone https://github.com/MRNK1/OathWatch.git
cd OathWatch

# Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# (Development only) install tooling and test dependencies
pip install -r requirements-dev.txt
```

## Configuration

1. Copy `.env.example` to `.env` and fill in the required values:

   ```bash
   cp .env.example .env
   ```

2. Set your **Discord bot token**, **Hypixel API key**, and the **owner Discord IDs** (see [Environment variables](#environment-variables)).

3. Start the bot:

   ```bash
   python bot.py
   ```

   (`python -m oathwatch` works too — both delegate to the same `oathwatch.bot.main`.)

4. Invite the bot to your server (scopes: `bot` + `applications.commands`; permissions: Send Messages, Embed Links, Read Message History) and run `/setup`.

The `data/` directory (config and world state) is created automatically on first run. **Back it up** — it holds your guild configurations and the last-known world state.

## Environment variables

| Variable                  | Required | Description                                                                                  |
| ------------------------- | -------- | -------------------------------------------------------------------------------------------- |
| `DISCORD_TOKEN`           | ✅       | Discord bot token from [Discord Developer Portal](https://discord.com/developers).           |
| `HYPIXEL_API_KEY`         | ✅       | Hypixel API key from [developer.hypixel.net](https://developer.hypixel.net) (`/api` in-game). |
| `OWNER_USER_ID`           | ✅       | Owner's Discord user ID — who may run `/owner` commands.                                      |
| `OWNER_GUILD_ID`          | ✅       | Owner guild ID — the only guild where `/owner` commands register.                             |
| `BOT_STATUS_CHANNEL_ID`   | —        | Status channel: 🟢/🔄/🔁 startup + reconnect markers and 🔴 shutdown only.                   |
| `BOT_LOG_CHANNEL_ID`      | —        | Log channel: one operational summary per refresh cycle, setup/config changes, version info.   |
| `BOT_ERROR_CHANNEL_ID`    | —        | Error channel: failures with tracebacks in code blocks.                                       |

Every variable is validated at startup with a per-variable ✅/⚠ report. The four required variables must be present or the bot refuses to launch with a clear message. The three channel IDs are optional — leave them blank (or unset) to disable that channel; a missing optional value logs a warning but does not block startup.

## Commands

All commands are slash commands. Administrator commands are marked 🔒.

| Command       | Description                                             | Admin |
| ------------- | ------------------------------------------------------- | ----- |
| `/setup`      | Configure this server in one step (choose boards).      | 🔒    |
| `/unsetup`    | Remove this server's configuration and boards.          | 🔒    |
| `/board`      | Show the Mayor Board in the current channel.            |       |
| `/checkmayor` | Fetch and apply the latest world state immediately.     |       |
| `/status`     | Check bot status and latency.                           |       |
| `/testchannel`| Send a test message to the configured channel.          | 🔒    |
| `/setchannel` | Set this server's **announcement channel** (where owner announcements are posted). | 🔒 |

Owner-only commands are registered only inside the owner guild and never appear in any public server. Only the owner user may run them; every reply is ephemeral.

- **`/owner botstatus`**, **`/owner refresh`**, **`/owner shutdown`**
- **`/owner health`**, **`/owner stats`**, **`/owner version`**
- **`/owner announce`** (with a Confirm/Cancel preview) and **`/owner announcement history|resend|delete|clear`**
- **`/owner whitelist`** (`enable` / `disable` / `status` / `add` / `remove` / `list`) and **`/owner blacklist`** (`add` with reason / `remove` / `list`)

Guild whitelist/blacklist control which servers may use the bot; a blocked guild is disabled (commands ignored) but never left.

## Architecture overview

OathWatch is deliberately modular so new boards and features plug in without rewriting core logic. All application code lives in the `oathwatch/` package; the top-level `bot.py` is a thin launcher that preserves the `python bot.py` entry point.

- **`bot.py`** — launcher. Keeps the documented `python bot.py` entry point working; delegates to `oathwatch.bot.main`.
- **`oathwatch/bot.py`** — the bot itself. Owns the Discord client, slash commands, the hourly update loop, startup validation, and lifecycle cleanup. Blocking API calls are offloaded off the event loop with `asyncio.to_thread`.
- **`oathwatch/hypixel_api.py`** — all Hypixel API requests, with retries and exponential backoff. Sync by design; callers run it in a worker thread.
- **`oathwatch/board_registry.py`** — the board-type registry. Registering a board (key, name, embed builder) makes it usable by `/setup` and the hourly loop — setup logic never changes.
- **`oathwatch/board_health.py`** — stale-board health. Tracks a consecutive permanent-failure counter per (guild, board); after 3 consecutive permanent failures the stale reference is removed from config with a single cleanup log, and a board that recovers resets its counter (one-time recovery log). Transient failures never touch the counter.
- **`oathwatch/board.py`** / **`oathwatch/election.py`** — Mayor and Election board renderers. They register themselves with the registry.
- **`oathwatch/formatting.py`** — shared embed helpers (Minecraft §-code stripping, field-limit truncation, perk rendering, and Discord timestamps for Last Updated / Next Refresh) used by every board.
- **`oathwatch/setup.py`** — board-agnostic setup orchestration: permission checks, board placement (create / update / recreate), self-healing refresh, and `/unsetup`.
- **`oathwatch/world_state.py`** — runtime world-state cache, API response validation, and normalization of persisted/legacy state.
- **`oathwatch/storage.py`** — guild configuration with automatic legacy-schema migration.
- **`oathwatch/storage_utils.py`** / **`oathwatch/world_storage.py`** — atomic JSON persistence and world-state persistence.
- **`oathwatch/access_control.py`** — guild whitelist/blacklist. `is_guild_allowed` is the single source of truth for commands, boards, refresh, and notifications; persisted independently in `data/access_control.json`.
- **`oathwatch/owner.py`** / **`oathwatch/reporting.py`** / **`oathwatch/refresh.py`** — owner-only administration (`/owner botstatus|refresh|shutdown|health|stats|version|announce`, whitelist/blacklist, announcement history), status/log/error channel reporting, and the shared refresh pipeline.
- **`oathwatch/runtime.py`** — central runtime metrics (start time, refresh counters/averages, versions, platform, memory) shared by health/stats/version and slow-refresh detection.
- **`oathwatch/announcements.py`** — announcement broadcasting (`send_announcement`), history persistence (`data/announcement_history.json`), and the Confirm/Cancel preview views.

## Project structure

```
OathWatch/
├── bot.py                # Launcher → oathwatch.bot.main (python bot.py)
├── oathwatch/            # Application package
│   ├── __init__.py       # Package metadata; registers boards on import
│   ├── __main__.py       # python -m oathwatch entry point
│   ├── bot.py            # Discord client, commands, hourly loop, lifecycle
│   ├── board.py          # Mayor Board renderer
│   ├── election.py       # Election Board renderer
│   ├── board_registry.py # Board-type registry
│   ├── board_health.py   # Stale-board failure counter + cleanup/recovery logs
│   ├── formatting.py     # Shared embed-formatting helpers
│   ├── setup.py          # Board-agnostic setup orchestration
│   ├── world_state.py    # World-state cache, validation, normalization
│   ├── storage.py        # Guild configuration + legacy migration
│   ├── storage_utils.py  # Atomic JSON persistence helpers
│   ├── world_storage.py  # World-state persistence
│   ├── access_control.py # Guild whitelist/blacklist + persistence
│   ├── owner.py          # Owner-only /owner command group
│   ├── reporting.py      # Status/log/error channel reporting
│   ├── refresh.py        # Shared refresh pipeline
│   ├── runtime.py        # Central runtime metrics
│   ├── announcements.py  # Announcements + history + preview views
│   └── hypixel_api.py    # Hypixel API client (retry + backoff)
├── tests/                # Automated test suite (pytest)
├── data/                 # Runtime data (auto-created; git-ignored)
├── requirements.txt      # Runtime dependencies
├── requirements-dev.txt  # Dev/test tooling
├── .env.example          # Environment template
├── pyproject.toml        # Ruff / mypy / pytest configuration
└── .github/workflows/    # CI workflow
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full phase tracker. In short:

- ✅ Phases 1–6: production stability, mayor polish, setup system, election system, release infrastructure, guild access control
- ✅ v1.0.1: election board UI polish — support bars, computed percentages, native time display
- ✅ v1.1.0: owner system & reporting (`/owner botstatus|refresh|shutdown`, status/log/error channels)
- ✅ Stale-board cleanup: deleted-message self-healing preserved; deleted channels auto-clean after 3 consecutive permanent failures
- ✅ Final production polish: `/owner health|stats|version`, `/owner announce` + history, slow-refresh detection, per-variable env validation, config backup, shared embed polish, `/setchannel` as the announcement channel
- ✅ v1.1.1: maintenance release — startup notification fix (fresh / reconnect / restart now distinguished), documentation + changelog polish
- 🔜 v1.2 quality-of-life (`/diagnose`, better setup validation & diagnostics), v1.3 market & Bazaar (30s cache, Bazaar commands, market tools), v1.4 multi-server architecture (provider system, CraftersMC, default game per server), v1.5 verification, v1.6 experimental guilds (community-managed until official APIs), then verified-guild migration / website / historical market data / more servers

## Development setup

```bash
pip install -r requirements-dev.txt
pytest          # run the test suite (isolated; never touches real data/)
ruff check .    # lint
mypy .          # type check
```

The test suite redirects all persistence to a temporary directory, so running it never reads or modifies your real `data/` files.

## Contributing

Contributions are welcome! To keep the codebase healthy:

1. **No duplicated logic** — reuse `oathwatch/formatting.py`, `oathwatch/board_registry.py`, and the setup orchestration instead of copying.
2. **Never break existing features** — the hourly loop, commands, and config schema must stay backward compatible.
3. **Add tests** for anything you change; run the full suite before opening a PR.
4. **Keep commands small** and put logic in modules.

New boards are especially easy: create a module that renders an embed, then call `register_board("key", "Display Name", builder)` — the registry, `/setup`, and the hourly refresh pick it up automatically.

### Adding a board (walkthrough)

1. Create `oathwatch/myboard.py` with a `build_my_board_embed()` returning a `discord.Embed`.
2. Call `register_board("myboard", "My Board", build_my_board_embed)` at the bottom of the module.
3. Import the module in `oathwatch/__init__.py` (alongside `board` and `election`) so it registers whenever the package loads.
4. Add a `/setup` toggle if you want admins to choose it explicitly.

## License

[MIT](LICENSE)

## Credits

- **[Hypixel API](https://developer.hypixel.net)** — SkyBlock world-state data.
- **[discord.py](https://github.com/Rapptz/discord.py)** — the Discord library powering the bot.
