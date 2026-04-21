import os
import json
import logging
from flask import Flask, request, jsonify
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

slack_app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

SLACK_USER_ID = os.environ["SLACK_USER_ID"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")

# Map of "Project Name" -> "clockify_project_id"
CLOCKIFY_PROJECTS: dict[str, str] = json.loads(os.environ.get("CLOCKIFY_PROJECTS", "{}"))


def send_daily_prompt():
    """Fire at 4:45 PM on weekdays — posts to the configured channel."""
    logger.info("Sending daily prompt...")
    try:
        slack_app.client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            text=(
                f":clock445: <@{SLACK_USER_ID}> *End-of-day check-in!*\n\n"
                "What did you work on today? Use `/timesheet` to log, like:\n"
                "> `/timesheet 2h fixing the login bug, 1h code review, 30min planning`\n\n"
                "I'll grab your calendar meetings automatically and log everything to Clockify."
            ),
        )
        logger.info("Daily prompt sent.")
    except Exception as e:
        logger.error(f"Failed to send daily prompt: {e}")


def process_time_entries(text, user_id, say):
    """Shared logic for processing time entries from both DMs and slash commands."""
    try:
        from clockify import ClockifyClient
        from calendar_client import GoogleCalendarClient
        from ai_parser import parse_time_entries

        tz = pytz.timezone(TIMEZONE)
        today = datetime.now(tz).date()

        # Parse manual entries — pass project names so Gemini can assign them
        project_names = list(CLOCKIFY_PROJECTS.keys()) if CLOCKIFY_PROJECTS else None
        entries = parse_time_entries(text, today, project_names)
        logger.info(f"Parsed entries: {entries}")

        if not entries:
            logger.warning("No entries parsed from text — check Gemini API key or input format")
            say(":thinking_face: Couldn't parse any entries. Try something like: _'2h on bug fixes, 1h standup'_")
            return

        # Fetch today's calendar meetings
        try:
            meetings = GoogleCalendarClient().get_todays_meetings(TIMEZONE)
        except Exception as e:
            logger.warning(f"Calendar fetch skipped: {e}")
            meetings = []

        clockify = ClockifyClient(tz)
        logged = []
        fallback_project = os.environ.get("CLOCKIFY_DEFAULT_PROJECT_ID")

        # Stack manual entries from 9 AM
        cursor = tz.localize(datetime.combine(today, datetime.min.time()).replace(hour=9))
        for entry in entries:
            end = cursor + timedelta(minutes=entry["duration_minutes"])
            project_id = CLOCKIFY_PROJECTS.get(entry.get("project", ""), fallback_project)
            project_label = entry.get("project") or "default"
            logger.info(f"Logging entry: {entry['description']} | {entry['duration_str']} | project: {project_label}")
            result = clockify.create_entry(
                description=entry["description"],
                start=cursor,
                end=end,
                project_id=project_id,
            )
            if result:
                logged.append(f"• {entry['description']} — {entry['duration_str']} _{project_label}_")
            else:
                logger.warning(f"Clockify failed to create entry: {entry['description']}")
            cursor = end

        # Log meetings using their real start/end times — skip any already logged today
        meetings_project = os.environ.get("CLOCKIFY_MEETINGS_PROJECT_ID") or fallback_project
        existing = clockify.get_todays_descriptions(today)
        for m in meetings:
            desc = f"Meeting: {m['summary']}"
            if desc in existing:
                logger.info(f"Skipping duplicate meeting entry: {desc}")
                continue
            if clockify.create_entry(
                description=desc,
                start=m["start_dt"],
                end=m["end_dt"],
                project_id=meetings_project,
            ):
                logged.append(f"• Meeting: {m['summary']} — {m['duration_str']}")

        if logged:
            say(":white_check_mark: *Logged to Clockify!*\n" + "\n".join(logged))
        else:
            say(
                ":thinking_face: Couldn't parse any entries. "
                "Try something like: _'2h on bug fixes, 1h standup'_"
            )

    except Exception as e:
        logger.error(f"Error processing entries: {e}", exc_info=True)
        say(f":x: Something went wrong: {e}")



@slack_app.command("/timesheet")
def handle_timesheet_command(ack, say, command):
    """Handle /timesheet slash command."""
    ack()  # Acknowledge immediately to avoid Slack timeout

    user_id = command["user_id"]
    text = (command.get("text") or "").strip()

    if not text:
        say(
            ":spiral_notepad: *Timesheet Bot*\n\n"
            "Log your time like this:\n"
            "> `/timesheet 2h fixing login bug, 1h code review, 30min planning`\n\n"
            "I'll parse your entries and log them to Clockify. :clockify:"
        )
        return

    say(":hourglass_flowing_sand: Processing your time entries…")
    process_time_entries(text, user_id, say)


flask_app = Flask(__name__)
handler = SlackRequestHandler(slack_app)


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


@flask_app.route("/slack/commands", methods=["POST"])
def slack_commands():
    return handler.handle(request)


@flask_app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    tz = pytz.timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        send_daily_prompt,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=45, timezone=tz),
    )
    scheduler.start()
    logger.info(f"Scheduler running — daily prompt at 4:45 PM {TIMEZONE}")

    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)