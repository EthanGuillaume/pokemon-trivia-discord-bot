# this brings in the stuff we need to make the bot work
import discord
from dotenv import load_dotenv
from discord.ext import commands
import logging
import os
import random
import aiohttp
from io import BytesIO
from PIL import Image


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


# this keeps track of the game for each user
# it remembers the answer, the image, and how many guesses
games = {}


# this turns the pokemon artwork into a black silhouette
async def make_silhouette(session, image_url):
    async with session.get(image_url) as resp:
        if resp.status != 200:
            return None

        image_bytes = await resp.read()
    # here we use pillow to keep the original transparency and just swap the visible part of the artwork to black.
    # luckily the api has transparant pngs so we don't have to do any fancy masking or anything, we can just take the alpha channel and apply it to a new black image.
    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    alpha_channel = image.getchannel("A")

    silhouette = Image.new("RGBA", image.size, (0, 0, 0, 0))
    silhouette.putalpha(alpha_channel)

    output = BytesIO()
    silhouette.save(output, format="PNG")
    output.seek(0)
    return output


# this cleans up api text like generation-i into Generation I
def pretty_text(text):
    if not text:
        return "Unknown"
    return text.replace("-", " ").title()


# this sets up the hints in the order we want
def build_hints(pokemon_data, species_data):
    pokemon_types = [entry["type"]["name"] for entry in pokemon_data.get("types", [])]
    color = pretty_text(species_data.get("color", {}).get("name"))
    generation = pretty_text(species_data.get("generation", {}).get("name"))
    primary_type = pretty_text(pokemon_types[0]) if pokemon_types else "Unknown"
    answer = pokemon_data["name"]

    hints = [
        f"Hint 1: this pokémon's main pokedex color is **{color}**.",
        f"Hint 2: this pokémon was introduced in **{generation}**.",
        f"Hint 3: this pokémon's primary type is **{primary_type}**.",
        f"Hint 4: this pokémon starts with the letter **{answer[0].upper()}**." if answer else "Hint 4: no first-letter hint available.",
        f"Hint 5: this pokémon's name has **{len(answer)}** letters.",
    ]

    return hints


# this runs when the bot is ready and logged in
@bot.event
async def on_ready():
    print(f"Successfully running, {bot.user.name}")


# this shows the user all the commands they can use
@bot.command()
async def help(ctx):
    # make a simple help menu so users can see every command quickly
    embed = discord.Embed(
        title="Pokémon trivia commands",
        description="Here are the commands you can use in the game."
    )
    # each field is one command with a short explanation
    embed.add_field(name="!start", value="start a new pokémon trivia game.", inline=False)
    embed.add_field(name="!guess <name>", value="submit your guess for the current pokémon.", inline=False)
    embed.add_field(name="!hint", value="get the next hint for your current game.", inline=False)
    embed.add_field(name="!end", value="end your current game and reveal the answer.", inline=False)
    embed.add_field(name="!help", value="show this command list.", inline=False)
    await ctx.send(embed=embed)


