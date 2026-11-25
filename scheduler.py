"""Wann wird geweckt, mit welchem Lied, und welcher Gruss steht auf dem LCD.

Alles wird live aus settings gelesen; die Weboberflaeche kann jederzeit
aendern. Jeder Wecker loest pro Datum hoechstens einmal aus; mit state_file
ueberlebt diese Sperre einen Neustart (config/alarm_state.json).
alarm['calendar'] schraenkt die Wochentage weiter ein: 'school' = nur
Schultage in Thueringen (school_calendar).

Verpasste Minuten werden nachgeholt (bis CATCH_UP_MINUTES): startet der
Wecker kurz nach der Weckzeit neu oder hing die Hauptschleife, klingelt er
trotzdem - spaeter, aber nicht gar nicht.
"""
from datetime import date, datetime, timedelta
import random
import config
import school_calendar
import settings
from util import parse_hhmm, time_in_range

WEEKDAYS = ('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So')
# Bis Alexa ein angefordertes Lied wirklich spielt, vergehen ein paar Sekunden (Cloud).
ALEXA_START_SECONDS = 3
# So weit zurueck holt AlarmScheduler.due() verpasste Weckzeiten nach.
CATCH_UP_MINUTES = 10


class AlarmScheduler:
    """Liefert pro Tick faellige Ereignisse: ('light', wecker) und ('alarm', wecker).

    'light' kommt light_lead_minutes vor der Weckzeit (nur wenn > 0), damit
    das Licht schon vor der Musik langsam heller werden kann.
    """

    def __init__(self, store=settings, state_file=None):
        self.store = store
        # Datei fuer die Sperre "heute schon geweckt" (None = nur im Speicher, z. B. Tests).
        self.state_file = state_file
        self._fired = self._load_state()
        self._last_minute = None

    def due(self, now):
        minute = now.replace(second=0, microsecond=0)
        # Seit dem letzten Aufruf (beim Start: CATCH_UP_MINUTES zurueck) jede Minute pruefen.
        first = minute - timedelta(minutes=CATCH_UP_MINUTES)
        if self._last_minute is not None and first < self._last_minute <= minute:
            first = self._last_minute
        self._last_minute = minute
        data = self.store.load()
        if not data['alarms_enabled']:
            return []
        lead = data['wake']['light_lead_minutes'] if data['wake']['effect'] else 0
        events = []
        moment = first
        while moment <= minute:
            events += self._due_at(data, moment, lead)
            moment += timedelta(minutes=1)
        late = [alarm['label'] for kind, alarm in events
                if kind == 'alarm' and alarm['time'] != minute.strftime('%H:%M')]
        if late:
            print(f'Wecker nachgeholt: {", ".join(late)}', flush=True)
        return events

    def _due_at(self, data, minute, lead):
        events = []
        if lead:
            target = minute + timedelta(minutes=lead)
            for alarm in self._alarms(data, target.date()):
                if self._matches(alarm, target) and self._claim(alarm, 'light', target.date()):
                    events.append(('light', alarm))
        for alarm in self._alarms(data, minute.date()):
            if (self._matches(alarm, minute) and (alarm['id'], 'done', minute.date()) not in self._fired
                    and self._claim(alarm, 'alarm', minute.date())):
                events.append(('alarm', alarm))
        return events

    def _alarms(self, data, day):
        """Aktive Wecker fuer diesen Tag, ggf. plus Weihnachtswecker."""
        alarms = [alarm for alarm in data['alarms'] if alarm['enabled']]
        extra = christmas_alarm(day, self.store, data)
        return alarms + [extra] if extra else alarms

    def _matches(self, alarm, moment):
        return (moment.weekday() in alarm['days'] and moment.strftime('%H:%M') == alarm['time']
                and school_calendar.matches(alarm['calendar'], moment.date(), self.store))

    def _claim(self, alarm, kind, day):
        key = (alarm['id'], kind, day)
        if key in self._fired:
            return False
        # Alte Eintraege wegraeumen, damit die Menge nicht waechst.
        self._fired = {entry for entry in self._fired if entry[2] >= day - timedelta(days=1)}
        self._fired.add(key)
        self._save_state()
        return True

    def skip(self, alarm_id, day):
        """Wecker fuer diesen Tag erledigt (z. B. im Licht-Vorlauf gestoppt)."""
        self._fired.add((alarm_id, 'done', day))
        self._save_state()

    def _load_state(self):
        if self.state_file is None:
            return set()
        fired = set()
        for entry in settings.read_json(self.state_file).get('fired', []):
            try:
                alarm_id, kind, day = entry
                fired.add((str(alarm_id), str(kind), date.fromisoformat(day)))
            except (TypeError, ValueError):
                continue
        return fired

    def _save_state(self):
        if self.state_file is None:
            return
        entries = sorted([alarm_id, kind, day.isoformat()] for alarm_id, kind, day in self._fired)
        try:
            settings.write_json(self.state_file, {'fired': entries})
        except OSError as error:
            # Ohne Datei gilt die Sperre eben nur bis zum Neustart.
            print(f'Weckerstatus nicht speicherbar: {error}', flush=True)


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
        # Bis zu 8 Wochen voraus: die Sommerferien dauern 6 Wochen.
        for offset in range(57):
            day = now.date() + timedelta(days=offset)
            moment = datetime.combine(day, clock)
            if (moment > now and day.weekday() in alarm['days']
                    and school_calendar.matches(alarm['calendar'], day, store)):
                if best is None or moment < best[0]:
                    best = (moment, alarm)
                break
    for offset in range(57):
        day = now.date() + timedelta(days=offset)
        alarm = christmas_alarm(day, store, data)
        if alarm is None:
            continue
        moment = datetime.combine(day, parse_hhmm(alarm['time']))
        if moment > now:
            if best is None or moment < best[0]:
                best = (moment, alarm)
            break
    return best


