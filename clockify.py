import os
import requests
import pytz
import logging
from datetime import datetime

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

    def create_entry(
        self,
        description: str,
        start: datetime,
        end: datetime,
        project_id: str = None,
    ) -> dict | None:
        # Ensure timezone-aware, then convert to UTC
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
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Clockify error for '{description}': {e}")
            return None
