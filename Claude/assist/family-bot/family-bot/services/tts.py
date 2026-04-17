from __future__ import annotations
"""
services/tts.py
Generates spoken Hebrew audio via OpenAI TTS (single events and daily summaries).
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
# Style for single-event 🔊 button
TTS_INSTRUCTIONS = os.getenv(
    "OPENAI_TTS_INSTRUCTIONS",
    "Speak in Hebrew. Sound like a loud military drill sergeant or army commander shouting "
    "orders: urgent, authoritative, clipped, with short pauses between phrases. "
    "Do not whisper. Project like you are addressing troops in an open field.",
)
# Calmer delivery for long morning readouts (8am daily summary)
DAILY_SUMMARY_INSTRUCTIONS = os.getenv(
    "OPENAI_TTS_DAILY_SUMMARY_INSTRUCTIONS",
    "Speak in Hebrew. Morning briefing tone: clear, steady pace, friendly and efficient. "
    "Pause briefly between schedule items so each event is easy to follow.",
)

logger = logging.getLogger(__name__)


def _create_speech(text: str, instructions: str | None) -> bytes | None:
    """Core TTS call. instructions=None or empty skips the instructions parameter."""
    text = text.strip()
    if not text:
        return None

    model = TTS_MODEL
    inst = (instructions or "").strip()
    use_instructions = bool(inst)
    if use_instructions and model in ("tts-1", "tts-1-hd"):
        model = "gpt-4o-mini-tts"

    kwargs: dict = {
        "model": model,
        "voice": TTS_VOICE,
        "input": text,
        "response_format": "opus",
    }
    sig = inspect.signature(client.audio.speech.create)
    if use_instructions and "instructions" in sig.parameters:
        kwargs["instructions"] = inst

    try:
        response = client.audio.speech.create(**kwargs)
        audio_bytes = response.read()
        logger.info(f"[tts] speech generated ({len(audio_bytes)} bytes)")
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
    Generates TTS audio bytes for a single event (🔊 האזן button).
    Returns raw opus bytes suitable for Telegram send_voice, or None on failure.
    """
    text = _build_tts_text(event, persona_name)
    logger.info(f"[tts] event {event.get('id')} — {text}")
    return _create_speech(text, TTS_INSTRUCTIONS if TTS_INSTRUCTIONS.strip() else None)


def generate_daily_summary_audio(spoken_script: str) -> bytes | None:
    """
    TTS for the 8:00 morning daily schedule readout.
    spoken_script should be plain Hebrew (no markdown).
    """
    script = spoken_script.strip()
    max_chars = int(os.getenv("OPENAI_TTS_MAX_CHARS", "3800"))
    if len(script) > max_chars:
        logger.warning(f"[tts] daily summary truncated from {len(script)} to {max_chars} chars")
        script = script[: max_chars - 20] + "... נמשיך בטקסט."
    logger.info(f"[tts] daily summary script ({len(script)} chars)")
    inst = DAILY_SUMMARY_INSTRUCTIONS if DAILY_SUMMARY_INSTRUCTIONS.strip() else None
    return _create_speech(script, inst)
