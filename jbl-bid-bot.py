import discord
from discord.ext import commands, tasks
import json
import os
import signal
import atexit
import asyncio
from datetime import datetime
from pathlib import Path

# Create bot folder if not present
APPDATA_FOLDER = os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming"
BOT_FOLDER = Path(APPDATA_FOLDER) / "JuntaBot"
BOT_FOLDER.mkdir(parents=True, exist_ok=True)

# Draft state file
DATA_FILE = BOT_FOLDER / "draft-bot-data.json"

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
intents.presences = False
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Load draft state --- #
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        saved_data = json.load(f)
else:
    saved_data = {"draft": [], "round": []}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(saved_data, f)

# --- Core state helpers --- #
def draft_is_active():
    return len(saved_data["draft"]) > 0 and any(entry["ClaimTm"] == "" for entry in saved_data["draft"])

def next_team_to_introduce():
    for entry in saved_data["draft"]:
        if entry["Player"] == "":
            return entry["IntroTm"]
    return None

def on_clock_team():
    """Team whose action is next: to bid/pass while a round is live, else to nominate."""
    if len(saved_data["draft"]) == 0:
        return None
    if len(saved_data["round"]) == 0:
        return next_team_to_introduce()
    return saved_data["round"][0]["Tm"]

def round_is_live():
    return len(saved_data["draft"]) > 0 and len(saved_data["round"]) > 0

def team_entry(team):
    for entry in saved_data["draft"]:
        if entry["IntroTm"] == team:
            return entry
    return None

def team_controller(team):
    """User id allowed to act for a team, or '' if open to everyone."""
    entry = team_entry(team)
    return entry.get("Ctrl", "") if entry else ""

def actor_allowed(interaction, team):
    """True if this user may act for the team (controller match, or team is open)."""
    ctrl = team_controller(team)
    return ctrl == "" or str(interaction.user.id) == ctrl

def denied_message(team):
    ctrl = team_controller(team)
    if ctrl:
        return f"❌ **{team}** is controlled by <@{ctrl}> — you can't act for them."
    return "❌ Unknown team."

def parse_controller(raw):
    """Accept a Discord mention (<@id> / <@!id>), a bare user id, or -1 / blank for open."""
    s = (raw or "").strip()
    if s in ("", "-1"):
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits if digits else None

def set_turn_clock():
    saved_data["turn_started_at"] = datetime.now().isoformat(timespec="seconds")
    saved_data["last_reminder_min"] = 0
    save_data()

def clear_turn_clock():
    saved_data["turn_started_at"] = ""
    saved_data["last_reminder_min"] = 0
    save_data()

def fmt_elapsed():
    ts = saved_data.get("turn_started_at", "")
    if not ts:
        return ""
    delta = datetime.now() - datetime.fromisoformat(ts)
    secs = max(0, int(delta.total_seconds()))
    m, s = divmod(secs, 60)
    return f"{m}m {s:02d}s"

# --- Actions --- #
def parse_amount(raw):
    s = raw.strip()
    if s.lower().endswith("k"):
        s = s[:-1]
    if not s.isdigit():
        return None
    return int(s)

def declare_winner():
    """End the round: the single remaining team wins at the current bid."""
    roundList = saved_data["round"]
    winner = roundList[0]["Tm"]
    winnerAmt = roundList[0]["Amt"]
    playerName = ""
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
    saved_data["round"] = []
    clear_turn_clock()
    save_data()
    return f"WIN:{winner}:{playerName}:{winnerAmt}"

def do_nominate(player, amount_k):
    """Apply a nomination for the next team in rotation. Returns an error string, or '' on success."""
    if len(saved_data["draft"]) == 0:
        return "No draft in progress. Use `!startdraft` to begin."
    if len(saved_data["round"]) > 0:
        return "A player is already up for bid — nominate is only possible after a player is won."
    team = next_team_to_introduce()
    if team is None:
        return "The draft is already complete."
    if player.strip() == "":
        return "Player name cannot be empty."
    if amount_k is None:
        return "Invalid amount. Use a number (e.g., 1 for 1k)."

    for entry in saved_data["draft"]:
        if entry["IntroTm"] == team:
            if entry["MoneyLeft"] < amount_k:
                return f"Team '{team}' does not have enough money to nominate at {amount_k}k."
            entry["Player"] = player.strip()
            break

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

    first = structuredRoundList.pop(0)
    first["Amt"] = amount_k
    structuredRoundList.append(first)

    saved_data["round"] = structuredRoundList
    set_turn_clock()
    return ""

