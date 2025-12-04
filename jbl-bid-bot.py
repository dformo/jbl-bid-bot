import discord
from discord.ext import commands
import json
import os
from pathlib import Path

# Create bot folder if not present
APPDATA_FOLDER = os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming"
BOT_FOLDER = Path(APPDATA_FOLDER) / "JuntaBot"
BOT_FOLDER.mkdir(parents=True, exist_ok=True)

# Full path to the data file
DATA_FILE = BOT_FOLDER / "draft-bot-data.json"

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
intents.presences = False
bot = commands.Bot(command_prefix="!", intents=intents)

# Load data from file
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        saved_data = json.load(f)
else:
    saved_data = {"draft": [], "round": []}  # default structure

# Method for saving data to file
def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(saved_data, f)

# Log bot login
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

# COMMAND !startdraft: Start bidding round (!startdraft TT,OO,MN,...)
@bot.command()
async def startdraft(ctx, *, teams):
    teamList = teams.split(",")
    structuredTeamList = [{"IntroTm": tm.strip(), "ClaimTm": "", "Player": "", "Amt": 0} for tm in teamList]
    saved_data["draft"] = structuredTeamList
    saved_data["round"] = []
    save_data()
    await draftstatus(ctx)

# COMMAND !draftstatus: Show current round status
@bot.command()
async def draftstatus(ctx):
    # ToDo: Format output better
    await ctx.send(f"{saved_data}")

# COMMAND !introduce: Introduce a player for bidding (!introduce TT PlayerName 1k)
@bot.command()
async def introduce(ctx, *, tmPlayerAndAmt):
    # Validate command is expected (can't introduce if previous round isn't finished)
    if len(saved_data["round"]) > 0:
        await ctx.send("❌ A player cannot be introduced until the current player bidding is finished.")
        return

    # Validate Team
    team = tmPlayerAndAmt.split(" ")[0]
    if not any(entry["IntroTm"] == team for entry in saved_data["draft"]):
        await ctx.send(f"❌ Team '{team}' is not in the draft.")
        return
    nextTmToIntro = ""
    for entry in saved_data["draft"]:
        if entry["Player"] == "":
            nextTmToIntro = entry["IntroTm"]
            break
    if team != nextTmToIntro:
        await ctx.send(f"❌ It's not {team}'s turn to introduce a player. Next to introduce: {nextTmToIntro}")
        return

    # Validate Player
    first_space = tmPlayerAndAmt.find(" ")
    last_space = tmPlayerAndAmt.rfind(" ")
    if first_space != -1 and last_space != -1 and last_space > first_space:
        player = tmPlayerAndAmt[first_space+1:last_space]
    else:
        player = ""
    if player.strip() == "":
        await ctx.send("❌ Player name cannot be empty.")
        return
    
    # Validate Amount
    amount = tmPlayerAndAmt.rsplit(" ", 1)[-1]
    if amount.endswith("k"):
        amount = amount[:-1]
    if not amount.isdigit():
        await ctx.send("❌ Invalid amount format. Use a number followed by 'k' (e.g., 1k).")
        return
    amount = int(amount)

    # Update draft status
    for entry in saved_data["draft"]:
        if entry["IntroTm"] == team:
            entry["Player"] = player
            break
    
    # Build round list from introducing team
    structuredRoundList = []
    ctr = 0
    for entry in saved_data["draft"]:
        if entry["IntroTm"] == team:
            break
        ctr += 1
    for i in range(ctr, len(saved_data["draft"])):
        structuredRoundList.append({"Tm": saved_data["draft"][i]["IntroTm"], "Amt": 0})
    for i in range(0, ctr):
        structuredRoundList.append({"Tm": saved_data["draft"][i]["IntroTm"], "Amt": 0})

    # Update introduction amount arrangement order
    first = structuredRoundList.pop(0)
    first["Amt"] = amount
    structuredRoundList.append(first)

    saved_data["round"] = structuredRoundList
    save_data()
    await draftstatus(ctx)

# COMMAND !bid: Bid for a player (!bid TT PlayerName 1k)
@bot.command()
async def bid(ctx, *, tmPlayerAndAmt):
    # Validate command is expected (can't bid unless a player has been introduced)
    if len(saved_data["round"]) == 0:
        await ctx.send("❌ A player must be introduced before bidding can begin.")
        return
    
    # Validate Team
    team = tmPlayerAndAmt.split(" ")[0]
    currentBidTeam = saved_data["round"][0]["Tm"]
    if team != currentBidTeam:
        await ctx.send(f"❌ It's not {team}'s turn to bid. Next to bid: {currentBidTeam}")
        return
    
    # Validate Player
    first_space = tmPlayerAndAmt.find(" ")
    last_space = tmPlayerAndAmt.rfind(" ")
    if first_space != -1 and last_space != -1 and last_space > first_space:
        player = tmPlayerAndAmt[first_space+1:last_space]
    else:
        player = ""
    
    
    # Validate Amount
    amount = tmPlayerAndAmt.rsplit(" ", 1)[-1]
    amount = amount.strip()
    if amount.endswith("k"):
        amount = amount[:-1]
    
    isPassing = amount.lower() == "pass"
    if not isPassing:
        if not amount.isdigit():
            await ctx.send("❌ Invalid amount format. Use a number followed by 'k' (e.g., 1k).")
            return
        else:
            amount = int(amount)
            if amount <= saved_data["round"][-1]["Amt"]:
                await ctx.send(f"❌ Bid amount must be higher than the current bid of {saved_data['round'][-1]['Amt']}k.")
                return

    # Update round bidding
    roundList = saved_data["round"]
    if isPassing:
        roundList.pop(0)
    else:
        first = roundList.pop(0)
        first["Amt"] = amount
        roundList.append(first)
    
    # ToDo: Check if bidding is over (only one team left or all but one passed)

    saved_data["round"] = roundList
    save_data()

    await draftstatus(ctx)


# Run the bot with the token
bot.run("MTQ0NjE0MjQ1NTc2OTYwMDAzMA.GL1EL-.3M79H9co7kmzBp4kKFMcpuU5loIXVTio-LP8fU")