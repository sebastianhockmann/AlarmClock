"""Shared JSON settings, read by the clock and atomically replaced by the web UI."""
import json
import math
import os
import tempfile
import config

SETTINGS_FILE = config.BASE_DIR / 'settings.json'
MAPPING_FILE = config.BASE_DIR / 'mp3_mapping.json'


def read_json(path):
    try:
        with open(path, encoding='utf-8') as source:
            result = json.load(source)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False) as target:
            name = target.name
            json.dump(data, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def alarm_time():
    settings = read_json(SETTINGS_FILE)
    hour, minute = settings.get('hour'), settings.get('minute')
    if type(hour) is int and type(minute) is int and 0 <= hour < 24 and 0 <= minute < 60:
        return hour, minute
    return config.ALARM_HOUR, config.ALARM_MINUTE


def alarm_enabled():
    enabled = read_json(SETTINGS_FILE).get('enabled')
    return enabled if isinstance(enabled, bool) else config.ALARM_ENABLED


def save_alarm(hour, minute, enabled):
    if not isinstance(hour, int) or not isinstance(minute, int) or not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError('Ungueltige Weckzeit')
    if not isinstance(enabled, bool):
        raise ValueError('Aktiv muss ein boolescher Wert sein')
    settings = read_json(SETTINGS_FILE)
    settings.update(hour=hour, minute=minute, enabled=enabled)
    write_json(SETTINGS_FILE, settings)


def validate_wled_settings(enabled, host, timeout):
    if not isinstance(enabled, bool):
        raise ValueError('Aktiv muss ein boolescher Wert sein')
    if isinstance(timeout, bool):
        raise ValueError('Timeout muss zwischen 0.5 und 30 Sekunden liegen')
    timeout = float(timeout)
    if not math.isfinite(timeout) or not 0.5 <= timeout <= 30:
        raise ValueError('Timeout muss zwischen 0.5 und 30 Sekunden liegen')
    if not isinstance(host, str):
        raise ValueError('Hostname muss Text sein')
    return {'enabled': enabled, 'host': config.normalize_wled_host(host), 'timeout': timeout}


def wled_settings():
    values = read_json(SETTINGS_FILE).get('wled', {})
    if not isinstance(values, dict):
        values = {}
    defaults = {'enabled': config.WLED_ENABLED, 'host': config.WLED_HOST,
                'timeout': config.WLED_TIMEOUT_SECONDS}
    # Invalid individual fields fall back without discarding valid settings.
    result = defaults.copy()
    for key in defaults:
        try:
            result = validate_wled_settings(**{**result, key: values.get(key, defaults[key])})
        except (ValueError, TypeError):
            pass
    return result


def save_wled_settings(enabled, host, timeout):
    values = validate_wled_settings(enabled, host, timeout)
    settings = read_json(SETTINGS_FILE)
    settings['wled'] = values
    write_json(SETTINGS_FILE, settings)
    return values
