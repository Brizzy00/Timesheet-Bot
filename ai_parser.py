import os
import json
import logging
from datetime import date
import google.generativeai as genai

logger = logging.getLogger(__name__)

_model: genai.GenerativeModel | None = None


def _get_model() -> genai.GenerativeModel:
    global _model
    if _model is None:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        _model = genai.GenerativeModel("gemini-2.5-flash")
    return _model


def parse_time_entries(text: str, work_date: date) -> list[dict]:
    """
    Ask Gemini to turn a free-text work log into structured time entries.
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
        response = _get_model().generate_content(prompt)
        raw = response.text.strip()
        # Strip optional markdown code fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Gemini parse failed: {e}")
        return []
