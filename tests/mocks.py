"""Mock Discord objects for testing board/setup flows without a network.

The mocks mirror enough of the discord.py API that the bot's logic can be
exercised end to end: channels hold messages, messages can be edited or
deleted, and missing messages raise the same discord.NotFound the real
library would.
"""
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

    async def send(self, embed=None, content=None):
        MockChannel._counter += 1
        msg = MockMessage(MockChannel._counter, channel=self)
        msg.last_embed = embed
        self.messages[msg.id] = msg
        return msg

    async def fetch_message(self, msg_id):
        msg = self.messages.get(msg_id)
        if msg is None:
            raise discord.NotFound(MockResponse(404),
                                   f"Message {msg_id} not found")
        return msg


class MockBot:
    def __init__(self, channels=None):
        self.channels = channels or {}

    def get_channel(self, cid):
        return self.channels.get(cid)
