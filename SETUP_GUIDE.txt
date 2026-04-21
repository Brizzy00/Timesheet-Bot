================================================================
       DAILY TIMESHEET BOT — SETUP GUIDE
================================================================

WHAT IT DOES
------------
Every weekday at 4:45 PM, the bot DMs you on Slack and asks
what you worked on. You reply naturally (e.g. "2h fixing bugs,
1h code review") and it logs everything to Clockify. It also
pulls your Google Calendar meetings and logs those automatically.


PREREQUISITES
-------------
- A Slack workspace where you can create apps
- A Clockify account
- A Google account (for Calendar)
- A Google Gemini API key (free at aistudio.google.com)
- A Railway account for hosting (free at railway.app)
- Python 3.11+ installed locally (only needed for Google auth setup)


================================================================
STEP 1 — CREATE THE SLACK APP
================================================================

1. Go to https://api.slack.com/apps and click "Create New App"
   → Choose "From scratch"
   → Name it (e.g. "Timesheet Bot") and select your workspace

2. In the left sidebar, go to "OAuth & Permissions"
   → Scroll to "Bot Token Scopes" and add:
      - chat:write
      - im:write
      - im:history
      - im:read
      - channels:read

3. Click "Install to Workspace" at the top of the same page
   → Authorize it
   → Copy the Bot Token (starts with xoxb-...)
   → Save it as: SLACK_BOT_TOKEN

4. Go to "Basic Information" in the sidebar
   → Scroll to "App Credentials"
   → Copy the Signing Secret
   → Save it as: SLACK_SIGNING_SECRET

5. Find your personal Slack User ID:
   → Open Slack → click your name/profile picture
   → Click "Profile" → click the three dots (...)
   → Click "Copy member ID"
   → Save it as: SLACK_USER_ID


================================================================
STEP 2 — GET CLOCKIFY CREDENTIALS
================================================================

1. Log into Clockify → click your avatar (top right) →
   "Profile Settings" → "API" tab
   → Copy your API key
   → Save it as: CLOCKIFY_API_KEY

2. Your Workspace ID is in the URL when you're on Clockify:
   clockify.me/workspaces/WORKSPACE_ID/...
   → Save it as: CLOCKIFY_WORKSPACE_ID

3. (Optional) To assign entries to a project:
   → Open a project in Clockify — the ID is in the URL
   → Save it as: CLOCKIFY_DEFAULT_PROJECT_ID

4. (Optional) For a separate project just for meetings:
   → Same as above for your meetings project
   → Save it as: CLOCKIFY_MEETINGS_PROJECT_ID


================================================================
STEP 3 — GET YOUR GEMINI API KEY (FREE)
================================================================

1. Go to https://aistudio.google.com/app/apikey
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the key
   → Save it as: GEMINI_API_KEY

No billing required — the free tier is enough for this bot.


================================================================
STEP 4 — SET UP GOOGLE CALENDAR (run once on your PC)
================================================================

1. Go to https://console.cloud.google.com
   → Create a new project (or use an existing one)

2. Enable the Google Calendar API:
   → Search "Google Calendar API" → Enable it

3. Create OAuth credentials:
   → Go to "APIs & Services" → "Credentials"
   → Click "Create Credentials" → "OAuth 2.0 Client IDs"
   → Application type: "Desktop app"
   → Download the JSON file
   → Rename it to: google_credentials.json
   → Place it in the daily-timesheet-bot folder

4. Run the setup script on your PC:

      cd daily-timesheet-bot
      pip install -r requirements.txt
      python setup_google_auth.py

   → A browser window opens — sign in and allow access
   → The script prints a JSON block in the terminal

5. Copy the entire printed JSON (one long line)
   → Save it as: GOOGLE_TOKEN_JSON


================================================================
STEP 5 — DEPLOY TO RAILWAY
================================================================

1. Push the daily-timesheet-bot folder to a GitHub repo

2. Go to https://railway.app → "New Project"
   → "Deploy from GitHub repo" → select your repo

3. Once deployed, go to your service → "Variables" tab
   → Add all of the following environment variables:

      SLACK_BOT_TOKEN         = xoxb-...
      SLACK_SIGNING_SECRET    = ...
      SLACK_USER_ID           = U...
      CLOCKIFY_API_KEY        = ...
      CLOCKIFY_WORKSPACE_ID   = ...
      CLOCKIFY_DEFAULT_PROJECT_ID  = (optional)
      CLOCKIFY_MEETINGS_PROJECT_ID = (optional)
      GOOGLE_TOKEN_JSON       = {"token":"..."}
      GEMINI_API_KEY          = ...
      TIMEZONE                = Africa/Lagos

4. Go to "Settings" → "Networking" → "Generate Domain"
   → Copy the public URL (e.g. https://my-bot.railway.app)


================================================================
STEP 6 — CONNECT SLACK TO RAILWAY
================================================================

1. Go back to your Slack app at https://api.slack.com/apps

2. Click "Event Subscriptions" in the sidebar
   → Toggle "Enable Events" ON
   → Set Request URL to:
      https://YOUR-RAILWAY-URL.railway.app/slack/events
   → Wait for the green "Verified" checkmark

3. Under "Subscribe to bot events" → Add:
      message.im

4. Click "Save Changes"
   → Reinstall the app if prompted


================================================================
STEP 7 — TEST IT
================================================================

Open Slack and send a DM to your bot:

   "2h writing test cases, 1h bug bash, 30min standup"

The bot should reply with a Clockify confirmation listing
all logged entries including any calendar meetings from today.

At 4:45 PM on weekdays it will message you automatically.


================================================================
FILE STRUCTURE
================================================================

daily-timesheet-bot/
├── main.py              — Slack bot + 4:45 PM scheduler
├── clockify.py          — Clockify API client
├── calendar_client.py   — Google Calendar client
├── ai_parser.py         — Gemini parses your text into entries
├── setup_google_auth.py — Run once locally for Google auth
├── requirements.txt
├── Procfile
├── .env.example         — Copy to .env and fill in your values
└── SETUP_GUIDE.txt      — This file


================================================================
TROUBLESHOOTING
================================================================

Bot not responding in Slack?
  → Check Railway logs for errors
  → Make sure Event Subscriptions URL is verified in Slack
  → Confirm SLACK_USER_ID matches your actual Slack ID

Clockify entries not appearing?
  → Double-check CLOCKIFY_WORKSPACE_ID (check the URL)
  → Make sure the API key has write access

Calendar meetings not logged?
  → GOOGLE_TOKEN_JSON may be invalid — re-run setup_google_auth.py
  → Make sure Google Calendar API is enabled in Cloud Console

Timezone wrong?
  → TIMEZONE must be a valid pytz zone, e.g.:
      Africa/Lagos     (West Africa, UTC+1)
      America/New_York (US Eastern)
      Europe/London    (UK)
  → Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

================================================================
