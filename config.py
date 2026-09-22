from pathlib import Path
import os
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent


def normalize_wled_host(value):
    host = str(value or 'wled.local').strip() or 'wled.local'
    parsed = urlsplit(host if '://' in host else 'http://' + host)
    if (parsed.scheme != 'http' or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ('', '/') or parsed.query
            or parsed.fragment or any(c.isspace() for c in host)):
        raise ValueError('Hostname/IP oder http://Hostname ohne Pfad angeben')
    # Preserve optional ports; accessing .port also validates its range.
    port = parsed.port
    name = parsed.hostname
    if ':' in name:
        name = '[' + name + ']'
    return name + (f':{port}' if port is not None else '')


# WLED settings are centrally configured and stored in settings.json.
# Supported values are hostnames like wled.local/alarm-led.local and IPv4 addresses.
WLED_ENABLED = True
WLED_HOST = normalize_wled_host(os.environ.get('WLED_HOST') or os.environ.get('WLED_URL') or 'wled.local')
WLED_TIMEOUT_SECONDS = 3.0

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
    {"date": "12-13", "file": "mp3/xmas/jingle_bells..mp3", "message": "3"},
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
ALSA_DEVICE = os.environ.get("ALARM_ALSA_DEVICE", "plughw:3,0")

# Lautstaerke in Prozent (0-100) je Schritt am rechten Drehknopf.
VOLUME_STEP = 5

# =========================
# Debug-Ausgaben
# =========================
# Bei True gibt jede ausgeloeste Aktion (Eingabe-Events, Effektwechsel,
# WLED-Befehle) eine Zeile auf der Konsole aus. Mit ALARM_DEBUG=0 abschaltbar.
DEBUG = os.environ.get("ALARM_DEBUG", "1") != "0"

# =========================
# Weboberfläche
# =========================
# 0.0.0.0 bindet an alle Netzwerkschnittstellen und macht die Oberfläche im
# lokalen Netzwerk erreichbar. Die Oberfläche hat KEINE Anmeldung; das Gerät
# darf deshalb nur in einem vertrauenswürdigen Heimnetz stehen und nicht per
# Portweiterleitung direkt aus dem Internet erreichbar sein.
WEB_HOST = os.environ.get("ALARM_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("ALARM_WEB_PORT", "8080"))

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


# Alarm remains active until stopped or this duration expires.
ALARM_DURATION_SECONDS = 300
LCD_I2C_PORT = 1

# Daily rotation; replace these entries with your own music and sayings.
WAKE_ITEMS = [
    {"file": entry["file"], "message": message}
    for entry, message in zip(DATE_SONGS, [
        "Heute ist dein Tag!", "Ein Schritt nach dem anderen.",
        "Mach etwas Schoenes.", "Neuer Tag, neues Glueck!",
        "Nimm dir Zeit zum Lachen.", "Kleine Schritte zaehlen.",
        "Bleib neugierig!", "Du kannst etwas bewegen.",
        "Zeit fuer neue Ideen.", "Geniesse den Augenblick.",
        "Heute darf leicht sein.", "Schoen, dass du da bist!",
    ])
]

# WLED communicates over HTTP/Wi-Fi, local peripherals over I2C.
EFFECT_LIBRARY = BASE_DIR / "effects.json"
ALARM_EFFECT = None  # library ID, e.g. "warm" or "music"

# =========================
# Drehencoder (MCP23017) + 4x4-Tastenfeld (PCF8574)
# =========================
# Durch Messung bestaetigte Verkabelung, siehe rotary_clock.py:
# MCP23017 0x21 - links: PB6/PB7 (A/B), PB5 (Taster); rechts: PA0/PA1 (A/B), PA2 (Taster).
# Tastenfeld 0x20 - Zeilen P0..P3, Spalten P4..P7. Mit "i2cdetect -y 1" pruefen.
INPUT_I2C_PORT = LCD_I2C_PORT
MCP23017_ADDRESS = 0x21
KEYPAD_ADDRESS = 0x20

# Optional I2C adapter module: open_controls(emit) -> object with close().
# emit("left_rotate", signed_steps), emit("left_press"), emit("key", "1")
# emit("right_rotate", signed_steps), emit("right_press")
INPUT_MODULE = "controls_mcp"
LEGACY_BUTTON_ENABLED = False
