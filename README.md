# OathWatch

OathWatch is a production-quality Discord bot that tracks Hypixel SkyBlock world state. It posts live **Mayor** and **Election** boards to your server, announces mayor changes, and refreshes every hour — all configured with a single `/setup` command.

> 🚧 **Public beta** — the bot is feature-complete for its current boards. See the [Roadmap](#roadmap) for what is planned next.

## Features

- 🏰 **Mayor Board** — current mayor, minister, and their perks, updated hourly.
- 🗳️ **Election Board** — election status, every candidate sorted by vote percentage, vote counts, and candidate perks.
- 📣 **Mayor change notifications** — announced once per mayor across all configured servers (no duplicates, even across restarts).
- 🛠️ **One-step setup** — `/setup` creates and manages every board in place; `/unsetup` removes them.
- 🔁 **Self-healing boards** — deleted board messages are recreated automatically on the next hourly refresh.
- 🧹 **Clean lifecycle** — configuration is removed when the bot leaves a server.
- 👥 **Multi-server support** — independent boards and settings per server.
- 💾 **Persistent storage** — atomic, crash-safe writes with automatic legacy-config migration.

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

1. Copy `.env.example` to `.env` and fill in both values:

   ```bash
   cp .env.example .env
   ```

2. Set your **Discord bot token** and **Hypixel API key** (see [Environment variables](#environment-variables)).

3. Start the bot:

   ```bash
   python bot.py
   ```

4. Invite the bot to your server (scopes: `bot` + `applications.commands`; permissions: Send Messages, Embed Links, Read Message History) and run `/setup`.

The `data/` directory (config and world state) is created automatically on first run. **Back it up** — it holds your guild configurations and the last-known world state.

## Environment variables

| Variable           | Required | Description                                                                                     |
| ------------------ | -------- | ----------------------------------------------------------------------------------------------- |
| `DISCORD_TOKEN`    | ✅       | Discord bot token from [Discord Developer Portal](https://discord.com/developers).              |
| `HYPIXEL_API_KEY`  | ✅       | Hypixel API key from [developer.hypixel.net](https://developer.hypixel.net) (`/api` in-game).    |

Both are validated at startup; the bot refuses to launch with a clear message if either is missing.

## Commands

All commands are slash commands. Administrator commands are marked 🔒.

| Command      | Description                                             | Admin |
| ------------ | ------------------------------------------------------- | ----- |
| `/setup`     | Configure this server in one step (choose boards).      | 🔒    |
| `/unsetup`   | Remove this server's configuration and boards.          | 🔒    |
| `/board`     | Show the Mayor Board in the current channel.            |       |
| `/checkmayor`| Fetch and apply the latest world state immediately.     |       |
| `/status`    | Check bot status and latency.                           |       |
| `/testchannel`| Send a test message to the configured channel.          | 🔒    |
| `/setchannel`| Set the update channel.                                 | 🔒    |

## Architecture overview

OathWatch is deliberately modular so new boards and features plug in without rewriting core logic.

- **`bot.py`** — entry point. Owns the Discord client, slash commands, the hourly update loop, startup validation, and lifecycle cleanup. Blocking API calls are offloaded off the event loop with `asyncio.to_thread`.
- **`hypixel_api.py`** — all Hypixel API requests, with retries and exponential backoff. Sync by design; callers run it in a worker thread.
- **`board_registry.py`** — the board-type registry. Registering a board (key, name, embed builder) makes it usable by `/setup` and the hourly loop — setup logic never changes.
- **`board.py`** / **`election.py`** — Mayor and Election board renderers. They register themselves with the registry.
- **`formatting.py`** — shared embed helpers (Minecraft §-code stripping, field-limit truncation, perk rendering) used by every board.
- **`setup.py`** — board-agnostic setup orchestration: permission checks, board placement (create / update / recreate), self-healing refresh, and `/unsetup`.
- **`world_state.py`** — runtime world-state cache, API response validation, and normalization of persisted/legacy state.
- **`storage.py`** — guild configuration with automatic legacy-schema migration.
- **`storage_utils.py`** / **`world_storage.py`** — atomic JSON persistence and world-state persistence.

## Project structure

```
OathWatch/
├── bot.py                # Entry point, commands, hourly loop, lifecycle
├── board.py              # Mayor Board renderer
├── election.py           # Election Board renderer
├── board_registry.py     # Board-type registry
├── formatting.py         # Shared embed-formatting helpers
├── setup.py              # Board-agnostic setup orchestration
├── world_state.py        # World-state cache, validation, normalization
├── storage.py            # Guild configuration + legacy migration
├── storage_utils.py      # Atomic JSON persistence helpers
├── world_storage.py      # World-state persistence
├── hypixel_api.py        # Hypixel API client (retry + backoff)
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

- ✅ Phases 1–4: production stability, mayor polish, setup system, election system
- 🔜 Public API, Website, Bazaar board, Release Candidate, v1.0

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

1. **No duplicated logic** — reuse `formatting.py`, `board_registry.py`, and the setup orchestration instead of copying.
2. **Never break existing features** — the hourly loop, commands, and config schema must stay backward compatible.
3. **Add tests** for anything you change; run the full suite before opening a PR.
4. **Keep commands small** and put logic in modules.

New boards are especially easy: create a module that renders an embed, then call `register_board("key", "Display Name", builder)` — the registry, `/setup`, and the hourly refresh pick it up automatically.

### Adding a board (walkthrough)

1. Create `myboard.py` with a `build_my_board_embed()` returning a `discord.Embed`.
2. Call `register_board("myboard", "My Board", build_my_board_embed)` at the bottom of the module.
3. Import the module in `setup.py` (alongside `board` and `election`) so it registers on startup.
4. Add a `/setup` toggle if you want admins to choose it explicitly.

## License

[MIT](LICENSE)

## Credits

- **[Hypixel API](https://developer.hypixel.net)** — SkyBlock world-state data.
- **[discord.py](https://github.com/Rapptz/discord.py)** — the Discord library powering the bot.