CHRISTMAS_ALARM_ID = 'weihnachten'


def christmas_alarm(day, store=settings, data=None):
    """Weihnachtswecker fuer Tage ohne eigenen Wecker (Wochenende, Ferien, Feiertage).

    Nur mit music.christmas_playlist.daily, im Zeitraum und wenn das
    Weckprogramm ueberhaupt Musik spielt. Klingelt an dem Tag schon ein
    normaler Wecker, bringt der das Weihnachtslied mit - dann None, damit
    nicht zweimal geweckt wird.
    """
    data = data or store.load()
    playlist = data['music']['christmas_playlist']
    if (not playlist['enabled'] or not playlist['daily'] or not playlist['songs']
            or data['wake']['music'] == 'none' or christmas_season_start(playlist, day) is None):
        return None
    for alarm in data['alarms']:
        if (alarm['enabled'] and day.weekday() in alarm['days']
                and school_calendar.matches(alarm['calendar'], day, store)):
            return None
    return {'id': CHRISTMAS_ALARM_ID, 'label': 'Weihnachtslieder', 'enabled': True,
            'time': playlist['time'], 'days': list(range(7)), 'calendar': 'all'}


CALENDAR_TEXT = {'school': 'Schultage', 'free': 'freie Tage', 'before_school': 'vor Schultagen'}


def describe_days(days, calendar='all'):
    text = _describe_weekdays(days)
    return f'{text}, {CALENDAR_TEXT[calendar]}' if calendar in CALENDAR_TEXT else text


def _describe_weekdays(days):
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


def get_alexa_item(today=None, store=settings):
    """Alexa-Lied des Tages reihum aus music.alexa_songs; None bei leerer Liste.

    Ergebnis: {'alexa': Sprachbefehl, 'file': None, 'message': Spruch}.
    """
    today = today or date.today()
    music = store.load()['music']
    if not music['alexa_songs']:
        return None
    entry = music['alexa_songs'][today.toordinal() % len(music['alexa_songs'])]
    return {'alexa': entry['text'], 'file': None,
            'message': entry['message'] or music['default_message']}


def christmas_season_start(playlist, today):
    """Erster Tag des laufenden Weihnachtszeitraums oder None ausserhalb.

    Der Zeitraum darf ueber Neujahr gehen (z. B. 11-25 bis 01-06).
    """
    start, end = playlist['start_date'], playlist['end_date']
    key = today.strftime('%m-%d')
    if start <= end:
        inside = start <= key <= end
        year = today.year
    else:
        inside = key >= start or key <= end
        year = today.year if key >= start else today.year - 1
    if not inside:
        return None
    month, day = (int(part) for part in start.split('-'))
    if (month, day) == (2, 29):
        month, day = 3, 1
    return date(year, month, day)


def alexa_music_command(text, service):
    """Sprachbefehl mit Musikdienst: 'spiele X' -> 'spiele X auf Amazon Music'.

    Ohne Dienst entscheidet der Standarddienst der Alexa-App. Nennt der Befehl
    den Dienst schon selbst, bleibt er unveraendert.
    """
    text = text.strip()
    service = (service or '').strip()
    if not service or service.lower() in text.lower():
        return text
    return f'{text} auf {service}'


def get_christmas_playlist_item(today=None, store=settings):
    """Weihnachtslied des Tages (Alexa) oder None ausserhalb des Zeitraums.

    Reihum ab dem ersten Tag des Zeitraums: am Starttag das erste Lied.
    Ergebnis wie get_alexa_item plus 'max_minutes' (Liedlaenge oder Hoechstdauer),
    denn Alexa meldet das Liedende nicht.
    """
    today = today or date.today()
    music = store.load()['music']
    playlist = music['christmas_playlist']
    if not playlist['enabled'] or not playlist['songs']:
        return None
    start = christmas_season_start(playlist, today)
    if start is None:
        return None
    entry = playlist['songs'][(today - start).days % len(playlist['songs'])]
    seconds = settings.length_seconds(entry['length'])
    return {'alexa': alexa_music_command(entry['text'], playlist['service']), 'file': None,
            'message': entry['message'] or music['default_message'],
            'max_minutes': ((seconds + ALEXA_START_SECONDS) / 60 if seconds
                            else playlist['stop_after_minutes']),
            'christmas': True}


def wake_item(mode, today=None, store=settings):
    """Weckmusik fuer mode (daily|random|alexa); im Weihnachtszeitraum die Weihnachts-Playlist."""
    christmas = get_christmas_playlist_item(today, store)
    if christmas is not None:
        return christmas
    if mode == 'alexa':
        return get_alexa_item(today, store) or get_today_wake_item(today, store)
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
