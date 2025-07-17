# ------------------- Imports and Setup -------------------
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands, Interaction, ButtonStyle
from discord.ui import View, Button, Select
import asyncio
import aiosqlite
from database import initialize, get_player, update_stats, ensure_player_exists, save_match, remove_match, get_active_matches
from utils import get_rank_info  # assume you have a utils.py for rank images/labels

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
ALLOWED_MATCH_CHANNELS = ["1v1", "1v1test", "2v2"]
matches = {}

# ------------------- Rank Emojis -------------------
RANK_EMOJIS = {
    "Master": "<:Rank_Master:1395022666611691610>",
    "Diamond": "<:Rank_Diamond:1395022649700384868>",
    "Platinum": "<:Rank_Plat:1395022636903563365>",
    "Gold": "<:Rank_Gold:1395022614937997343>",
    "Silver": "<:Rank_Silver:1395022579827343400>",
    "Bronze": "<:Rank_Bronze:1395022552346136627>",
}

# ------------------- Rank Info Function -------------------
def get_rank_info(elo: int) -> tuple[str, str, str]:
    if elo < 800:
        return "Bronze", RANK_EMOJIS["Bronze"], "https://i.imgur.com/bTg35hk.png"
    elif elo < 1000:
        return "Silver", RANK_EMOJIS["Silver"], "https://i.imgur.com/MKggqhq.png"
    elif elo < 1200:
        return "Gold", RANK_EMOJIS["Gold"], "https://i.imgur.com/NEiM1M6.png"
    elif elo < 1400:
        return "Platinum", RANK_EMOJIS["Platinum"], "https://i.imgur.com/dOCTxJB.png"
    elif elo < 1600:
        return "Diamond", RANK_EMOJIS["Diamond"], "https://i.imgur.com/4yfiGqq.png"
    else:
        return "Master", RANK_EMOJIS["Master"], "https://i.imgur.com/EwMudQL.png"


# ------------------- MatchView -------------------
class MatchView(View):
    def __init__(self, host_id, game_mode):
        super().__init__(timeout=None)
        self.host_id = host_id
        self.players = [host_id]
        self.teams = {"Team A": [host_id], "Team B": []} if game_mode == "2v2" else {}
        self.mode = game_mode
        self.max_players = 4 if game_mode == "2v2" else 2
        self.match_id = host_id
        self.message = None
        self.timer_task = None
        self.timer_remaining = 25
        self.timer_active = False

    async def start_match_timer(self):
        self.timer_active = True
        for remaining in range(25, 0, -1):
            self.timer_remaining = remaining
            if self.message:
                await self.message.edit(content=self.format_message() + f"\n\n⏱️ Match starts in **{remaining}** seconds...")
            await asyncio.sleep(1)
        if self.message and len(self.players) == self.max_players:
            await self.message.edit(content=self.format_message() + "\n\n✅ Match has started! Report win to end the match.")
        self.timer_active = False

    def maybe_start_timer(self):
        if len(self.players) == self.max_players and not self.timer_active:
            self.timer_task = asyncio.create_task(self.start_match_timer())

    def format_message(self):
        if self.mode == "2v2":
            a = ', '.join(f"<@{uid}>" for uid in self.teams["Team A"])
            b = ', '.join(f"<@{uid}>" for uid in self.teams["Team B"])
            return f"2v2 Match hosted by <@{self.host_id}>\nTeam A: {a}\nTeam B: {b}"
        else:
            return f"1v1 Match hosted by <@{self.host_id}>\nPlayers: {', '.join(f'<@{p}>' for p in self.players)}"

    @discord.ui.button(label="Join Match", style=ButtonStyle.primary)
    async def join_button(self, interaction: Interaction, button: Button):
        if interaction.user.id in self.players:
            await interaction.response.send_message("You've already joined!", ephemeral=True)
            return
        if self.mode == "2v2":
            await interaction.response.send_message("Choose a team:", view=TeamSelectView(self, interaction.user.id), ephemeral=True)
        else:
            self.players.append(interaction.user.id)
            await interaction.response.edit_message(content=self.format_message(), view=self)
            self.maybe_start_timer()

    @discord.ui.button(label="Leave Match", style=ButtonStyle.secondary)
    async def leave_button(self, interaction: Interaction, button: Button):
        uid = interaction.user.id
        if uid in self.players:
            self.players.remove(uid)
        for team in self.teams.values():
            if uid in team:
                team.remove(uid)
        await interaction.response.edit_message(content=self.format_message(), view=self)

    @discord.ui.button(label="Report Win", style=ButtonStyle.success)
    async def report_button(self, interaction: Interaction, button: Button):
        if self.mode == "2v2":
            await interaction.response.send_message("Select winning team:", view=TeamWinSelectView(self), ephemeral=True)
        else:
            await interaction.response.send_message("Select the winner:", view=WinnerSelectView(self, interaction), ephemeral=True)

