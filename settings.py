"""Web-editierbare Einstellungen: config/defaults.json + config/settings.json.

defaults.json (versioniert) liefert fuer jede Sektion den Standard,
settings.json (gitignored, von der Weboberflaeche geschrieben) ueberschreibt
ihn: Objekte werden feldweise zusammengefuehrt, Listen komplett ersetzt.
Wecker und Weboberflaeche lesen live; ein Neustart ist nie noetig.

Jede Sektion hat einen Validator. Beim Speichern (strict) fuehrt ein
ungueltiger Wert zu ValueError mit deutscher Meldung fuer die Oberflaeche.
Beim Laden faellt ein ungueltiges Feld still auf den Standard zurueck bzw.
ein ungueltiger Listeneintrag wird uebersprungen - der Wecker laeuft weiter.
"""
import copy
from datetime import datetime
import json
import math
import os
import re
import tempfile
import threading
import uuid
import config

KEYPAD_KEYS = tuple('123A456B789C*0#D')
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


# ---------------------------------------------------------------------------
# JSON-Dateien
# ---------------------------------------------------------------------------

def read_json(path, default=None):
    """JSON lesen; bei fehlender/kaputter Datei den Default (Standard: {})."""
    fallback = {} if default is None else default
    try:
        with open(path, encoding='utf-8') as source:
            result = json.load(source)
    except (OSError, ValueError):
        return fallback
    return result if isinstance(result, type(fallback)) else fallback


def write_json(path, data):
    """Atomar ersetzen: der andere Prozess sieht nie eine halbe Datei."""
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


def deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override)
    result = copy.deepcopy(base)
    for key, value in override.items():
        result[key] = deep_merge(result[key], value) if key in result else copy.deepcopy(value)
    return result


# ---------------------------------------------------------------------------
# Einzelwerte
# ---------------------------------------------------------------------------

def boolean(value):
    if not isinstance(value, bool):
        raise ValueError('muss an/aus sein')
    return value


def int_range(low, high):
    def convert(value):
        if isinstance(value, bool):
            raise ValueError(f'muss eine Zahl von {low} bis {high} sein')
        if isinstance(value, str):
            value = value.strip()
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f'muss eine Zahl von {low} bis {high} sein') from None
        if not math.isfinite(number) or number != int(number) or not low <= number <= high:
            raise ValueError(f'muss eine ganze Zahl von {low} bis {high} sein')
        return int(number)
    return convert


def float_range(low, high, optional=False):
    def convert(value):
        if optional and value in (None, ''):
            return None
        if isinstance(value, bool):
            raise ValueError(f'muss zwischen {low} und {high} liegen')
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f'muss zwischen {low} und {high} liegen') from None
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'muss zwischen {low} und {high} liegen')
        return number
    return convert


def choice(*options):
    def convert(value):
        if value not in options:
            raise ValueError('muss eines von ' + ', '.join(map(str, options)) + ' sein')
        return value
    return convert


def text(max_length, required=False):
    def convert(value):
        if value is None:
            value = ''
        if not isinstance(value, str):
            raise ValueError('muss Text sein')
        value = value.strip()
        if required and not value:
            raise ValueError('darf nicht leer sein')
        if len(value) > max_length:
            raise ValueError(f'darf hoechstens {max_length} Zeichen haben')
        return value
    return convert


def hhmm(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,2}:\d{2}', value.strip()):
        raise ValueError('Uhrzeit als HH:MM angeben')
    hour, minute = (int(part) for part in value.strip().split(':'))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError('Uhrzeit als HH:MM angeben')
    return f'{hour:02d}:{minute:02d}'


def date_key(value):
    """'MM-DD' (jedes Jahr) oder 'YYYY-MM-DD' (einmalig)."""
    if not isinstance(value, str):
        raise ValueError('Datum als MM-DD oder YYYY-MM-DD angeben')
    value = value.strip()
    try:
        parsed = datetime.strptime(value if len(value) == 10 else '2000-' + value, '%Y-%m-%d')
    except ValueError:
        raise ValueError('Datum als MM-DD oder YYYY-MM-DD angeben') from None
    if value not in (parsed.strftime('%Y-%m-%d'), parsed.strftime('%m-%d')):
        raise ValueError('Datum als MM-DD oder YYYY-MM-DD angeben')
    return value


