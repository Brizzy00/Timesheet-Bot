# Daily Timesheet Bot

A Slack bot that messages you every weekday at 4:45 PM and automatically logs your tasks and Google Calendar meetings to Clockify.

**How it works:**
1. Bot posts in your Slack channel at 4:45 PM — "What did you work on today?"
2. You reply with `/timesheet 2h fixing the login bug, 1h code review, 30min planning`
3. Gemini AI parses your message and assigns each task to the right Clockify project
4. Bot pulls your Google Calendar meetings for the day and logs those too
5. Everything lands in Clockify — tasks and meetings combined, no overlapping times

---

## Commands

| Command | What it does |
|---|---|
| `/timesheet 2h bug fixes, 1h review` | Log time for today |
| `/timesheet yesterday 2h testing` | Log time for yesterday |
| `/timesheet monday 3h QA, 1h standup` | Log time for the most recent Monday |
| `/timesheet 2025-01-06 2h regression` | Log time for a specific date |
| `/backfill` | Scan since Jan 1 — lists every day with less than 8h logged |
| `/backfill Regression testing, bug fixes, code review` | Auto-fill all incomplete days using those tasks |

**Notes on `/backfill`:**
- A day is considered incomplete if it has **less than 8 hours** logged (not just missing entirely)
- When filling, tasks are distributed proportionally across the free 9am–5pm slots for each day
- Calendar meetings are added automatically and duplicates are skipped
- Public holidays are logged automatically to your holiday project

---

## Stack

