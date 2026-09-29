"""Wetterbericht fuers LCD ueber Open-Meteo (kostenlos, ohne API-Schluessel).

Nur Anzeige auf dem Pi. Soll der Wetterbericht gesprochen werden, eignet
sich eine Alexa-Aktion (command 'weather') besser - Alexa kennt den Ort
aus der App und spricht deutlich natuerlicher als eine Sprachsynthese
auf dem Pi.
"""
import json
import threading
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

API_URL = 'https://api.open-meteo.com/v1/forecast'
TIMEOUT_SECONDS = 8
CACHE_SECONDS = 30 * 60

# WMO-Wettercodes, kurz und ohne Umlaute (LCD).
CODES = {
    0: 'klar', 1: 'heiter', 2: 'wolkig', 3: 'bedeckt', 45: 'Nebel', 48: 'Nebel',
    51: 'Niesel', 53: 'Niesel', 55: 'Niesel', 56: 'Eisniesel', 57: 'Eisniesel',
    61: 'Regen', 63: 'Regen', 65: 'starker Regen', 66: 'Eisregen', 67: 'Eisregen',
    71: 'Schnee', 73: 'Schnee', 75: 'viel Schnee', 77: 'Schneegriesel',
    80: 'Schauer', 81: 'Schauer', 82: 'starke Schauer', 85: 'Schneeschauer',
    86: 'Schneeschauer', 95: 'Gewitter', 96: 'Gewitter', 99: 'Gewitter',
}


def fetch(latitude, longitude, opener=urlopen):
    query = urlencode({
        'latitude': latitude, 'longitude': longitude, 'timezone': 'auto', 'forecast_days': 1,
        'current': 'temperature_2m,weather_code',
        'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code',
    })
    with opener(f'{API_URL}?{query}', timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read(256 * 1024))


def summary(data):
    """z. B. 'Jetzt 12C, heute 9-19C, Regenrisiko 40%, wolkig'."""
    current, daily = data.get('current', {}), data.get('daily', {})
    def first(key):
        values = daily.get(key) or [None]
        return values[0]
    parts = []
    if current.get('temperature_2m') is not None:
        parts.append(f'Jetzt {round(current["temperature_2m"])}C')
    low, high = first('temperature_2m_min'), first('temperature_2m_max')
    if low is not None and high is not None:
        parts.append(f'heute {round(low)}-{round(high)}C')
    rain = first('precipitation_probability_max')
    if rain is not None:
        parts.append(f'Regenrisiko {rain}%')
    code = first('weather_code')
    if code is None:
        code = current.get('weather_code')
    if code in CODES:
        parts.append(CODES[code])
    if not parts:
        raise ValueError('Leere Wetterantwort')
    return ', '.join(parts)


class WeatherService:
    """Holt das Wetter im Hintergrund und merkt sich das letzte Ergebnis."""

    def __init__(self, store, fetcher=fetch):
        self.store = store
        self.fetcher = fetcher
        self.text = None
        self.updated = 0.0
        self._lock = threading.Lock()
        self._busy = False

    def configured(self):
        cfg = self.store.get('weather')
        return cfg['latitude'] is not None and cfg['longitude'] is not None

    def cached(self, max_age=CACHE_SECONDS):
        if self.text and time.monotonic() - self.updated < max_age:
            return self.text
        return None

    def request(self, done=None):
        """Abruf starten; done(text) wird im Hintergrund-Thread aufgerufen."""
        if not self.configured():
            if done:
                done('Wetter: Ort fehlt (Web)')
            return False
        with self._lock:
            if self._busy:
                return True
            self._busy = True
        threading.Thread(target=self._worker, args=(done,), daemon=True).start()
        return True

    def lookup(self):
        """Synchron abrufen: Text oder ValueError/OSError."""
        cfg = self.store.get('weather')
        return summary(self.fetcher(cfg['latitude'], cfg['longitude']))

    def _worker(self, done):
        try:
            text = self.lookup()
            self.text, self.updated = text, time.monotonic()
        except (URLError, OSError, ValueError, KeyError, TypeError) as error:
            text = 'Wetter nicht abrufbar'
            print(f'Wetterabruf fehlgeschlagen: {error}', flush=True)
        finally:
            with self._lock:
                self._busy = False
        if done:
            done(text)
