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
import queue
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import config
import network
import settings

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 5
ALEXA_TIMEOUT_SECONDS = 30
# Home Assistant antwortet bei Alexa-Befehlen erst, wenn die Amazon-Cloud fertig ist.
HA_ALEXA_TIMEOUT_SECONDS = 15
REMOTE_TYPES = ('http', 'home_assistant', 'ha_color', 'ha_alexa', 'alexa')
# Letzte per Taste gesetzte Farbe je Lampe: (Index in der Farbliste, Zeitpunkt).
# Gilt, wenn die Lampe aus ist, und bei schnellem Weiterdruecken: dann meldet
# Home Assistant oft noch die alte Farbe.
_last_color = {}
_color_lock = threading.Lock()
COLOR_REPEAT_SECONDS = 15


def label(action):
    if action.get('label'):
        return action['label']
    kind = action.get('type')
    if kind == 'alexa':
        return 'Alexa: ' + (action.get('text') or 'Wetter')
    if kind == 'ha_alexa':
        return 'Alexa: ' + action.get('text', '')
    if kind == 'home_assistant':
        return action.get('entity_id', 'Home Assistant')
    if kind == 'ha_color':
        return 'Farbe wechseln'
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
        # Beim Farbwechsel steht erst nach der Abfrage fest, welche Farbe kommt.
        if report is not None and (not ok or action.get('type') == 'ha_color'):
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
        if kind == 'ha_color':
            return home_assistant_color(action['entity_id'], action['colors'])
        if kind == 'ha_alexa':
            return home_assistant('alexa_devices.send_text_command', data={
                'device_id': action['device_id'], 'text_command': action['text']},
                timeout=HA_ALEXA_TIMEOUT_SECONDS)
        if kind == 'alexa':
            return alexa(action.get('device', ''), action.get('command', 'text'),
                         action.get('text', ''))
    except KeyError as error:
        return False, f'Feld fehlt: {error}'
    return False, f'Keine externe Aktion: {kind}'


def _open(request, timeout, wait=None):
    """urlopen mit Live-Check.

    Kam die Verbindung nicht zustande (z. B. errno 113, WLAN kurz weg), bis zu
    network.WAIT_SECONDS warten, bis das Ziel wieder erreichbar ist, dann
    erneut senden. Nach Timeouts nie - sonst koennte light.toggle doppelt schalten.
    """
    wait = network.WAIT_SECONDS if wait is None else wait
    deadline = time.monotonic() + wait
    for attempt in range(1, 4):
        try:
            return urlopen(request, timeout=timeout)
        except HTTPError:
            raise
        except (URLError, OSError) as error:
            place = network.endpoint(request.full_url)
            remaining = deadline - time.monotonic()
            if attempt == 3 or place is None or remaining <= 0 or not network.not_connected(error):
                raise
            logger.warning('%s nicht erreichbar (%s), warte auf Netzwerk', place[0],
                           getattr(error, 'reason', error))
            if config.DEBUG:
                print(f'[Netz] {place[0]} nicht erreichbar, warte bis {int(remaining)} s', flush=True)
            if not network.wait_reachable(*place, timeout=remaining):
                raise
    raise AssertionError('unreachable')


def http_call(target, method='GET', body='', headers=None, timeout=TIMEOUT_SECONDS):
    data = None
    headers = dict(headers or {})
    if method == 'POST':
        data = (body or '').encode('utf-8')
        headers.setdefault('Content-Type', 'application/json' if (body or '').lstrip()[:1] in '{['
                           else 'text/plain')
    request = Request(target, data=data, headers=headers, method=method)
    try:
        with _open(request, timeout) as response:
            return True, f'HTTP {response.status}'
    except HTTPError as error:
        return False, f'HTTP-Fehler {error.code}'
    except (URLError, OSError) as error:
        return False, f'Nicht erreichbar ({getattr(error, "reason", error)})'


