"""Feste Konfiguration aus config/hardware.json plus Pfade der JSON-Dateien.

Nur Hardware- und Betriebswerte werden hier als Konstanten bereitgestellt;
sie gelten ab Programmstart. Alles, was die Weboberflaeche aendern kann
(Wecker, Weckprogramm, Tasten, WLED, ...), liest settings.py live aus
defaults.json + settings.json.

Umgebungsvariablen haben Vorrang vor hardware.json:
ALARM_ALSA_DEVICE, ALARM_DEBUG, ALARM_WEB_HOST, ALARM_WEB_PORT,
WLED_HOST (Rueckfall WLED_URL) als Default fuer den WLED-Host.
"""
from pathlib import Path
import json
import os
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / 'config'
HARDWARE_FILE = CONFIG_DIR / 'hardware.json'
DEFAULTS_FILE = CONFIG_DIR / 'defaults.json'
EFFECTS_FILE = CONFIG_DIR / 'effects.json'
# Laufzeitdateien der Weboberflaeche (gitignored).
SETTINGS_FILE = CONFIG_DIR / 'settings.json'
# Alte Ablageorte vor dem Umzug nach config/, siehe settings.migrate_legacy().
LEGACY_SETTINGS_FILE = BASE_DIR / 'settings.json'
LEGACY_MAPPING_FILE = BASE_DIR / 'mp3_mapping.json'


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


def _load_hardware():
    try:
        with open(HARDWARE_FILE, encoding='utf-8') as source:
            data = json.load(source)
        if isinstance(data, dict):
            return data
        raise ValueError('kein JSON-Objekt')
    except (OSError, ValueError) as error:
        # Der Wecker soll auch mit kaputter Datei starten: eingebaute Defaults.
        print(f'{HARDWARE_FILE} nicht lesbar ({error}), verwende eingebaute Werte', flush=True)
        return {}


_HARDWARE = _load_hardware()


def _hw(section, key, default):
    value = _HARDWARE.get(section, {})
    value = value.get(key, default) if isinstance(value, dict) else default
    return default if value is None else value


def _address(value, default):
    try:
        return int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return default


# LCD
LCD_ADDRESS = _address(_hw('lcd', 'address', 0x27), 0x27)
LCD_I2C_PORT = int(_hw('lcd', 'i2c_port', 1))
LCD_COLS = int(_hw('lcd', 'cols', 16))
LCD_ROWS = int(_hw('lcd', 'rows', 2))

# Drehencoder (MCP23017) + 4x4-Tastenfeld (PCF8574), siehe tools/rotary_clock.py.
# Optional I2C adapter module: open_controls(emit) -> object with close().
INPUT_MODULE = _hw('inputs', 'module', 'controls_mcp') or None
INPUT_I2C_PORT = int(_hw('inputs', 'i2c_port', LCD_I2C_PORT))
MCP23017_ADDRESS = _address(_hw('inputs', 'mcp23017_address', 0x21), 0x21)
KEYPAD_ADDRESS = _address(_hw('inputs', 'keypad_address', 0x20), 0x20)
BUTTON_HOLD_SECONDS = float(_hw('inputs', 'button_hold_seconds', 2.0))
EFFECT_FAST_SECONDS = float(_hw('inputs', 'effect_fast_seconds', 0.15))
EFFECT_FAST_STEPS = int(_hw('inputs', 'effect_fast_steps', 10))
# Drehrichtung umkehren, falls A/B am Encoder andersherum verdrahtet sind.
LEFT_REVERSE = bool(_hw('inputs', 'left_reverse', False))
RIGHT_REVERSE = bool(_hw('inputs', 'right_reverse', False))
LEGACY_BUTTON_ENABLED = bool(_hw('inputs', 'legacy_button_enabled', False))
BUTTON_PIN = int(_hw('inputs', 'legacy_button_pin', 17))

# Audio
ALSA_DEVICE = os.environ.get('ALARM_ALSA_DEVICE') or _hw('audio', 'alsa_device', 'plughw:3,0')
VOLUME_STEP = int(_hw('audio', 'volume_step', 5))
MUSIC_DIR = BASE_DIR / _hw('audio', 'music_dir', 'mp3')
CLICK_SOUND = BASE_DIR / _hw('audio', 'click_sound', 'sounds/click.wav')

# Weboberflaeche: keine Anmeldung, nur fuers Heimnetz.
WEB_HOST = os.environ.get('ALARM_WEB_HOST') or _hw('web', 'host', '0.0.0.0')
WEB_PORT = int(os.environ.get('ALARM_WEB_PORT') or _hw('web', 'port', 8080))
MAX_UPLOAD_MB = int(_hw('web', 'max_upload_mb', 32))

# Steuerkanal Weboberflaeche -> Wecker-Prozess (nur localhost), siehe ipc.py.
IPC_HOST = _hw('ipc', 'host', '127.0.0.1')
IPC_PORT = int(_hw('ipc', 'port', 8099))

ALEXA_SCRIPT = _hw('alexa', 'script', '')

DEBUG = os.environ.get('ALARM_DEBUG', '1' if _HARDWARE.get('debug', True) else '0') != '0'

# Default fuer den WLED-Host, falls weder settings.json noch defaults.json
# einen gueltigen Wert liefern. WLED_HOST aus der Umgebung ersetzt den Wert
# aus defaults.json, settings.json (Weboberflaeche) hat weiterhin Vorrang.
_ENV_WLED_HOST = os.environ.get('WLED_HOST') or os.environ.get('WLED_URL')
WLED_HOST = normalize_wled_host(_ENV_WLED_HOST or 'wled.local')
WLED_ENABLED = True
WLED_TIMEOUT_SECONDS = 3.0
