from __future__ import annotations
"""
handlers/intent.py
Uses Anthropic to understand free-text Hebrew replies.
Returns a structured intent dict.
"""

import json
import logging
import os

from services.llm import complete, DEFAULT_HAIKU

logger = logging.getLogger(__name__)

INTENT_MODEL = os.getenv("ANTHROPIC_INTENT_MODEL", DEFAULT_HAIKU)

SYSTEM_PROMPT = """
אתה עוזר משפחתי חכם. תפקידך לזהות את הכוונה של הודעה שנשלחה בעברית
בתגובה לתזכורת על פעילות.

החזר JSON בלבד, ללא הסברים נוספים, בפורמט הבא:
{
  "intent": "<אחת מהאפשרויות הבאות>",
  "snooze_minutes": <מספר דקות או null>,
  "new_datetime": "<ISO datetime string או null>",
  "question_text": "<תוכן השאלה או null>"
}

אפשרויות intent:
- confirm   — מאשר שידע / יגיע ("אוקי", "ידעתי", "בסדר", "מגיעים")
- skip      — לא יגיע הפעם ("לא נוכל", "דלג", "ביטול", "אין לנו היום")
- snooze    — רוצה תזכורת מאוחר יותר ("דחה 30", "תזכיר לי בעוד שעה")
- reschedule — רוצה לשנות מועד ("נעביר לשעה 17", "שנה ליום רביעי")
- question  — שואל שאלה ("איפה זה?", "מי לוקח?", "כמה עולה?")
- unknown   — לא ברור

דוגמאות:
"אוקי תודה" → {"intent": "confirm", ...}
"לא נוכל היום" → {"intent": "skip", ...}
"תזכיר לי בעוד שעה" → {"intent": "snooze", "snooze_minutes": 60, ...}
"נעביר לשעה 17:00" → {"intent": "reschedule", "new_datetime": null, ...}
"איפה זה בדיוק?" → {"intent": "question", "question_text": "איפה זה בדיוק?", ...}
"""


def detect_intent(reply_text: str, event_context: dict = None) -> dict:
    """
    Detects the intent from a Hebrew reply.

    Args:
        reply_text: The raw message from the family member
        event_context: Optional dict with event title/time for better context

    Returns:
        dict with keys: intent, snooze_minutes, new_datetime, question_text
    """
    context_str = ""
    if event_context:
        context_str = (
            f"\nהקשר — הפעילות שעליה מדובר: {event_context.get('title', '')} "
            f"בשעה {event_context.get('time', '')}"
        )

    try:
        raw = complete(
            SYSTEM_PROMPT + context_str,
            reply_text,
            model=INTENT_MODEL,
            max_tokens=200,
            temperature=0,
        )

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw)

        result.setdefault("intent", "unknown")
        result.setdefault("snooze_minutes", None)
        result.setdefault("new_datetime", None)
        result.setdefault("question_text", None)
        return result

    except Exception as e:
        print(f"[intent] Anthropic error: {e}")
        return {
            "intent": "unknown",
            "snooze_minutes": None,
            "new_datetime": None,
            "question_text": None,
        }
