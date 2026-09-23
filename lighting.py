"""Effect selection and bounded, asynchronous WLED HTTP commands."""
import json
import logging
import queue
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import config
from settings import wled_settings, validate_wled_settings

logger = logging.getLogger(__name__)


def load_effects(path):
    with open(path, encoding='utf-8') as source:
        effects = json.load(source)
    if not isinstance(effects, list) or not effects:
        raise ValueError('Effect library must be a nonempty list')
    ids, keys = set(), set()
    for effect in effects:
        if not isinstance(effect, dict):
            raise ValueError('Each effect must be an object')
        for field in ('id', 'name'):
            if not isinstance(effect.get(field), str) or not effect[field]:
                raise ValueError(f'Effect needs {field}')
        if not isinstance(effect.get('state'), dict) or not effect['state']:
            raise ValueError('Effect needs a WLED state')
        if effect['id'] in ids:
            raise ValueError('Duplicate effect ID')
        ids.add(effect['id'])
        if 'key' in effect:
            if not isinstance(effect['key'], str) or effect['key'] in keys:
                raise ValueError('Invalid or duplicate effect key')
            keys.add(effect['key'])
    return effects


class EffectSelector:
    def __init__(self, effects, send):
        self.effects = effects
        self.send = send
        self.index = 0

    @property
    def selected(self):
        return self.effects[self.index]

    def rotate(self, steps):
        self.index = (self.index + steps) % len(self.effects)
        return f"{self.index + 1}/{len(self.effects)} {self.selected['name']}"

    def confirm(self):
        self.send(self.selected['state'])
        return self.selected['name']

    def select(self, field, value):
        for index, effect in enumerate(self.effects):
            if effect.get(field) == value:
                self.index = index
                return self.confirm()
        raise ValueError(f'Unknown effect {field}: {value}')


def browser_entries(effects):
    """(fx, Name) aus der kuratierten Bibliothek: Ersatzliste ohne Geraetekontakt."""
    entries = []
    for effect in effects:
        segments = effect['state'].get('seg')
        if isinstance(segments, list) and segments and isinstance(segments[0], dict):
            fx = segments[0].get('fx')
            known = [value for value, _ in entries]
            if isinstance(fx, int) and not isinstance(fx, bool) and fx not in known:
                entries.append((fx, effect['name']))
    return entries or [(0, 'Solid')]


class EffectBrowser:
    """Linker Drehknopf: die komplette WLED-Effektliste mit Live-Vorschau.

    Jeder Drehschritt schaltet den Streifen sofort um; es gibt kein
    Bestaetigen. Das vertraegt sich mit der Queue in WLEDManager.send(),
    die alte Befehle verwirft, statt schnelles Drehen aufzustauen.
    Die Namen holt refresh() im Hintergrund vom Geraet (/json -> "effects");
    bis dahin dient die kuratierte Bibliothek als Ersatzliste.
    """

    def __init__(self, send, status=None, fallback=(), fast_seconds=None, fast_steps=None):
        self.send = send
        self.status = status
        self.entries = list(fallback) or [(0, 'Solid')]
        self.live = False
        self.index = 0
        self.power = True
        self.last_rotate = 0.0
        self.fast_seconds = config.EFFECT_FAST_SECONDS if fast_seconds is None else fast_seconds
        self.fast_steps = config.EFFECT_FAST_STEPS if fast_steps is None else fast_steps
        self._lock = threading.Lock()
        self._thread = None

    def refresh(self):
        """Effektliste und Zustand einmal beim Geraet abfragen, ohne zu blockieren."""
        if self.status is None:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._load, daemon=True)
            self._thread.start()

    def _load(self):
        status = self.status()
        if not isinstance(status, dict):
            return
        effects = status.get('effects')
        if not isinstance(effects, list) or not effects:
            return
        state = status.get('state')
        state = state if isinstance(state, dict) else {}
        segments = state.get('seg')
        current = (segments[0].get('fx') if isinstance(segments, list) and segments
                   and isinstance(segments[0], dict) else None)
        # Erst die Liste tauschen, dann den Index: ein gleichzeitiges rotate()
        # arbeitet so nie auf einem Index ausserhalb der Liste.
        self.entries = [(fx, str(name)) for fx, name in enumerate(effects)]
        self.live = True
        if isinstance(current, int) and not isinstance(current, bool) and 0 <= current < len(effects):
            self.index = current
        if isinstance(state.get('on'), bool):
            self.power = state['on']

    def rotate(self, steps, now=None):
        """Einen Schritt weiter und sofort senden; schnelles Drehen springt weiter."""
        now = time.monotonic() if now is None else now
        if not self.live:
            self.refresh()
        if 0 < now - self.last_rotate < self.fast_seconds:
            steps *= self.fast_steps
        self.last_rotate = now
        entries = self.entries
        self.index = (self.index + steps) % len(entries)
        fx, name = entries[self.index]
        self.power = True
        # Ohne "bri": die am Geraet eingestellte Helligkeit bleibt erhalten.
        self.send({'on': True, 'seg': [{'id': 0, 'fx': fx}]})
        return f'{self.index + 1}/{len(entries)} {name}'

    def toggle_power(self):
        self.power = not self.power
        self.send({'on': self.power})
        return 'Licht an' if self.power else 'Licht aus'

    def set_power(self, on):
        self.power = bool(on)
        self.send({'on': self.power})
        return 'Licht an' if self.power else 'Licht aus'


