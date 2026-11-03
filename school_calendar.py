"""Schultage in Thueringen: Wochenende, Feiertage, Schulferien, eigene freie Tage.

Feiertage werden berechnet (kein Netz noetig). Die Schulferien kommen von
openholidaysapi.org: config/school_holidays.json (versioniert, Startbestand,
tools/update_school_holidays.py) plus config/school_holidays_cache.json, die
HolidayUpdater im Wecker-Prozess taeglich neu holt. Fehlen Daten fuer einen
Tag, gilt er als Schultag - lieber einmal zu viel geweckt als verschlafen.

Kalender-Regeln fuer Wecker und Lichtprogramme (settings.CALENDAR_RULES):
'all' = nur die Wochentage zaehlen, 'school' = nur Schultage,
'free' = nur freie Tage, 'before_school' = Abend vor einem Schultag.
"""
from datetime import date, timedelta
import json
import logging
import os
import threading
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
import config
import settings

logger = logging.getLogger(__name__)
REGION = 'DE-TH'
SEED_FILE = config.CONFIG_DIR / 'school_holidays.json'
CACHE_FILE = config.CONFIG_DIR / 'school_holidays_cache.json'
API_URL = 'https://openholidaysapi.org/SchoolHolidays'
REFRESH_SECONDS = 24 * 3600
RETRY_SECONDS = 3600


