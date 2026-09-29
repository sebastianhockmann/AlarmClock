"""Weboberflaeche: eine Seite (templates/index.html) plus JSON-API.

Einstellungen schreibt sie ueber settings.save() nach config/settings.json;
der Wecker liest sie live. Alles, was Ton, Licht oder LCD betrifft
(Abspielen, Tasten testen, Weck-Test), geht ueber ipc.py an den
Wecker-Prozess - die Weboberflaeche selbst spielt nichts ab.

Keine Anmeldung: nur fuers Heimnetz gedacht (siehe README).
"""
from datetime import datetime
import json
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from flask import Flask, abort, jsonify, make_response, render_template, request, send_file
from werkzeug.utils import secure_filename
import config
import integrations
import ipc
import settings
from lighting import WLEDManager
from scheduler import describe_days, get_today_wake_item, list_music, next_alarm
from weather import WeatherService

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = config.MAX_UPLOAD_MB * 1024 * 1024
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
CONTROL_EVENTS = ('play_today', 'play_random', 'play_file', 'stop_audio', 'wake_test',
                  'wake_stop', 'key', 'volume')


def error(message, status=400):
    return jsonify(success=False, error=message), status


def fail(message, status=400):
    abort(make_response(*error(message, status)))


@app.errorhandler(413)
def too_large(_):
    return error(f'Datei zu gross (max. {config.MAX_UPLOAD_MB} MB)', 413)


