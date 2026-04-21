# Daily Timesheet Bot

A Slack bot that messages you every weekday at 4:45 PM, asks what you worked on, and automatically logs your tasks and calendar meetings to Clockify.

**How it works:**
1. Bot DMs you at 4:45 PM — "What did you work on today?"
2. You reply naturally: `2h fixing the login bug, 1h code review, 30min planning`
3. Gemini AI parses your message into structured time entries
4. Bot pulls your Google Calendar meetings for the day
5. Everything gets logged to Clockify — tasks and meetings

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
3. *(Optional)* Open a project in Clockify — the ID is in the URL → save as `CLOCKIFY_DEFAULT_PROJECT_ID`
4. *(Optional)* Do the same for a meetings-specific project → save as `CLOCKIFY_MEETINGS_PROJECT_ID`

---

### Step 3 — Get Your Gemini API Key (Free)

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account → **Create API Key**
3. Copy the key → save as `GEMINI_API_KEY`

> No billing required — the free tier is more than enough for this bot.

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
| `SLACK_USER_ID` | `U...` |
| `CLOCKIFY_API_KEY` | `...` |
| `CLOCKIFY_WORKSPACE_ID` | `...` |
| `CLOCKIFY_DEFAULT_PROJECT_ID` | *(optional)* |
| `CLOCKIFY_MEETINGS_PROJECT_ID` | *(optional)* |
| `GOOGLE_TOKEN_JSON` | `{"token":"..."}` |
| `GEMINI_API_KEY` | `...` |
| `TIMEZONE` | e.g. `Africa/Lagos` |

4. Go to **Settings → Networking → Generate Domain** → copy your public URL

---

### Step 6 — Connect Slack to Railway

1. Go back to your Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Event Subscriptions** → toggle **Enable Events** ON
3. Set the Request URL to:
   ```
   https://YOUR-RAILWAY-URL.railway.app/slack/events
   ```
   Wait for the green **Verified** checkmark
4. Under **Subscribe to bot events** → add `message.im`
5. **Save Changes** and reinstall the app if prompted

---

### Step 7 — Test It

Open Slack and DM your bot:

```
2h writing test cases, 1h bug bash, 30min standup
```

The bot will reply with a Clockify confirmation listing all logged entries. At **4:45 PM on weekdays** it will message you automatically.

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

**Bot not responding in Slack**
- Check Railway logs for errors
- Make sure the Event Subscriptions URL is verified in Slack
- Confirm `SLACK_USER_ID` matches your actual Slack ID

**Clockify entries not appearing**
- Double-check `CLOCKIFY_WORKSPACE_ID` (look at the URL in Clockify)
- Verify the API key is correct

**Calendar meetings not logged**
- `GOOGLE_TOKEN_JSON` may be invalid — re-run `setup_google_auth.py` and update the env var
- Make sure Google Calendar API is enabled in Cloud Console

**Timezone is wrong**
- `TIMEZONE` must be a valid [tz database name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), e.g.:
  - `Africa/Lagos` — West Africa (UTC+1)
  - `America/New_York` — US Eastern
  - `Europe/London` — UK
