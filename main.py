import os
import re
import json
import logging
from flask import Flask, request, jsonify
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import holidays as holidays_lib
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
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
COUNTRY_CODE = os.environ.get("COUNTRY_CODE", "")

# Map of "Project Name" -> "clockify_project_id"
CLOCKIFY_PROJECTS: dict[str, str] = json.loads(os.environ.get("CLOCKIFY_PROJECTS", "{}"))


def get_holiday_name(target_date: date) -> str | None:
    """Return the public holiday name for target_date, or None if it's a regular day."""
    if not COUNTRY_CODE:
        logger.warning("COUNTRY_CODE is not set — public holiday detection is disabled")
        return None
    try:
        country_holidays = holidays_lib.country_holidays(COUNTRY_CODE, years=target_date.year)
        name = country_holidays.get(target_date)
        logger.info(f"Holiday check {target_date} ({COUNTRY_CODE}): {name or 'not a holiday'}")
        return name
    except Exception as e:
        logger.error(f"Holiday lookup failed for {target_date} with COUNTRY_CODE={COUNTRY_CODE!r}: {e}")
        return None


def send_daily_prompt():
    """Fire at 4:45 PM on weekdays — posts to the configured channel."""
    logger.info("Sending daily prompt...")
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()

    # Auto-log public holidays and skip the prompt
    holiday_name = get_holiday_name(today)
    if holiday_name:
        try:
            from clockify import ClockifyClient
            clockify = ClockifyClient(tz)
            holiday_start = tz.localize(datetime.combine(today, datetime.min.time().replace(hour=9)))
            holiday_end = tz.localize(datetime.combine(today, datetime.min.time().replace(hour=17)))
            clockify.create_entry(
                description=f"Public Holiday: {holiday_name}",
                start=holiday_start,
                end=holiday_end,
                project_id=os.environ.get("CLOCKIFY_PUBLICHOLIDAY"),
            )
            slack_app.client.chat_postMessage(
                channel=SLACK_CHANNEL_ID,
                text=f":beach_with_umbrella: <@{SLACK_USER_ID}> Today is *{holiday_name}* — enjoy your day off! I've logged it to Clockify automatically.",
            )
            logger.info(f"Public holiday logged: {holiday_name}")
        except Exception as e:
            logger.error(f"Failed to log public holiday: {e}")
        return

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


def _fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def _calculate_free_slots(existing_intervals, meetings, work_date: date, tz) -> list[dict]:
    """Return free gaps in the 9am–5pm window not covered by existing entries or meetings."""
    day_start = tz.localize(datetime.combine(work_date, datetime.min.time()).replace(hour=9))
    day_end = tz.localize(datetime.combine(work_date, datetime.min.time()).replace(hour=17))

    occupied = []
    for start, end in existing_intervals:
        s, e = max(start, day_start), min(end, day_end)
        if s < e:
            occupied.append((s, e))
    for m in meetings:
        s, e = max(m["start_dt"], day_start), min(m["end_dt"], day_end)
        if s < e:
            occupied.append((s, e))

    occupied.sort(key=lambda x: x[0])
    merged = []
    for s, e in occupied:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append([s, e])

    free = []
    cursor = day_start
    for occ_start, occ_end in merged:
        if cursor < occ_start:
            gap_min = int((occ_start - cursor).total_seconds() / 60)
            if gap_min >= 15:
                free.append({"start": cursor.strftime("%H:%M"), "end": occ_start.strftime("%H:%M"), "duration_str": _fmt_duration(gap_min)})
        cursor = max(cursor, occ_end)
    if cursor < day_end:
        gap_min = int((day_end - cursor).total_seconds() / 60)
        if gap_min >= 15:
            free.append({"start": cursor.strftime("%H:%M"), "end": day_end.strftime("%H:%M"), "duration_str": _fmt_duration(gap_min)})

    return free


def parse_date_prefix(text: str, tz) -> tuple[date, str]:
    """
    Extract an optional date prefix from the command text.
    Supports: YYYY-MM-DD, 'yesterday', weekday names (most recent occurrence).
    Returns (target_date, remaining_text).
    """
    today = datetime.now(tz).date()

    # YYYY-MM-DD prefix
    m = re.match(r'^(\d{4}-\d{2}-\d{2})\s+(.+)$', text, re.DOTALL)
    if m:
        try:
            return date.fromisoformat(m.group(1)), m.group(2).strip()
        except ValueError:
            pass

    # 'yesterday' prefix
    if text.lower().startswith("yesterday "):
        return today - timedelta(days=1), text[10:].strip()

    # Weekday name prefix — only match a full word followed by a space and more text
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, name in enumerate(day_names):
        pattern = rf'^{name}\s+\S'
        if re.match(pattern, text.lower()):
            days_ago = (today.weekday() - i) % 7 or 7
            return today - timedelta(days=days_ago), text[len(name):].strip()

    return today, text


