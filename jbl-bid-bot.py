import discord
from discord.ext import commands, tasks
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

# Method for checking if draft is active
def draft_is_active():
    return len(saved_data["draft"]) > 0 and any(entry["ClaimTm"] == "" for entry in saved_data["draft"])

# Send draft status to a channel (!draftstatus commmand helper)
async def send_draft_status(channel):
    if len(saved_data["draft"]) == 0:
        await channel.send("❌ No draft in progress. Use !startdraft to begin.")
        return
    if len(saved_data["round"]) == 0:
        nextTmToIntro = ""
        for entry in saved_data["draft"]:
            if entry["Player"] == "":
                nextTmToIntro = entry["IntroTm"]
                break
        if nextTmToIntro == "":
            await channel.send("🧢 Free agent bidding round complete ⚾")
        else:
            await channel.send(f"📝 Next to introduce a player: **{nextTmToIntro}**")
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
    
    await channel.send(msg)

# Send draft recap to a channel (!draftrecap commmand helper)
async def send_draft_recap(channel):
    # Build a formatted grid for `draft` and `round` and send as a code block
    draft = saved_data.get("draft", [])
    roundlist = saved_data.get("round", [])

    if not draft and not roundlist:
        await channel.send("❌ No draft available. Use !startdraft to begin.")
        return

    # --- Draft table ---
    draft_lines = []
    if draft:
        # compute column widths
        team_w = max(len("Tm"), max((len(entry.get("IntroTm", "")) for entry in draft), default=0))
        money_w = max(len("Cash"), max((1 if entry.get("MoneyLeft", 0) == 0 else len(f"{entry['MoneyLeft']}k") for entry in draft), default=0))
        player_w = max(len("Player"), max((len(entry.get("Player", "")) for entry in draft), default=0))
        claim_w = max(len("Wn"), max((len(entry.get("ClaimTm", "")) for entry in draft), default=0))
        amt_w = max(len("Amt"), max((1 if entry.get("Amt", 0) == 0 else len(f"{entry['Amt']}k") for entry in draft), default=0))

        header = (
            f"{ 'Tm'.ljust(team_w) }  { 'Cash'.rjust(money_w) }  { 'Player'.ljust(player_w) }  { 'Wn'.ljust(claim_w) }  { 'Amt'.rjust(amt_w) }"
        )
        sep = "-" * len(header)
        draft_lines.append(header)
        draft_lines.append(sep)
        for entry in draft:
            amt_str = "-" if entry.get("Amt", 0) == 0 else f"{entry['Amt']}k"
            money_str = f"{entry['MoneyLeft']}k"
            draft_lines.append(
                f"{ entry.get('IntroTm','').ljust(team_w)  }  { money_str.rjust(money_w) }  { entry.get('Player','').ljust(player_w) }  { entry.get('ClaimTm','').ljust(claim_w) }  { amt_str.rjust(amt_w) }"
            )
    else:
        draft_lines.append("(no draft entries)")

    # --- Round table ---
    round_lines = []
    if roundlist:
        order_w = max(len("#"), len(str(len(roundlist))))
        team_w_r = max(len("Tm"), max((len(entry.get("Tm", "")) for entry in roundlist), default=0))
        amt_w_r = max(len("Amt"), max((1 if entry.get("Amt", 0) == 0 else len(f"{entry['Amt']}k") for entry in roundlist), default=0))
        header_r = (
            f"{ '#'.ljust(order_w) }  { 'Tm'.ljust(team_w_r) }  { 'Bid'.rjust(amt_w_r) }"
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
        content.append("BIDDING:")
        content.extend(round_lines)

    msg = "```text\n" + "\n".join(content) + "\n```"
    await channel.send(msg)

# Send draft status message periodically if no activity
@tasks.loop(seconds=300.0)
async def check_for_reminder_task():
    if not draft_is_active():
        return
    last_chan_id = saved_data.get("last_channel_id")
    if last_chan_id:
        channel = bot.get_channel(last_chan_id)
        if channel:
            try:
                await send_draft_status(channel)
            except Exception:
                print("Error sending draft status reminder.")

# Log bot login
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    if draft_is_active():
        try:
            check_for_reminder_task.start()
        except Exception:
            print("Reminder task failed to startup.")

# *** COMMANDS BELOW ***
# COMMAND !startdraft: Start bidding round (!startdraft TT 100, OO 150 ,MN 175, ...)
@bot.command()
async def startdraft(ctx, *, teams):
    teamList = teams.split(",")
    if len(teamList) < 2:
        await ctx.send("❌ At least two teams are required to start a draft.")
        return
    for tm in teamList:
        parts = tm.strip().split(" ")
        if len(parts) != 2:
            await ctx.send(f"❌ Invalid team format: '{tm.strip()}'. Use 'TeamCode Money' format.")
            return
    
    structuredTeamList = []
    for tm in teamList:
        token = tm.strip()
        if not token:
            continue
        parts = token.split()
        intro = parts[0]
        money_str = parts[1] if len(parts) > 1 else "0"
        if money_str.lower().endswith("k"):
            money_str = money_str[:-1]
        try:
            money_val = int(money_str)
        except Exception:
            money_val = 0
        structuredTeamList.append({
            "IntroTm": intro,
            "MoneyLeft": money_val,
            "ClaimTm": "",
            "Player": "",
            "Amt": 0,
        })   
    saved_data["draft"] = structuredTeamList
    saved_data["round"] = []
    saved_data["last_channel_id"] = ctx.channel.id
    save_data()
    await send_draft_recap(ctx.channel)
    try:
        if check_for_reminder_task.is_running():
            check_for_reminder_task.restart()
        else:
            check_for_reminder_task.start()
    except Exception:
        print("Reminder task failed to start.")


# COMMAND !draftstatus: Show current round status
@bot.command()
async def draftstatus(ctx):
    await send_draft_status(ctx.channel)


# COMMAND !draftrecap: Show draft recap
@bot.command()
async def draftrecap(ctx):
    await send_draft_recap(ctx.channel)
    await send_draft_status(ctx.channel)


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
            if entry["MoneyLeft"] < amount:
                await ctx.send(f"❌ Team '{team}' does not have enough money to introduce at {amount}k.")
                return
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
    saved_data["last_channel_id"] = ctx.channel.id
    save_data()
    try:
        if check_for_reminder_task.is_running():
            check_for_reminder_task.restart()
        else:
            check_for_reminder_task.start()
    except Exception:
        print("Reminder task failed to start.")


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
            for entry in saved_data["draft"]:
                if entry["IntroTm"] == team and entry["MoneyLeft"] < amount:
                    await ctx.send(f"❌ Team '{team}' does not have enough money to bid at {amount}k.")
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
        for entry in saved_data["draft"]:
            if entry["IntroTm"] == winner:
                entry["MoneyLeft"] -= winnerAmt
                break
        roundList = []

    saved_data["round"] = roundList
    saved_data["last_channel_id"] = ctx.channel.id
    save_data()

    if bidRoundOver:
        await ctx.send(f"💵 **{winner}** wins **{playerName}** for **${winnerAmt}k**!")
        await send_draft_recap(ctx.channel)
        if draft_is_active():
            try:
                if check_for_reminder_task.is_running():
                    check_for_reminder_task.restart()
                else:
                    check_for_reminder_task.start()
            except Exception:
                print("Reminder task failed to start.")
        else:
            try:
                if check_for_reminder_task.is_running():
                    check_for_reminder_task.stop()
            except Exception:
                print("Reminder task failed to stop.")
            await draftstatus(ctx)
    else:
        try:
            if check_for_reminder_task.is_running():
                check_for_reminder_task.restart()
            else:
                check_for_reminder_task.start()
        except Exception:
            print("Reminder task failed to start.")


# COMMAND !drafthelp: Show bot commands with examples
@bot.command()
async def drafthelp(ctx):
    help_text = (
        "❓ **JBL Draft Bot — Commands & Examples**\n\n"
        "**Start a free agent bidding round**\n"
        "`!startdraft TT 100, OO 112, MN 98`\n— Initialize the bidding round with comma-separated team codes and cash in draft pick order.\n"
        "*Sample*: `!startdraft AA 170, BA 40, BC 370, CG 207, GG 254, KC 165, OO 380, PF 99, DC 140, MN 514, SR 159, TT 314, WW 175, PY 100, RI 144, SH 35`\n\n"
        "**Introduce a player**\n"
        "`!introduce TT Player Name 1k`\n— Team *TT* introduces *Player Name* starting at *1k*.\n\n"
        "**Place a bid**\n"
        "`!bid TT 2k`\n— Team *TT* bids *2k* on the current player.\n"
        "`!bid TT pass`\n— Team *TT* passes.\n\n"
        "**Status & recap**\n"
        "`!draftstatus`\n— Show current bidding status (who's on the clock, current bid).\n"
        "`!draftrecap`\n— Show entire bidding round progress.\n\n"
        "**Amount format**: use numbers with optional trailing *k* (e.g. *1k*, *20k*, *100k*)."
    )
    await ctx.send(help_text)


# Run the bot with the token
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise SystemExit("Set DISCORD_TOKEN in your environment.")
bot.run(token)