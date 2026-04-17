from __future__ import annotations
"""
services/transcription.py
Transcribes Telegram voice messages using the OpenAI Whisper API.
"""

import logging
import os
import tempfile

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

logger = logging.getLogger(__name__)

WHISPER_MODEL = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Whisper artifacts to strip — emitted on blank/silent audio
_BLANK_ARTIFACTS = {"[BLANK_AUDIO]", "[BLANK AUDIO]", "(BLANK_AUDIO)", "(BLANK AUDIO)"}


async def transcribe_voice(file_bytes: bytes, filename: str = "voice.ogg") -> str | None:
    """
    Transcribe raw OGG/OPUS audio bytes via the OpenAI Whisper API.
    Returns the transcribed Hebrew text, or None if audio was blank/failed.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            response = _client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=audio_file,
                language="he",
            )

        os.unlink(tmp_path)

        text = (response.text or "").strip()

        # Guard against blank audio artifacts
        if not text or text in _BLANK_ARTIFACTS:
            logger.info("[whisper] blank audio — ignoring")
            return None

        logger.info(f"[whisper] transcribed: {text!r}")
        return text

    except Exception as exc:
        logger.warning(f"[whisper] transcription failed: {exc}")
        return None