def do_bid(amount_k):
    """Apply a bid from whoever is on the clock. Returns an error string, or '' on success."""
    if not round_is_live():
        return "Nominate a player first — no one is up for bid yet."
    if amount_k is None:
        return "Invalid amount. Enter a number (e.g., 2 for 2k)."
    team = saved_data["round"][0]["Tm"]
    if amount_k <= saved_data["round"][-1]["Amt"]:
        return f"Bid must be greater than the current bid of {saved_data['round'][-1]['Amt']}k."
    for entry in saved_data["draft"]:
        if entry["IntroTm"] == team and entry["MoneyLeft"] < amount_k:
            return f"Team '{team}' does not have enough money to bid at {amount_k}k."

    roundList = saved_data["round"]
    first = roundList.pop(0)
    first["Amt"] = amount_k
    roundList.append(first)

    if len(roundList) == 1:
        # Sole remaining team raised their own bid: they win at the new amount
        return declare_winner()

    saved_data["round"] = roundList
    set_turn_clock()
    return ""

def do_pass():
    """Apply a pass from whoever is on the clock. Returns an error string, or '' on success."""
    if not round_is_live():
        return "Nominate a player first — no one is up for bid yet."

    passing_team = saved_data["round"][0]["Tm"]
    saved_data["round"].pop(0)

    if len(saved_data["round"]) == 1:
        # Everyone else has passed: the last team standing wins at the current bid
        return declare_winner()

    set_turn_clock()
    save_data()
    return f"PASS:{passing_team}"

# --- Shared recap table builder (used by the board footer and !cash) --- #
def build_recap_lines():
    """The DRAFT table exactly as !cash renders it: Tm / Cash / Player / Wn / Amt."""
    draft = saved_data.get("draft", [])
    if not draft:
        return ["(no draft entries)"]

    team_w = max(len("Tm"), max((len(entry.get("IntroTm", "")) for entry in draft), default=0))
    money_w = max(len("Cash"), max((1 if entry.get("MoneyLeft", 0) == 0 else len(f"{entry['MoneyLeft']}k") for entry in draft), default=0))
    player_w = max(len("Player"), max((len(entry.get("Player", "")) for entry in draft), default=0))
    claim_w = max(len("Wn"), max((len(entry.get("ClaimTm", "")) for entry in draft), default=0))
    amt_w = max(len("Amt"), max((1 if entry.get("Amt", 0) == 0 else len(f"{entry['Amt']}k") for entry in draft), default=0))
    header = f"{ 'Tm'.ljust(team_w) }  { 'Cash'.rjust(money_w) }  { 'Player'.ljust(player_w) }  { 'Wn'.ljust(claim_w) }  { 'Amt'.rjust(amt_w) }"
    lines = [header, "-" * len(header)]
    for entry in draft:
        amt_str = "" if entry.get("Amt", 0) == 0 else f"{entry['Amt']}k"
        money_str = f"{entry['MoneyLeft']}k"
        lines.append(
            f"{ entry.get('IntroTm','').ljust(team_w)  }  { money_str.rjust(money_w) }  { entry.get('Player','').ljust(player_w) }  { entry.get('ClaimTm','').ljust(claim_w) }  { amt_str.rjust(amt_w) }"
        )
    return lines

def build_recap_table():
    """Board-footer version of the !cash DRAFT table (identical data and format)."""
    return "\n".join(build_recap_lines())

def add_recap_footer_field(embed):
    """Add the recap table as the last full-width field — renders at the bottom (footer) of the board."""
    table = build_recap_table()
    if len(table) > 1010:  # keep room for the ``` fences inside the 1024-char field limit
        table = table[:1007] + "..."
    embed.add_field(name="\u200b", value=f"```text\n{table}\n```", inline=False)

