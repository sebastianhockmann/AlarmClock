"""Effect selection and bounded, asynchronous WLED HTTP commands."""
import json
import logging
import queue
import threading
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
