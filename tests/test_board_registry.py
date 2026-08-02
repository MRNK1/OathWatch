"""Board registry tests."""
import discord
import pytest

from oathwatch.board_registry import (
    UnknownBoardError,
    all_boards,
    build_board_embed,
    get_board,
    register_board,
)


@pytest.mark.usefixtures("reset_world_state")
class TestRegistry:
    def test_known_boards_registered(self):
        keys = {b.key for b in all_boards()}
        assert {"mayor", "election"} <= keys

    def test_get_board_metadata(self):
        assert get_board("mayor").name == "Mayor Board"
        assert get_board("election").name == "Election Board"

    def test_boards_build_real_embeds(self):
        assert isinstance(get_board("mayor").build_embed(), discord.Embed)
        assert isinstance(get_board("election").build_embed(), discord.Embed)
        assert isinstance(build_board_embed("mayor"), discord.Embed)

    def test_unknown_board_raises(self):
        with pytest.raises(UnknownBoardError):
            get_board("does-not-exist")

    def test_register_new_board(self):
        def builder():
            return discord.Embed(title="Test Board")

        register_board("testboard", "Test Board", builder)
        assert get_board("testboard").name == "Test Board"
