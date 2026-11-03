"""Lichtprogramme: Morgenlicht, Abendlicht ... nach Uhrzeit und Schulkalender.

Ein Programm leuchtet von start bis end (ueber Mitternacht moeglich, dann
zaehlt der Kalender des Starttags). Die Helligkeit laeuft in ramp_minutes
von brightness_start nach brightness_end - aufwaerts zum Wachwerden,
abwaerts zum Einschlafen - und wird aus der Uhrzeit berechnet. Startet der
Wecker mitten im Zeitfenster neu, geht es deshalb mit der passenden
Helligkeit weiter. Um end blendet das Licht aus.

Dreht jemand am Licht (linker Knopf, Effekt-/Lichttaste), haelt das Programm
still; ausgeschaltet wird um end trotzdem. Solange ein Weckvorgang selbst
Licht macht (Weckprogramm mit Lichteffekt), pausiert das Programm.
"""
import copy
from datetime import datetime, timedelta
import school_calendar
import settings
from util import parse_hhmm
from wake import LIGHT_OFF_TRANSITION, LIGHT_STEP_SECONDS, percent_to_bri, ramp


def window(program, day):
    """(Beginn, Ende) als datetime fuer das Programm, das an day startet."""
    start = datetime.combine(day, parse_hhmm(program['start']))
    end = datetime.combine(day, parse_hhmm(program['end']))
    if end <= start:
        end += timedelta(days=1)
    return start, end


def applies(program, day, store=settings):
    return (program['enabled'] and day.weekday() in program['days']
            and school_calendar.matches(program['calendar'], day, store))


def active(now, store=settings):
    """(Programm, Beginn, Ende) des Programms, das jetzt laeuft, oder None.

    Ueberschneiden sich zwei, gilt das erste in der Liste.
    """
    for program in store.get('programs'):
        # Gestern gestartet zaehlt mit (Fenster ueber Mitternacht).
        for day in (now.date(), now.date() - timedelta(days=1)):
            start, end = window(program, day)
            if start <= now < end and applies(program, day, store):
                return program, start, end
    return None


def upcoming(now, store=settings, days=14):
    """Naechste Starts aller Programme: [(Beginn, Ende, Programm)], sortiert."""
    result = []
    for program in store.get('programs'):
        for offset in range(days):
            day = now.date() + timedelta(days=offset)
            start, end = window(program, day)
            if end > now and applies(program, day, store):
                result.append((start, end, program))
                break
    return sorted(result, key=lambda entry: entry[0])


class ProgramRunner:
    """Fuehrt das gerade aktive Programm aus. tick() aus der Hauptschleife.

    tick() liefert 'start' / 'end' beim Wechsel (fuer LCD und Effekt-Browser),
    sonst None.
    """

    def __init__(self, send_light, store=settings):
        self.send_light = send_light
        self.store = store
        self.current = None  # {'program', 'start', 'end', 'state'}
        self.manual = False
        self._last_send = None
        self._last_bri = None
        self._found = None
        self._checked = None

    @property
    def label(self):
        return self.current['program']['label'] if self.current else None

    def override(self):
        """Jemand hat selbst am Licht gedreht: bis zum Programmende nichts mehr senden."""
        if self.current is not None:
            self.manual = True

    def tick(self, now, monotonic, paused=False):
        # Kalender und Einstellungen reichen einmal pro Sekunde (Hauptschleife: 20 ms).
        if self._checked is None or not 0 <= monotonic - self._checked < 1:
            self._found, self._checked = active(now, self.store), monotonic
        found = self._found
        key = None if found is None else (found[0]['id'], found[1])
        current = self.current
        if current is not None and key != (current['program']['id'], current['start']):
            self.current = None
            self.send_light({'on': False, 'tt': LIGHT_OFF_TRANSITION})
            if found is None:
                return 'end'
        if found is None:
            return None
        if self.current is None:
            program, start, end = found
            effect = self.store.effect_by_id(program['effect'])
            if effect is None:
                print(f'Lichtprogramm "{program["label"]}": Effekt "{program["effect"]}" fehlt',
                      flush=True)
                effect = {'state': {'on': True}}
            self.current = {'program': program, 'start': start, 'end': end,
                            'state': effect['state']}
            self.manual = False
            self._last_send = self._last_bri = None
            if not paused:
                self._update(now, monotonic, force=True)
            return 'start'
        # Helligkeit aus der Weboberflaeche gilt sofort.
        self.current['program'] = found[0]
        if paused:
            # Danach den vollen Zustand neu senden (das Weckprogramm hat das Licht belegt).
            self._last_bri = None
        elif not self.manual:
            self._update(now, monotonic, force=self._last_bri is None)
        return None

    def brightness(self, now):
        program = self.current['program']
        elapsed = (now - self.current['start']).total_seconds()
        return percent_to_bri(ramp(program['brightness_start'], program['brightness_end'],
                                   elapsed, program['ramp_minutes'] * 60))

    def _update(self, now, monotonic, force=False):
        if not force and self._last_send is not None and monotonic - self._last_send < LIGHT_STEP_SECONDS:
            return
        bri = self.brightness(now)
        if not force and bri == self._last_bri:
            return
        state = copy.deepcopy(self.current['state'])
        # Erster Befehl (oder nach einer Pause) mit vollem Effekt, danach weich nachziehen.
        state.update(on=True, bri=bri, tt=int(LIGHT_STEP_SECONDS * 10) if self._last_bri else 10)
        self.send_light(state)
        self._last_send, self._last_bri = monotonic, bri