# --- Board embed builder --- #
def build_board_embed():
    embed = discord.Embed(title="⚾ JBL Free Agent Bidding Board", color=0x6D4AFF)

    if len(saved_data["draft"]) == 0:
        embed.description = "No draft in progress. Use `!startdraft TT 100, OO 150, ...` to begin."
        return embed

    code = on_clock_team()
    elapsed = fmt_elapsed()

    if not round_is_live():
        if code is None:
            embed.description = "🧢 Free agent bidding round complete ⚾"
        else:
            line = f"📝 **{code}** is up to nominate a player."
            if elapsed:
                line += f" (⏱ {elapsed})"
            embed.description = line
        add_recap_footer_field(embed)
        return embed

    playerName = ""
    for entry in saved_data["draft"]:
        if entry["Player"] != "":
            playerName = entry["Player"]
        else:
            break
    amount = saved_data["round"][-1]["Amt"]
    teamName = saved_data["round"][-1]["Tm"]
    next_to_bid = ", ".join(entry["Tm"] for entry in saved_data["round"][1:]) or "—"

    clock_line = f"**{code}**" + (f" (⏱ {elapsed})" if elapsed else "")

    embed.add_field(name="⏰ On the clock", value=clock_line, inline=True)
    embed.add_field(name="🔨 Up for bid", value=f"**{playerName}**", inline=True)
    embed.add_field(name="💰 High bid", value=f"**{amount}k** — {teamName}", inline=True)
    embed.add_field(name="⏭ Still in (order)", value=next_to_bid, inline=False)

    add_recap_footer_field(embed)

    return embed

# --- Recap (cash, players won, winning amounts) --- #
async def send_draft_recap(channel):
    if not saved_data.get("draft", []):
        await channel.send("❌ No draft available. Use !startdraft to begin.")
        return
    msg = "```text\n" + "\n".join(build_recap_lines()) + "\n```"
    await channel.send(msg)

# --- Board refresh --- #
async def refresh_board():
    cid = saved_data.get("board_channel_id")
    mid = saved_data.get("board_message_id")
    if not cid or not mid:
        return False
    channel = bot.get_channel(cid)
    if channel is None:
        try:
            channel = await bot.fetch_channel(cid)
        except Exception:
            return False
    try:
        msg = await channel.fetch_message(mid)
        await msg.edit(embed=build_board_embed(), view=build_board_view())
        return True
    except Exception:
        return False

async def post_board(channel):
    """Post a fresh board message in the given channel and track it as the live board."""
    msg = await channel.send(embed=build_board_embed(), view=build_board_view())
    saved_data["board_channel_id"] = channel.id
    saved_data["board_message_id"] = msg.id
    save_data()
    try:
        await msg.pin(reason="JBL draft board")
    except Exception:
        pass
    return msg

# --- On-the-clock reminder loop --- #
@tasks.loop(seconds=10)
async def reminder_loop():
    """While a team is on the clock, remind the channel once per minute and refresh the board."""
    code = on_clock_team()
    ts = saved_data.get("turn_started_at", "")
    if code is None or not ts:
        saved_data["last_reminder_min"] = 0
        return

    try:
        elapsed_secs = int((datetime.now() - datetime.fromisoformat(ts)).total_seconds())
    except Exception:
        return
    if elapsed_secs < 60:
        return

    minutes = elapsed_secs // 60
    if minutes <= saved_data.get("last_reminder_min", 0):
        return  # already reminded for this minute

    saved_data["last_reminder_min"] = minutes
    save_data()

    cid = saved_data.get("board_channel_id") or saved_data.get("last_channel_id")
    if not cid:
        return
    channel = bot.get_channel(cid)
    if channel is None:
        return

    ctrl = team_controller(code)
    ping = f" <@{ctrl}>" if ctrl else ""
    try:
        await channel.send(f"⏰ **{code}**{ping} has been on the clock for {minutes} minute{'s' if minutes > 1 else ''} (⏱ {fmt_elapsed()})")
    except Exception:
        pass
    await refresh_board()

@reminder_loop.before_loop
async def _wait_before_reminding():
    await bot.wait_until_ready()

