# pokemon-trivia-discord-bot

Discord bot for Pokemon trivia gameplay with progressive hints and leaderboards

# Feature 1: Core Game Functionality [Priority 1]

Description: Users start games, submit guesses, and receive feedback on Pokémon identification.

Estimated Complexity: High, must be completely functional for other features to work off of, and many moving components that must be accurate. All aspects are individual and testing for functionality will take the longest out of all other features.

Target Users: All Discord server members

User-System Interactions:

User: !start → Bot: displays Pokémon silhouette
User: !guess [name] → Bot: "Correct!" or "Try again!"
Correct guess reveals full Pokémon image and awards points

System Behaviors:
Listen for commands in specific channels
Query the Pokémon database for random selection
Display embedded images
Validate guesses (handles spelling variations)
Track game state per channel
Award points on a correct guess
Value: Provides core entertainment and reason to use the bot.

Rationale: Without gameplay, there is no product. It’s the foundation for all other features.

Dependencies: None

# First-time setup instructions

1. **Clone this repository and open a terminal in the project folder.**

2. **Create a virtual environment (recommended):**

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**

   ```sh
   pip install -r requirements.txt
   ```

4. **Create a `.env` file in the project folder and add the Discord bot token (Ethan will provide this):**

   ```env
   DISCORD_TOKEN=bot-token-here
   ```

5. **Run the bot:**

   ```sh
   python3 bot.py
   ```

6. **Check `discord.log` for debugging information if needed.**