def public_settings():
    data = settings.load()
    result = {key: value for key, value in data.items()}
    ha = dict(data['home_assistant'])
    # Token nie an den Browser zurueckgeben, nur ob einer gesetzt ist.
    ha['token_set'] = bool(ha.pop('token'))
    result['home_assistant'] = ha
    return result


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/state')
def state():
    now = datetime.now()
    upcoming = next_alarm(now)
    today = get_today_wake_item(now.date())
    alarms = settings.get('alarms')
    for alarm in alarms:
        alarm['days_text'] = describe_days(alarm['days'])
    overridden = sorted(settings.overrides())
    return jsonify(
        settings=public_settings(),
        alarms_view=alarms,
        overridden=overridden,
        music_files=list_music(),
        keypad=[list('123A'), list('456B'), list('789C'), list('*0#D')],
        today=today,
        next_alarm=None if upcoming is None else {
            'at': upcoming[0].isoformat(timespec='minutes'),
            'label': upcoming[1]['label'],
            'in_minutes': int((upcoming[0] - now).total_seconds() // 60),
        },
        clock=ipc.status(),
        alexa_script=bool(config.ALEXA_SCRIPT and Path(config.ALEXA_SCRIPT).is_file()),
    )


@app.route('/api/settings/<section>', methods=['PUT'])
def save_section(section):
    if section not in settings.VALIDATORS:
        return error('Unbekannter Bereich', 404)
    payload = request.get_json(silent=True)
    if payload is None:
        return error('JSON erwartet')
    if section == 'home_assistant' and isinstance(payload, dict):
        # Leeres Tokenfeld = bisherigen Token behalten; loeschen nur ausdruecklich.
        payload = dict(payload)
        if payload.pop('clear_token', False):
            payload['token'] = ''
        elif not payload.get('token'):
            payload['token'] = settings.get('home_assistant')['token']
    try:
        settings.save(section, payload)
    except (TypeError, ValueError) as problem:
        return error(str(problem))
    return jsonify(success=True, value=public_settings()[section])


@app.route('/api/settings/<section>', methods=['DELETE'])
def reset_section(section):
    if section not in settings.VALIDATORS:
        return error('Unbekannter Bereich', 404)
    settings.reset(section)
    return jsonify(success=True, value=public_settings()[section])


# ---------------------------------------------------------------------------
# Musik
# ---------------------------------------------------------------------------

def music_path(value):
    try:
        relative = settings.music_file(value)
    except ValueError as problem:
        fail(str(problem))
    path = config.BASE_DIR / relative
    if not path.is_file():
        fail('Datei nicht gefunden', 404)
    return relative, path


@app.route('/api/music', methods=['POST'])
def upload_music():
    files = request.files.getlist('file')
    if not files:
        return error('MP3-Datei waehlen')
    config.MUSIC_DIR.mkdir(exist_ok=True)
    saved = []
    for file in files:
        filename = secure_filename(file.filename or '')
        if not filename or Path(filename).suffix.lower() != '.mp3':
            return error(f'Nur MP3-Dateien: {file.filename}')
        try:
            with (config.MUSIC_DIR / filename).open('xb') as target:
                file.save(target)
        except FileExistsError:
            return error(f'Datei existiert bereits: {filename}', 409)
        saved.append((config.MUSIC_DIR / filename).relative_to(config.BASE_DIR).as_posix())
    return jsonify(success=True, files=saved)


@app.route('/api/music', methods=['DELETE'])
def delete_music():
    relative, path = music_path(request.args.get('file', ''))
    music = settings.get('music')
    used = ([music['default_song']] + [entry['file'] for entry in music['dates']]
            + [entry['file'] for entry in music['rotation']])
    if relative in used:
        return error('Datei wird noch verwendet (Standardlied, Datum oder Rotation)', 409)
    path.unlink()
    return jsonify(success=True)


@app.route('/api/music/file')
def music_download():
    _, path = music_path(request.args.get('file', ''))
    return send_file(path, mimetype='audio/mpeg', conditional=True)


# ---------------------------------------------------------------------------
# Steuerung des Weckers (ueber ipc)
# ---------------------------------------------------------------------------

@app.route('/api/control', methods=['POST'])
def control():
    payload = request.get_json(silent=True) or {}
    event = payload.get('event')
    if event not in CONTROL_EVENTS:
        return error('Unbekannter Befehl')
    try:
        ipc.send(event, payload.get('value'))
    except OSError as problem:
        return error(f'{problem} - laeuft alarmclock.service?', 503)
    except ValueError as problem:
        return error(str(problem))
    return jsonify(success=True)


@app.route('/api/action/test', methods=['POST'])
def test_action():
    try:
        action = settings.validate_action(request.get_json(silent=True))
    except (TypeError, ValueError) as problem:
        return error(str(problem))
    if action['type'] in integrations.REMOTE_TYPES and request.args.get('direct'):
        # Direkt aus der Weboberflaeche, mit Rueckmeldung (dauert bis zu 30 s).
        ok, message = integrations.run_sync(action)
        return jsonify(success=ok, message=message, error=None if ok else message)
    try:
        ipc.send('action', action)
    except OSError as problem:
        return error(f'{problem} - laeuft alarmclock.service?', 503)
    return jsonify(success=True, message='Am Wecker ausgeloest')


# ---------------------------------------------------------------------------
# WLED / Wetter / Alexa
# ---------------------------------------------------------------------------

@app.route('/api/wled/test')
def wled_test():
    cfg = settings.wled_settings()
    manager = WLEDManager(host=cfg['host'], enabled=cfg['enabled'], timeout=cfg['timeout'])
    status = manager.get_status()
    if status is None:
        return jsonify(success=False, host=cfg['host'], error=manager.last_error or 'Connection failed')
    info = status.get('info', {}) if isinstance(status.get('info'), dict) else {}
    return jsonify(success=True, host=cfg['host'], version=info.get('ver'),
                   leds=(info.get('leds') or {}).get('count'))


@app.route('/api/wled/effects')
def wled_effects():
    """Effektliste des Geraets; 'audio' = 'v' (Lautstaerke) / 'f' (Frequenz) fuers Mikrofon."""
    manager = WLEDManager(**settings.wled_settings())
    names = manager.fetch('effects')
    if not isinstance(names, list):
        return error(f'WLED nicht erreichbar ({manager.last_error})', 502)
    fxdata = manager.fetch('fxdata')
    fxdata = fxdata if isinstance(fxdata, list) and len(fxdata) == len(names) else [''] * len(names)
    result = []
    for number, (name, data) in enumerate(zip(names, fxdata)):
        if name == 'RSVD' or not isinstance(name, str):
            continue
        parts = str(data).split(';')
        flags = parts[3] if len(parts) > 3 else ''
        result.append({'fx': number, 'name': name,
                       'audio': 'f' if 'f' in flags else 'v' if 'v' in flags else '',
                       'matrix': flags.startswith('2')})
    return jsonify(success=True, effects=result)


@app.route('/api/wled/preview', methods=['POST'])
def wled_preview():
    """Einen Effektzustand direkt an WLED schicken (Effekt-Editor)."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload:
        return error('WLED-Zustand erwartet')
    manager = WLEDManager(**settings.wled_settings())
    if manager._request(payload) is None:
        return error(f'WLED nicht erreichbar ({manager.last_error})', 502)
    return jsonify(success=True)


@app.route('/api/weather/test')
def weather_test():
    try:
        return jsonify(success=True, text=WeatherService(settings).lookup())
    except (URLError, OSError, ValueError, KeyError, TypeError) as problem:
        return error(f'Wetter nicht abrufbar: {problem}', 502)


@app.route('/api/weather/search')
def weather_search():
    name = request.args.get('q', '').strip()
    if len(name) < 2:
        return error('Mindestens 2 Zeichen')
    query = urlencode({'name': name, 'count': 6, 'language': 'de', 'format': 'json'})
    try:
        with urlopen(f'{GEOCODING_URL}?{query}', timeout=8) as response:
            data = json.loads(response.read(256 * 1024))
    except (URLError, OSError, ValueError) as problem:
        return error(f'Ortssuche fehlgeschlagen: {problem}', 502)
    places = [{'name': ', '.join(filter(None, [place.get('name'), place.get('admin1'),
                                               place.get('country_code')])),
               'latitude': place.get('latitude'), 'longitude': place.get('longitude')}
              for place in data.get('results') or []]
    return jsonify(success=True, places=places)


@app.route('/api/alexa/devices')
def alexa_devices():
    devices = integrations.alexa_devices()
    if devices is None:
        return error('alexa_remote_control.sh nicht installiert oder nicht angemeldet', 404)
    return jsonify(success=True, devices=devices)


if __name__ == '__main__':
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, threaded=True)
