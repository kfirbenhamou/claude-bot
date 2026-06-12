from __future__ import annotations
"""
services/tts.py
Generates spoken Hebrew audio for the daily schedule summary (optional OpenAI TTS).
"""

import inspect
import os
import logging
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "onyx")
DAILY_SUMMARY_INSTRUCTIONS = os.getenv(
    "OPENAI_TTS_DAILY_SUMMARY_INSTRUCTIONS",
    "Speak in Hebrew. Morning briefing tone: clear, steady pace, friendly and efficient. "
    "Pause briefly between schedule items so each event is easy to follow.",
)


def _create_speech(text: str, instructions: str | None) -> bytes | None:
    """Core TTS call. Requires OPENAI_API_KEY; returns None when disabled."""
    if not OPENAI_API_KEY:
        logger.info("[tts] disabled — OPENAI_API_KEY not set")
        return None

    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)

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
