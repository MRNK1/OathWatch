# Changelog

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