| Service | Purpose |
|---|---|
| [Slack Bolt](https://github.com/slackapi/bolt-python) | Bot messaging |
| [Clockify API](https://clockify.me/developers-api) | Timesheet logging |
| [Google Calendar API](https://developers.google.com/calendar) | Auto-import meetings |
| [Gemini API](https://aistudio.google.com) | Parse free-text replies (free tier) |
| [Railway](https://railway.app) | Cloud hosting |

---

## Setup

### Prerequisites

- Slack workspace (admin access to create apps)
- Clockify account
- Google account
- [Gemini API key](https://aistudio.google.com/app/apikey) (free)
- [Railway account](https://railway.app) (free tier)
- Python 3.11+ installed locally (only needed for the one-time Google auth step)

---

### Step 1 — Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → *From scratch*
2. Name it (e.g. `Timesheet Bot`) and select your workspace
3. Go to **OAuth & Permissions** → add these Bot Token Scopes:
   - `chat:write`
   - `im:write`
   - `im:history`
   - `im:read`
   - `channels:read`
4. Click **Install to Workspace** → copy the **Bot Token** (`xoxb-...`) → save as `SLACK_BOT_TOKEN`
5. Go to **Basic Information** → copy the **Signing Secret** → save as `SLACK_SIGNING_SECRET`
6. Find your personal Slack User ID: open Slack → click your profile → `...` → **Copy member ID** → save as `SLACK_USER_ID`

---

### Step 2 — Get Clockify Credentials

1. Log into Clockify → avatar → **Profile Settings** → **API** tab → copy your API key → save as `CLOCKIFY_API_KEY`
2. Your **Workspace ID** is in the URL: `clockify.me/workspaces/WORKSPACE_ID/...` → save as `CLOCKIFY_WORKSPACE_ID`
3. For each of your Clockify projects, get the project ID from the URL and add it as `CLOCKIFY_<NAME>=<project_id>` — for example:
   - `CLOCKIFY_NHLMIS=686698e2dcbebb4dffba691d`
   - `CLOCKIFY_INFRASTRUCTURE=6867e8cf3aa1ec7de112cf16`
   - `CLOCKIFY_SHELFLIFE=68a2f87ab968421b4c697d80`
4. Add a dedicated project for calendar meetings → save as `CLOCKIFY_MEETINGS=<project_id>`
5. *(Optional)* Add a project for public holidays → save as `CLOCKIFY_PUBLICHOLIDAY=<project_id>`

The bot auto-discovers all `CLOCKIFY_<NAME>` vars and passes the names to Gemini for project matching. The first one alphabetically is used as the fallback when no project matches a task.

---

### Step 3 — Get Your Gemini API Key (Free)

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account → **Create API Key**
3. Copy the key → save as `GEMINI_API_KEY`

> No billing required — the free tier (gemini-2.5-flash: 1,500 req/day, 15 req/min) is enough for normal daily use.

---

### Step 4 — Set Up Google Calendar (run once locally)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create or select a project
2. Search for **Google Calendar API** and enable it
3. Go to **APIs & Services → Credentials** → **Create Credentials** → **OAuth 2.0 Client IDs**
   - Application type: **Desktop app**
   - Download the JSON file and rename it to `google_credentials.json`
   - Place it in this project folder
4. Run the auth setup script:

```bash
pip install -r requirements.txt
python setup_google_auth.py
```

A browser window opens — sign in and allow access. The script prints a JSON block in the terminal.

5. Copy the entire printed JSON (one line) → save as `GOOGLE_TOKEN_JSON`

---

### Step 5 — Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select your repo
3. Go to your service → **Variables** tab → add all environment variables:

| Variable | Value |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-...` |
| `SLACK_SIGNING_SECRET` | `...` |
| `SLACK_USER_ID` | `U...` — your personal Slack user ID |
| `SLACK_CHANNEL_ID` | `C...` — channel where the bot posts the daily prompt |
| `CLOCKIFY_API_KEY` | `...` |
| `CLOCKIFY_WORKSPACE_ID` | `...` |
| `CLOCKIFY_MEETINGS` | Project ID for calendar meetings |
| `CLOCKIFY_PUBLICHOLIDAY` | Project ID for public holidays |
| `CLOCKIFY_<NAME>` | One var per project (e.g. `CLOCKIFY_NHLMIS`, `CLOCKIFY_INFRASTRUCTURE`) |
| `GOOGLE_TOKEN_JSON` | `{"token":"..."}` printed by setup script |
| `GEMINI_API_KEY` | `...` |
| `TIMEZONE` | e.g. `Africa/Lagos` |
| `COUNTRY_CODE` | ISO country code for public holidays (e.g. `NG`, `US`, `GB`) |

4. Go to **Settings → Networking → Generate Domain** → copy your public URL

**Setting up projects:**

Add one `CLOCKIFY_<NAME>` variable per project. The name becomes the label Gemini uses to match tasks. Example:

```
CLOCKIFY_NHLMIS=686698e2dcbebb4dffba691d
CLOCKIFY_INFRASTRUCTURE=6867e8cf3aa1ec7de112cf16
CLOCKIFY_SHELFLIFE=68a2f87ab968421b4c697d80
```

**Improving project matching with keywords:**

If Gemini doesn't assign tasks to the right project, add a `CLOCKIFY_<NAME>_KEYWORDS` var with comma-separated hints:

```
CLOCKIFY_INFRASTRUCTURE_KEYWORDS=staging release, prod release, deployment, hotfix
CLOCKIFY_NHLMIS_KEYWORDS=regression testing, PSM, RMS, assigned tickets, QA
```

Gemini uses these hints to route tasks even when the description doesn't match the project name exactly.

---

### Step 5b — Add the Bot to Your Channel

1. In Slack, open the channel you want the bot to post in
2. Click the channel name → **Integrations** → **Add an App** → find and add your bot
3. Get the Channel ID: right-click the channel → **Copy Link** — the ID starts with `C` at the end of the URL → save as `SLACK_CHANNEL_ID`

---

### Step 6 — Connect Slack to Railway

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → your app → **Event Subscriptions**
   - Toggle **Enable Events** ON
   - Set Request URL to `https://YOUR-RAILWAY-URL.railway.app/slack/events`
   - Wait for the green **Verified** checkmark
   - Under **Subscribe to bot events** → add `message.im`
   - **Save Changes** and reinstall if prompted

2. Go to **Slash Commands** → **Create New Command**:

   | Field | Value |
   |---|---|
   | Command | `/timesheet` |
   | Request URL | `https://YOUR-RAILWAY-URL.railway.app/slack/commands` |
   | Description | `Log your time to Clockify` |
   | Usage hint | `2h bug fixes, 1h review \| yesterday 2h testing \| 2025-01-06 3h QA` |

3. **Create another New Command** for backfill:

   | Field | Value |
   |---|---|
   | Command | `/backfill` |
   | Request URL | `https://YOUR-RAILWAY-URL.railway.app/slack/commands` |
   | Description | `Find days with less than 8h logged — or auto-fill them with your tasks` |
   | Usage hint | `[Regression testing, bug fixes, code review]` |

4. Save and reinstall the app if prompted

---

### Step 7 — Test It

**Log today's time:**
```
/timesheet 2h writing test cases, 1h bug bash, 30min standup
```

**Find incomplete days:**
```
/backfill
```
The bot lists every weekday since Jan 1 with less than 8 hours logged, showing how much is already there and how much is still needed. Calendar meetings on those days are noted and will be added automatically.

**Auto-fill all incomplete days:**
```
/backfill Regression testing, bug fixes, code review
```
Tasks are distributed proportionally across each day's free 9am–5pm slots. Meetings are added automatically. Duplicates are skipped.

**Log a specific past day manually:**
```
/timesheet 2025-01-06 2h regression testing, 3h bug fixes
```

At **4:45 PM on weekdays** the bot will automatically prompt you in your channel.

---

## Project Structure

```
daily-timesheet-bot/
├── main.py              # Slack bot + 4:45 PM scheduler
├── clockify.py          # Clockify API client
├── calendar_client.py   # Google Calendar client
├── ai_parser.py         # Gemini parses your text into time entries
├── setup_google_auth.py # Run once locally for Google Calendar auth
├── requirements.txt
├── Procfile
└── .env.example         # Copy to .env and fill in your values
```

---

## Troubleshooting

**Bot not posting in the channel**
- Make sure the bot is added to the channel (channel settings → Integrations → Add an App)
- Confirm `SLACK_CHANNEL_ID` is correct (should start with `C`)

**Slash commands not working**
- Verify the Request URL is verified in Slack (green checkmark)
- Check Railway logs for errors

**Clockify entries not appearing**
- Double-check `CLOCKIFY_WORKSPACE_ID` (look at the URL in Clockify)
- Verify the API key is correct
- If your workspace has "Project required" enabled, every `CLOCKIFY_<NAME>` var must have a valid project ID

**All tasks going to the wrong project**
- Add `CLOCKIFY_<NAME>_KEYWORDS` vars so Gemini knows which task types belong to each project
- Check Railway logs for `No project matched` warnings

**Calendar meetings not logged**
- `GOOGLE_TOKEN_JSON` may be invalid — re-run `setup_google_auth.py` and update the env var
- Make sure Google Calendar API is enabled in Cloud Console

**Gemini rate limit errors**
- The bot uses gemini-2.5-flash (1,500 req/day free). Normal daily use is 1–2 calls per `/timesheet` and 1 call total for `/backfill` regardless of how many days it fills
- If you hit the limit, wait until midnight UTC for the quota to reset

**Timezone is wrong**
- `TIMEZONE` must be a valid [tz database name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), e.g.:
  - `Africa/Lagos` — West Africa (UTC+1)
  - `America/New_York` — US Eastern
  - `Europe/London` — UK
