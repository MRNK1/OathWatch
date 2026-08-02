"""OathWatch — a Discord bot tracking Hypixel SkyBlock world state."""

__version__ = "1.1.1"

# Importing the package registers every board type (board_registry). Boards
# are imported here — not by setup — so registration is guaranteed as soon as
# the package is imported, however it is reached (bot, tests, python -m).
from . import board, election  # noqa: F401  (registers boards on import)
