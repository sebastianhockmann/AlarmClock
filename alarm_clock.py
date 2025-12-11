#!/usr/bin/env python3
from scheduler import check_alarm, get_greeting, get_today_wake_item
from lcd import lcd_show, lcd_set_backlight
from audio import AudioPlayer
from servo_control import start_servo_waving, stop_servo_waving
from button import init_button
from datetime import datetime, date
import config
import time

from util import scrolling_text  # für die Schneeflocken-Anzeige

player = AudioPlayer()
alarm_active = False

# Spezialanzeige (Countdown / Schnee)
special_mode = None       # None, "countdown", "snow"
special_text = ""
special_mode_end = 0
snow_offset = 0

# -----------------------------
# Button-Aktionen
# -----------------------------

def single_click():
    # Backlight toggeln
    print("Schalte Backlight um")
    lcd_set_backlight(toggle=True)


def double_click():
    # Weihnachtssong des Tages abspielen
    wake_item = get_today_wake_item()
    print("[Button] Doppelklick → spiele Lied:", wake_item["file"])
    player.play(wake_item["file"])


def triple_click():
    global special_mode, special_text, special_mode_end, snow_offset

    today = date.today()
    year = today.year
    dec24 = date(year, 12, 24)

    if today <= dec24:
        days = (dec24 - today).days
    else:
        # Wenn wir nach dem 24.12. sind → bis nächstes Jahr zählen
        dec24_next = date(year + 1, 12, 24)
        days = (dec24_next - today).days

    if days == 0:
        msg = "Heute ist 24.12!"
    elif days == 1:
        msg = "Noch 1 Tag bis 24.12."
    else:
        msg = f"Noch {days} Tage"

    print("[Button] Triple-Klick → Countdown:", msg)

    special_text = msg
    special_mode = "countdown"
    special_mode_end = time.time() + 5   # 5 Sekunden Countdown anzeigen
    snow_offset = 0                      # Schneeflocken-Startposition zurücksetzen


# Button initialisieren
button = init_button(single_click, double_click, triple_click)


# -----------------------------
# Hauptschleife
# -----------------------------
while True:
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
    display_text = None

    if special_mode == "countdown":
        # Countdown-Text anzeigen
        display_text = special_text
        # Nach Ablauf in Schneemodus wechseln
        if time.time() > special_mode_end:
            special_mode = "snow"
            special_mode_end = time.time() + 15  # 15 Sekunden Schneeflocken

    elif special_mode == "snow":
        # einfache Schneeflocken-Animation über die untere Zeile
        pattern = "*   *   *   *   *   "
        display_text = scrolling_text(pattern, config.LCD_COLS, snow_offset)
        snow_offset += 1
        # Nach Ablauf zurück in den Normalmodus
        if time.time() > special_mode_end:
            special_mode = None

    # Wenn kein Spezialmodus aktiv ist → normaler Text
    if display_text is None:
        if alarm_active:
            display_text = wake_item["message"]
        else:
            greeting = get_greeting(now)
            display_text = greeting["text"]

    # Anzeige tatsächlich schreiben
    lcd_show(now, display_text)

    time.sleep(0.1)