class WLEDManager:
    """One HTTP implementation; writes are queued so clock inputs never wait.

    With no explicit host, reload shared settings before every request.
    Explicit instances (e.g. tests) keep their supplied configuration.
    Status queries are synchronous and belong in the web request thread.
    """
    def __init__(self, host=None, enabled=None, timeout=None, report=None):
        self._shared = host is None and enabled is None and timeout is None
        values = wled_settings() if self._shared else validate_wled_settings(
            config.WLED_ENABLED if enabled is None else enabled,
            config.WLED_HOST if host is None else host,
            config.WLED_TIMEOUT_SECONDS if timeout is None else timeout)
        self.enabled, self.host, self.timeout = values['enabled'], values['host'], values['timeout']
        self.report = report
        self.last_error = None
        self.commands = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self._thread = None
        self._queue_lock = threading.Lock()
        self.log('WLED configured: %s', self.host)

    @property
    def base_url(self):
        return f'http://{self.host}'

    def log(self, message, *args):
        logger.info(message, *args)
        if self.report:
            self.report(message % args)

    def refresh_from_settings(self):
        if self._shared:
            values = wled_settings()
            if (self.enabled, self.host, self.timeout) != (values['enabled'], values['host'], values['timeout']):
                self.enabled, self.host, self.timeout = values['enabled'], values['host'], values['timeout']
                self.log('WLED configured: %s', self.host)

    def _request(self, payload=None):
        self.refresh_from_settings()
        if not self.enabled:
            self.last_error = 'WLED disabled'
            return None
        if config.DEBUG and payload is not None:
            print(f'[WLED] Sende an {self.host}: {payload}', flush=True)
        host = self.host
        try:
            request = Request(self.base_url + ('/json' if payload is None else '/json/state'),
                              data=None if payload is None else json.dumps(payload).encode('utf-8'),
                              headers={'Content-Type': 'application/json'},
                              method='GET' if payload is None else 'POST')
            with urlopen(request, timeout=self.timeout) as response:
                # /json includes the effect list and can exceed 4 KiB.
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise ValueError('Response too large')
                result = json.loads(body)
                if not isinstance(result, dict) or (payload is None and not isinstance(result.get('state'), dict)):
                    raise ValueError('Invalid WLED response')
        except HTTPError as error:
            self.last_error = f'HTTP error {error.code}'
        except (TimeoutError, OSError, URLError) as error:
            reason = getattr(error, 'reason', error)
            self.last_error = 'Connection timeout' if isinstance(reason, TimeoutError) else 'Connection failed'
        except (ValueError, UnicodeError):
            self.last_error = 'Invalid WLED response'
        else:
            self.last_error = None
            self.log('WLED connected: %s', host)
            return result
        self.log('WLED unavailable: %s (%s)', host, self.last_error)
        return None

    def get_status(self):
        return self._request()

    def is_available(self):
        return self.get_status() is not None

    def send(self, state):
        if not isinstance(state, dict):
            raise ValueError('WLED state must be an object')
        # Copy nested data before handing ownership to the worker.
        state = json.loads(json.dumps(state))
        with self._queue_lock:
            if self.stopping.is_set():
                return
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
            try:
                self.commands.get_nowait()
            except queue.Empty:
                pass
            self.commands.put_nowait(state)

    def set_power(self, on):
        self.send({'on': bool(on)})

    def set_brightness(self, value):
        value = int(value)
        if not 0 <= value <= 255:
            raise ValueError('Brightness must be between 0 and 255')
        self.send({'bri': value})

    def activate_preset(self, preset_id):
        preset_id = int(preset_id)
        if not 1 <= preset_id <= 250:
            raise ValueError('Preset must be between 1 and 250')
        self.send({'ps': preset_id})

    def _run(self):
        while not self.stopping.is_set():
            try:
                state = self.commands.get(timeout=0.1)
            except queue.Empty:
                continue
            self._request(state)

    def close(self):
        self.stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=0.2)


class WLEDClient(WLEDManager):
    """Compatibility name for existing callers; all HTTP lives in WLEDManager."""
    def __init__(self, url, timeout=None, report=None):
        super().__init__(host=url or config.WLED_HOST, enabled=bool(url),
                         timeout=timeout, report=report)
