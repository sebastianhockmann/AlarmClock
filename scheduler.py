"""Wann wird geweckt, mit welchem Lied, und welcher Gruss steht auf dem LCD.

Alles wird live aus settings gelesen; die Weboberflaeche kann jederzeit
aendern. Jeder Wecker loest pro Datum hoechstens einmal aus (Sperre im
Speicher, gilt bis zum Neustart).
"""
from datetime import date, datetime, timedelta
import random
import config
import settings
from util import parse_hhmm, time_in_range

WEEKDAYS = ('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So')


class AlarmScheduler:
    """Liefert pro Tick faellige Ereignisse: ('light', wecker) und ('alarm', wecker).

    'light' kommt light_lead_minutes vor der Weckzeit (nur wenn > 0), damit
    das Licht schon vor der Musik langsam heller werden kann.
    """

    def __init__(self, store=settings):
        self.store = store
        self._fired = set()

    def due(self, now):
        data = self.store.load()
        if not data['alarms_enabled']:
            return []
        lead = data['wake']['light_lead_minutes'] if data['wake']['effect'] else 0
        minute = now.replace(second=0, microsecond=0)
        events = []
        for alarm in data['alarms']:
            if not alarm['enabled']:
                continue
            if lead:
                target = minute + timedelta(minutes=lead)
                if self._matches(alarm, target) and self._claim(alarm, 'light', target.date()):
                    events.append(('light', alarm))
            if (self._matches(alarm, minute) and (alarm['id'], 'done', minute.date()) not in self._fired
                    and self._claim(alarm, 'alarm', minute.date())):
                events.append(('alarm', alarm))
        return events

    @staticmethod
    def _matches(alarm, moment):
        return moment.weekday() in alarm['days'] and moment.strftime('%H:%M') == alarm['time']

    def _claim(self, alarm, kind, day):
        key = (alarm['id'], kind, day)
        if key in self._fired:
            return False
        # Alte Eintraege wegraeumen, damit die Menge nicht waechst.
        self._fired = {entry for entry in self._fired if entry[2] >= day - timedelta(days=1)}
        self._fired.add(key)
        return True

    def skip(self, alarm_id, day):
        """Wecker fuer diesen Tag erledigt (z. B. im Licht-Vorlauf gestoppt)."""
        self._fired.add((alarm_id, 'done', day))


def next_alarm(now, store=settings):
    """(datetime, wecker) des naechsten aktiven Weckers oder None."""
    data = store.load()
    if not data['alarms_enabled']:
        return None
    best = None
    for alarm in data['alarms']:
        if not alarm['enabled'] or not alarm['days']:
            continue
        clock = parse_hhmm(alarm['time'])
        for offset in range(8):
            day = now.date() + timedelta(days=offset)
            moment = datetime.combine(day, clock)
            if moment > now and day.weekday() in alarm['days']:
                if best is None or moment < best[0]:
                    best = (moment, alarm)
                break
    return best


def describe_days(days):
    if sorted(days) == list(range(7)):
        return 'taeglich'
    if sorted(days) == list(range(5)):
        return 'Mo-Fr'
    if sorted(days) == [5, 6]:
        return 'Sa+So'
    return ','.join(WEEKDAYS[day] for day in sorted(days)) or 'nie'


# -----------------------------
# Musik
# -----------------------------

def list_music():
    """Alle MP3s unterhalb des Musikordners, als Pfad relativ zum Projekt."""
    if not config.MUSIC_DIR.is_dir():
        return []
    return sorted(path.relative_to(config.BASE_DIR).as_posix()
                  for path in config.MUSIC_DIR.rglob('*') if path.suffix.lower() == '.mp3')


def get_today_wake_item(today=None, store=settings):
    """Tageslied: exaktes Datum -> jaehrliches Datum -> Rotation -> Standardlied."""
    today = today or date.today()
    music = store.load()['music']
    by_date = {entry['date']: entry for entry in music['dates']}
    entry = by_date.get(today.isoformat()) or by_date.get(today.strftime('%m-%d'))
    if entry:
        return {'file': entry['file'], 'message': entry['message'] or music['default_message']}
    if music['rotation']:
        entry = music['rotation'][today.toordinal() % len(music['rotation'])]
        return {'file': entry['file'], 'message': entry['message'] or music['default_message']}
    return {'file': music['default_song'], 'message': music['default_message']}


def get_random_item(store=settings, rng=random):
    """Zufallssong aus dem ganzen Musikordner; Spruch = Dateiname."""
    files = list_music()
    if not files:
        return get_today_wake_item(store=store)
    chosen = rng.choice(files)
    name = chosen.rsplit('/', 1)[-1][:-4].replace('_', ' ').strip(' .')
    return {'file': chosen, 'message': f'Zufall: {name}'}


def wake_item(mode, today=None, store=settings):
    return get_random_item(store) if mode == 'random' else get_today_wake_item(today, store)


# -----------------------------
# Greeting (Tag, Nacht etc.)
# -----------------------------

def get_greeting(now, store=settings):
    """{'text', 'backlight'} passend zur Uhrzeit laut Einstellungen."""
    moment = now.time().replace(second=0, microsecond=0)
    for greeting in store.load()['greetings']:
        if time_in_range(moment, parse_hhmm(greeting['start']), parse_hhmm(greeting['end'])):
            return greeting
    return {'text': '', 'backlight': True}
