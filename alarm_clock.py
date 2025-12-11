#!/usr/bin/env python3
from scheduler import check_alarm, get_greeting, get_today_wake_item
from lcd import lcd_show, lcd_set_backlight
from audio import AudioPlayer
from servo_control import start_servo_waving, stop_servo_waving
from button import init_button
import config
import time
from datetime import datetime

player = AudioPlayer()
alarm_active = False


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
    # explizit: "aktueller Weihnachtssong"
    wake_item = get_today_wake_item()
    print("[Button] TRIPPEL-Klick → spiele aktuellen Weihnachtssong:", wake_item["file"])
    player.play(wake_item["file"])

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

    # Display-Steuerung
    if alarm_active:
        lcd_show(now, wake_item["message"])
    else:
        greeting = get_greeting(now)
        lcd_show(now, greeting["text"])

    time.sleep(0.1)
