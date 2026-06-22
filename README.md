# Card Sniper

**The Problem**
As a video editor at Aditor, checking Trello constantly to catch new cards before someone else takes them is exhausting. Cards appear at any time and disappear fast.

**The Solution**
Card Sniper runs silently in the background on your computer and scans all Trello boards every 2 minutes. The moment an eligible card lands in a **Next Up** list, it sends you a Slack DM with a Claim button — so you can grab it before anyone else.

**Features**
- Scans all your Trello boards every 2 minutes
- Instant Slack DM with a one-tap Claim button
- Filters out health/wellness brands automatically
- Suppresses alerts while you already have a card in progress
- Weekly cap (default 4 cards) to avoid overloading
- Fully customisable filters — your config, your rules

---

## Installation

### Step 1 — Install Python
Download and install Python 3.12 from the Microsoft Store (search "Python 3.12") or from python.org.

### Step 2 — Download this repo
Click the green **Code** button above → **Download ZIP** → unzip it somewhere on your computer (e.g. `C:\Card Sniper`).

### Step 3 — Set up your config
1. Inside the folder, find `sniper_config.example.json`
2. Copy it and rename the copy to `sniper_config.json`
3. Open `sniper_config.json` in Notepad and fill in:

| Field | What to put |
|-------|------------|
| `editor_label` | Your Trello label name (e.g. `mariab`) — ask Jelena if unsure |
| `slack_user_id` | Your Slack user ID — go to your Slack profile → ⋯ menu → Copy member ID |
| `trello_token` | Ask Jelena for the shared token, or generate your own (see below) |
| `slack_token` | Ask Jelena for this |

**To get your own Trello token:** open this URL in your browser (replacing YOUR_API_KEY with the key already in the config):
```
https://trello.com/1/authorize?expiration=never&scope=read&response_type=token&name=CardSniper&key=YOUR_API_KEY
```
Click Allow, copy the token shown, paste it into your config.

### Step 4 — Install pytest (one-time)
Open a terminal in your Card Sniper folder and run:
```
pip install pytest
```

### Step 5 — Run the tests
```
python -m pytest test_card_sniper_core.py -q
```
All 30 tests should pass. If they do, you're good to go.

### Step 6 — Set it up to run automatically
Open PowerShell and run this (replace the path if you unzipped somewhere different):

```powershell
$action = New-ScheduledTaskAction `
    -Execute (Get-Command python).Source `
    -Argument "`"C:\Card Sniper\card_sniper.py`" --loop" `
    -WorkingDirectory "C:\Card Sniper"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask -TaskName "Card Sniper" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force
Start-ScheduledTask -TaskName "Card Sniper"
```

That's it. The sniper is now running in the background and will start automatically every time you log in.

---

## Customising your filters

Open `sniper_config.json` and adjust:

- **`weekly_cap`** — max cards you want per week (default: 4)
- **`health_blocklist_brands`** — brands you don't want to work on (substring match on board name)
- **`excluded_board_names`** — specific boards to skip entirely
- **`allowlist`** — if set, ONLY scan these boards (leave as `[]` to scan everything)
- **`min_script_len`** — minimum script length in characters to consider a card ready (default: 50)

After changing the config, restart the sniper:
```
Stop-ScheduledTask -TaskName "Card Sniper"
Start-ScheduledTask -TaskName "Card Sniper"
```

---

## Stopping / uninstalling

To stop temporarily:
```
Stop-ScheduledTask -TaskName "Card Sniper"
```

To remove completely:
```
Unregister-ScheduledTask -TaskName "Card Sniper" -Confirm:$false
```