def process_time_entries(text, user_id, say, target_date: date = None):
    """Shared logic for processing time entries from both DMs and slash commands."""
    try:
        from clockify import ClockifyClient
        from calendar_client import GoogleCalendarClient
        from ai_parser import parse_time_entries

        tz = pytz.timezone(TIMEZONE)
        today = target_date or datetime.now(tz).date()

        # Parse manual entries — pass project names so Gemini can assign them
        project_names = list(CLOCKIFY_PROJECTS.keys()) if CLOCKIFY_PROJECTS else None
        entries = parse_time_entries(text, project_names)
        logger.info(f"Parsed entries: {entries}")

        if not entries:
            logger.warning("No entries parsed from text — check Gemini API key or input format")
            say(":thinking_face: Couldn't parse any entries. Try something like: _'2h on bug fixes, 1h standup'_")
            return

        # Fetch calendar meetings for the target date
        try:
            meetings = GoogleCalendarClient().get_meetings_for_date(today, TIMEZONE)
        except Exception as e:
            logger.warning(f"Calendar fetch skipped: {e}")
            meetings = []

        clockify = ClockifyClient(tz)
        logged = []
        fallback_project = os.environ.get("CLOCKIFY_DEFAULT_PROJECT_ID")

        # Re-parse with free slots so Gemini assigns non-overlapping times
        existing_intervals = clockify.get_day_intervals(today)
        free_slots = _calculate_free_slots(existing_intervals, meetings, today, tz)
        if free_slots:
            entries = parse_time_entries(text, project_names, free_slots=free_slots)
            logger.info(f"Re-parsed with {len(free_slots)} free slot(s): {entries}")

        # Log manual entries — use explicit times if provided, otherwise stack from 9 AM
        cursor = tz.localize(datetime.combine(today, datetime.min.time()).replace(hour=9))
        for entry in entries:
            try:
                if entry.get("start_time") and entry.get("end_time"):
                    start = tz.localize(datetime.combine(today, datetime.strptime(entry["start_time"], "%H:%M").time()))
                    end = tz.localize(datetime.combine(today, datetime.strptime(entry["end_time"], "%H:%M").time()))
                else:
                    start = cursor
                    end = cursor + timedelta(minutes=entry["duration_minutes"])
            except ValueError:
                start = cursor
                end = cursor + timedelta(minutes=entry["duration_minutes"])

            project_id = CLOCKIFY_PROJECTS.get(entry.get("project", ""), fallback_project)
            project_label = entry.get("project") or "default"
            logger.info(f"Logging entry: {entry['description']} | {entry['duration_str']} | {start.strftime('%H:%M')}–{end.strftime('%H:%M')} | project: {project_label}")
            result = clockify.create_entry(
                description=entry["description"],
                start=start,
                end=end,
                project_id=project_id,
            )
            if result:
                logged.append(f"• {entry['description']} — {entry['duration_str']} _{project_label}_")
            else:
                logger.warning(f"Clockify failed to create entry: {entry['description']}")
            cursor = max(cursor, end)

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



