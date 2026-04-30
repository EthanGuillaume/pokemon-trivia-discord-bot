# this brings in the stuff we need to make the bot work
from pydoc import text

import discord
from dotenv import load_dotenv
from discord.ext import commands
import logging
import os
import random
import aiohttp
from io import BytesIO
from PIL import Image
import sqlite3
import re
import unicodedata


# this loads the secret token for the bot from a file
load_dotenv()
token = os.getenv('DISCORD_TOKEN')

#https://www.youtube.com/watch?v=YD_N6Ffoojw
# great resource for how to setup discord bot.

# this sets up logging and lets the bot read messages
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True


# this makes the bot listen for commands that start with !
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# used for converting characters and removing any non basic ascii characters, also handles case sensitivity
def normalize_text(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[^a-z0-9]', '', text.lower())


# ------------------------------------------------------------
# GameState class
# this holds all the data for one active game session
# keeping it in its own class makes it easier to manage and
# means the bot doesnt have to know about all the fields
# ------------------------------------------------------------
class GameState:
    def __init__(self, pokemon_name, species_name, display_name, image_url, hints, difficulty):
        self.answer = species_name.lower()
        self.answers = [pokemon_name.lower(), species_name.lower()] #a list of correct answers, for certain forms or variations of names
        self.display_name = display_name
        self.image_url = image_url
        self.hints = hints
        self.difficulty = difficulty
        self.guesses = 0
        self.hint_index = 0


# ------------------------------------------------------------
# HintService class
# this is responsible for building hints from pokemon data
# and cleaning up text from the api
# we separated this out because hint logic shouldnt live
# inside the bot command handlers
# ------------------------------------------------------------
class HintService:

    # this cleans up api text like generation-i into Generation I
    def pretty_text(self, text):
        if not text:
            return "Unknown"
        return text.replace("-", " ").title()

    # this builds the list of hints in the order we want
    def build_hints(self, pokemon_data, species_data):
        pokemon_types = [entry["type"]["name"] for entry in pokemon_data.get("types", [])]
        color = self.pretty_text(species_data.get("color", {}).get("name"))
        generation = self.pretty_text(species_data.get("generation", {}).get("name"))
        primary_type = self.pretty_text(pokemon_types[0]) if pokemon_types else "Unknown"

        #answer = pokemon_data["name"] 
        answer = species_data["name"] #using species name helps with consistency in answering

        hints = [
            f"Hint 1: this pokémon's main pokedex color is **{color}**.",
            f"Hint 2: this pokémon was introduced in **{generation}**.",
            f"Hint 3: this pokémon's primary type is **{primary_type}**.",
            f"Hint 4: this pokémon starts with the letter **{answer[0].upper()}**." if answer else "Hint 4: no first-letter hint available.",
            f"Hint 5: this pokémon's name has **{len(answer)}** letters.",
        ]

        return hints


# ------------------------------------------------------------
# PokemonRepository class
# this is responsible for fetching pokemon data from the api
# and building the silhouette image
# we separated this so the bot command doesnt have to know
# anything about how the data is fetched
# ------------------------------------------------------------
class PokemonRepository:

    # fetches the main pokemon data like types and artwork
    async def get_pokemon(self, session, poke_id):
        async with session.get(f'https://pokeapi.co/api/v2/pokemon/{poke_id}') as resp:
            if resp.status != 200:
                return None
            return await resp.json()

    # fetches the species data like color and generation for hints
    async def get_species(self, session, poke_id):
        async with session.get(f'https://pokeapi.co/api/v2/pokemon-species/{poke_id}') as resp:
            if resp.status != 200:
                return None
            return await resp.json()

    # this turns the pokemon artwork into a black silhouette using pillow
    # the api returns transparent pngs so we just pull the alpha channel
    # and put it on a black background
    async def make_silhouette(self, session, image_url):
        async with session.get(image_url) as resp:
            if resp.status != 200:
                return None
            image_bytes = await resp.read()

        image = Image.open(BytesIO(image_bytes)).convert("RGBA")
        alpha_channel = image.getchannel("A")

        silhouette = Image.new("RGBA", image.size, (0, 0, 0, 0))
        silhouette.putalpha(alpha_channel)

        output = BytesIO()
        silhouette.save(output, format="PNG")
        output.seek(0)
        return output


# ------------------------------------------------------------
# create instances of each service so the bot can use them
# ------------------------------------------------------------
hint_service = HintService()
pokemon_repo = PokemonRepository()

# this keeps track of the active game for each user by their discord id
games = {}


# ------------------------------------------------------------
# DifficultyService class
# this owns the difficulty configuration and scoring logic
# keeping it here means the bot command doesnt need to know
# how ranges are defined or how scores are calculated
# ------------------------------------------------------------
class DifficultyService:

    DIFFICULTY_RANGES = {
        "easy": (1, 151),    # gen 1
        "medium": (1, 386),  # gen 1-3
        "hard": (1, 1025),   # all gens
    }

    DIFFICULTY_BASE_SCORES = {
        "easy": 100,
        "medium": 150,
        "hard": 200,
    }

    # starts at the base score for the difficulty then subtracts
    # 10 points per extra guess and 5 per hint used
    def calculate_score(self, guesses: int, hints_used: int, difficulty: str) -> int:
        score = self.DIFFICULTY_BASE_SCORES.get(difficulty, 100)
        score -= (guesses - 1) * 10
        score -= hints_used * 5
        return max(score, 10)


# ------------------------------------------------------------
# LeaderboardEntry class
# this is a simple object that holds one row from the leaderboard
# table instead of passing raw tuples around we wrap them in
# this class so the code is easier to read
# ------------------------------------------------------------
class LeaderboardEntry:
    def __init__(self, discord_user_id, server_id, total_score):
        self.discord_user_id = discord_user_id
        self.server_id = server_id
        self.total_score = total_score


# ------------------------------------------------------------
# LeaderboardService class
# this handles formatting the leaderboard into a discord embed
# we pull this out of the bot command so the command doesnt
# have to know anything about how the embed is built
# ------------------------------------------------------------
class LeaderboardService:

    # takes a list of LeaderboardEntry objects and the server name
    # and builds a discord embed to send back to the user
    def format_leaderboard(self, entries, guild_name):
        embed = discord.Embed(title=f"🏆 {guild_name} Pokémon Trivia Leaderboard", color=0xFFD700)

        leaderboard_text = ""
        for index, entry in enumerate(entries, start=1):
            name = f"<@{entry.discord_user_id}>"
            medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else f"**{index}.**"
            leaderboard_text += f"{medal} {name}: `{entry.total_score} pts`\n"

        embed.description = leaderboard_text
        return embed


# ------------------------------------------------------------
# LeaderboardRepository class
# this handles all database stuff for saving and reading scores
# keeping this separate means the bot commands dont need to
# know how the database works
# ------------------------------------------------------------
class LeaderboardRepository:

    DB_NAME = "leaderboard.db"

    # sets up the table if it doesnt exist yet
    def init_database(self):
        conn = sqlite3.connect(self.DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leaderboard (
                discord_user_id TEXT NOT NULL,
                server_id TEXT NOT NULL,
                total_score INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (discord_user_id, server_id)
            )
        """)
        conn.commit()
        conn.close()

    # saves the score only if its a new personal best
    def update_score(self, user_id, server_id, new_score):
        conn = sqlite3.connect(self.DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO leaderboard (discord_user_id, server_id, total_score)
            VALUES (?, ?, ?)
            ON CONFLICT(discord_user_id, server_id) DO UPDATE SET
            total_score = leaderboard.total_score + excluded.total_score
        """, (str(user_id), str(server_id), new_score))
        conn.commit()
        conn.close()

    # gets the top 10 scores for a server and returns them as LeaderboardEntry objects
    def get_top_scores(self, server_id):
        conn = sqlite3.connect(self.DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT discord_user_id, total_score
            FROM leaderboard
            WHERE server_id = ?
            ORDER BY total_score DESC
            LIMIT 10
        """, (str(server_id),))
        rows = cursor.fetchall()
        conn.close()
        return [LeaderboardEntry(discord_user_id=row[0], server_id=str(server_id), high_score=row[1]) for row in rows]


# create the leaderboard repo and service instances
leaderboard_repo = LeaderboardRepository()
leaderboard_repo.init_database()
leaderboard_service = LeaderboardService()
difficulty_service = DifficultyService()


# this runs when the bot is ready and logged in
@bot.event
async def on_ready():
    print(f"Successfully running, {bot.user.name}")


# this shows the user all the commands they can use
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="Pokémon trivia commands",
        description="Here are the commands you can use in the game."
    )
    embed.add_field(name="!start [difficulty]", value="start a new pokémon trivia game. difficulty can be `easy` (gen 1), `medium` (gen 1-3), or `hard` (all gens). defaults to `easy`.", inline=False)
    embed.add_field(name="!guess <name>", value="submit your guess for the current pokémon.", inline=False)
    embed.add_field(name="!hint", value="get the next hint for your current game.", inline=False)
    embed.add_field(name="!end", value="end your current game and reveal the answer.", inline=False)
    embed.add_field(name="!leaderboard", value="show the Pokémon trivia leaderboard.", inline=False)
    embed.add_field(name="!help", value="show this command list.", inline=False)
    await ctx.send(embed=embed)


# this command starts the game
# it uses PokemonRepository to get the data and HintService to build hints
# then stores a GameState object for the user
@bot.command()
async def start(ctx, difficulty: str = "easy"):
    user_id = ctx.author.id

    # dont let them start a new game if one is already running
    if user_id in games:
        await ctx.send(f"{ctx.author.mention}, you already have a game running! Use `!end` to stop it.")
        return

    difficulty = difficulty.lower()
    if difficulty not in DifficultyService.DIFFICULTY_RANGES:
        await ctx.send(f"{ctx.author.mention}, invalid difficulty. Choose `easy`, `medium`, or `hard`.")
        return

    poke_min, poke_max = DifficultyService.DIFFICULTY_RANGES[difficulty]
    poke_id = random.randint(poke_min, poke_max)

    # TEMPORARY EDGE CASE TESTING
    # poke_id = 122 # mr mime (Mr. Mime)
    # poke_id = 669 # flabebe (Flabébé)
    # poke_id = 386 # deoxys (deoxys-normal)
    # poke_id = 778 # mimikyu (mimikyu-disguised)


    async with aiohttp.ClientSession() as session:
        # use the repository to fetch pokemon and species data
        pokemon_data = await pokemon_repo.get_pokemon(session, poke_id)
        if not pokemon_data:
            await ctx.send("Failed to fetch pokémon data. Try again.")
            return

        species_data = await pokemon_repo.get_species(session, poke_id)
        if not species_data:
            await ctx.send("Failed to fetch pokémon hint data. Try again.")
            return

        answer = pokemon_data['name']

        # try the official artwork first, fall back to normal sprite
        image_url = pokemon_data['sprites']['other']['official-artwork']['front_default']
        if not image_url:
            image_url = pokemon_data['sprites']['front_default']

        if not image_url:
            await ctx.send("Could not find artwork for this pokémon. Try again.")
            return

        # use the repository to build the silhouette
        silhouette_bytes = await pokemon_repo.make_silhouette(session, image_url)
        if not silhouette_bytes:
            await ctx.send("Could not build the silhouette image. Try again.")
            return

        # use the hint service to build the hint list
        hints = hint_service.build_hints(pokemon_data, species_data)

        # create a GameState object and store it for this user
        games[user_id] = GameState(
            pokemon_name = pokemon_data["name"],
            species_name = species_data["name"],
            display_name=hint_service.pretty_text(species_data["name"]),
            image_url=image_url,
            hints=hints,
            difficulty=difficulty,
        )

        embed = discord.Embed(
            title="Who's That Pokémon?",
            description="Guess the Pokémon from the silhouette!"
        )
        silhouette_file = discord.File(silhouette_bytes, filename="silhouette.png")
        embed.set_image(url="attachment://silhouette.png")
        await ctx.send(file=silhouette_file, embed=embed)
        await ctx.send(f"{ctx.author.mention}, your trivia game has started! Difficulty: **{difficulty.capitalize()}**. Use `!guess <name>` to answer, `!hint` for assistance, or `!end` to stop your game.")


# this gives the user their next hint from the GameState
@bot.command()
async def hint(ctx):
    user_id = ctx.author.id
    game = games.get(user_id)

    if not game:
        await ctx.send(f"{ctx.author.mention}, you don't have a game running. Start one with `!start`.")
        return

    # all hints have been used
    if game.hint_index >= len(game.hints):
        await ctx.send(f"{ctx.author.mention}, you already used all the hints for this pokémon.")
        return

    # grab the next hint and move the index forward
    next_hint = game.hints[game.hint_index]
    game.hint_index += 1
    await ctx.send(f"{ctx.author.mention}, {next_hint}")


# this lets the user guess the pokemon name
# uses the GameState to track guesses and check the answer
@bot.command()
async def guess(ctx, *, user_guess: str):
    user_id = ctx.author.id
    game = games.get(user_id)

    if not game:
        await ctx.send(f"{ctx.author.mention}, you don't have a game running. Start one with `!start`.")
        return

    game.guesses += 1

    normalized_user_guess = normalize_text(user_guess)

    # checks if the guess is any of the possible correct answers (for varying forms or names)
    is_correct = False
    for a in game.answers:
        if normalize_text(a) == normalized_user_guess:
            is_correct = True
            break

    if is_correct:
        reveal_embed = discord.Embed(
            title="Correct!",
            description=f"The answer was **{game.display_name}**."
        )
        reveal_embed.set_image(url=game.image_url)

        score = difficulty_service.calculate_score(game.guesses, game.hint_index, game.difficulty)

        # save the score using the leaderboard repository
        leaderboard_repo.update_score(ctx.author.id, ctx.guild.id, score)

        await ctx.send(embed=reveal_embed)
        await ctx.send(f"🎉 Correct, {ctx.author.mention}! **Score: {score} | Total Guesses: {game.guesses} | Hints used: {game.hint_index}**")
        del games[user_id]
    else:
        await ctx.send(f"❌ Incorrect, {ctx.author.mention}! Try again. **(Guesses: {game.guesses})**")


# this shows the top 10 leaderboard for the server
# uses the leaderboard repository to get the scores
# and the leaderboard service to format the embed
@bot.command()
async def leaderboard(ctx):
    entries = leaderboard_repo.get_top_scores(ctx.guild.id)

    if not entries:
        await ctx.send("The leaderboard is empty! Start a game with `!start` to claim your spot.")
        return

    # delegate embed building to the leaderboard service
    embed = leaderboard_service.format_leaderboard(entries, ctx.guild.name)
    await ctx.send(embed=embed)


# this ends the current game and reveals the answer without giving points
@bot.command()
async def end(ctx):
    user_id = ctx.author.id
    game = games.get(user_id)

    if game:
        answer = game.display_name
        del games[user_id]

        reveal_embed = discord.Embed(
            title="Game Ended",
            description=f"The pokémon was **{answer}**."
        )
        reveal_embed.set_image(url=game.image_url)
        await ctx.send(embed=reveal_embed)
        await ctx.send(f"{ctx.author.mention}, Game over! The answer was **{answer}**. Better luck next time! No points awarded.")
    else:
        await ctx.send(f"{ctx.author.mention}, you don't have a game running.")


# this starts the bot
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
