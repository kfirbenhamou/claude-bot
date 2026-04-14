import sqlite3
from datetime import datetime, timedelta
import pytz

conn = sqlite3.connect('family_bot.db')
cursor = conn.cursor()

# Get all events
cursor.execute('SELECT id, title, event_datetime, rrule, rrule_start, remind_before_minutes, is_recurring FROM events WHERE active = 1')
events = cursor.fetchall()

print('=== ACTIVE EVENTS ===')
print()

now = datetime.now(pytz.timezone('Asia/Jerusalem'))
print(f'Current time: {now.strftime("%Y-%m-%d %H:%M:%S %Z")}')
print()

for event in events:
    event_id, title, event_dt, rrule, rrule_start, remind_before, is_recurring = event
    print(f'ID {event_id}: {title}')
    print(f'  Recurring: {is_recurring}')
    if event_dt:
        event_obj = datetime.fromisoformat(event_dt)
        reminder_dt = event_obj - timedelta(minutes=remind_before)
        print(f'  Event time: {event_obj}')
        print(f'  Reminder due at: {reminder_dt.strftime("%Y-%m-%d %H:%M:%S")}')
        time_until = (reminder_dt - now).total_seconds() / 3600
        print(f'  Hours until reminder: {time_until:.1f}h')
    if rrule:
        print(f'  RRule: {rrule}')
        print(f'  Start: {rrule_start}')
    print()
