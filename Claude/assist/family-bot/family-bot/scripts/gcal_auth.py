"""
scripts/gcal_auth.py
One-time Google Calendar OAuth2 setup.

Run once from the project root (with a browser available):
    python scripts/gcal_auth.py

What it does:
  1. Reads credentials.json (downloaded from Google Cloud Console).
  2. Opens a browser window — you log in and click Allow.
  3. Saves token.json next to credentials.json (or the path in GCAL_TOKEN_PATH).

After this, the bot uses token.json forever (auto-refreshes in the background).

Google Cloud Console setup (do this once before running the script):
  1. Go to https://console.cloud.google.com/
  2. Create a project (or select an existing one).
  3. Enable the Google Calendar API.
  4. Go to APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID.
  5. Application type: Desktop app.
  6. Download the JSON file and save it as credentials.json next to this script
     (or set GCAL_CREDENTIALS_PATH in .env).
"""

import os
import sys

# Allow running from the project root: python scripts/gcal_auth.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(override=True)

CREDENTIALS_PATH = os.getenv("GCAL_CREDENTIALS_PATH", "credentials.json")
TOKEN_PATH = os.getenv("GCAL_TOKEN_PATH", "token.json")
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(CREDENTIALS_PATH):
        print(f"❌  credentials.json not found at: {CREDENTIALS_PATH}")
        print()
        print("Steps to fix:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Enable the Google Calendar API.")
        print("  3. Create OAuth 2.0 credentials (Desktop app).")
        print("  4. Download the JSON and save it as:", CREDENTIALS_PATH)
        sys.exit(1)

    print(f"📂  Using credentials: {CREDENTIALS_PATH}")
    print(f"💾  Will save token to: {TOKEN_PATH}")
    print()
    print("A browser window will open. Log in with the Google account that owns")
    print("the family calendar, then click Allow.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "w") as fh:
        fh.write(creds.to_json())

    print()
    print(f"✅  token.json saved to: {TOKEN_PATH}")
    print()
    print("Next steps:")
    print("  1. Find your Calendar ID:")
    print("     Google Calendar → ⚙️ Settings → your calendar → 'Calendar ID'")
    print("     It looks like: abc123@group.calendar.google.com")
    print("     (Use 'primary' for your main calendar.)")
    print()
    print("  2. Add to .env:")
    print(f"     GCAL_TOKEN_PATH={TOKEN_PATH}")
    print(f"     GCAL_CREDENTIALS_PATH={CREDENTIALS_PATH}")
    print("     GCAL_CALENDAR_ID=<your calendar ID>")
    print()
    print("  3. Restart the bot — new events will sync to Google Calendar automatically.")


if __name__ == "__main__":
    main()
