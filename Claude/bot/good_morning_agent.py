import os
import requests
import logging
import sys
import re
import random
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# ── Load environment variables ─────────────────────────────────
load_dotenv()

# ── Configuration ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
MODEL = os.getenv("MODEL", "gpt-4o-mini")

RECIPIENTS = [
    {"name": "משפחת בן חמו",  "chat_id": "-5028432647", "send_song": True},
]

# YouTube search settings
YOUTUBE_SEARCH_QUERIES = [
    "שירי בוקר חילוניים"
]
YOUTUBE_RESULTS_POOL = 10   # fetch this many results, then pick randomly

LOG_FILE = Path(__file__).parent / "logs" / "agent.log"
# ───────────────────────────────────────────────────────────────


# ── Logging setup ───────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)
# ───────────────────────────────────────────────────────────────


def validate_url(url: str, timeout: int = 5) -> bool:
    """Return True if the URL is reachable."""
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        valid = response.status_code < 400
        if not valid:
            log.warning(f"URL validation failed [{response.status_code}]: {url}")
        return valid
    except requests.RequestException as e:
        log.warning(f"URL unreachable: {url} — {e}")
        return False


def sanitize_message(text: str) -> str:
    """Strip any URLs from AI-generated text that fail validation."""
    url_pattern = re.compile(r"https?://\S+")
    for url in url_pattern.findall(text):
        clean_url = url.rstrip(".,;:!?)")
        if not validate_url(clean_url):
            log.warning(f"Removing invalid URL from message: {clean_url}")
            text = text.replace(url, "")
    return text.strip()


# ── YouTube ─────────────────────────────────────────────────────

def fetch_youtube_song() -> str | None:
    """Search YouTube for a fresh good morning song and return its URL."""
    query = random.choice(YOUTUBE_SEARCH_QUERIES)
    log.info(f"Searching YouTube for: '{query}'")

    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part":       "snippet",
            "q":          query,
            "type":       "video",
            "videoCategoryId": "10",   # Music category
            "maxResults": YOUTUBE_RESULTS_POOL,
            "safeSearch": "strict",
            "key":        YOUTUBE_API_KEY,
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        items = response.json().get("items", [])
        if not items:
            log.warning("YouTube search returned no results.")
            return None

        # Pick a random video from the results pool
        video = random.choice(items)
        video_id = video["id"]["videoId"]
        title    = video["snippet"]["title"]
        channel  = video["snippet"]["channelTitle"]
        yt_url   = f"https://www.youtube.com/watch?v={video_id}"

        log.info(f"YouTube song selected: '{title}' by {channel} — {yt_url}")

        # Validate the URL is reachable
        if not validate_url(yt_url):
            log.warning(f"YouTube URL unreachable: {yt_url}")
            return None

        return yt_url

    except Exception as e:
        log.error(f"YouTube fetch failed: {e}")
        return None


# ── Core logic ──────────────────────────────────────────────────

def generate_morning_message(name: str) -> str:
    """Ask GPT-4o mini to write a warm, personalised Hebrew good morning message."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    today  = datetime.now().strftime("%A, %B %d")

    prompt = (
        f"היום הוא {today}. כתוב הודעת בוקר טוב קצרה, חמה וידידותית בעברית "
        f"עבור {name}. "
        "גרום לה להרגיש אישית וכנה — לא גנרית. "
        "כלול מנה קטנה של אופטימיות או מחשבה פשוטה ליום. "
        "עד 3 משפטים. ללא האשטאגים, ללא חתימה, רק ההודעה. "
        "אל תכלול קישורים או כתובות URL."
    )

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()
    return sanitize_message(raw)


def send_telegram_message(chat_id: str, text: str) -> bool:
    """Send a text message via the Telegram Bot API."""
    if not validate_url("https://api.telegram.org"):
        log.error("Telegram API is unreachable.")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        if not response.ok:
            log.error(f"Telegram error {response.status_code}: {response.text}")
        return response.ok
    except requests.RequestException as e:
        log.error(f"Failed to send message: {e}")
        return False


def main():
    log.info("=" * 50)
    log.info("Good Morning Agent started")

    # Fetch one song for all recipients that need it (avoid duplicate API calls)
    song_url = None
    if any(r.get("send_song") for r in RECIPIENTS):
        song_url = fetch_youtube_song()
        if not song_url:
            log.warning("Could not fetch a YouTube song today — will skip for all recipients.")

    success_count = 0

    for recipient in RECIPIENTS:
        name      = recipient["name"]
        chat_id   = recipient["chat_id"]
        send_song = recipient.get("send_song", False)

        log.info(f"Processing recipient: {name}")

        # Generate Hebrew morning message
        try:
            message = generate_morning_message(name)
            log.info(f"Generated message: {message}")
        except Exception as e:
            log.error(f"Failed to generate message for {name}: {e}")
            continue

        # Send the morning message
        sent = send_telegram_message(chat_id, message)
        if sent:
            log.info(f"✅ Message sent to {name} successfully")
            success_count += 1
        else:
            log.error(f"❌ Failed to send message to {name}")
            continue

        # Send YouTube song link as a separate message
        if send_song and song_url:
            song_sent = send_telegram_message(chat_id, song_url)
            log.info(f"Song link {'sent' if song_sent else 'failed'} for {name}: {song_url}")

    log.info(f"Done. {success_count}/{len(RECIPIENTS)} messages sent.")
    log.info("=" * 50)

    if success_count == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()