# this command starts the game
@bot.command()
async def start(ctx):
    user_id = ctx.author.id
    # if a game is already running for this user, don't start a new one
    if user_id in games:
        await ctx.send(f"{ctx.author.mention}, you already have a game running! Use `!end` to stop it.")
        return
    # pick a random pokemon from the first 151
    poke_id = random.randint(1, 151)
    async with aiohttp.ClientSession() as session:
        # this api is for the actual pokemon data like types and the image
        async with session.get(f'https://pokeapi.co/api/v2/pokemon/{poke_id}') as pokemon_resp:
            if pokemon_resp.status != 200:
                await ctx.send("Failed to fetch pokémon data. Try again.")
                return

            pokemon_data = await pokemon_resp.json()
        #this api is for the species data like color and generation, which we use for hints
        async with session.get(f'https://pokeapi.co/api/v2/pokemon-species/{poke_id}') as species_resp:
            if species_resp.status != 200:
                await ctx.send("Failed to fetch pokémon hint data. Try again.")
                return

            species_data = await species_resp.json()

            answer = pokemon_data['name']
            # get the pokemon's picture
            image_url = pokemon_data['sprites']['other']['official-artwork']['front_default']
            if not image_url:
                # if there is no artwork, use the normal sprite
                image_url = pokemon_data['sprites']['front_default']

            if not image_url:
                await ctx.send("Could not find artwork for this pokémon. Try again.")
                return

            silhouette_bytes = await make_silhouette(session, image_url)
            if not silhouette_bytes:
                await ctx.send("Could not build the silhouette image. Try again.")
                return

            # build the list of hints before the game starts
            hints = build_hints(pokemon_data, species_data)

            # save the answer, image, and guesses for this user
            games[user_id] = {
                "answer": answer.lower(),
                "display_name": pretty_text(answer),
                "image_url": image_url,
                "guesses": 0,
                "hint_index": 0,
                "hints": hints,
            }

            # make a message with the picture
            embed = discord.Embed(
                title="Who's That Pokémon?",
                description="Guess the Pokémon from the silhouette!"
            )
            silhouette_file = discord.File(silhouette_bytes, filename="silhouette.png")
            embed.set_image(url="attachment://silhouette.png")
            await ctx.send(file=silhouette_file, embed=embed)
            await ctx.send(f"{ctx.author.mention}, your trivia game has started! Use `!guess <name>` to answer, `!hint` for assistance, or `!end` to stop your game.")


# this gives the next hint to the user
@bot.command()
async def hint(ctx):
    user_id = ctx.author.id
    game = games.get(user_id)

    if not game:
        await ctx.send(f"{ctx.author.mention}, you don't have a game running. Start one with `!start`.")
        return

    # stop once the user has already seen every hint
    if game["hint_index"] >= len(game["hints"]):
        await ctx.send(f"{ctx.author.mention}, you already used all the hints for this pokémon.")
        return

    # send the next hint and move the counter forward
    next_hint = game["hints"][game["hint_index"]]
    game["hint_index"] += 1
    await ctx.send(f"{ctx.author.mention}, {next_hint}")


# this command lets you guess the pokemon
@bot.command()
async def guess(ctx, *, user_guess: str):
    user_id = ctx.author.id
    # get the game for this user
    game = games.get(user_id)
    if not game:
        await ctx.send(f"{ctx.author.mention}, you don't have a game running. Start one with `!start`.")
        return
    # add 1 to the number of guesses
    game["guesses"] += 1
    # check if the guess is right
    if user_guess.lower().strip() == game["answer"]:
        # reveal the normal artwork once the user gets it right
        reveal_embed = discord.Embed(
            title="Correct!",
            description=f"The answer was **{game['display_name']}**."
        )
        reveal_embed.set_image(url=game["image_url"])
        await ctx.send(embed=reveal_embed)
        await ctx.send(f"🎉 Correct, {ctx.author.mention}! **Total Guesses: {game['guesses']} | Hints used: {game['hint_index']}**")
        del games[user_id]
    else:
        await ctx.send(f"❌ Incorrect, {ctx.author.mention}! Try again. **(Guesses: {game['guesses']})**")


# this command ends the game and shows the answer
@bot.command()
async def end(ctx):
    user_id = ctx.author.id
    game = games.get(user_id)
    if game:
        answer = game["display_name"]
        # remove the game first so the user can start a new one right away
        del games[user_id]

        # show the real image when the game is ended
        reveal_embed = discord.Embed(
            title="Game Ended",
            description=f"The pokémon was **{answer}**."
        )
        reveal_embed.set_image(url=game["image_url"])
        await ctx.send(embed=reveal_embed)
        await ctx.send(f"{ctx.author.mention}, Game over! The answer was **{answer}**. Better luck next time! **Total Guesses: {game['guesses']} | Hints used: {game['hint_index']}**")
    else:
        await ctx.send(f"{ctx.author.mention}, you don't have a game running.")


# this starts the bot
bot.run(token, log_handler=handler, log_level=logging.DEBUG)