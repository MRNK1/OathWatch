import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import os
from storage import load_config, save_config
from world_state import WORLD_STATE
from hypixel_api import get_election_data
from datetime import datetime
from world_storage import load_world_state, save_world_state
from discord.ext import tasks

saved_state = load_world_state()

if saved_state:
    WORLD_STATE.update(saved_state)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

def create_board_embed():

    embed = discord.Embed(
        title="📜 OathWatch",
        description="Current SkyBlock World Status",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="Mayor",
        value=WORLD_STATE["mayor"],
        inline=False
    )

    embed.add_field(
        name="Minister",
        value=WORLD_STATE["minister"],
        inline=False
    )

    perk_text = ""

    for perk in WORLD_STATE["perks"]:
        perk_text += (
            f"**{perk['name']}**\n"
            f"{perk['description']}\n\n"
        )

    embed.add_field(
        name="Perks",
        value=perk_text,
        inline=False
    )

    embed.set_footer(
        text=f"Last Updated: {WORLD_STATE['last_updated']}"
    )

    return embed

@bot.event
async def on_ready():
    print(f"{bot.user} is online!")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)

    if not mayor_update_loop.is_running():
        mayor_update_loop.start()

@bot.tree.command(name="status", description="Check bot status")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"🏰 OathWatch Online\nLatency: {round(bot.latency * 1000)}ms"
    )

@bot.tree.command(name="setchannel", description="Set update channel")
async def setchannel(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):
    data = load_config()

    guild_id = str(interaction.guild.id)

    if "guilds" not in data:
        data["guilds"] = {}

    data["guilds"][guild_id] = {
        "channel_id": channel.id
    }

    save_config(data)

    await interaction.response.send_message(
        f"✅ Update channel set to {channel.mention}"
    )

@bot.tree.command(name="testchannel", description="Send a test message")
async def testchannel(interaction: discord.Interaction):
    data = load_config()

    guild_id = str(interaction.guild.id)

    if guild_id not in data["guilds"]:
        await interaction.response.send_message(
            "❌ No channel configured."
        )
        return

    channel_id = data["guilds"][guild_id]["channel_id"]
    channel = bot.get_channel(channel_id)

    if channel is None:
        await interaction.response.send_message(
            "❌ Channel not found."
        )
        return

    await channel.send("📜 OathWatch test message.")

    await interaction.response.send_message(
        "✅ Test message sent."
    )

@bot.tree.command(name="board", description="Show OathWatch board")
async def board(interaction: discord.Interaction):

    embed = create_board_embed()

    await interaction.response.send_message(embed=embed)

    message = await interaction.original_response()

    data = load_config()

    guild_id = str(interaction.guild.id)

    data["guilds"][guild_id]["board_message_id"] = message.id

    save_config(data)

@bot.tree.command(name="checkmayor", description="Update mayor data")
async def checkmayor(interaction: discord.Interaction):

    data = get_election_data()

    print(data)

    WORLD_STATE["mayor"] = data["mayor"]["name"]

    WORLD_STATE["perks"] = data["mayor"]["perks"]

    WORLD_STATE["last_updated"] = datetime.fromtimestamp(
    data["lastUpdated"] / 1000
).strftime("%Y-%m-%d %H:%M:%S") 
    save_world_state(WORLD_STATE)

    await interaction.response.send_message(
        "✅ World state updated."
    )

@tasks.loop(hours=1)
async def mayor_update_loop():

    data = get_election_data()

    old_mayor = WORLD_STATE["mayor"]

    WORLD_STATE["mayor"] = data["mayor"]["name"]
    WORLD_STATE["perks"] = data["mayor"]["perks"]

    WORLD_STATE["last_updated"] = datetime.fromtimestamp(
        data["lastUpdated"] / 1000
    ).strftime("%Y-%m-%d %H:%M:%S")

    save_world_state(WORLD_STATE)

    if old_mayor != WORLD_STATE["mayor"]:

        config = load_config()

        for guild_id, guild_data in config["guilds"].items():

            channel = bot.get_channel(
                guild_data["channel_id"]
            )

            if not channel:
                continue

            board_message_id = guild_data.get(
                "board_message_id"
            )

            if not board_message_id:
                continue

            try:
                message = await channel.fetch_message(
                    board_message_id
                )

                await message.edit(
                    embed=create_board_embed()
                )

            except Exception as e:
                print(
                    f"Failed to update board: {e}"
                )

        print(
            f"Mayor changed: {old_mayor} -> {WORLD_STATE['mayor']}"
        )

        for guild_id, guild_data in config["guilds"].items():

            channel = bot.get_channel(
                guild_data["channel_id"]
            )

            if not channel:
              print(
                 f"Channel not found for guild {guild_id}"
    )
            continue

        await channel.send(
                  f"📜 Mayor changed!\n"
                 f"{old_mayor} ➜ {WORLD_STATE['mayor']}"
)

bot.run(TOKEN)