from __future__ import annotations
"""
scripts/gcal_sync_existing.py
One-time migration: push all existing DB events to Google Calendar.

Run from the project root (with venv activated):
    python scripts/gcal_sync_existing.py

Safe to run multiple times — skips events that already have a gcal_event_id.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(override=True)

from db.queries import get_all_active_events, get_persona_by_id, get_gcal_event_id, set_gcal_event_id
from services.gcal import create_gcal_event


def main():
    events = get_all_active_events()
    total = len(events)
    print(f"Found {total} active events in DB.\n")

    synced = 0
    skipped = 0
    failed = 0

    for event in events:
        event_id = event["id"]
        title = event["title"]

        # Skip if already synced
        if get_gcal_event_id(event_id):
            print(f"  ⏭️  [{event_id}] '{title}' — already synced, skipping")
            skipped += 1
            continue

        persona = get_persona_by_id(event["persona_id"])
        persona_name = persona["name"] if persona else "משפחה"

        gcal_id = create_gcal_event(event, persona_name)
        if gcal_id:
            set_gcal_event_id(event_id, gcal_id)
            print(f"  ✅  [{event_id}] '{title}' ({persona_name}) → {gcal_id}")
            synced += 1
        else:
            print(f"  ❌  [{event_id}] '{title}' — failed to sync")
            failed += 1

    print(f"\nDone. Synced: {synced} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    main()
