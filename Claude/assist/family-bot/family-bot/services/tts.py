"""
services/tts.py
Generates a spoken Hebrew audio summary of an event using OpenAI TTS.
"""

import os
import logging
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")
TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "nova")

logger = logging.getLogger(__name__)


def _build_tts_text(event: dict, persona_name: str) -> str:
    """Builds a natural Hebrew sentence describing the event."""
    parts = [f"אירוע עבור {persona_name}: {event['title']}"]

    if event.get("event_datetime"):
        try:
            dt = datetime.fromisoformat(event["event_datetime"])
            parts.append(f"בתאריך {dt.strftime('%d/%m/%Y')} בשעה {dt.strftime('%H:%M')}")
        except Exception:
            pass
    elif event.get("is_recurring") and event.get("rrule"):
        parts.append("אירוע חוזר")

    if event.get("location"):
        parts.append(f"מיקום: {event['location']}")

    if event.get("notes"):
        parts.append(f"הערות: {event['notes']}")

    remind = event.get("remind_before_minutes")
    if remind:
        if remind >= 60 and remind % 60 == 0:
            parts.append(f"תזכורת {remind // 60} שעות לפני")
        else:
            parts.append(f"תזכורת {remind} דקות לפני")

    return ". ".join(parts) + "."


def generate_event_audio(event: dict, persona_name: str) -> bytes | None:
    """
    Generates TTS audio bytes for an event.
    Returns raw opus bytes suitable for Telegram send_voice, or None on failure.
    """
    text = _build_tts_text(event, persona_name)
    logger.info(f"[tts] generating audio for event {event.get('id')} — {text}")

    try:
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=text,
            response_format="opus",
        )
        audio_bytes = response.read()
        logger.info(f"[tts] audio generated ({len(audio_bytes)} bytes)")
        return audio_bytes
    except Exception as e:
        logger.error(f"[tts] failed to generate audio: {e}")
        return None
