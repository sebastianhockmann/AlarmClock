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
    {"date": "12-11", "file": "mp3/xmas/maria.mp3", "message": "Happy Xmas"},
    {"date": "12-12", "file": "mp3/xmas/frosty_snowman.mp3", "message": "2"},
    {"date": "12-13", "file": "mp3/xmas/jingle_bells.mp3", "message": "3"},
    {"date": "12-14", "file": "mp3/xmas/last_christmas.mp3", "message": "4"},
    {"date": "12-15", "file": "mp3/xmas/let_it_snow.mp3", "message": "5"},
    {"date": "12-16", "file": "mp3/xmas/morgen_weihnachtsmann.mp3", "message": "6"},
    {"date": "12-17", "file": "mp3/xmas/oh_tannenbaum.mp3", "message": "7" },
    {"date": "12-18", "file": "mp3/xmas/otto_weihnachtsbaeckerei.mp3", "message": "8"},
    {"date": "12-19", "file": "mp3/xmas/polar_express.mp3", "message": "9"},
    {"date": "12-20", "file": "mp3/xmas/santa_claus_town.mp3", "message": "10"},
    {"date": "12-21", "file": "mp3/xmas/under_mistletoe.mp3", "message": "11"},
    {"date": "12-22", "file": "mp3/xmas/zuckowski_weihnachtsbaeckerei.mp3", "message": "12"},
    
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
    {"start": "18:00", "end": "20:30", "text": "Guten Abend",  "backlight": True},
    # Nacht: Display aus
    {"start": "20:30", "end": "06:00", "text": "Gute Nacht",   "backlight": False},
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
