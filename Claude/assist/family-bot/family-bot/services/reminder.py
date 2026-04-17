from __future__ import annotations
"""
services/reminder.py
Sends reminders to the group and/or privately.
Handles the Alma/Arbel case: parents get a private message on their behalf.
"""

import os
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv

from db.queries import (
    get_persona_by_id,
    get_parents,
    was_reminder_sent,
    was_reminder_sent_recently,
    log_reminder,
    is_occurrence_handled,
)
from utils.formatting import (
    reminder_message,
    parents_reminder_message,
)

load_dotenv(override=True)
GROUP_CHAT_ID = int(os.getenv("FAMILY_GROUP_CHAT_ID", "0"))
GROUP_REMIND_REPEAT_MINUTES = int(os.getenv("GROUP_REMIND_REPEAT_MINUTES", "30"))

def _reminder_keyboard(event_id: int, occurrence_dt: datetime) -> InlineKeyboardMarkup:
    date_str = occurrence_dt.strftime("%Y-%m-%d")
    time_str = occurrence_dt.strftime("%H%M")
    prefix = f"evt:{event_id}:{date_str}:{time_str}"
    keyboard = [
        [
            InlineKeyboardButton("✅ סיום", callback_data=f"{prefix}:confirm"),
            InlineKeyboardButton("⏭ דלג", callback_data=f"{prefix}:skip"),
        ],
        [
            InlineKeyboardButton("⏰ דחה 30", callback_data=f"{prefix}:snooze30"),
            InlineKeyboardButton("❓ שאלה", callback_data=f"{prefix}:question"),
        ],
        [
            InlineKeyboardButton("🗑 הסר", callback_data=f"{prefix}:remove"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_reminder(bot: Bot, event: dict, occurrence_dt: datetime):
    """
    Sends a reminder for a single event occurrence.
    Decides automatically whether to send to group, private, or both,
    and whether to notify parents for Alma/Arbel.
    """
    persona = get_persona_by_id(event["persona_id"])
    if not persona:
        return

    send_to = event["send_to"]  # 'group', 'private', or 'both'
    date_str = occurrence_dt.strftime("%Y-%m-%d")

    # ── Group message ─────────────────────────────────────────────────────────
    if send_to in ("group", "both"):
        if is_occurrence_handled(event["id"], date_str):
            return
        if not was_reminder_sent_recently(event["id"], date_str, "group", within_minutes=GROUP_REMIND_REPEAT_MINUTES):
            text = reminder_message(persona, event, occurrence_dt, is_group=True)
            await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=text,
                reply_markup=_reminder_keyboard(event["id"], occurrence_dt),
            )
            log_reminder(event["id"], date_str, "group", status="sent")

    # ── Private message ───────────────────────────────────────────────────────
    if send_to in ("private", "both"):
        has_telegram = bool(persona["private_chat_id"])

        if has_telegram:
            # Persona has their own Telegram — send directly
            if not was_reminder_sent(event["id"], date_str, "private"):
                text = reminder_message(persona, event, occurrence_dt, is_group=False)
                await bot.send_message(
                    chat_id=persona["private_chat_id"],
                    text=text,
                    reply_markup=_reminder_keyboard(event["id"], occurrence_dt),
                )
                log_reminder(event["id"], date_str, "private")

        else:
            # No personal Telegram yet (Alma / Arbel) —
            # send to each parent who manages this persona
            parents = _get_managing_parents(persona["id"])
            for parent in parents:
                if not parent["private_chat_id"]:
                    continue
                channel = f"private_via_parent_{parent['id']}"
                if not was_reminder_sent(event["id"], date_str, channel):
                    text = parents_reminder_message(persona, event, occurrence_dt)
                    await bot.send_message(
                        chat_id=parent["private_chat_id"],
                        text=text,
                        reply_markup=_reminder_keyboard(event["id"], occurrence_dt),
                    )
                    log_reminder(event["id"], date_str, channel)


def _get_managing_parents(child_persona_id: int) -> list:
    """Returns all parents who have this persona_id in their manages_for list."""
    parents = get_parents()
    result = []
    for parent in parents:
        manages = [m.strip() for m in (parent["manages_for"] or "").split(",") if m.strip()]
        if str(child_persona_id) in manages:
            result.append(parent)
    return result