def easter(year):
    """Ostersonntag (gregorianisch, Algorithmus nach Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def public_holidays(year):
    """{datum: name} der gesetzlichen Feiertage in Thueringen.

    Fronleichnam gilt nur in einzelnen Eichsfeld-Gemeinden und fehlt hier
    (bei Bedarf als eigener freier Tag eintragen).
    """
    sunday = easter(year)
    return {
        date(year, 1, 1): 'Neujahr',
        sunday - timedelta(days=2): 'Karfreitag',
        sunday + timedelta(days=1): 'Ostermontag',
        date(year, 5, 1): 'Tag der Arbeit',
        sunday + timedelta(days=39): 'Himmelfahrt',
        sunday + timedelta(days=50): 'Pfingstmontag',
        date(year, 9, 20): 'Weltkindertag',
        date(year, 10, 3): 'Tag der Einheit',
        date(year, 10, 31): 'Reformationstag',
        date(year, 12, 25): '1. Weihnachtstag',
        date(year, 12, 26): '2. Weihnachtstag',
    }


# ---------------------------------------------------------------------------
# Schulferien
# ---------------------------------------------------------------------------

def parse_periods(data):
    """[{start, end, name}] aus Datei oder API-Antwort; ungueltige Eintraege fallen weg."""
    periods = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        name = entry.get('name', 'Ferien')
        if isinstance(name, list):  # API: [{"language": "DE", "text": ...}]
            name = next((item.get('text') for item in name if isinstance(item, dict)), 'Ferien')
        try:
            start = date.fromisoformat(entry.get('start') or entry.get('startDate'))
            end = date.fromisoformat(entry.get('end') or entry.get('endDate'))
        except (TypeError, ValueError):
            continue
        if start <= end:
            periods.append({'start': start, 'end': end, 'name': str(name or 'Ferien')})
    return periods


_cache = {'stamp': None, 'periods': []}
_cache_lock = threading.Lock()


def _stamp():
    result = []
    for path in (SEED_FILE, CACHE_FILE):
        try:
            info = os.stat(path)
            result.append((info.st_mtime_ns, info.st_size))
        except OSError:
            result.append(None)
    return tuple(result)


def school_holidays():
    """Alle bekannten Ferienzeitraeume, sortiert. Live aus den Dateien (mtime-Cache)."""
    stamp = _stamp()
    with _cache_lock:
        if _cache['stamp'] != stamp:
            merged = {}
            for path in (SEED_FILE, CACHE_FILE):
                for period in parse_periods(settings.read_json(path, [])):
                    merged[(period['start'], period['end'])] = period
            _cache['periods'] = sorted(merged.values(), key=lambda period: period['start'])
            _cache['stamp'] = stamp
        return _cache['periods']


def known_until():
    """Letzter Tag, fuer den Ferientermine vorliegen (oder None)."""
    periods = school_holidays()
    return periods[-1]['end'] if periods else None


def fetch(first_year, last_year, timeout=15):
    """Ferien fuer die Jahre von der API holen. Wirft URLError/OSError/ValueError."""
    query = urlencode({'countryIsoCode': 'DE', 'subdivisionCode': REGION, 'languageIsoCode': 'DE',
                       'validFrom': f'{first_year}-01-01', 'validTo': f'{last_year}-12-31'})
    with urlopen(f'{API_URL}?{query}', timeout=timeout) as response:
        periods = parse_periods(json.loads(response.read(512 * 1024)))
    if not periods:
        raise ValueError('keine Ferientermine in der Antwort')
    return periods


def write_periods(path, periods):
    settings.write_json(path, [{'start': period['start'].isoformat(),
                                'end': period['end'].isoformat(), 'name': period['name']}
                               for period in periods])


def refresh(today=None):
    """Ferien fuer dieses und naechstes Jahr in den Cache holen. (ok, Meldung)."""
    today = today or date.today()
    try:
        periods = fetch(today.year, today.year + 1)
    except (URLError, OSError, ValueError) as error:
        return False, f'Ferientermine nicht abrufbar ({getattr(error, "reason", error)})'
    write_periods(CACHE_FILE, periods)
    return True, f'{len(periods)} Ferientermine bis {periods[-1]["end"]:%d.%m.%Y}'


class HolidayUpdater:
    """Hintergrund-Thread: Ferien taeglich aktualisieren, bei Fehlern stuendlich erneut."""

    def __init__(self, report=None):
        self.report = report or (lambda message: None)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            ok, message = refresh()
            if not ok:
                logger.warning(message)
            if config.DEBUG or not ok:
                self.report(f'[Kalender] {message}')
            self._stop.wait(REFRESH_SECONDS if ok else RETRY_SECONDS)

    def close(self):
        self._stop.set()


# ---------------------------------------------------------------------------
# Abfragen
# ---------------------------------------------------------------------------

def free_reason(day, store=settings):
    """Warum der Tag schulfrei ist ('Wochenende', Feiertag, Ferienname) oder None."""
    if day.isoformat() in store.get('calendar')['free_days']:
        return 'Freier Tag'
    holiday = public_holidays(day.year).get(day)
    if holiday:
        return holiday
    for period in school_holidays():
        if period['start'] <= day <= period['end']:
            return period['name']
    if day.weekday() >= 5:
        return 'Wochenende'
    return None


def is_school_day(day, store=settings):
    return free_reason(day, store) is None


def matches(rule, day, store=settings):
    """Gilt die Kalender-Regel an diesem Tag?"""
    if rule == 'school':
        return is_school_day(day, store)
    if rule == 'free':
        return not is_school_day(day, store)
    if rule == 'before_school':
        return is_school_day(day + timedelta(days=1), store)
    return True


def describe(day, store=settings):
    reason = free_reason(day, store)
    return {'date': day.isoformat(), 'school': reason is None, 'reason': reason or 'Schultag'}


def upcoming_holidays(today, count=4, store=settings):
    """Naechste Ferien und Feiertage (ohne Wochenenden) fuer die Weboberflaeche."""
    periods = [period for period in school_holidays() if period['end'] >= today]
    entries = [{'start': period['start'].isoformat(), 'end': period['end'].isoformat(),
                'name': period['name']} for period in periods]
    single = {day: name for year in (today.year, today.year + 1)
              for day, name in public_holidays(year).items()}
    single.update({date.fromisoformat(day): 'Freier Tag'
                   for day in store.get('calendar')['free_days']})
    # Einzelne Tage mitten in den Ferien nicht extra auffuehren.
    entries += [{'start': day.isoformat(), 'end': day.isoformat(), 'name': name}
                for day, name in single.items()
                if day >= today and not any(p['start'] <= day <= p['end'] for p in periods)]
    return sorted(entries, key=lambda entry: entry['start'])[:count]
