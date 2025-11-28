# config.py 

# Alarm-Einstellungen
ALARM_ENABLED = True
ALARM_HOUR = 6      # Beispiel: 07 Uhr
ALARM_MINUTE = 1  # Beispiel: 30 Minuten

# Hardware-Pins (Raspberry Pi)

BUTTON_PIN = 17     # GPIO-Pin für den Taster

# LCD-Einstellungen
LCD_ADDRESS = 0x27  # I2C-Adresse (prüfe mit "i2cdetect -y 1")
LCD_COLS = 16       # Anzahl der Spalten
LCD_ROWS = 2        # Anzahl der Zeilen

SERVO_PIN = 18      # GPIO-Pin für das PWM-Signal

# MP3 Datei (Pfad zur MP3-Datei, die abgespielt werden soll)
MP3_FILE = "mp3/happy.mp3"