def run_backfill(say):
    """
    Scan Clockify from Jan 1 to yesterday, find weekdays with no entries,
    and report what's missing along with any calendar meetings for each day.
    """
    from clockify import ClockifyClient
    from calendar_client import GoogleCalendarClient

    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()
    start_of_year = date(today.year, 1, 1)
    yesterday = today - timedelta(days=1)

    say(f":mag: Scanning for missed days from *Jan 1* to *{yesterday.strftime('%b %d')}*…")

    try:
        clockify = ClockifyClient(tz)
        calendar = GoogleCalendarClient()

        # All weekdays from Jan 1 to yesterday
        all_weekdays = []
        current = start_of_year
        while current <= yesterday:
            if current.weekday() < 5:
                all_weekdays.append(current)
            current += timedelta(days=1)

        dates_with_entries = clockify.get_dates_with_entries(start_of_year, yesterday)
        missed_days = [d for d in all_weekdays if d not in dates_with_entries]

        if not missed_days:
            say(":white_check_mark: No missed days — you're all caught up!")
            return

        holiday_project = os.environ.get("CLOCKIFY_PUBLICHOLIDAY")
        holidays_logged = []
        lines = []

        for missed_date in missed_days:
            # Auto-log public holidays — no user input needed
            holiday_name = get_holiday_name(missed_date)
            if holiday_name:
                h_start = tz.localize(datetime.combine(missed_date, datetime.min.time().replace(hour=9)))
                h_end = tz.localize(datetime.combine(missed_date, datetime.min.time().replace(hour=17)))
                clockify.create_entry(
                    description=f"Public Holiday: {holiday_name}",
                    start=h_start,
                    end=h_end,
                    project_id=holiday_project,
                )
                holidays_logged.append(f"• *{missed_date.strftime('%a %b %d')}* — {holiday_name}")
                continue

            # Regular missed day — report it for manual entry
            meetings = calendar.get_meetings_for_date(missed_date, TIMEZONE)
            meeting_minutes = sum(m["duration_minutes"] for m in meetings)
            unfilled_minutes = max((8 * 60) - meeting_minutes, 0)
            h, m = divmod(unfilled_minutes, 60)
            unfilled_str = f"{h}h {m}m" if m else f"{h}h"

            if meetings:
                meeting_summary = ", ".join(f"{m['summary']} ({m['duration_str']})" for m in meetings)
                calendar_note = f"_Calendar: {meeting_summary} — added automatically_"
            else:
                calendar_note = "_No meetings on calendar_"

            lines.append(
                f"• *{missed_date.strftime('%a %b %d')}* — *{unfilled_str}* to fill\n"
                f"  {calendar_note}"
            )

        summary = []
        if holidays_logged:
            summary.append(":beach_with_umbrella: *Public holidays logged automatically:*\n" + "\n".join(holidays_logged))
        if lines:
            summary.append(
                f":calendar: *{len(lines)} day(s) need your input:*\n" + "\n".join(lines) +
                "\n\nTo log a day, use:\n"
                "> `/timesheet 2025-01-06 2h regression testing, 3h bug fixes`\n"
                "Calendar meetings will be added automatically on top."
            )
        if not summary:
            say(":white_check_mark: No missed days — you're all caught up!")
            return

        say("\n\n".join(summary))

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        say(f":x: Backfill failed: {e}")


