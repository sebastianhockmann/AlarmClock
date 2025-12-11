# config.py

# =========================
# Alarm-Einstellungen
# =========================
ALARM_ENABLED = True
ALARM_HOUR = 6        # Weckzeit Stunde
ALARM_MINUTE = 15     # Weckzeit Minute

# Wenn True: beim Alarm Backlight auf jeden Fall AN
ALARM_BACKLIGHT = True

# =========================================================
# Datumsspezifische Weihnachtslieder
# =========================================================
# Format "MM-DD" → jedes Jahr gültig
# Wird exakt an diesem Datum abgespielt
DATE_SONGS = [
    {"date": "12-01", "file": "mp3/xmas/song1.mp3", "message": "Es geht los! Weihnachtszeit beginnt 🎄"},
    {"date": "12-02", "file": "mp3/xmas/song2.mp3", "message": "2. Dezember – Musik an! 🎶"},
    {"date": "12-03", "file": "mp3/xmas/song3.mp3", "message": "3. Dezember – Ein schöner Tag beginnt!"},
    {"date": "12-04", "file": "mp3/xmas/song4.mp3", "message": "4. Dezember – Viel Freude heute! ⭐"},
    {"date": "12-05", "file": "mp3/xmas/song5.mp3", "message": "5. Dezember – Musik für die Seele"},
    {"date": "12-06", "file": "mp3/xmas/nicholas.mp3", "message": "Nikolaus! 🎅"},
    {"date": "12-24", "file": "mp3/xmas/heiligabend.mp3", "message": "Frohe Weihnachten! ✨"},
    {"date": "12-25", "file": "mp3/xmas/christmas_day.mp3", "message": "Schönen 1. Weihnachtstag! 🎁"},
    {"date": "12-26", "file": "mp3/xmas/zweiter_feiertag.mp3", "message": "Schönen 2. Weihnachtstag! 🎄"},
]

# Welche Audiokarte soll verwendet werden?
ALSA_DEVICE = "plughw:3,0"

DEFAULT_SONG = "mp3/xmas/default.mp3"
DEFAULT_MESSAGE = "Guten Morgen!"

# =========================
# Greeting-Zeiten & Backlight
# =========================
# Zeitspannen im Format "HH:MM".
# backlight=True/False steuert, ob in dieser Zeit das Backlight an sein soll
# (sofern der Benutzer es nicht manuell überschrieben hat).
GREETINGS = [
    {"start": "06:00", "end": "10:00", "text": "Guten Morgen", "backlight": True},
    {"start": "10:00", "end": "14:00", "text": "Guten Mittag", "backlight": True},
    {"start": "14:00", "end": "18:00", "text": "Guten Tag",    "backlight": True},
    {"start": "18:00", "end": "22:00", "text": "Guten Abend",  "backlight": True},
    # Nacht: Display aus
    {"start": "22:00", "end": "06:00", "text": "Gute Nacht",   "backlight": False},
]

# =========================
# Hardware-Pins
# =========================
BUTTON_PIN = 17     # GPIO-Pin für den Taster
SERVO_PIN = 18      # GPIO-Pin für das PWM-Signal (Servo)

# LCD-Einstellungen
LCD_ADDRESS = 0x27  # I2C-Adresse (prüfen mit "i2cdetect -y 1")
LCD_COLS = 16       # Spalten
LCD_ROWS = 2        # Zeilen
