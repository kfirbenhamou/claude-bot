"""
services/tts.py
Generates a spoken Hebrew audio summary of an event using OpenAI TTS.
"""

import inspect
import os
import logging
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "onyx")
# Style instructions (only applied with gpt-4o-mini-tts). Empty = neutral delivery.
TTS_INSTRUCTIONS = os.getenv(
    "OPENAI_TTS_INSTRUCTIONS",
    "Speak in Hebrew. Sound like a loud military drill sergeant or army commander shouting "
    "orders: urgent, authoritative, clipped, with short pauses between phrases. "
    "Do not whisper. Project like you are addressing troops in an open field.",
)

logger = logging.getLogger(__name__)


def _build_tts_text(event: dict, persona_name: str) -> str:
    """Short Hebrew briefing — facts only, suitable for shouted delivery."""
    chunks: list[str] = [persona_name, event["title"]]

    if event.get("event_datetime"):
        try:
            dt = datetime.fromisoformat(event["event_datetime"])
            chunks.append(f"{dt.strftime('%d/%m/%Y')} {dt.strftime('%H:%M')}")
        except Exception:
            pass
    elif event.get("is_recurring") and event.get("rrule"):
        chunks.append("חוזר")

    if event.get("location"):
        chunks.append(event["location"])

    if event.get("notes"):
        chunks.append(event["notes"])

    remind = event.get("remind_before_minutes")
    if remind:
        if remind >= 60 and remind % 60 == 0:
            chunks.append(f"תזכורת {remind // 60} שעות לפני")
        else:
            chunks.append(f"תזכורת {remind} דקות לפני")

    return "! ".join(chunks) + "!"


def generate_event_audio(event: dict, persona_name: str) -> bytes | None:
    """
    Generates TTS audio bytes for an event.
    Returns raw opus bytes suitable for Telegram send_voice, or None on failure.
    """
    text = _build_tts_text(event, persona_name)
    logger.info(f"[tts] generating audio for event {event.get('id')} — {text}")

    model = TTS_MODEL
    use_instructions = bool(TTS_INSTRUCTIONS.strip())
    # instructions only work with gpt-4o-mini-tts
    if use_instructions and model in ("tts-1", "tts-1-hd"):
        model = "gpt-4o-mini-tts"

    kwargs: dict = {
        "model": model,
        "voice": TTS_VOICE,
        "input": text,
        "response_format": "opus",
    }
    sig = inspect.signature(client.audio.speech.create)
    if (
        use_instructions
        and TTS_INSTRUCTIONS.strip()
        and "instructions" in sig.parameters
    ):
        kwargs["instructions"] = TTS_INSTRUCTIONS.strip()

    try:
        response = client.audio.speech.create(**kwargs)
        audio_bytes = response.read()
        logger.info(f"[tts] audio generated ({len(audio_bytes)} bytes)")
        return audio_bytes
    except Exception as e:
        msg = str(e)
        if "instructions" in kwargs and (
            "instructions" in msg.lower() or "not supported" in msg.lower()
        ):
            logger.warning(f"[tts] retrying without instructions: {e}")
            kwargs.pop("instructions", None)
            try:
                kwargs["model"] = "tts-1"
                response = client.audio.speech.create(**kwargs)
                return response.read()
            except Exception as e2:
                logger.error(f"[tts] fallback failed: {e2}")
                return None
        logger.error(f"[tts] failed to generate audio: {e}")
        return None
