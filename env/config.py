# config.py

# Alarm-Einstellungen
ALARM_ENABLED = True
ALARM_HOUR = 7      # Beispiel: 07 Uhr
ALARM_MINUTE = 30   # Beispiel: 30 Minuten

# Hardware-Pins (an den Raspberry Pi angeschlossen)
BUZZER_PIN = 18     # GPIO-Pin für den Buzzer
BUTTON_PIN = 17     # GPIO-Pin für den Taster

# LCD-Einstellungen
LCD_ADDRESS = 0x27  # I2C-Adresse (prüfe mit "i2cdetect -y 1")
LCD_COLS = 16       # Anzahl der Spalten
LCD_ROWS = 2        # Anzahl der Zeilen
