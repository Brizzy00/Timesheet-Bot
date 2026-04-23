import os
import time
import json
import logging

import google.generativeai as genai

logger = logging.getLogger(__name__)

_model: genai.GenerativeModel | None = None

# Sliding-window rate limiter — stay under 15 RPM (Gemini free tier limit)
_RPM_LIMIT = 14  # one below the cap for safety
_call_timestamps: list[float] = []


def _get_model() -> genai.GenerativeModel:
    global _model
    if _model is None:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        _model = genai.GenerativeModel("gemma-3-27b")
    return _model


def _throttle():
    """Block until sending the next request stays within _RPM_LIMIT calls per 60s."""
    now = time.time()
    cutoff = now - 60.0

    # Drop timestamps outside the rolling window
    while _call_timestamps and _call_timestamps[0] < cutoff:
        _call_timestamps.pop(0)

    if len(_call_timestamps) >= _RPM_LIMIT:
        wait = 60.0 - (now - _call_timestamps[0]) + 0.5
        if wait > 0:
            logger.info(f"Gemini rate limit: waiting {wait:.1f}s to stay under {_RPM_LIMIT} RPM…")
            time.sleep(wait)
        # Re-clean after sleeping
        cutoff = time.time() - 60.0
        while _call_timestamps and _call_timestamps[0] < cutoff:
            _call_timestamps.pop(0)

    _call_timestamps.append(time.time())


def parse_time_entries(
    text: str,
    project_names: list[str] = None,
    free_slots: list[dict] = None,
    project_keywords: dict[str, str] = None,
) -> list[dict]:
    """
    Ask Gemini to turn a free-text work log into structured time entries.
    Returns a list of dicts with keys:
      description, duration_minutes, duration_str, project, start_time, end_time
    start_time / end_time are "HH:MM" strings when explicit times were given, else null.
    """
    projects_section = ""
    if project_names:
        lines = []
        for p in project_names:
            hints = (project_keywords or {}).get(p, "")
            if hints:
                lines.append(f'  - "{p}" — typically used for: {hints}')
            else:
                lines.append(f'  - "{p}"')
        projects_section = (
            "\nAvailable projects:\n" + "\n".join(lines) + "\n"
            "For each entry, pick the best matching project from that list using the name and hints above. "
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
- If a task has NO explicit duration, assign it duration_minutes=60 as a placeholder (it will be scaled later)
- If free slots are given, assign every task a start_time and end_time that fits within a slot
- Tasks must not overlap with each other
- If no slots are given and no explicit time, set start_time and end_time to null
- Split distinct tasks into separate entries
- Exclude meetings — those are pulled from calendar automatically
- Return ONLY valid JSON, no markdown or extra text

Examples:

With explicit durations:
[
  {{"description": "UAT testing", "duration_minutes": 390, "duration_str": "6h 30m", "project": "QA Testing", "start_time": "10:30", "end_time": "17:00"}},
  {{"description": "Fixed login bug", "duration_minutes": 120, "duration_str": "2h", "project": "Development", "start_time": "09:00", "end_time": "11:00"}}
]

With no explicit durations (placeholder 60 min each):
[
  {{"description": "Regression test for PSM", "duration_minutes": 60, "duration_str": "1h", "project": "QA Testing", "start_time": null, "end_time": null}},
  {{"description": "Regression test for RMS", "duration_minutes": 60, "duration_str": "1h", "project": "QA Testing", "start_time": null, "end_time": null}},
  {{"description": "Testing assigned tickets", "duration_minutes": 60, "duration_str": "1h", "project": "QA Testing", "start_time": null, "end_time": null}}
]"""

    try:
        _throttle()
        response = _get_model().generate_content(prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Gemini parse failed: {e}")
        return []