def run_backfill_with_tasks(tasks_text: str, say):
    """
    Find all missed weekdays since Jan 1, then auto-fill each one using the
    provided task hints — Gemini distributes them across the free slots for each day.
    """
    from clockify import ClockifyClient
    from calendar_client import GoogleCalendarClient
    from ai_parser import parse_time_entries

    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()
    start_of_year = date(today.year, 1, 1)
    yesterday = today - timedelta(days=1)

    say(f":mag: Scanning missed days from *Jan 1* to *{yesterday.strftime('%b %d')}* and filling with your tasks…")

    try:
        clockify = ClockifyClient(tz)
        calendar = GoogleCalendarClient()
        project_names = list(CLOCKIFY_PROJECTS.keys()) if CLOCKIFY_PROJECTS else None
        fallback_project = os.environ.get("CLOCKIFY_DEFAULT_PROJECT_ID")
        meetings_project = os.environ.get("CLOCKIFY_MEETINGS_PROJECT_ID") or fallback_project
        holiday_project = os.environ.get("CLOCKIFY_PUBLICHOLIDAY")

        all_weekdays = []
        current = start_of_year
        while current <= yesterday:
            if current.weekday() < 5:
                all_weekdays.append(current)
            current += timedelta(days=1)

        dates_with_entries = clockify.get_dates_with_entries(start_of_year, yesterday)
        missed_days = [d for d in all_weekdays if d not in dates_with_entries]

        if not missed_days:
            say(":white_check_mark: No missed days — you're all caught up!")
            return

        say(f":calendar: Found *{len(missed_days)} missed day(s)*. Logging now…")

        filled_days = []
        holidays_logged = []
        no_slots = []

        for missed_date in missed_days:
            # Auto-log public holidays
            holiday_name = get_holiday_name(missed_date)
            if holiday_name:
                h_start = tz.localize(datetime.combine(missed_date, datetime.min.time().replace(hour=9)))
                h_end = tz.localize(datetime.combine(missed_date, datetime.min.time().replace(hour=17)))
                clockify.create_entry(
                    description=f"Public Holiday: {holiday_name}",
                    start=h_start, end=h_end, project_id=holiday_project,
                )
                holidays_logged.append(f"• *{missed_date.strftime('%a %b %d')}* — {holiday_name}")
                continue

            meetings = calendar.get_meetings_for_date(missed_date, TIMEZONE)
            existing_intervals = clockify.get_day_intervals(missed_date)
            free_slots = _calculate_free_slots(existing_intervals, meetings, missed_date, tz)

            if not free_slots:
                no_slots.append(missed_date.strftime("%a %b %d"))
                continue

            entries = parse_time_entries(tasks_text, project_names, free_slots=free_slots)
            day_logged = []

            # Log tasks
            cursor = tz.localize(datetime.combine(missed_date, datetime.min.time()).replace(hour=9))
            for entry in entries:
                try:
                    if entry.get("start_time") and entry.get("end_time"):
                        start = tz.localize(datetime.combine(missed_date, datetime.strptime(entry["start_time"], "%H:%M").time()))
                        end = tz.localize(datetime.combine(missed_date, datetime.strptime(entry["end_time"], "%H:%M").time()))
                    else:
                        start = cursor
                        end = cursor + timedelta(minutes=entry["duration_minutes"])
                except ValueError:
                    start = cursor
                    end = cursor + timedelta(minutes=entry["duration_minutes"])

                project_id = CLOCKIFY_PROJECTS.get(entry.get("project", ""), fallback_project)
                if clockify.create_entry(entry["description"], start, end, project_id):
                    day_logged.append(f"  _{entry['description']} — {entry['duration_str']}_")
                cursor = max(cursor, end)

            # Log meetings
            for m in meetings:
                if clockify.create_entry(f"Meeting: {m['summary']}", m["start_dt"], m["end_dt"], meetings_project):
                    day_logged.append(f"  _Meeting: {m['summary']} — {m['duration_str']}_")

            if day_logged:
                filled_days.append(f"• *{missed_date.strftime('%a %b %d')}*\n" + "\n".join(day_logged))

        # Summary
        parts = []
        if filled_days:
            parts.append(f":white_check_mark: *Filled {len(filled_days)} day(s):*\n" + "\n".join(filled_days))
        if holidays_logged:
            parts.append(":beach_with_umbrella: *Public holidays logged:*\n" + "\n".join(holidays_logged))
        if no_slots:
            parts.append(f":grey_question: *No free slots on {len(no_slots)} day(s)* (fully covered by meetings):\n" + ", ".join(no_slots))

        say("\n\n".join(parts) if parts else ":white_check_mark: Done!")

    except Exception as e:
        logger.error(f"Backfill with tasks failed: {e}", exc_info=True)
        say(f":x: Backfill failed: {e}")


@slack_app.command("/backfill")
def handle_backfill_command(ack, say, command):
    """Handle /backfill slash command."""
    ack()
    text = (command.get("text") or "").strip()
    if text:
        run_backfill_with_tasks(text, say)
    else:
        run_backfill(say)


@slack_app.command("/timesheet")
def handle_timesheet_command(ack, say, command):
    """Handle /timesheet slash command."""
    ack()  # Acknowledge immediately to avoid Slack timeout

    user_id = command["user_id"]
    text = (command.get("text") or "").strip()

    if text == "backfill":
        run_backfill(say)
        return

    if not text:
        say(
            ":spiral_notepad: *Timesheet Bot*\n\n"
            "Log today:\n"
            "> `/timesheet 2h fixing login bug, 1h code review, 30min planning`\n\n"
            "Log a specific past day:\n"
            "> `/timesheet 2025-01-06 2h regression testing, 3h bug fixes`\n"
            "> `/timesheet yesterday 2h regression testing`\n"
            "> `/timesheet monday 1h standup, 3h testing`\n\n"
            "Find missed days since Jan 1:\n"
            "> `/timesheet backfill`"
        )
        return

    tz = pytz.timezone(TIMEZONE)
    target_date, task_text = parse_date_prefix(text, tz)
    date_label = "" if target_date == datetime.now(tz).date() else f" for *{target_date.strftime('%a %b %d')}*"

    say(f":hourglass_flowing_sand: Processing your time entries{date_label}…")
    process_time_entries(task_text, user_id, say, target_date=target_date)


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