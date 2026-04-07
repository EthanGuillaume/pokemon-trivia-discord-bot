# this brings in the stuff we need to make the bot work
import discord
from dotenv import load_dotenv
from discord.ext import commands
import logging
import os
import random
import aiohttp


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
bot = commands.Bot(command_prefix='!', intents=intents)


# this keeps track of the game for each user
# it remembers the answer, the image, and how many guesses
games = {}


# this runs when the bot is ready and logged in
@bot.event
async def on_ready():
    print(f"Successfully running, {bot.user.name}")


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
        async with session.get(f'https://pokeapi.co/api/v2/pokemon/{poke_id}') as resp:
            if resp.status != 200:
                await ctx.send("Failed to fetch Pokémon data. Try again.")
                return
            data = await resp.json()
            answer = data['name']
            # get the pokemon's picture
            image_url = data['sprites']['other']['official-artwork']['front_default']
            if not image_url:
                # if there is no artwork, use the normal sprite
                image_url = data['sprites']['front_default']
            # save the answer, image, and guesses for this user
            games[user_id] = {"answer": answer.lower(), "image_url": image_url, "guesses": 0}
            # make a message with the picture
            embed = discord.Embed(title="Who's That Pokémon?", description="Guess the Pokémon!")
            embed.set_image(url=image_url)
            await ctx.send(embed=embed)
            await ctx.send(f"{ctx.author.mention}, your trivia game has started! Use `!guess <name>` to answer or `!end` to stop your game.")


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
        await ctx.send(f"🎉 Correct, {ctx.author.mention}! The answer was **{game['answer'].title()}**. Number of guesses: {game['guesses']}")
        del games[user_id]
    else:
        await ctx.send(f"❌ Incorrect, {ctx.author.mention}! Try again. **(Guesses: {game['guesses']})**")


# this command ends the game and shows the answer
@bot.command()
async def end(ctx):
    user_id = ctx.author.id
    game = games.get(user_id)
    if game:
        answer = game["answer"].title()
        del games[user_id]
        await ctx.send(f"{ctx.author.mention}, your game ended. The Pokémon was **{answer}**.")
    else:
        await ctx.send(f"{ctx.author.mention}, you don't have a game running.")


# this starts the bot
bot.run(token, log_handler=handler, log_level=logging.DEBUG)