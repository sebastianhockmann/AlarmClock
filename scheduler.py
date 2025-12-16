# scheduler.py
from datetime import date, time as dtime
import config
from util import parse_hhmm, time_in_range

# -----------------------------
# Weckzeit pro Tag
# -----------------------------

def get_today_alarm_time(now):
    """
    Liefert datetime.time für die heutige Weckzeit
    basierend auf config.ALARM_TIMES (Wochentag)
    """
    weekday = now.weekday()  # Montag=0

    alarm_times = getattr(config, "ALARM_TIMES", {})
    default_time = getattr(
        config,
        "DEFAULT_ALARM_TIME",
        {"hour": 6, "minute": 15}   # HARTE DEFAULTS
    )

    entry = alarm_times.get(weekday, default_time)

    return dtime(entry["hour"], entry["minute"])



# -----------------------------
# Weck-Song / Nachricht pro Tag
# -----------------------------

def get_today_wake_item():
    """
    1. Prüft, ob heute ein Lied in DATE_SONGS zugeordnet ist.
    2. Falls nein: rotiert durch WAKE_ITEMS (Fallback).
    3. Falls nichts vorhanden: DEFAULT-Song/Message.
    """
    today = date.today()
    today_key = today.strftime("%m-%d")  # z.B. "12-05"

    # 1. Datumsspezifische Einträge prüfen
    for entry in getattr(config, "DATE_SONGS", []):
        if entry.get("date") == today_key:
            return {
                "file": entry.get("file"),
                "message": entry.get("message", config.DEFAULT_MESSAGE)
            }

    # 2. Fallback: rotierend aus WAKE_ITEMS
    items = getattr(config, "WAKE_ITEMS", []) or []
    if items:
        idx = today.toordinal() % len(items)
        return items[idx]

    # 3. Letzter Fallback
    return {
        "file": getattr(config, "DEFAULT_SONG", "mp3/happy.mp3"),
        "message": getattr(config, "DEFAULT_MESSAGE", "Guten Morgen!")
    }


# -----------------------------
# Greeting (Tag, Nacht etc.)
# -----------------------------

def get_greeting(now):
    """
    Liefert:
        { "text": "...", "backlight": True/False }
    passend zur aktuellen Uhrzeit gemäß config.GREETINGS.
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

    if not getattr(config, "ALARM_ENABLED", False):
        return False, None

    # Zeit muss gültig sein (nach Boot/NTP)
    if now.year < 2024:
        return False, None

    target = get_today_alarm_time(now)

    now_t = now.time()
    target_seconds = target.hour * 3600 + target.minute * 60
    now_seconds = now_t.hour * 3600 + now_t.minute * 60 + now_t.second

    # Alarm-Fenster: 0–60 Sekunden nach Weckzeit
    ALARM_WINDOW = 60

    if (
        target_seconds <= now_seconds < target_seconds + ALARM_WINDOW
        and _last_alarm_day != now.day
    ):
        _last_alarm_day = now.day
        wake_item = get_today_wake_item()
        return True, wake_item

    return False, None

