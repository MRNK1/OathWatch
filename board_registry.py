"""Board-type registry for OathWatch.

A board is anything that renders world data into a Discord embed. Registering
a new board type is the only step needed to make it usable by the setup system
and the hourly update loop — the core setup logic never changes.
"""
from collections.abc import Callable
from dataclasses import dataclass

import discord


class UnknownBoardError(KeyError):
    """Raised when a board key is not registered."""


@dataclass(frozen=True)
class BoardType:
    """A registered board: its key, display name, and embed builder."""
    key: str
    name: str
    build_embed: Callable[[], discord.Embed]


_REGISTRY: dict = {}


def register_board(key: str, name: str, build_embed: Callable[[], discord.Embed]) -> None:
    """Register a board type under a unique key. Re-registering replaces."""
    _REGISTRY[key] = BoardType(key=key, name=name, build_embed=build_embed)


def get_board(key: str) -> BoardType:
    """Return a registered board type, or raise UnknownBoardError."""
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownBoardError(key) from None


def all_boards() -> list:
    """Return the registered boards in insertion order."""
    return list(_REGISTRY.values())


def build_board_embed(key: str) -> discord.Embed:
    """Build the embed for a registered board key."""
    return get_board(key).build_embed()
