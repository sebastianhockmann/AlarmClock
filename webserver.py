from datetime import datetime
from pathlib import Path
import threading
from flask import Flask, abort, jsonify, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename
import config
from audio import AudioPlayer
from lighting import WLEDManager
from scheduler import get_today_wake_item
from settings import (SETTINGS_FILE, MAPPING_FILE, read_json, write_json, alarm_enabled, alarm_time,
                      save_alarm, save_wled_settings, wled_settings)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024
UPLOAD_FOLDER = config.BASE_DIR / 'mp3'
player = AudioPlayer()
mapping_lock = threading.Lock()
settings_lock = threading.Lock()


def audio_path(filename):
    path = (UPLOAD_FOLDER / filename).resolve()
    if not path.is_relative_to(UPLOAD_FOLDER.resolve()) or path.suffix.lower() != '.mp3' or not path.is_file():
        abort(400, 'Ungueltige MP3-Datei')
    return path


def _mapping_entries():
    entries = []
    for key, value in read_json(MAPPING_FILE).items():
        if isinstance(value, str):
            value = {'file': 'mp3/' + value}
        if isinstance(value, dict) and isinstance(value.get('file'), str):
            entries.append({'date': key, 'file': value['file'],
                            'message': value.get('message', config.DEFAULT_MESSAGE)})
    return sorted(entries, key=lambda entry: entry['date'])


@app.route('/')
def index():
    files = sorted(str(path.relative_to(UPLOAD_FOLDER)) for path in UPLOAD_FOLDER.rglob('*.mp3'))
    hour, minute = alarm_time()
    wled_cfg = wled_settings()
    return render_template('index.html', mp3_files=files,
                           config={'ALARM_HOUR': hour, 'ALARM_MINUTE': minute, 'ALARM_ENABLED': alarm_enabled()},
                           mapping=_mapping_entries(),
                           wled=wled_cfg)


@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file')
    filename = secure_filename(file.filename or '') if file else ''
    if not filename or Path(filename).suffix.lower() != '.mp3':
        abort(400, 'MP3-Datei erforderlich')
    UPLOAD_FOLDER.mkdir(exist_ok=True)
    try:
        with (UPLOAD_FOLDER / filename).open('xb') as target:
            file.save(target)
    except FileExistsError:
        abort(409, 'Datei existiert bereits')
    return redirect(url_for('index'))


@app.route('/set_alarm', methods=['POST'])
def set_alarm():
    try:
        hour, minute = int(request.form['hour']), int(request.form['minute'])
        enabled = 'enabled' in request.form
        with settings_lock:
            save_alarm(hour, minute, enabled)
    except (KeyError, ValueError):
        abort(400, 'Ungueltige Weckzeit')
    return redirect(url_for('index'))


@app.route('/set_mapping', methods=['POST'])
def set_mapping():
    key = request.form.get('date', '')
    try:
        parsed = datetime.strptime(key if len(key) == 10 else '2000-' + key, '%Y-%m-%d')
        if key not in (parsed.strftime('%Y-%m-%d'), parsed.strftime('%m-%d')):
            raise ValueError()
    except ValueError:
        abort(400, 'Datum als YYYY-MM-DD oder MM-DD angeben')
    path = audio_path(request.form.get('filename', ''))
    with mapping_lock:
        mapping = read_json(MAPPING_FILE)
        mapping[key] = {'file': str(path.relative_to(config.BASE_DIR)),
                        'message': request.form.get('message', '').strip() or config.DEFAULT_MESSAGE}
        write_json(MAPPING_FILE, mapping)
    return redirect(url_for('index'))


@app.route('/delete_mapping', methods=['POST'])
def delete_mapping():
    key = request.form.get('date', '')
    with mapping_lock:
        mapping = read_json(MAPPING_FILE)
        mapping.pop(key, None)
        write_json(MAPPING_FILE, mapping)
    return redirect(url_for('index'))


@app.route('/api/wled/test', methods=['GET'])
def wled_test():
    settings = wled_settings()
    manager = WLEDManager(host=settings['host'], enabled=settings['enabled'], timeout=settings['timeout'])
    status = manager.get_status()
    if status is None:
        return jsonify({'success': False, 'host': settings['host'], 'error': manager.last_error or 'Connection failed'}), 200
    return jsonify({'success': True, 'host': settings['host']})


@app.route('/api/wled/settings', methods=['POST'])
def wled_settings_api():
    payload = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(payload, dict):
        return jsonify(success=False, error='Ungueltige Einstellungen'), 400
    enabled = payload.get('enabled', False)
    if not request.is_json:
        enabled = enabled == 'on'
    try:
        with settings_lock:
            saved = save_wled_settings(enabled, payload.get('host', config.WLED_HOST),
                                       payload.get('timeout', config.WLED_TIMEOUT_SECONDS))
    except (TypeError, ValueError) as error:
        return jsonify(success=False, error=str(error)), 400
    if not request.is_json:
        return redirect(url_for('index'))
    return jsonify({'success': True, 'wled': saved})


@app.route('/play_now', methods=['POST'])
def play_now():
    try:
        player.play(get_today_wake_item()['file'])
    except (OSError, ValueError) as error:
        abort(400, f'Wiedergabe fehlgeschlagen: {error}')
    return redirect(url_for('index'))


@app.route('/play_file/<path:filename>', methods=['POST'])
def play_file(filename):
    try:
        player.play(audio_path(filename))
    except (OSError, ValueError) as error:
        abort(400, f'Wiedergabe fehlgeschlagen: {error}')
    return redirect(url_for('index'))


@app.route('/stop', methods=['POST'])
def stop():
    player.stop()
    return redirect(url_for('index'))


if __name__ == '__main__':
    try:
        app.run(host=config.WEB_HOST, port=config.WEB_PORT, threaded=True)
    finally:
        player.stop()
