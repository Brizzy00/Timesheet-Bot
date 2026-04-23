import os
import time
import requests
import pytz
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)


class ClockifyClient:
    BASE_URL = "https://api.clockify.me/api/v1"

    def __init__(self, timezone=None):
        self.api_key = os.environ["CLOCKIFY_API_KEY"]
        self.workspace_id = os.environ["CLOCKIFY_WORKSPACE_ID"]
        self.tz = timezone or pytz.UTC
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
        self._user_id: str | None = None
        self._descriptions_by_date: dict[date, set] = {}

    def _get_user_id(self) -> str:
        if self._user_id is None:
            resp = requests.get(f"{self.BASE_URL}/user", headers=self.headers, timeout=10)
            resp.raise_for_status()
            self._user_id = resp.json()["id"]
        return self._user_id

    def get_day_intervals(self, work_date: date) -> list[tuple]:
        """Return sorted list of (start, end) datetimes for all entries on work_date."""
        day_start = self.tz.localize(
            datetime.combine(work_date, datetime.min.time())
        ).astimezone(pytz.UTC)
        day_end = self.tz.localize(
            datetime.combine(work_date, datetime.max.time())
        ).astimezone(pytz.UTC)

        try:
            user_id = self._get_user_id()
            resp = requests.get(
                f"{self.BASE_URL}/workspaces/{self.workspace_id}/user/{user_id}/time-entries",
                params={
                    "start": day_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": day_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch day intervals: {e}")
            return []

        intervals = []
        for entry in resp.json():
            interval = entry.get("timeInterval", {})
            start_str = interval.get("start", "")
            end_str = interval.get("end", "")
            if start_str and end_str:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(self.tz)
                end = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(self.tz)
                intervals.append((start, end))

        return sorted(intervals, key=lambda x: x[0])

    def get_todays_descriptions(self, work_date: date) -> set[str]:
        """Return the set of entry descriptions already logged on work_date."""
        if work_date in self._descriptions_by_date:
            return self._descriptions_by_date[work_date]

        day_start = self.tz.localize(
            datetime.combine(work_date, datetime.min.time())
        ).astimezone(pytz.UTC)
        day_end = self.tz.localize(
            datetime.combine(work_date, datetime.max.time())
        ).astimezone(pytz.UTC)

        try:
            user_id = self._get_user_id()
            resp = requests.get(
                f"{self.BASE_URL}/workspaces/{self.workspace_id}/user/{user_id}/time-entries",
                params={
                    "start": day_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": day_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
            self._descriptions_by_date[work_date] = {e.get("description", "") for e in resp.json()}
        except requests.RequestException as e:
            logger.error(f"Failed to fetch today's Clockify entries: {e}")
            self._descriptions_by_date[work_date] = set()

        return self._descriptions_by_date[work_date]

    def get_date_logged_minutes(self, start_date: date, end_date: date) -> dict[date, int]:
        """
        Return a dict of local-date → total minutes logged across all entries in the range.
        Only dates with at least one completed entry appear in the dict.
        Handles Clockify pagination automatically.
        """
        range_start = self.tz.localize(
            datetime.combine(start_date, datetime.min.time())
        ).astimezone(pytz.UTC)
        range_end = self.tz.localize(
            datetime.combine(end_date, datetime.max.time())
        ).astimezone(pytz.UTC)

        user_id = self._get_user_id()
        minutes_by_date: dict[date, int] = {}
        page = 1

        while True:
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/workspaces/{self.workspace_id}/user/{user_id}/time-entries",
                    params={
                        "start": range_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "end": range_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "page": page,
                        "page-size": 200,
                    },
                    headers=self.headers,
                    timeout=30,
                )
                resp.raise_for_status()
                batch = resp.json()
            except requests.RequestException as e:
                logger.error(f"Failed to fetch Clockify entries page {page}: {e}")
                break

            for entry in batch:
                interval = entry.get("timeInterval") or {}
                start_str = interval.get("start", "")
                end_str = interval.get("end", "")
                if start_str and end_str:
                    entry_start = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(self.tz)
                    entry_end = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(self.tz)
                    day = entry_start.date()
                    duration_mins = max(0, int((entry_end - entry_start).total_seconds() / 60))
                    minutes_by_date[day] = minutes_by_date.get(day, 0) + duration_mins

            if len(batch) < 200:
                break
            page += 1

        return minutes_by_date

    def create_entry(
        self,
        description: str,
        start: datetime,
        end: datetime,
        project_id: str = None,
    ) -> dict | None:
        if start.tzinfo is None:
            start = self.tz.localize(start)
        if end.tzinfo is None:
            end = self.tz.localize(end)

        # Guard against invalid time ranges
        if end <= start:
            logger.error(f"Skipping '{description}': end ({end}) is not after start ({start})")
            return None

        start_utc = start.astimezone(pytz.UTC)
        end_utc = end.astimezone(pytz.UTC)

        payload = {
            "description": description,
            "start": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "billable": False,
        }
        if project_id:
            payload["projectId"] = project_id

        logger.debug(f"Clockify payload: {payload}")

        try:
            resp = requests.post(
                f"{self.BASE_URL}/workspaces/{self.workspace_id}/time-entries",
                json=payload,
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
            logger.info(f"Clockify entry created: {description}")
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Clockify error for '{description}': {e} — response: {getattr(e.response, 'text', 'n/a')}")
            return None
