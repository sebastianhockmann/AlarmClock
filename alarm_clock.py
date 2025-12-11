#!/usr/bin/env python3
from scheduler import check_alarm, get_greeting, get_today_wake_item
from lcd import lcd_show, lcd_set_backlight
from audio import AudioPlayer
from servo_control import start_servo_waving, stop_servo_waving
from button import init_button
from datetime import datetime, date
import config
import time
from log import log
from watchdog import Watchdog
from util import scrolling_text

# ---------------------------------------
# Globale Zustände
# ---------------------------------------

# Spezialanzeige (Countdown / Manual / Schnee)
special = {
    "mode": None,         # "manual", "countdown", "snow"
    "text": "",
    "end": 0,
    "snow_offset": 0
}

player = AudioPlayer()
wd = Watchdog(audio_player_ref=player, button_ref=None, special_ref=special)

alarm_active = False

# -----------------------------
# Button-Aktionen
# -----------------------------

def single_click():
    wd.notify_button_event()
    log("Schalte Backlight um")
    lcd_set_backlight(toggle=True)


def double_click():
    wd.notify_button_event()

    wake_item = get_today_wake_item()
    log("[Button] Doppelklick → spiele Lied:", wake_item["file"])

    try:
        player.play(wake_item["file"])
    except Exception as e:
        log("[Button] Fehler beim Starten des Liedes:", e)

    # Spezialmodus anzeigen
    special["text"] = wake_item["message"]
    special["mode"] = "manual"
    special["end"] = time.time() + 5


def triple_click():
    wd.notify_button_event()

    today = date.today()
    year = today.year
    dec24 = date(year, 12, 24)

    if today <= dec24:
        days = (dec24 - today).days
    else:
        dec24_next = date(year + 1, 12, 24)
        days = (dec24_next - today).days

    if days == 0:
        msg = "Heute ist 24.12!"
    elif days == 1:
        msg = "Noch 1 Tag bis 24.12."
    else:
        msg = f"Noch {days} Tage"

    log("[Button] Triple-Klick → Countdown:", msg)

    special["text"] = msg
    special["mode"] = "countdown"
    special["end"] = time.time() + 5
    special["snow_offset"] = 0


# Button initialisieren
button = init_button(single_click, double_click, triple_click)

# -----------------------------
# Hauptschleife
# -----------------------------
while True:
    #wd.beat()  # Watchdog-Herzschlag
    now = datetime.now()

    # Alarm prüfen
    alarm_state, wake_item = check_alarm(now)

    if alarm_state and not alarm_active:
        alarm_active = True
        player.play(wake_item["file"])
        start_servo_waving()

    elif not alarm_state and alarm_active:
        alarm_active = False
        player.stop()
        stop_servo_waving()

    # -----------------------------
    # Display-Steuerung mit Spezialmodus
    # -----------------------------
    mode = special["mode"]
    display_text = None

    if mode == "manual":
        display_text = special["text"]
        if time.time() > special["end"]:
            special["mode"] = None

    elif mode == "countdown":
        display_text = special["text"]
        if time.time() > special["end"]:
            special["mode"] = "snow"
            special["end"] = time.time() + 15

    elif mode == "snow":
        pattern = "*   *   *   *   *   "
        display_text = scrolling_text(pattern, config.LCD_COLS, special["snow_offset"])
        special["snow_offset"] += 1

        if time.time() > special["end"]:
            special["mode"] = None

    # Normaler Modus, wenn kein Spezialmodus aktiv
    if display_text is None:
        if alarm_active:
            display_text = wake_item["message"]
        else:
            greeting = get_greeting(now)
            display_text = greeting["text"]

    lcd_show(now, display_text)

    time.sleep(0.1)
