"""
handlers/agent_actions.py
Turns free-text (Hebrew) requests into concrete DB actions.
"""

import json
import os
import logging
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
אתה עוזר אוטומציה לבוט משפחתי. תפקידך להפוך הודעות בעברית לפעולות מובנות.

החזר JSON בלבד, ללא טקסט נוסף, בפורמט:
{
  "action": "create_event" | "update_event" | "none",
  "event": { ... } | null,
  "match": {
    "event_id": <int|null>,
    "persona_name": "<שם בעברית|null>",
    "title_query": "<מחרוזת לחיפוש בכותרת|null>"
  } | null,
  "updates": {
    "title": "<string|null>",
    "location": "<string|null>",
    "notes": "<string|null>",
    "remind_before_minutes": <int|null>,
    "send_to": "group" | "private" | "both" | null,
    "is_recurring": true | false | null,
    "days_of_week": ["SU","MO","TU","WE","TH","FR","SA"] | null,
    "start_time": "HH:MM" | null,
    "end_time": "HH:MM" | null,
    "event_datetime": "<ISO datetime string|null>"
  } | null
}

כללים:
- אם המשתמש מבקש "הוסף אירוע" או "צור אירוע" — action=create_event.
- אם המשתמש מבקש "עדכן" / "שנה" / "ערוך" / "לתקן" / "להזיז" / "להסיר" / "למחוק" — action=update_event (גם אם יש פרטים מלאים של אירוע).
- אם ההודעה כוללת מילים שמרמזות על עריכה (עדכן/שנה/ערוך/להסיר/למחוק וכו') אסור לבחור create_event אלא אם המשתמש כתב במפורש גם "צור/הוסף אירוע חדש".
- אם לא ברור מה לעשות — action=none.
- days_of_week חייב להיות בקודי iCal (SU,MO,...).
- אם יש טווח שעות (למשל 18:45 עד 19:45) שים start_time/end_time.
- אם לא נאמר אחרת, send_to="group".
- בעריכה: אם יש מספר אירועים דומים, עדיף להחזיר match עם title_query+persona_name. אם המשתמש ציין מספר אירוע, השתמש event_id.

ליצירה (create_event):
- אם המשתמש כתב "עבור X ו-Y" / "עבור X,Y" אז החזר event.persona_names כמערך שמות, למשל ["עלמה","ארבל"].
- אם יש רק שם אחד, אפשר להשתמש או ב-persona_name או ב-persona_names עם איבר אחד.
"""


def parse_agent_action(text: str, persona_names: list[str] | None = None) -> dict:
    """
    Uses OpenAI to parse a free-text request into a structured action.
    """
    try:
        personas_hint = ""
        if persona_names:
            personas_hint = (
                "\n\nשמות פרסונות אפשריים (אם מופיע 'עבור' / 'בשביל' חובה לבחור אחד או יותר מהרשימה; אם יש כמה, החזר מערך persona_names): "
                + ", ".join(persona_names)
            )
        model = os.getenv("OPENAI_AGENT_MODEL", os.getenv("OPENAI_QA_MODEL", "gpt-4o-mini"))
        logger.info(f"[openai] agent model={model}")
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT + personas_hint},
                    {"role": "user", "content": text},
                ],
                temperature=0,
                max_tokens=400,
            )
        except Exception as e:
            # If model is not available (common 404), fall back to a widely available model.
            msg = str(e)
            if "404" in msg or "Not Found" in msg or "model" in msg.lower():
                fallback = "gpt-4o"
                logger.warning(f"[openai] agent model failed ({model}); retrying with {fallback}. error={msg}")
                resp = client.chat.completions.create(
                    model=fallback,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT + personas_hint},
                        {"role": "user", "content": text},
                    ],
                    temperature=0,
                    max_tokens=400,
                )
            else:
                raise
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"action": "none"}
    except Exception:
        return {"action": "none"}


def build_rrule(days_of_week: list[str], start_time: str | None) -> str | None:
    if not days_of_week:
        return None
    parts = ["FREQ=WEEKLY", f"BYDAY={','.join(days_of_week)}"]
    if start_time:
        try:
            hh, mm = start_time.split(":")
            parts.append(f"BYHOUR={int(hh)}")
            parts.append(f"BYMINUTE={int(mm)}")
        except Exception:
            pass
    return ";".join(parts)


def today_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")

