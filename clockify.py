import os
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
        self._todays_descriptions: set | None = None  # cache for duplicate check

    def _get_user_id(self) -> str:
        if self._user_id is None:
            resp = requests.get(f"{self.BASE_URL}/user", headers=self.headers, timeout=10)
            resp.raise_for_status()
            self._user_id = resp.json()["id"]
        return self._user_id

    def get_todays_descriptions(self, work_date: date) -> set[str]:
        """Return the set of entry descriptions already logged today."""
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
            # Keep cache in sync so subsequent calls in the same session also deduplicate
            if self._todays_descriptions is not None:
                self._todays_descriptions.add(description)
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Clockify error for '{description}': {e}")
            return None