# ------------------- Team Selection View -------------------
class TeamSelectView(View):
    def __init__(self, match_view, user_id):
        super().__init__(timeout=30)
        self.match_view = match_view
        self.user_id = user_id
        options = [
            discord.SelectOption(label="Team A", value="Team A"),
            discord.SelectOption(label="Team B", value="Team B")
        ]
        self.select = Select(placeholder="Choose your team", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        team = self.select.values[0]
        if self.user_id in self.match_view.players:
            await interaction.response.send_message("You're already in the match!", ephemeral=True)
            return
        if len(self.match_view.teams[team]) >= 2:
            await interaction.response.send_message(f"{team} is already full!", ephemeral=True)
            return
        self.match_view.teams[team].append(self.user_id)
        self.match_view.players.append(self.user_id)
        await interaction.message.delete()
        await self.match_view.message.edit(content=self.match_view.format_message(), view=self.match_view)
        self.match_view.maybe_start_timer()

# ------------------- Team Win Select View -------------------
class TeamWinSelectView(View):
    def __init__(self, match_view):
        super().__init__(timeout=30)
        self.match_view = match_view
        options = [
            discord.SelectOption(label="Team A", value="Team A"),
            discord.SelectOption(label="Team B", value="Team B")
        ]
        self.select = Select(placeholder="Select the winning team", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        if self.match_view.timer_active:
            await interaction.response.send_message("⏳ Please wait for the match to start before reporting a win.", ephemeral=True)
            return
        if len(self.match_view.players) < self.match_view.max_players:
            await interaction.response.send_message("⚠️ The match is not full. Please wait until all players join.", ephemeral=True)
            return
        winning_team = self.select.values[0]
        losing_team = "Team B" if winning_team == "Team A" else "Team A"
        for winner in self.match_view.teams[winning_team]:
            for loser in self.match_view.teams[losing_team]:
                await update_stats(winner, loser, "2v2")
        try:
            await interaction.message.delete()  # Dropdown
        except (discord.Forbidden, discord.NotFound):
            pass
        if self.match_view.message:
            try:
                await interaction.response.edit_message(
                    content="✅ Result submitted! Thank you.",
                    view=None
                )
            except (discord.Forbidden, discord.NotFound):
                pass
        if self.match_view.match_id in matches:
            del matches[self.match_view.match_id]
        await remove_match(self.match_view.match_id)

# ------------------- Winner Select View -------------------
class WinnerSelectView(View):
    def __init__(self, match_view, interaction):
        super().__init__(timeout=30)
        self.match_view = match_view
        options = []
        for uid in match_view.players:
            try:
                user_obj = interaction.client.get_user(uid)
                display = user_obj.display_name or user_obj.name or f"User {uid}"
            except Exception:
                display = f"User {uid}"
            options.append(discord.SelectOption(label=display, value=str(uid)))
        self.select = Select(
            placeholder="Select the winner",
            options=options,
            min_values=1, max_values=1
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        if self.match_view.timer_active:
            await interaction.response.send_message("⏳ The match hasn't started yet. Please wait for the countdown to finish before reporting a win.", ephemeral=True)
            return
        if len(self.match_view.players) < 2:
            await interaction.response.send_message("⚠️ A match must have at least two players to report a result.", ephemeral=True)
            return
        winner_id = int(self.select.values[0])
        loser_id = [uid for uid in self.match_view.players if uid != winner_id][0]
        await update_stats(winner_id, loser_id, "1v1")
        await interaction.response.edit_message(
            content="✅ Result submitted! Thank you.",
            view=None
        )
        await remove_match(self.match_view.match_id)
        if self.match_view.match_id in matches:
            del matches[self.match_view.match_id]
        if self.match_view.message:
            try:
                await self.match_view.message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass

# ------------------- Bot Ready Event -------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await initialize()

    active_matches = await get_active_matches()
    for match_data in active_matches:
        match_id = match_data["match_id"]
        host_id = match_data["host_id"]
        mode = match_data["mode"]
        players = match_data["players"]
        teams = match_data["teams"]
        message_id = match_data["message_id"]

        view = MatchView(host_id, mode)
        view.players = players
        view.teams = teams if teams else {}
        view.match_id = match_id

        # Attempt to find the message to reattach the view
        message_found = False
        for guild in bot.guilds:
            for channel in guild.text_channels:
                try:
                    message = await channel.fetch_message(message_id)
                    view.message = message
                    bot.add_view(view, message_id=message_id)
                    matches[match_id] = view
                    message_found = True
                    break
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue
            if message_found:
                break

    try:
        synced = await bot.tree.sync()
        print(f"🔄 Synced {len(synced)} commands.")
    except Exception as e:
        print("Sync error:", e)

# ------------------- Slash Commands -------------------
@bot.tree.command(name="start_match", description="Start a ranked match")
@app_commands.describe(mode="Choose between 1v1 or 2v2")
@app_commands.choices(mode=[
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
])
async def start_match(interaction: Interaction, mode: app_commands.Choice[str]):
    channel = interaction.channel.name
    if channel not in ALLOWED_MATCH_CHANNELS:
        await interaction.response.send_message("You can only start matches in #1v1 or #2v2 channels.", ephemeral=True)
        return
    host_id = interaction.user.id
    if any(host_id in match.players for match in matches.values()):
        await interaction.response.send_message("You already have a match running!", ephemeral=True)
        return
    view = MatchView(host_id, mode.value)
    matches[host_id] = view

    await interaction.response.send_message(view.format_message(), view=view)
    sent = await interaction.original_response()
    view.message = sent
    matches[host_id] = view

    await save_match(
        match_id=host_id,
        mode=mode.value,
        host_id=host_id,
        players=view.players,
        teams=view.teams,
        status="active",
        message_id=sent.id
    )

# ------------------- Stats Command -------------------
@bot.tree.command(name="stats", description="View your ELO, wins, and losses")
@app_commands.describe(mode="Choose a game mode")
@app_commands.choices(mode=[
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
])
async def stats(interaction: Interaction, mode: app_commands.Choice[str]):
    user_id = interaction.user.id
    wins, losses, elo = await get_player(user_id, mode.value)
    rank, rank_emoji, image_url = get_rank_info(elo)

    description = (
        f"{rank_emoji} **{rank}**\n"
        f"**ELO:** {elo}\n"
        f"**Wins:** {wins} | **Losses:** {losses}"
    )

    embed = discord.Embed(
        title=f"Stats for {interaction.user.display_name}",
        description=description,
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=image_url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="View the top ranked players")
@app_commands.describe(mode="Choose a game mode")
@app_commands.choices(mode=[
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
])
async def leaderboard(interaction: Interaction, mode: app_commands.Choice[str]):
    mode_value = mode.value
    async with aiosqlite.connect("db.sqlite") as db:
        cursor = await db.execute(f"""
            SELECT id, wins_{mode_value}, losses_{mode_value}, elo_{mode_value}
            FROM players
            ORDER BY elo_{mode_value} DESC
            LIMIT 10
        """)
        top_players = await cursor.fetchall()

    if not top_players:
        await interaction.response.send_message("No leaderboard data yet!", ephemeral=True)
        return

    _, _, top_image_url = get_rank_info(top_players[0][3])

    embed = discord.Embed(
        title=f"🏆 Top 10 Leaderboard - {mode_value.upper()}",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=top_image_url)

    for i, (player_id, wins, losses, elo) in enumerate(top_players, start=1):
        try:
            user = await bot.fetch_user(player_id)
            user_name = user.display_name or user.name or f"User {player_id}"
        except Exception:
            user_name = f"User {player_id}"

        rank, rank_emoji, _ = get_rank_info(elo)
        embed.add_field(
            name=f"{i}. {user_name} {rank_emoji} {rank}",
            value=f"**ELO:** {elo} | **Wins:** {wins} | **Losses:** {losses}",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="reset_elo", description="Admin only: Reset a player's ELO/wins/losses for a game mode")
@app_commands.describe(user="User to reset", mode="Game mode")
@app_commands.choices(mode=[
    app_commands.Choice(name="1v1", value="1v1"),
    app_commands.Choice(name="2v2", value="2v2"),
])
async def reset_elo(interaction: Interaction, user: discord.User, mode: app_commands.Choice[str]):
    ADMIN_IDS = [228719376415719426]  # Update with your admin ID
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await ensure_player_exists(user.id)
    mode_suffix = mode.value
    async with aiosqlite.connect("db.sqlite") as db:
        await db.execute(
            f"""UPDATE players SET
                    wins_{mode_suffix}=0,
                    losses_{mode_suffix}=0,
                    elo_{mode_suffix}=1000
                WHERE id=?
            """, (user.id,)
        )
        await db.commit()
    await interaction.response.send_message(
        f"Reset {user.mention}'s {mode_suffix.upper()} stats to defaults.",
        ephemeral=True
    )

# ------------------- Finalize Run -------------------
bot.run(TOKEN)
