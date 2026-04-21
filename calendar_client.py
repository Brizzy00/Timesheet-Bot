import os
import json
import pytz
import logging
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class GoogleCalendarClient:
    def __init__(self):
        self.service = self._build_service()

    def _build_service(self):
        token_json = os.environ.get("GOOGLE_TOKEN_JSON")
        if not token_json:
            raise ValueError(
                "GOOGLE_TOKEN_JSON is not set. Run setup_google_auth.py first."
            )
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            logger.info("Google OAuth token refreshed.")
        return build("calendar", "v3", credentials=creds)

    def get_todays_meetings(self, timezone_str: str = "UTC") -> list[dict]:
        tz = pytz.timezone(timezone_str)
        today = datetime.now(tz).date()

        day_start = tz.localize(datetime.combine(today, datetime.min.time())).astimezone(pytz.UTC)
        day_end = tz.localize(datetime.combine(today, datetime.max.time())).astimezone(pytz.UTC)

        try:
            result = (
                self.service.events()
                .list(
                    calendarId="primary",
                    timeMin=day_start.isoformat(),
                    timeMax=day_end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception as e:
            logger.error(f"Google Calendar API error: {e}")
            return []

        meetings = []
        for event in result.get("items", []):
            start_raw = event.get("start", {})
            end_raw = event.get("end", {})

            # Skip all-day events
            if "dateTime" not in start_raw:
                continue

            start_dt = _parse_dt(start_raw["dateTime"], tz)
            end_dt = _parse_dt(end_raw["dateTime"], tz)
            duration_min = int((end_dt - start_dt).total_seconds() / 60)

            meetings.append(
                {
                    "summary": event.get("summary", "Meeting"),
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "duration_minutes": duration_min,
                    "duration_str": _fmt(duration_min),
                }
            )

        return meetings


def _parse_dt(raw: str, fallback_tz) -> datetime:
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = fallback_tz.localize(dt)
    return dt


def _fmt(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"
