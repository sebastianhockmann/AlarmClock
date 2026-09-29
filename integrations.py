"""Aktionen, die andere Geraete steuern: HTTP, Home Assistant, Alexa.

Alle Aufrufe laufen im Hintergrund-Thread; run() gibt sofort den LCD-Text
zurueck. Das Ergebnis meldet der Thread ueber report(text) - der Wecker legt
das als 'notice'-Ereignis in die Eingabe-Warteschlange, damit nur die
Hauptschleife das LCD aendert.

Alexa hat keine lokale Schnittstelle (die IP eines Echos nuetzt nichts).
Es gibt drei Wege, alle ueber die Amazon-Cloud:
- 'http' auf eine Trigger-URL (z. B. "URL Routine Trigger" / Voice Monkey),
  die in der Alexa-App eine Routine startet - empfohlen, kein Login noetig;
- 'home_assistant' mit der Integration "Alexa Media Player";
- 'alexa' ueber alexa_remote_control.sh (config/hardware.json: alexa.script),
  das Befehle wie gesprochen an ein bestimmtes Echo schickt.
"""
import json
import logging
from pathlib import Path
import subprocess
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import config
import settings

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 5
ALEXA_TIMEOUT_SECONDS = 30
REMOTE_TYPES = ('http', 'home_assistant', 'alexa')


def label(action):
    if action.get('label'):
        return action['label']
    kind = action.get('type')
    if kind == 'alexa':
        return 'Alexa: ' + (action.get('text') or 'Wetter')
    if kind == 'home_assistant':
        return action.get('entity_id', 'Home Assistant')
    if kind == 'http':
        return 'Aufruf gesendet'
    return kind or '?'


def run(action, report=None):
    """Aktion im Hintergrund starten, LCD-Text sofort zurueckgeben."""
    def worker():
        ok, message = run_sync(action)
        if not ok:
            logger.warning('%s fehlgeschlagen: %s', label(action), message)
        if config.DEBUG:
            print(f'[Aktion] {label(action)}: {message}', flush=True)
        if report is not None and not ok:
            report(message)
    threading.Thread(target=worker, daemon=True).start()
    return label(action)


def run_sync(action):
    """(erfolgreich, Meldung). Blockiert - nur im Hintergrund oder Web-Request."""
    kind = action.get('type')
    try:
        if kind == 'http':
            return http_call(action['url'], action.get('method', 'GET'), action.get('body', ''))
        if kind == 'home_assistant':
            return home_assistant(action['service'], action['entity_id'])
        if kind == 'alexa':
            return alexa(action.get('device', ''), action.get('command', 'text'),
                         action.get('text', ''))
    except KeyError as error:
        return False, f'Feld fehlt: {error}'
    return False, f'Keine externe Aktion: {kind}'


def http_call(target, method='GET', body='', headers=None):
    data = None
    headers = dict(headers or {})
    if method == 'POST':
        data = (body or '').encode('utf-8')
        headers.setdefault('Content-Type', 'application/json' if (body or '').lstrip()[:1] in '{['
                           else 'text/plain')
    request = Request(target, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return True, f'HTTP {response.status}'
    except HTTPError as error:
        return False, f'HTTP-Fehler {error.code}'
    except (URLError, OSError) as error:
        return False, f'Nicht erreichbar ({getattr(error, "reason", error)})'


def home_assistant(service, entity_id):
    ha = settings.get('home_assistant')
    if not ha['url']:
        return False, 'Home Assistant nicht eingerichtet'
    domain, _, name = service.partition('.')
    headers = {'Content-Type': 'application/json'}
    if ha['token']:
        headers['Authorization'] = f'Bearer {ha["token"]}'
    return http_call(f'{ha["url"].rstrip("/")}/api/services/{domain}/{name}', 'POST',
                     json.dumps({'entity_id': entity_id}), headers)


ALEXA_COMMANDS = {
    'text': 'textcommand:{}',   # wie gesprochen: "spiele Amazon Music", "Licht an"
    'routine': 'automation:{}',  # Routine aus der Alexa-App, per Name
    'speak': 'speak:{}',         # Text vorlesen
    'weather': 'weather',        # Wetterbericht von Alexa
}


def alexa(device, command, text):
    script = Path(config.ALEXA_SCRIPT) if config.ALEXA_SCRIPT else None
    if script is None or not script.is_file():
        return False, 'alexa_remote_control.sh fehlt'
    device = device or settings.get('alexa')['default_device']
    if not device:
        return False, 'Kein Alexa-Geraet gewaehlt'
    argument = ALEXA_COMMANDS.get(command, ALEXA_COMMANDS['text']).format(text)
    try:
        # Argumentliste ohne Shell: der Text kann keine Befehle einschleusen.
        result = subprocess.run([str(script), '-d', device, '-e', argument],
                                capture_output=True, text=True, timeout=ALEXA_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f'Alexa-Aufruf fehlgeschlagen ({error})'
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0 or 'ERROR' in output.upper():
        return False, 'Alexa: ' + (output.splitlines()[-1] if output else f'Fehler {result.returncode}')
    return True, 'Alexa ok'


def alexa_devices():
    """Geraetenamen, wie alexa_remote_control.sh -a sie liefert (fuer die Weboberflaeche)."""
    script = Path(config.ALEXA_SCRIPT) if config.ALEXA_SCRIPT else None
    if script is None or not script.is_file():
        return None
    try:
        result = subprocess.run([str(script), '-a'], capture_output=True, text=True,
                                timeout=ALEXA_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = [line.strip() for line in result.stdout.splitlines()]
    return [line for line in lines if line and not line.startswith('the following devices')]
