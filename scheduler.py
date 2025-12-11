# scheduler.py
from datetime import date, time as dtime
import config
from util import parse_hhmm, time_in_range


# -----------------------------
# Weck-Song / Nachricht pro Tag
# -----------------------------

def get_today_wake_item():
    """
    1. Prüft, ob heute ein Lied in DATE_SONGS zugeordnet ist.
    2. Falls nein: rotiert durch WAKE_ITEMS (Fallback).
    """
    today = date.today()
    today_key = today.strftime("%m-%d")  # z.B. "12-05"

    # 1. Datumsspezifische Einträge prüfen
    for entry in getattr(config, "DATE_SONGS", []):
        if entry.get("date") == today_key:
            return {
                "file": entry.get("file"),
                "message": entry.get("message", config.DEFAULT_WAKE_MESSAGE)
            }

    # 2. Fallback: rotierend aus WAKE_ITEMS
    items = getattr(config, "WAKE_ITEMS", []) or []
    if items:
        idx = today.toordinal() % len(items)
        return items[idx]

    # 3. Fallback, falls WAKE_ITEMS auch leer ist
    return {
        "file": getattr(config, "DEFAULT_SONG", "mp3/happy.mp3"),
        "message": getattr(config, "DEFAULT_MESSAGE", "Guten Morgen!")
    }

# -----------------------------
# Greeting (Tag, Nacht etc.)
# -----------------------------

def get_greeting(now):
    """
    Liefert ein Dict:
        { "text": "...", "backlight": True/False }
    passend zur aktuellen Zeit.
    """
    t = now.time().replace(second=0, microsecond=0)

    for g in config.GREETINGS:
        start = parse_hhmm(g["start"])
        end   = parse_hhmm(g["end"])
        if time_in_range(t, start, end):
            return g

    # failsafe
    return {"text": "", "backlight": True}


# -----------------------------
# Alarmsteuerung
# -----------------------------

_last_alarm_day = None

def check_alarm(now):
    """
    Gibt zurück:
        (alarm_ausgeloest, wake_item)
    """
    global _last_alarm_day

    if not config.ALARM_ENABLED:
        return False, None

    hour  = now.hour
    minute = now.minute

    if (hour == config.ALARM_HOUR and
        minute == config.ALARM_MINUTE and
        _last_alarm_day != now.day):

        _last_alarm_day = now.day
        wake_item = get_today_wake_item()
        return True, wake_item

    return False, None
