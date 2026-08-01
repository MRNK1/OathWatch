# Changelog

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