# --- Modals --- #
class NominateModal(discord.ui.Modal, title="Nominate a player"):
    player = discord.ui.TextInput(label="Player name", placeholder="e.g. Shohei Ohtani", max_length=60, required=True)
    amount = discord.ui.TextInput(label="Opening bid in k", placeholder="e.g. 1", max_length=10, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        team = next_team_to_introduce()
        if team and not actor_allowed(interaction, team):
            await interaction.response.send_message(denied_message(team), ephemeral=True)
            return
        err = do_nominate(self.player.value, parse_amount(self.amount.value))
        if err:
            await interaction.response.send_message(f"❌ {err}", ephemeral=True)
            return
        await interaction.response.defer()
        if not await refresh_board():
            await interaction.followup.send("⚠️ Board message not found — run `!board` to recreate it.", ephemeral=True)

class BidModal(discord.ui.Modal, title="Place a bid"):
    amount = discord.ui.TextInput(label="Bid amount in k", placeholder="e.g. 2", max_length=10, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if round_is_live():
            team = saved_data["round"][0]["Tm"]
            if not actor_allowed(interaction, team):
                await interaction.response.send_message(denied_message(team), ephemeral=True)
                return
        result = do_bid(parse_amount(self.amount.value))
        if result.startswith("WIN:"):
            _, winner, playerName, winnerAmt = result.split(":")
            await interaction.response.send_message(f"💵 **{winner}** wins **{playerName}** for **${winnerAmt}k**!")
            await refresh_board()
            return
        if result:
            await interaction.response.send_message(f"❌ {result}", ephemeral=True)
            return
        await interaction.response.defer()
        if not await refresh_board():
            await interaction.followup.send("⚠️ Board message not found — run `!board` to recreate it.", ephemeral=True)

# --- Board buttons (open to everyone) --- #
class BoardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔨 Bid", style=discord.ButtonStyle.success, custom_id="jbl:bid")
    async def bid_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not round_is_live():
            await interaction.response.send_message("❌ Nominate a player first.", ephemeral=True)
            return
        team = saved_data["round"][0]["Tm"]
        if not actor_allowed(interaction, team):
            await interaction.response.send_message(denied_message(team), ephemeral=True)
            return
        await interaction.response.send_modal(BidModal())

    @discord.ui.button(label="⏭ Pass", style=discord.ButtonStyle.secondary, custom_id="jbl:pass")
    async def pass_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not round_is_live():
            await interaction.response.send_message("❌ Nominate a player first.", ephemeral=True)
            return
        team = saved_data["round"][0]["Tm"]
        if not actor_allowed(interaction, team):
            await interaction.response.send_message(denied_message(team), ephemeral=True)
            return
        result = do_pass()
        if result.startswith("WIN:"):
            _, winner, playerName, winnerAmt = result.split(":")
            await interaction.response.send_message(f"💵 **{winner}** wins **{playerName}** for **${winnerAmt}k**!")
            await refresh_board()
            return
        if result.startswith("PASS:"):
            await interaction.response.defer()
            if not await refresh_board():
                await interaction.followup.send("⚠️ Board message not found — run `!board` to recreate it.", ephemeral=True)
            return
        await interaction.response.send_message(f"❌ {result}", ephemeral=True)

    @discord.ui.button(label="📋 Nominate", style=discord.ButtonStyle.primary, custom_id="jbl:nominate")
    async def nominate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if round_is_live():
            await interaction.response.send_message("❌ A player is still up for bid — nominate happens after a win.", ephemeral=True)
            return
        team = next_team_to_introduce()
        if team and not actor_allowed(interaction, team):
            await interaction.response.send_message(denied_message(team), ephemeral=True)
            return
        await interaction.response.send_modal(NominateModal())

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, custom_id="jbl:refresh")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not await refresh_board():
            await interaction.followup.send("⚠️ Board message not found — run `!board` to recreate it.", ephemeral=True)

def build_board_view():
    """View instance with buttons visually enabled/disabled to match the current state."""
    view = BoardView()
    live = round_is_live()
    can_nominate = (not live) and on_clock_team() is not None and draft_is_active()
    view.bid_button.disabled = not live
    view.pass_button.disabled = not live
    view.nominate_button.disabled = not can_nominate
    return view

# --- Events --- #
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    bot.add_view(BoardView())  # re-route persistent button interactions after restart
    if not reminder_loop.is_running():
        reminder_loop.start()

# --- COMMANDS --- #
@bot.command()
async def startdraft(ctx, *, teams):
    """!startdraft OO 630 @jimihaze, BC 570 -1, SH 363 @shorry — team, cash, controller (@user or -1 for open)."""
    teamList = teams.split(",")
    if len(teamList) < 2:
        await ctx.send("❌ At least two teams are required to start a draft.")
        return
    for tm in teamList:
        parts = tm.strip().split(" ")
        if len(parts) not in (2, 3):
            await ctx.send(f"❌ Invalid team format: '{tm.strip()}'. Use 'TeamCode Money [@user|-1]' format.")
            return

    structuredTeamList = []
    for tm in teamList:
        parts = tm.strip().split()
        intro = parts[0].upper()
        money_str = parts[1].lower()
        if money_str.endswith("k"):
            money_str = money_str[:-1]
        try:
            money_val = int(money_str)
        except Exception:
            money_val = 0
        ctrl_raw = parts[2] if len(parts) == 3 else ""
        ctrl = parse_controller(ctrl_raw)
        if ctrl is None:
            await ctx.send(f"❌ Invalid controller for team '{intro}': use a Discord @mention, a user id, or -1 for open control.")
            return
        duplicate = any(e["IntroTm"] == intro for e in structuredTeamList)
        if duplicate:
            await ctx.send(f"❌ Duplicate team code: '{intro}'.")
            return
        structuredTeamList.append({
            "IntroTm": intro,
            "MoneyLeft": money_val,
            "Ctrl": ctrl,
            "ClaimTm": "",
            "Player": "",
            "Amt": 0,
        })

    saved_data["draft"] = structuredTeamList
    saved_data["round"] = []
    saved_data["last_channel_id"] = ctx.channel.id
    clear_turn_clock()
    save_data()
    await refresh_board()          # update the existing board, if one is pinned
    await post_board(ctx.channel)  # post a fresh board where the draft was started

@bot.command()
async def board(ctx):
    """Create (or recreate) the visual draft board in the current channel."""
    await post_board(ctx.channel)

@bot.command()
async def cash(ctx):
    await send_draft_recap(ctx.channel)

@bot.command()
async def drafthelp(ctx):
    help_text = (
        "❓ **JBL Draft Bot — How it works**\n\n"
        "`!startdraft TT 100 @jimihaze7, OO 150 -1, MN 175 -1` — teams + cash + userid, in pick order.\n"
        "`!cash` — every team's remaining cash, players won, and winning amounts in draft order.\n"
        "`!board` — post the draft board (pins it). Everyone can use the buttons:\n"
        "　📋 **Nominate** — player name, opening bid (only between picks; nomination goes to the next team in rotation).\n"
        "　🔨 **Bid** — amount only; must beat the current bid. Applies to the team on the clock.\n"
        "　⏭ **Pass** — one click, passes the team on the clock.\n"
        "　🔄 **Refresh** — redraw the board, updating the on-the-clock timer.\n\n"
        "⏰ While a team is on the clock, the channel gets a reminder every minute and the board auto-refreshes."
    )
    await ctx.send(help_text)

# --- Bot shutdown methods --- #
async def _shutdown():
    try:
        reminder_loop.cancel()
    except Exception:
        pass
    try:
        save_data()
    except Exception:
        pass
    try:
        await bot.close()
    except Exception:
        pass

def _request_shutdown(signum=None, frame=None):
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_shutdown())
    except Exception:
        pass

def _cleanup():
    try:
        save_data()
    except Exception:
        pass

try:
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)
except Exception:
    pass

atexit.register(_cleanup)

token = os.getenv("DISCORD_TOKEN")
if not token:
    raise SystemExit("Set DISCORD_TOKEN in your environment.")
try:
    bot.run(token)
finally:
    _cleanup()
