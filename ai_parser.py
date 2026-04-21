import os
import json
import logging

import google.generativeai as genai

logger = logging.getLogger(__name__)

_model: genai.GenerativeModel | None = None


def _get_model() -> genai.GenerativeModel:
    global _model
    if _model is None:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        _model = genai.GenerativeModel("gemini-2.5-flash")
    return _model


def parse_time_entries(text: str, project_names: list[str] = None, free_slots: list[dict] = None) -> list[dict]:
    """
    Ask Gemini to turn a free-text work log into structured time entries.
    Returns a list of dicts with keys:
      description, duration_minutes, duration_str, project, start_time, end_time
    start_time / end_time are "HH:MM" strings when explicit times were given, else null.
    """
    projects_section = ""
    if project_names:
        names = ", ".join(f'"{p}"' for p in project_names)
        projects_section = (
            f"\nAvailable projects: {names}\n"
            "For each entry, pick the best matching project from that list. "
            'Include it as the "project" field (exact name from the list, or null if none fit).'
        )

    slots_section = ""
    if free_slots:
        slot_lines = "\n".join(
            f"  - {s['start']} to {s['end']} ({s['duration_str']} free)"
            for s in free_slots
        )
        slots_section = (
            f"\nAvailable time slots (all other time is already tracked today):\n{slot_lines}\n"
            "Distribute the tasks across these slots. "
            "Each task must fit inside a slot — no overlapping, no going outside the slot boundaries. "
            "Set start_time and end_time for every entry.\n"
        )

    prompt = f"""Parse this work log into structured time entries.

Work log: "{text}"
{projects_section}{slots_section}
Return a JSON array where each item has:
- "description": string (concise task label)
- "duration_minutes": integer
- "duration_str": string (e.g. "2h", "45m", "1h 30m")
- "project": string or null
- "start_time": string or null — 24h "HH:MM" if an explicit or assigned start time, else null
- "end_time": string or null — 24h "HH:MM" if an explicit or assigned end time, else null

Rules:
- "1h" = 60 min, "30m" or "30min" = 30, "1.5h" = 90, "half hour" = 30
- Time ranges like "from 10:30 to 17:00" or "10:30 - 17:00":
    → start_time="10:30", end_time="17:00", duration_minutes=390
- If free slots are given, assign every task a start_time and end_time that fits within a slot
- Tasks must not overlap with each other
- If no slots are given and no explicit time, set start_time and end_time to null
- Split distinct tasks into separate entries
- Exclude meetings — those are pulled from calendar automatically
- Return ONLY valid JSON, no markdown or extra text

Example:
[
  {{"description": "UAT testing", "duration_minutes": 390, "duration_str": "6h 30m", "project": "QA Testing", "start_time": "10:30", "end_time": "17:00"}},
  {{"description": "Fixed login bug", "duration_minutes": 120, "duration_str": "2h", "project": "Development", "start_time": "09:00", "end_time": "11:00"}}
]"""

    try:
        response = _get_model().generate_content(prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Gemini parse failed: {e}")
        return []
