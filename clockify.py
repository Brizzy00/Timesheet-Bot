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
        self._todays_descriptions: set | None = None

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
        if self._todays_descriptions is not None:
            return self._todays_descriptions

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
            self._todays_descriptions = {e.get("description", "") for e in resp.json()}
        except requests.RequestException as e:
            logger.error(f"Failed to fetch today's Clockify entries: {e}")
            self._todays_descriptions = set()

        return self._todays_descriptions

    def get_dates_with_entries(self, start_date: date, end_date: date) -> set[date]:
        """
        Return the set of local dates that have at least one time entry
        in the given range. Handles Clockify pagination automatically.
        """
        range_start = self.tz.localize(
            datetime.combine(start_date, datetime.min.time())
        ).astimezone(pytz.UTC)
        range_end = self.tz.localize(
            datetime.combine(end_date, datetime.max.time())
        ).astimezone(pytz.UTC)

        user_id = self._get_user_id()
        dates_found: set[date] = set()
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
                start_str = (entry.get("timeInterval") or {}).get("start", "")
                if start_str:
                    entry_utc = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    dates_found.add(entry_utc.astimezone(self.tz).date())

            if len(batch) < 200:
                break
            page += 1

        return dates_found

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

        try:
            resp = requests.post(
                f"{self.BASE_URL}/workspaces/{self.workspace_id}/time-entries",
                json=payload,
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
            logger.info(f"Clockify entry created: {description}")
            if self._todays_descriptions is not None:
                self._todays_descriptions.add(description)
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Clockify error for '{description}': {e}")
            return None