def _ha_connection():
    """(Basis-URL, Header) oder None, wenn Home Assistant nicht eingerichtet ist."""
    ha = settings.get('home_assistant')
    if not ha['url']:
        return None
    headers = {'Content-Type': 'application/json'}
    if ha['token']:
        headers['Authorization'] = f'Bearer {ha["token"]}'
    return ha['url'].rstrip('/'), headers


def home_assistant(service, entity_id=None, data=None, timeout=TIMEOUT_SECONDS):
    connection = _ha_connection()
    if connection is None:
        return False, 'Home Assistant nicht eingerichtet'
    base, headers = connection
    domain, _, name = service.partition('.')
    payload = dict(data or {})
    if entity_id:
        payload['entity_id'] = entity_id
    return http_call(f'{base}/api/services/{domain}/{name}', 'POST', json.dumps(payload), headers,
                     timeout)


def _ha_fetch(path, payload=None):
    """(Antwort als JSON oder None, Fehlermeldung). GET, mit payload POST."""
    connection = _ha_connection()
    if connection is None:
        return None, 'Home Assistant nicht eingerichtet'
    base, headers = connection
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    try:
        with _open(Request(base + path, data=data, headers=headers),
                   TIMEOUT_SECONDS) as response:
            return json.load(response), ''
    except HTTPError as error:
        return None, f'HTTP-Fehler {error.code}'
    except (URLError, OSError, ValueError) as error:
        return None, f'Nicht erreichbar ({getattr(error, "reason", error)})'


def home_assistant_state(entity_id):
    """(Zustand als dict oder None, Fehlermeldung)."""
    return _ha_fetch(f'/api/states/{entity_id}')


# Alexa-Geraete der HA-Integration "Alexa Devices" als [{id, name}].
ALEXA_DEVICES_TEMPLATE = (
    "{% set ns = namespace(ids=[], out=[]) %}"
    "{% for e in integration_entities('alexa_devices') %}{% set i = device_id(e) %}"
    "{% if i and i not in ns.ids %}{% set ns.ids = ns.ids + [i] %}"
    "{% set ns.out = ns.out + [{'id': i, 'name': device_attr(i, 'name_by_user')"
    " or device_attr(i, 'name')}] %}{% endif %}{% endfor %}{{ ns.out | tojson }}")


def home_assistant_alexa_devices():
    """(Liste oder None, Fehlermeldung) - fuer die Weboberflaeche."""
    devices, problem = _ha_fetch('/api/template', {'template': ALEXA_DEVICES_TEMPLATE})
    if devices is not None and not isinstance(devices, list):
        return None, 'Unerwartete Antwort von Home Assistant'
    return devices, problem


def _current_color_index(colors, attributes):
    """Index der Listenfarbe, die dem aktuellen Lampenzustand am naechsten ist."""
    parsed = [settings.parse_color(color) for color in colors]
    if attributes.get('color_mode') == 'color_temp' and attributes.get('color_temp_kelvin'):
        current, kind = attributes['color_temp_kelvin'], 'kelvin'
        distance = lambda value: abs(value - current)
    elif attributes.get('rgb_color'):
        current, kind = attributes['rgb_color'], 'rgb'
        distance = lambda value: sum((a - b) ** 2 for a, b in zip(value, current))
    else:
        return None
    matches = [(distance(value), index) for index, (mode, value) in enumerate(parsed) if mode == kind]
    return min(matches)[1] if matches else None


def home_assistant_color(entity_id, colors):
    """Naechste Farbe aus der Liste setzen; schaltet die Lampe dabei ein.

    Ausgangspunkt ist die Farbe, die Home Assistant meldet (die Lampe merkt
    sich ihre Farbe auch ueber Aus/An); ist die Lampe aus, die zuletzt hier
    gesetzte Farbe.
    """
    with _color_lock:
        last_index, last_time = _last_color.get(entity_id, (-1, None))
        index = None
        if last_time is None or time.monotonic() - last_time > COLOR_REPEAT_SECONDS:
            state, problem = home_assistant_state(entity_id)
            if state is None:
                return False, problem
            if state.get('state') == 'on':
                index = _current_color_index(colors, state.get('attributes') or {})
        if index is None:
            index = last_index
        index = (index + 1) % len(colors)
        mode, value = settings.parse_color(colors[index])
        data = {'rgb_color': list(value)} if mode == 'rgb' else {'color_temp_kelvin': value}
        ok, message = home_assistant('light.turn_on', entity_id, data)
        if not ok:
            return False, message
        _last_color[entity_id] = (index, time.monotonic())
        return True, colors[index][:16]


