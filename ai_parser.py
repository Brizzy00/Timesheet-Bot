import os
import json
import logging
from datetime import date
import anthropic

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def parse_time_entries(text: str, work_date: date) -> list[dict]:
    """
    Ask Claude to turn a free-text work log into structured time entries.
    Returns a list of dicts with keys: description, duration_minutes, duration_str.
    """
    prompt = f"""Parse this work log into structured time entries.

Work log: "{text}"

Return a JSON array where each item has:
- "description": string (concise task label)
- "duration_minutes": integer
- "duration_str": string (e.g. "2h", "45m", "1h 30m")

Rules:
- "1h" = 60 min, "30m" or "30min" = 30, "1.5h" = 90, "half hour" = 30
- If no duration is stated for a task, estimate reasonably (default 60 min)
- Split distinct tasks into separate entries
- Exclude meetings — those are pulled from calendar automatically
- Return ONLY valid JSON, no markdown or extra text

Example: [{{"description": "Fixed login bug", "duration_minutes": 120, "duration_str": "2h"}}]"""

    try:
        msg = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip optional markdown code fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
        return json.loads(raw)
    except Exception as e:
        logger.error(f"AI parse failed: {e}")
        return []
