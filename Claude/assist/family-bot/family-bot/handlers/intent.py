"""
handlers/intent.py
Uses OpenAI to understand free-text Hebrew replies.
Returns a structured intent dict.
"""

import os
import json
import logging
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
INTENT_MODEL = os.getenv("OPENAI_INTENT_MODEL", "gpt-4o-mini")
logger = logging.getLogger(__name__)

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
        logger.info(f"[openai] intent model={INTENT_MODEL}")
        try:
            response = client.chat.completions.create(
                model=INTENT_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT + context_str},
                    {"role": "user",   "content": reply_text}
                ],
                temperature=0,
                max_tokens=200,
            )
        except Exception as e:
            msg = str(e)
            if "404" in msg or "Not Found" in msg or "model" in msg.lower():
                fallback = "gpt-4o-mini"
                logger.warning(f"[openai] intent model failed ({INTENT_MODEL}); retrying with {fallback}. error={msg}")
                response = client.chat.completions.create(
                    model=fallback,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT + context_str},
                        {"role": "user",   "content": reply_text}
                    ],
                    temperature=0,
                    max_tokens=200,
                )
            else:
                raise
        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw)

        # Ensure all expected keys exist
        result.setdefault("intent", "unknown")
        result.setdefault("snooze_minutes", None)
        result.setdefault("new_datetime", None)
        result.setdefault("question_text", None)
        return result

    except Exception as e:
        print(f"[intent] OpenAI error: {e}")
        return {
            "intent": "unknown",
            "snooze_minutes": None,
            "new_datetime": None,
            "question_text": None,
        }