class LampDimmer:
    """Helligkeit von Home-Assistant-Lampen fuer den linken Drehknopf.

    prefetch() holt die aktuelle Helligkeit im Hintergrund, set() schickt
    einen neuen Wert. Ein Thread sendet; beim schnellen Drehen zaehlt nur der
    neueste Wert je Lampe, aeltere werden verworfen. Nichts davon blockiert.
    """

    PREFETCH_DELAY = 0.5  # Taste "an/aus" soll erst wirken, dann lesen

    def __init__(self, report=None):
        self.report = report
        self.levels = {}  # entity_id -> Prozent, 0 = aus
        self._pending = {}
        self._wake = threading.Condition()
        self._thread = None

    def prefetch(self, entity_id):
        def worker():
            time.sleep(self.PREFETCH_DELAY)
            state, _ = home_assistant_state(entity_id)
            if state is None:
                return
            brightness = (state.get('attributes') or {}).get('brightness')
            on = state.get('state') == 'on' and isinstance(brightness, (int, float))
            with self._wake:
                if entity_id not in self._pending:
                    self.levels[entity_id] = round(brightness * 100 / 255) if on else 0
        threading.Thread(target=worker, daemon=True).start()

    def set(self, entity_id, percent):
        with self._wake:
            self.levels[entity_id] = percent
            self._pending[entity_id] = percent
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
            self._wake.notify()

    def _run(self):
        while True:
            with self._wake:
                while not self._pending:
                    self._wake.wait()
                entity_id, percent = self._pending.popitem()
            ok, message = home_assistant('light.turn_on', entity_id, {'brightness_pct': percent})
            if config.DEBUG:
                print(f'[Lampe] {entity_id} {percent}%: {message}', flush=True)
            if not ok and self.report is not None:
                self.report(message)


def dim_step(level, steps, size=10):
    """Naechste Helligkeitsstufe: 1, 10, 20 ... 100 %. Nie 0 (aus)."""
    base = 0 if level is None or level <= 1 else round(level / size) * size
    return max(1, min(100, base + steps * size))


class AlexaSpeaker:
    """Sprachbefehle nacheinander an das Echo aus den Einstellungen (alexa.ha_device_id).

    Ein eigener Thread arbeitet die Befehle der Reihe nach ab, damit z. B.
    "Lautstärke 2" sicher vor "spiele ..." ankommt. say() blockiert nie.
    """

    def __init__(self, report=None, send=None):
        self.report = report
        self._send = send or (lambda device_id, text: run_sync(
            {'type': 'ha_alexa', 'device_id': device_id, 'text': text}))
        self.commands = queue.Queue(maxsize=20)
        self._thread = None
        self._lock = threading.Lock()

    @staticmethod
    def device():
        return settings.get('alexa')['ha_device_id']

    def say(self, text, on_error=None):
        """Befehl einreihen. False, wenn kein Echo eingestellt oder die Warteschlange voll ist."""
        device_id = self.device()
        if not device_id:
            return False
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        try:
            self.commands.put_nowait((device_id, text, on_error))
        except queue.Full:
            return False
        return True

    def _run(self):
        while True:
            device_id, text, on_error = self.commands.get()
            ok, message = self._send(device_id, text)
            if config.DEBUG:
                print(f'[Alexa] {text}: {message}', flush=True)
            if not ok:
                logger.warning('Alexa "%s" fehlgeschlagen: %s', text, message)
                if on_error is not None:
                    on_error(message)
                elif self.report is not None:
                    self.report('Alexa: ' + message)


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
