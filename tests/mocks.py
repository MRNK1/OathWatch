"""Mock Discord objects for testing board/setup/owner flows without a network.

The mocks mirror enough of the discord.py API that the bot's logic can be
exercised end to end: channels hold messages, messages can be edited or
deleted, missing messages raise the same discord.NotFound the real library
would, and interactions record their (ephemeral) replies for owner-command
and error-reporting tests.
"""
from types import SimpleNamespace

import discord


class MockResponse:
    """Minimal HTTP response used to construct discord.NotFound etc."""

    def __init__(self, status):
        self.status = status
        self.reason = {404: "Not Found", 403: "Forbidden",
                       500: "Internal Server Error"}.get(status, "")


class MockMessage:
    def __init__(self, msg_id, channel=None):
        self.id = msg_id
        self.channel = channel
        self.edits = []
        self.deleted = False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)

    async def delete(self):
        self.deleted = True
        if self.channel is not None:
            self.channel.messages.pop(self.id, None)


class MockPerms:
    def __init__(self, send_messages=True, embed_links=True,
                 read_message_history=True):
        self.send_messages = send_messages
        self.embed_links = embed_links
        self.read_message_history = read_message_history


class MockGuild:
    def __init__(self, gid, name, me, channels=None):
        self.id = gid
        self.name = name
        self.me = me
        self.channels = channels or {}

    def get_channel(self, cid):
        return self.channels.get(cid)


class MockChannel(discord.TextChannel):
    # Subclasses discord.TextChannel so production isinstance narrowing
    # (e.g. "is this a text channel?") behaves exactly as with a real channel.
    # The base __init__ is never called; only the attributes the bot uses are
    # provided. `mention` is left to the base property, which derives it from
    # `id`, and a custom __repr__ avoids the base repr (which needs _state).
    _counter = 5000  # Global counter mirrors Discord's globally-unique ids.

    def __init__(self, cid, guild, perms=None):
        self.id = cid
        self.guild = guild
        self.name = "boards"
        self.perms = perms or MockPerms()
        self.messages = {}

    def __repr__(self):
        return f"<MockChannel id={self.id} name={self.name!r}>"

    def permissions_for(self, member):
        return self.perms

    async def send(self, content=None, embed=None, **kwargs):
        # Signature mirrors discord.py's Messageable.send (content first), so
        # positional content and keyword embed calls both behave correctly.
        MockChannel._counter += 1
        msg = MockMessage(MockChannel._counter, channel=self)
        msg.last_embed = embed
        msg.content = content
        self.messages[msg.id] = msg
        return msg

    async def fetch_message(self, msg_id):
        msg = self.messages.get(msg_id)
        if msg is None:
            raise discord.NotFound(MockResponse(404),
                                   f"Message {msg_id} not found")
        return msg


class MockBot:
    def __init__(self, channels=None, guilds=None):
        self.channels = channels or {}
        self.guilds = guilds or []
        self._guild_map = {g.id: g for g in self.guilds}
        self.latency = 0.0
        self.closed = False
        self._ready = True

    def get_channel(self, cid):
        return self.channels.get(cid)

    def get_guild(self, gid):
        return self._guild_map.get(gid)

    def is_ready(self):
        return self._ready

    async def close(self):
        self.closed = True


class MockInteractionResponse:
    """Records replies/followups/edits so tests can assert on them."""

    def __init__(self, interaction):
        self._interaction = interaction

    def is_done(self):
        return self._interaction._done

    async def send_message(self, content=None, embed=None, ephemeral=False,
                           view=None):
        self._interaction._done = True
        self._interaction.replies.append({
            "content": content, "embed": embed, "ephemeral": ephemeral,
            "view": view,
        })

    async def edit_message(self, content=None, embed=None, view=None):
        # Mirrors InteractionResponse.edit_message, used by view callbacks to
        # replace the preview message after Confirm/Cancel.
        self._interaction.edits.append({
            "content": content, "embed": embed, "view": view,
        })

    async def defer(self, ephemeral=False):
        self._interaction._done = True
        self._interaction.deferred = ephemeral


class MockFollowup:
    """Records followup messages (used after an ephemeral defer)."""

    def __init__(self, interaction):
        self._interaction = interaction

    async def send(self, content=None, ephemeral=False):
        self._interaction.followups.append({
            "content": content, "ephemeral": ephemeral,
        })


class MockInteraction:
    """Minimal discord.Interaction stand-in for owner-command tests."""

    def __init__(self, user_id, guild_id, client=None, guild=None,
                 interaction_type=None):
        self.user = SimpleNamespace(id=user_id)
        self.guild_id = guild_id
        self.client = client or MockBot()
        self.guild = guild or MockGuild(guild_id, "Owner Guild", object())
        self.channel_id = None
        self.type = interaction_type or discord.InteractionType.application_command
        self._done = False
        self.deferred = False
        self.replies = []
        self.followups = []
        self.edits = []
        # The message an ephemeral preview was sent on; view callbacks edit it
        # in place via response.edit_message.
        self.message = MockMessage(9000)
        self.response = MockInteractionResponse(self)
        self.followup = MockFollowup(self)
