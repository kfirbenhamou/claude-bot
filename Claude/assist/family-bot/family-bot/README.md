# 🏠 Family Assistant Bot — כפיר, מורן, עלמה, ארבל

A Telegram bot that sends Hebrew reminders to the family group and privately,
understands free-text replies using OpenAI, and handles both recurring and single events.

## Project structure

```
family-bot/
├── .env                  # secrets (never commit this)
├── requirements.txt
├── main.py               # entry point
├── db/
│   ├── setup.py          # creates all tables and seeds personas
│   └── queries.py        # all DB helpers
├── handlers/
│   ├── incoming.py       # receives Telegram messages, identifies persona
│   └── intent.py         # OpenAI intent detection from Hebrew replies
├── services/
│   ├── reminder.py       # builds and sends reminder messages
│   └── scheduler.py      # cron jobs, expands recurring events
└── utils/
    └── formatting.py     # Hebrew message templates, @tag helpers
```

## Setup (5 steps)

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in your tokens
3. `python db/setup.py`           — creates the DB and seeds the 4 personas
4. Add the bot to your family Telegram group, make it admin
5. `python main.py`               — starts the bot

## Personas

| Name  | Role      | Telegram at launch |
|-------|-----------|--------------------|
| כפיר  | Dad       | yes — group + private |
| מורן  | Mom       | yes — group + private |
| עלמה  | Daughter  | not yet — parents get her reminders |
| ארבל  | Son       | not yet — parents get her reminders |

Alma and Arbel can be added later by updating their `telegram_username`
and `private_chat_id` in the personas table — no code changes needed.

## Adding an event (examples)

```python
# Single event
add_event("חוג ציור", persona_id=3, datetime="2025-10-15 16:00", location="מרכז אמנות", remind_before=60)

# Recurring event — every Tuesday and Thursday at 16:00
add_event("שחייה", persona_id=3, rrule="FREQ=WEEKLY;BYDAY=TU,TH;BYHOUR=16;BYMINUTE=0",
          rrule_start="2025-09-01", remind_before=60)
```
