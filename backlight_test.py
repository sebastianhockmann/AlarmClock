#!/usr/bin/env python3
import time
from RPLCD.i2c import CharLCD
from gpiozero import Button
import config

# LCD initialisieren
lcd = CharLCD(
    'PCF8574',
    config.LCD_ADDRESS,
    cols=config.LCD_COLS,
    rows=config.LCD_ROWS
)

# Button initialisieren (wie im Hauptprogramm)
button = Button(config.BUTTON_PIN, pull_up=True, bounce_time=0.2)

# Startzustand: Backlight an
backlight_on = True
lcd.backlight_enabled = True
lcd.clear()
lcd.write_string("Backlight: EIN")


def toggle_backlight():
    global backlight_on
    backlight_on = not backlight_on
    lcd.backlight_enabled = backlight_on

    lcd.clear()
    if backlight_on:
        lcd.write_string("Backlight: EIN")
        print("Backlight eingeschaltet")
    else:
        lcd.write_string("Backlight: AUS")
        print("Backlight ausgeschaltet")


# Callback registrieren
button.when_pressed = toggle_backlight

print("Taster-Backlight-Test laeuft. Druecke den Knopf auf GPIO", config.BUTTON_PIN)

try:
    # Endlosschleife, damit das Programm läuft
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    pass
finally:
    lcd.clear()
    lcd.backlight_enabled = True  # optional: beim Beenden wieder anschalten