def music_file(value):
    """Pfad relativ zum Projekt, muss im Musikordner liegen und .mp3 sein."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('MP3-Datei waehlen')
    path = (config.BASE_DIR / value.strip()).resolve()
    if not path.is_relative_to(config.MUSIC_DIR.resolve()) or path.suffix.lower() != '.mp3':
        raise ValueError('MP3-Datei aus dem Musikordner waehlen')
    return path.relative_to(config.BASE_DIR.resolve()).as_posix()


def url(value):
    if not isinstance(value, str) or not re.match(r'https?://[^\s/]+', value.strip()):
        raise ValueError('URL mit http:// oder https:// angeben')
    return value.strip()


def days(value):
    if not isinstance(value, list) or any(isinstance(day, bool) or day not in ALL_DAYS for day in value):
        raise ValueError('Wochentage 0 (Mo) bis 6 (So) angeben')
    return sorted(set(value))


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', value):
        raise ValueError('ID nur aus Buchstaben, Ziffern, _ und - (max. 40)')
    return value


def optional(convert):
    def wrapper(value):
        return '' if value in (None, '') else convert(value)
    return wrapper


def wled_host(value):
    if not isinstance(value, str):
        raise ValueError('Hostname muss Text sein')
    return config.normalize_wled_host(value)


def validate_fields(value, spec, strict, defaults=None, label=''):
    """Objekt feldweise pruefen. spec: {feld: (converter, eingebauter Rueckfall)}."""
    if not isinstance(value, dict):
        if strict:
            raise ValueError(f'{label or "Eintrag"} muss ein Objekt sein')
        value = {}
    defaults = defaults if isinstance(defaults, dict) else {}
    result = {}
    for field, (convert, fallback) in spec.items():
        try:
            result[field] = convert(value.get(field, defaults.get(field, fallback)))
        except (ValueError, TypeError) as error:
            if strict:
                raise ValueError(f'{label}{FIELD_NAMES.get(field, field)}: {error}') from None
            try:
                result[field] = convert(defaults.get(field, fallback))
            except (ValueError, TypeError):
                result[field] = fallback
    return result


FIELD_NAMES = {
    'time': 'Uhrzeit', 'days': 'Wochentage', 'label': 'Name', 'enabled': 'Aktiv',
    'host': 'Hostname', 'timeout': 'Timeout', 'effect': 'Lichteffekt',
    'light_lead_minutes': 'Licht-Vorlauf', 'light_ramp_minutes': 'Licht-Rampe',
    'brightness_start': 'Helligkeit Start', 'brightness_end': 'Helligkeit Ende',
    'volume_start': 'Lautstaerke Start', 'volume_end': 'Lautstaerke Ende',
    'volume_ramp_seconds': 'Lautstaerke-Rampe', 'max_minutes': 'Maximale Dauer',
    'snooze_minutes': 'Schlummerzeit', 'date': 'Datum', 'file': 'Datei',
    'message': 'Spruch', 'start': 'Beginn', 'end': 'Ende', 'text': 'Text',
    'url': 'URL', 'service': 'Service', 'entity_id': 'Entity-ID', 'device': 'Geraet',
    'latitude': 'Breitengrad', 'longitude': 'Laengengrad', 'name': 'Name',
}


# ---------------------------------------------------------------------------
# Sektionen
# ---------------------------------------------------------------------------

WLED_SPEC = {
    'enabled': (boolean, True),
    'host': (wled_host, config.WLED_HOST),
    'timeout': (float_range(0.5, 30), config.WLED_TIMEOUT_SECONDS),
}

WAKE_SPEC = {
    'effect': (optional(ident), ''),
    'light_lead_minutes': (int_range(0, 60), 0),
    'light_ramp_minutes': (int_range(0, 60), 2),
    'brightness_start': (int_range(1, 100), 3),
    'brightness_end': (int_range(1, 100), 80),
    'music': (choice('daily', 'random', 'none'), 'daily'),
    'volume_start': (int_range(0, 100), 20),
    'volume_end': (int_range(0, 100), 70),
    'volume_ramp_seconds': (int_range(0, 600), 60),
    'stop_after_song': (boolean, True),
    'max_minutes': (int_range(1, 120), 5),
    'light_end': (choice('keep', 'off'), 'off'),
    'snooze_minutes': (int_range(1, 60), 9),
    'snooze_any_key': (boolean, True),
    'backlight': (boolean, True),
    'show_weather': (boolean, False),
}

ALARM_SPEC = {
    'id': (ident, ''),
    'label': (text(30), 'Wecker'),
    'enabled': (boolean, True),
    'time': (hhmm, '06:15'),
    'days': (days, ALL_DAYS),
}

GREETING_SPEC = {
    'start': (hhmm, '00:00'),
    'end': (hhmm, '00:00'),
    'text': (text(60), ''),
    'backlight': (boolean, True),
}

DATE_SONG_SPEC = {
    'date': (date_key, None),
    'file': (music_file, None),
    'message': (text(120), ''),
}

ROTATION_SPEC = {
    'file': (music_file, None),
    'message': (text(120), ''),
}

MUSIC_SPEC = {
    'default_song': (music_file, 'mp3/xmas/default.mp3'),
    'default_message': (text(120), 'Guten Morgen!'),
}

HOME_ASSISTANT_SPEC = {
    'url': (optional(url), ''),
    'token': (text(1000), ''),
}

WEATHER_SPEC = {
    'location': (text(60), ''),
    'latitude': (float_range(-90, 90, optional=True), None),
    'longitude': (float_range(-180, 180, optional=True), None),
}

ALEXA_SPEC = {
    'default_device': (text(80), ''),
}

# Tastenaktionen. 'label' ist bei allen optional und erscheint auf dem LCD.
ACTION_SPECS = {
    'none': {},
    'effect': {'effect': (ident, 'off')},
    'light': {'mode': (choice('toggle', 'on', 'off'), 'toggle')},
    'music': {'source': (choice('today', 'random', 'toggle', 'stop'), 'toggle')},
    'display': {},
    'snooze': {},
    'wake_test': {},
    'alarm_toggle': {},
    'weather': {},
    'http': {'url': (url, None), 'method': (choice('GET', 'POST'), 'GET'),
             'body': (text(2000), '')},
    'home_assistant': {'service': (lambda v: _service(v), None),
                       'entity_id': (text(120, required=True), None)},
    'alexa': {'device': (text(80), ''),
              'command': (choice('text', 'routine', 'speak', 'weather'), 'text'),
              'text': (text(300), '')},
}


def _service(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', value.strip()):
        raise ValueError('als domain.service angeben, z. B. light.toggle')
    return value.strip()


def validate_action(value, strict=True, label=''):
    if not isinstance(value, dict) or value.get('type') not in ACTION_SPECS:
        if strict:
            raise ValueError(f'{label}unbekannte Aktion')
        return {'type': 'none'}
    action_type = value['type']
    result = {'type': action_type}
    result.update(validate_fields(value, ACTION_SPECS[action_type], True, label=label))
    if action_type in ('alexa',) and value.get('command') != 'weather' and not result['text']:
        raise ValueError(f'{label}Text/Routine fehlt')
    label_text = text(40)(value.get('label'))
    if label_text:
        result['label'] = label_text
    return result


def _validate_list(value, validate_entry, strict, name, max_items=100):
    if not isinstance(value, list):
        if strict:
            raise ValueError(f'{name} muss eine Liste sein')
        return []
    if len(value) > max_items:
        if strict:
            raise ValueError(f'{name}: hoechstens {max_items} Eintraege')
        value = value[:max_items]
    result = []
    for number, entry in enumerate(value, 1):
        try:
            result.append(validate_entry(entry, f'{name} {number}: '))
        except (ValueError, TypeError):
            if strict:
                raise
    return result


def _strict_fields(spec):
    return lambda entry, label: validate_fields(entry, spec, True, label=label)


def validate_alarms(value, strict=True):
    def entry(item, label):
        if isinstance(item, dict) and not item.get('id'):
            item = {**item, 'id': 'w' + uuid.uuid4().hex[:8]}
        return validate_fields(item, ALARM_SPEC, True, label=label)
    alarms = _validate_list(value, entry, strict, 'Wecker', 20)
    seen = set()
    for alarm in alarms:
        if alarm['id'] in seen:
            alarm['id'] = 'w' + uuid.uuid4().hex[:8]
        seen.add(alarm['id'])
    return alarms


def validate_greetings(value, strict=True):
    return _validate_list(value, _strict_fields(GREETING_SPEC), strict, 'Begruessung', 24)


def validate_music(value, strict=True, defaults=None):
    if not isinstance(value, dict):
        if strict:
            raise ValueError('Musik muss ein Objekt sein')
        value = {}
    result = validate_fields(value, MUSIC_SPEC, strict, defaults, 'Musik: ')
    result['dates'] = _validate_list(value.get('dates', []), _strict_fields(DATE_SONG_SPEC),
                                     strict, 'Datum', 400)
    if strict and len({entry['date'] for entry in result['dates']}) != len(result['dates']):
        raise ValueError('Jedes Datum darf nur einmal vorkommen')
    result['rotation'] = _validate_list(value.get('rotation', []), _strict_fields(ROTATION_SPEC),
                                        strict, 'Rotation', 400)
    return result


def validate_keys(value, strict=True):
    if not isinstance(value, dict):
        if strict:
            raise ValueError('Tastenbelegung muss ein Objekt sein')
        value = {}
    result = {}
    for key in KEYPAD_KEYS:
        try:
            result[key] = validate_action(value.get(key, {'type': 'none'}), True, f'Taste {key}: ')
        except (ValueError, TypeError):
            if strict:
                raise
            result[key] = {'type': 'none'}
    return result


def validate_effects(value, strict=True):
    def entry(item, label):
        result = validate_fields(item, {'id': (ident, None), 'name': (text(40, required=True), None)},
                                 True, label=label)
        state = item.get('state')
        if not isinstance(state, dict) or not state:
            raise ValueError(f'{label}WLED-Zustand fehlt')
        if len(json.dumps(state)) > 4000:
            raise ValueError(f'{label}WLED-Zustand zu gross')
        result['state'] = copy.deepcopy(state)
        return result
    effects = _validate_list(value, entry, strict, 'Effekt', 100)
    ids = [effect['id'] for effect in effects]
    if len(ids) != len(set(ids)):
        if strict:
            raise ValueError('Effekt-IDs muessen eindeutig sein')
        effects = [effect for number, effect in enumerate(effects) if effect['id'] not in ids[:number]]
    if strict and not effects:
        raise ValueError('Mindestens ein Effekt noetig')
    return effects


def _dict_section(spec, name):
    def validate(value, strict=True, defaults=None):
        return validate_fields(value, spec, strict, defaults, f'{name}: ')
    return validate


VALIDATORS = {
    'alarms_enabled': lambda value, strict=True: boolean(value) if strict or isinstance(value, bool) else True,
    'alarms': validate_alarms,
    'wake': _dict_section(WAKE_SPEC, 'Weckprogramm'),
    'music': validate_music,
    'greetings': validate_greetings,
    'wled': _dict_section(WLED_SPEC, 'WLED'),
    'keys': validate_keys,
    'home_assistant': _dict_section(HOME_ASSISTANT_SPEC, 'Home Assistant'),
    'alexa': _dict_section(ALEXA_SPEC, 'Alexa'),
    'weather': _dict_section(WEATHER_SPEC, 'Wetter'),
    'effects': validate_effects,
}
DICT_SECTIONS = ('wake', 'music', 'wled', 'home_assistant', 'alexa', 'weather')


# ---------------------------------------------------------------------------
# Laden / Speichern
# ---------------------------------------------------------------------------

_cache = {'stamp': None, 'data': None}
_cache_lock = threading.Lock()
_write_lock = threading.Lock()


def _stamp():
    stamps = []
    for path in (config.DEFAULTS_FILE, config.SETTINGS_FILE, config.EFFECTS_FILE):
        try:
            info = os.stat(path)
            stamps.append((str(path), info.st_mtime_ns, info.st_size))
        except OSError:
            stamps.append((str(path), None))
    return tuple(stamps)


def defaults():
    data = read_json(config.DEFAULTS_FILE)
    data['effects'] = read_json(config.EFFECTS_FILE, [])
    if config._ENV_WLED_HOST and isinstance(data.get('wled'), dict):
        data['wled']['host'] = config._ENV_WLED_HOST
    return {key: value for key, value in data.items() if not key.startswith('_')}


def overrides():
    return {key: value for key, value in read_json(config.SETTINGS_FILE).items()
            if key in VALIDATORS}


def _build():
    base = defaults()
    merged = deep_merge(base, overrides())
    result = {}
    for section, validate in VALIDATORS.items():
        if section in DICT_SECTIONS:
            base_section = validate(base.get(section), strict=False)
            result[section] = validate(merged.get(section), strict=False, defaults=base_section)
        else:
            value = validate(merged.get(section), strict=False)
            if section in ('effects', 'greetings') and not value:
                value = validate(base.get(section), strict=False)
            result[section] = value
    return result


def load():
    """Alle Sektionen, validiert. Nicht veraendern - get() liefert Kopien."""
    stamp = _stamp()
    with _cache_lock:
        if _cache['stamp'] != stamp or _cache['data'] is None:
            _cache['data'], _cache['stamp'] = _build(), stamp
        return _cache['data']


def get(section):
    return copy.deepcopy(load()[section])


def save(section, value):
    if section not in VALIDATORS:
        raise ValueError(f'Unbekannter Bereich: {section}')
    validate = VALIDATORS[section]
    validated = validate(value, strict=True)
    with _write_lock:
        data = read_json(config.SETTINGS_FILE)
        data[section] = validated
        write_json(config.SETTINGS_FILE, data)
    with _cache_lock:
        _cache['stamp'] = None
    return validated


def reset(section):
    """Eigene Aenderung verwerfen: wieder der Wert aus defaults.json."""
    with _write_lock:
        data = read_json(config.SETTINGS_FILE)
        if data.pop(section, None) is not None:
            write_json(config.SETTINGS_FILE, data)
    with _cache_lock:
        _cache['stamp'] = None


def effect_by_id(effect_id):
    for effect in load()['effects']:
        if effect['id'] == effect_id:
            return copy.deepcopy(effect)
    return None


# ---------------------------------------------------------------------------
# Kompatibilitaet fuer lighting.WLEDManager
# ---------------------------------------------------------------------------

def validate_wled_settings(enabled, host, timeout):
    return validate_fields({'enabled': enabled, 'host': host, 'timeout': timeout},
                           WLED_SPEC, True, label='WLED: ')


def wled_settings():
    return get('wled')


def save_wled_settings(enabled, host, timeout):
    return save('wled', {'enabled': enabled, 'host': host, 'timeout': timeout})


# ---------------------------------------------------------------------------
# Umzug der alten Dateien aus dem Projektstamm
# ---------------------------------------------------------------------------

def migrate_legacy():
    """settings.json / mp3_mapping.json aus dem Projektstamm nach config/ uebernehmen.

    Alte settings.json: {hour, minute, enabled, wled}. Alte Zuordnungen
    (Datum -> Datei/Spruch) werden Teil von music.dates. Die alten Dateien
    werden danach in *.migrated umbenannt. Idempotent.
    """
    messages = []
    legacy = config.LEGACY_SETTINGS_FILE
    mapping_file = config.LEGACY_MAPPING_FILE
    if not legacy.exists() and not mapping_file.exists():
        return messages
    with _write_lock:
        data = read_json(config.SETTINGS_FILE)
        if legacy.exists():
            old = read_json(legacy)
            if isinstance(old.get('wled'), dict) and 'wled' not in data:
                data['wled'] = old['wled']
            if 'alarms' not in data and any(key in old for key in ('hour', 'minute', 'enabled')):
                alarm = copy.deepcopy(defaults().get('alarms', [{}])[0]) or {}
                hour, minute = old.get('hour'), old.get('minute')
                if type(hour) is int and type(minute) is int and 0 <= hour < 24 and 0 <= minute < 60:
                    alarm['time'] = f'{hour:02d}:{minute:02d}'
                if isinstance(old.get('enabled'), bool):
                    alarm['enabled'] = old['enabled']
                data['alarms'] = [alarm]
            messages.append(f'{legacy.name} nach config/settings.json uebernommen')
        if mapping_file.exists():
            music = copy.deepcopy(load()['music'])
            dates = {entry['date']: entry for entry in music['dates']}
            for key, value in read_json(mapping_file).items():
                if isinstance(value, str):
                    value = {'file': 'mp3/' + value}
                if isinstance(value, dict) and isinstance(value.get('file'), str):
                    dates[key] = {'date': key, 'file': value['file'],
                                  'message': value.get('message', music['default_message'])}
            music['dates'] = sorted(dates.values(), key=lambda entry: entry['date'])
            data['music'] = validate_music(music, strict=False)
            messages.append(f'{mapping_file.name} nach config/settings.json (Musik) uebernommen')
        write_json(config.SETTINGS_FILE, data)
        for path in (legacy, mapping_file):
            if path.exists():
                try:
                    os.replace(path, path.with_name(path.name + '.migrated'))
                except OSError:
                    pass
    with _cache_lock:
        _cache['stamp'] = None
    return messages
