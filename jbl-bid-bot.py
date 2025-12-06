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

# *** COMMANDS AND BOT STARTUP BELOW ***

# COMMAND !startdraft: Start bidding round (!startdraft TT,OO,MN,...)
@bot.command()
async def startdraft(ctx, *, teams):
    teamList = teams.split(",")
    if len(teamList) < 2:
        await ctx.send("❌ At least two teams are required to start a draft.")
        return
    structuredTeamList = [{"IntroTm": tm.strip(), "ClaimTm": "", "Player": "", "Amt": 0} for tm in teamList]
    saved_data["draft"] = structuredTeamList
    saved_data["round"] = []
    save_data()
    await draftrecap(ctx)


# COMMAND !draftstatus: Show current round status
@bot.command()
async def draftstatus(ctx):
    if len(saved_data["draft"]) == 0:
        await ctx.send("❌ No draft in progress. Use !startdraft to begin.")
        return
    if len(saved_data["round"]) == 0:
        nextTmToIntro = ""
        for entry in saved_data["draft"]:
            if entry["Player"] == "":
                nextTmToIntro = entry["IntroTm"]
                break
        if nextTmToIntro == "":
            await ctx.send("🧢 Free agent bidding round complete ⚾")
        else:
            await ctx.send(f"📝 Next to introduce a player: **{nextTmToIntro}**")
        return
    
    playerName = ""
    for entry in saved_data["draft"]:
        if entry["Player"] != "":
            playerName = entry["Player"]
        else:
            break
    amount = saved_data["round"][-1]["Amt"]
    teamName = saved_data["round"][-1]["Tm"]
    on_the_clock = saved_data["round"][0]["Tm"]
    next_to_bid = ", ".join(entry["Tm"] for entry in saved_data["round"][1:])
    msg = (
        f"⏰  **{playerName}** currently at **{amount}k** to **{teamName}**\n"
        f"On the clock: **{on_the_clock}**"
    )
    if next_to_bid != "":
        msg = msg + f"\nNext up: **{next_to_bid}**"
    
    await ctx.send(msg)


# COMMAND !draftrecap: Show draft recap
@bot.command()
async def draftrecap(ctx):
    # Build a formatted grid for `draft` and `round` and send as a code block
    draft = saved_data.get("draft", [])
    roundlist = saved_data.get("round", [])

    if not draft and not roundlist:
        await ctx.send("❌ No draft available. Use !stardraft to begin.")
        return

    # --- Draft table ---
    draft_lines = []
    if draft:
        # compute column widths
        team_w = max(len("Intro"), max((len(entry.get("IntroTm", "")) for entry in draft), default=0))
        claim_w = max(len("Claim"), max((len(entry.get("ClaimTm", "")) for entry in draft), default=0))
        player_w = max(len("Player"), max((len(entry.get("Player", "")) for entry in draft), default=0))
        amt_w = max(len("Amt"), max((1 if entry.get("Amt", 0) == 0 else len(f"{entry['Amt']}k") for entry in draft), default=0))

        header = (
            f"{ 'Intro'.ljust(team_w) }  { 'Claim'.ljust(claim_w) }  { 'Player'.ljust(player_w) }  { 'Amt'.rjust(amt_w) }"
        )
        sep = "-" * len(header)
        draft_lines.append(header)
        draft_lines.append(sep)
        for entry in draft:
            amt_str = "-" if entry.get("Amt", 0) == 0 else f"{entry['Amt']}k"
            draft_lines.append(
                f"{ entry.get('IntroTm','').ljust(team_w) }  { entry.get('ClaimTm','').ljust(claim_w) }  { entry.get('Player','').ljust(player_w) }  { amt_str.rjust(amt_w) }"
            )
    else:
        draft_lines.append("(no draft entries)")

    # --- Round table ---
    round_lines = []
    if roundlist:
        order_w = max(len("#"), len(str(len(roundlist))))
        team_w_r = max(len("Team"), max((len(entry.get("Tm", "")) for entry in roundlist), default=0))
        amt_w_r = max(len("Amt"), max((1 if entry.get("Amt", 0) == 0 else len(f"{entry['Amt']}k") for entry in roundlist), default=0))
        header_r = (
            f"{ '#'.ljust(order_w) }  { 'Team'.ljust(team_w_r) }  { 'Last Bid'.rjust(amt_w_r) }"
        )
        sep_r = "-" * len(header_r)
        round_lines.append(header_r)
        round_lines.append(sep_r)
        for idx, entry in enumerate(roundlist, start=1):
            amt_str = "-" if entry.get("Amt", 0) == 0 else f"{entry['Amt']}k" 
            round_lines.append(
                f"{ str(idx).ljust(order_w) }  { entry.get('Tm','').ljust(team_w_r) }  { amt_str.rjust(amt_w_r) }"
            )

    content = []
    content.append("DRAFT:")
    content.extend(draft_lines)    
    if roundlist:
        content.append("")
        content.append("ROUND:")
        content.extend(round_lines)

    msg = "```text\n" + "\n".join(content) + "\n```"
    await ctx.send(msg)
    await draftstatus(ctx)


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
    if nextTmToIntro == "":
        await ctx.send("❌ A player cannot be introduced. The draft is already complete.")
        return
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
        await ctx.send(f"❌ It's not {team}'s turn to bid. On the clock to bid: {currentBidTeam}")
        return
       
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
    
    # Check if bidding is over (only one team left)
    bidRoundOver = len(roundList) == 1
    winner = ""
    winnerAmt = 0
    playerName = ""
    if bidRoundOver:
        winner = roundList[0]["Tm"]
        winnerAmt = roundList[0]["Amt"]
        for entry in saved_data["draft"]:
            if entry["Amt"] == 0:
                entry["ClaimTm"] = winner
                entry["Amt"] = winnerAmt
                playerName = entry["Player"]
                break
        roundList = []

    saved_data["round"] = roundList
    save_data()

    if bidRoundOver:
        await ctx.send(f"💵 **{winner}** wins **{playerName}** for **${winnerAmt}k**!")
        await draftrecap(ctx)
    else:
        await draftstatus(ctx)


# COMMAND !drafthelp: Show bot commands with examples
@bot.command()
async def drafthelp(ctx):
    help_text = (
        "❓ **JBL Draft Bot — Commands & Examples**\n\n"
        "**Start a free agent bidding round**\n"
        "`!startdraft TT,OO,MN`\n— Initialize the bidding round with comma-separated team codes in draft pick order.\n\n"
        "**Introduce a player**\n"
        "`!introduce TT Player Name 1k`\n— Team `TT` introduces 'Player Name' starting at 1k.\n\n"
        "**Place a bid**\n"
        "`!bid TT 2k`\n— Team `TT` bids 2k on the current player.\n"
        "`!bid TT pass`\n— Team `TT` passes.\n\n"
        "**Status & recap**\n"
        "`!draftstatus`\n— Show current bidding status (who's on the clock, current bid).\n"
        "`!draftrecap`\n— Show entire bidding round progress.\n\n"
        "**Amount format**: use numbers with optional trailing `k` (e.g., `1k`, `20k` - 1 = 1,000)."
    )
    await ctx.send(help_text)


# Run the bot with the token
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise SystemExit("Set DISCORD_TOKEN in your environment.")
bot.run(token)