import os
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
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")


def send_daily_prompt():
    """Fire at 4:45 PM on weekdays — DMs the user to log their day."""
    logger.info("Sending daily prompt...")
    try:
        result = slack_app.client.conversations_open(users=SLACK_USER_ID)
        channel_id = result["channel"]["id"]
        slack_app.client.chat_postMessage(
            channel=channel_id,
            text=(
                ":clock445: *End-of-day check-in!*\n\n"
                "What did you work on today? Reply naturally, like:\n"
                "> _2h fixing the login bug, 1h code review, 30min planning_\n\n"
                "I'll grab your calendar meetings automatically and log everything to Clockify."
            ),
        )
        logger.info("Daily prompt sent.")
    except Exception as e:
        logger.error(f"Failed to send daily prompt: {e}")


@slack_app.event("message")
def handle_dm(event, say):
    """Process any DM reply as a time-entry log."""
    if event.get("bot_id") or event.get("subtype"):
        return

    user_id = event.get("user")
    channel_type = event.get("channel_type")
    text = (event.get("text") or "").strip()

    if channel_type != "im" or user_id != SLACK_USER_ID or not text:
        return

    say(":hourglass_flowing_sand: Processing your time entries…")

    try:
        from clockify import ClockifyClient
        from calendar_client import GoogleCalendarClient
        from ai_parser import parse_time_entries

        tz = pytz.timezone(TIMEZONE)
        today = datetime.now(tz).date()

        # Parse manual entries via Claude
        entries = parse_time_entries(text, today)

        # Fetch today's calendar meetings
        try:
            meetings = GoogleCalendarClient().get_todays_meetings(TIMEZONE)
        except Exception as e:
            logger.warning(f"Calendar fetch skipped: {e}")
            meetings = []

        clockify = ClockifyClient(tz)
        logged = []

        # Stack manual entries from 9 AM
        cursor = tz.localize(datetime.combine(today, datetime.min.time()).replace(hour=9))
        for entry in entries:
            end = cursor + timedelta(minutes=entry["duration_minutes"])
            if clockify.create_entry(
                description=entry["description"],
                start=cursor,
                end=end,
                project_id=os.environ.get("CLOCKIFY_DEFAULT_PROJECT_ID"),
            ):
                logged.append(f"• {entry['description']} — {entry['duration_str']}")
            cursor = end

        # Log meetings using their real start/end times
        meetings_project = os.environ.get("CLOCKIFY_MEETINGS_PROJECT_ID") or os.environ.get(
            "CLOCKIFY_DEFAULT_PROJECT_ID"
        )
        for m in meetings:
            if clockify.create_entry(
                description=f"Meeting: {m['summary']}",
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


flask_app = Flask(__name__)
handler = SlackRequestHandler(slack_app)


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
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
