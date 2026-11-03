"""Hardware-independent alarm lifetime and input handling.

Laeuft ausschliesslich auf dem Haupt-Thread: Eingabegeraete, Weboberflaeche
(ipc.py) und Hintergrund-Threads (Wetter, Alexa, ...) legen Ereignisse in
die Warteschlange, alarm_clock.main() reicht sie an handle() weiter.
"""
from datetime import timedelta
import config
import integrations
import settings
from programs import ProgramRunner
from scheduler import (AlarmScheduler, get_random_item, get_today_wake_item, list_music,
                       wake_item)
from wake import WakeSession, alexa_volume_command

NOTICE_SECONDS = 5
TEST_ALARM = {'id': 'test', 'label': 'Weck-Test'}
# Liederliste: so lange bleibt der rechte Drehknopf nach dem letzten Dreh beim Blaettern.
BROWSE_SECONDS = 10
# Alexa-Lautstaerke: erst senden, wenn der Knopf so lange still steht (Cloud-Befehl).
ALEXA_VOLUME_DELAY = 0.8
# Startwert, solange der Wecker die Alexa-Lautstaerke noch nicht selbst gesetzt hat.
ALEXA_DEFAULT_LEVEL = 4
# Nach einer Lampen-Taste (Home Assistant) dimmt der linke Knopf so lange die Lampe.
LAMP_SECONDS = 10
# Solange die aktuelle Helligkeit noch nicht gelesen ist.
LAMP_DEFAULT_PERCENT = 50


class ClockController:
    def __init__(self, player, send_light, browser=None, backlight=None, emit=None,
                 store=settings, alarm_scheduler=None, weather=None, integration=None,
                 alexa=None, dimmer=None, programs=None):
        self.player = player
        self.send_light = send_light
        # Linker Drehknopf: alle Effekte des WLED-Geraets (lighting.EffectBrowser).
        self.browser = browser
        self.backlight = backlight or (lambda **kwargs: None)
        # Rueckkanal fuer Hintergrund-Threads: emit('notice', text).
        self.emit = emit or (lambda event, value=None: None)
        self.store = store
        self.scheduler = alarm_scheduler or AlarmScheduler(store)
        self.weather = weather
        self.integration = integration or integrations.run
        # Echo aus alexa.ha_device_id: Wecken mit Alexa, Liederliste, Alexa-Lautstaerke.
        self.alexa = alexa or integrations.AlexaSpeaker(
            report=lambda message: self.emit('notice', message))
        self.alexa_level = None
        self._alexa_volume_due = None
        self.browse = None
        # Lampe fuer den linken Knopf: {'entity_id', 'until'}.
        self.lamp = None
        self.dimmer = dimmer or integrations.LampDimmer(
            report=lambda message: self.emit('notice', message))
        # Morgen-/Abendlicht nach Uhrzeit und Schulkalender (programs.py).
        self.programs = programs or ProgramRunner(send_light, store)
        self.session = None
        self.active_item = None
        self.notice = ''
        self.notice_end = 0
        self.now = None
        self.monotonic = 0.0

    # ------------------------------------------------------------------
    # Weckvorgang
    # ------------------------------------------------------------------

    def tick(self, now, monotonic):
        self.now, self.monotonic = now, monotonic
        for kind, alarm in self.scheduler.due(now):
            if kind == 'light':
                self._begin_light(alarm, now, monotonic)
            else:
                self._begin_alarm(alarm, now, monotonic)
        if self.session is not None and not self.session.tick(monotonic):
            self._debug('Weckvorgang zu Ende')
            self._end_session()
        self._tick_programs(now, monotonic)
        session = self.session
        if session is not None and session.uses_alexa and not session.volume_manual:
            self.alexa_level = session.alexa_level
        if self._alexa_volume_due is not None and monotonic >= self._alexa_volume_due:
            self._alexa_volume_due = None
            self.alexa.say(alexa_volume_command(self.alexa_level))
        if self.browse is not None and monotonic >= self.browse['until']:
            self.browse = None
        if self.lamp is not None and monotonic >= self.lamp['until']:
            self.lamp = None

    def _tick_programs(self, now, monotonic):
        # Macht das Weckprogramm selbst Licht, hat es Vorrang.
        paused = self.session is not None and self.session.light_start is not None
        label = self.programs.label
        change = self.programs.tick(now, monotonic, paused)
        if change == 'start':
            self._debug(f'Lichtprogramm {self.programs.label} beginnt')
            if self.browser is not None:
                self.browser.power = True
            if not self.alarm_active:
                self._notify(self.programs.label)
        elif change == 'end':
            self._debug(f'Lichtprogramm {label} zu Ende')
            if self.browser is not None:
                self.browser.power = False

    def _new_session(self, alarm, now):
        program = self.store.get('wake')
        effect = self.store.effect_by_id(program['effect']) if program['effect'] else None
        if program['effect'] and effect is None:
            print(f'Weck-Lichteffekt "{program["effect"]}" fehlt in der Effektliste', flush=True)
        return WakeSession(program, self.player, self.send_light, effect, alarm, now.date(),
                           alexa=self._wake_alexa)

    def _wake_alexa(self, text):
        # Scheitert ein Befehl beim Wecken, springt 'alexa_error' auf MP3 um.
        return self.alexa.say(text, on_error=lambda message: self.emit('alexa_error', message))

    def _begin_light(self, alarm, now, monotonic):
        if self.session is None:
            self.session = self._new_session(alarm, now)
            self._debug(f'Licht-Vorlauf fuer {alarm["label"]} {alarm.get("time", "")}')
        self.session.start_light(monotonic)

    def _begin_alarm(self, alarm, now, monotonic):
        if self.session is None or self.session.phase != 'light':
            if self.session is not None:
                self.session.finish()
            self.session = self._new_session(alarm, now)
        program = self.session.program
        if program['music'] == 'none':
            item = {'file': None, 'message': self.store.get('music')['default_message']}
        else:
            item = wake_item(program['music'], now.date(), self.store)
            if item.get('alexa') and not self.alexa.device():
                print('Wecken mit Alexa: kein Echo eingestellt, spiele MP3', flush=True)
                item = get_today_wake_item(now.date(), self.store)
        self.active_item = item
        self._debug(f'Alarm ausgeloest ({alarm["label"]}): {item["file"]}')
        error = self.session.start_music(item, monotonic)
        if error:
            print(f'Audio Fehler: {error}', flush=True)
            self._notify('Audio Fehler!', 10)
        if program['show_weather'] and self.weather is not None:
            self.weather.request(lambda text: self.emit('weather_result', text))

    def _end_session(self):
        session, self.session = self.session, None
        self.active_item = None
        if session is not None and session.finish() and self.browser is not None:
            self.browser.power = False

    def stop(self):
        """Wecker aus. Im Licht-Vorlauf faellt damit auch die Musik fuer heute aus."""
        session = self.session
        if session is not None and session.phase == 'light' and session.alarm:
            self.scheduler.skip(session.alarm['id'], session.day)
        self._end_session()
        self.player.stop()

    def snooze(self):
        if self.session is None or self.session.phase != 'music':
            return 'Kein Wecker aktiv'
        self.session.snooze(self.monotonic)
        minutes = self.session.program['snooze_minutes']
        if self.now is not None:
            return f'Schlummern bis {(self.now + timedelta(minutes=minutes)):%H:%M}'
        return f'Schlummern {minutes} min'

    @property
    def alarm_active(self):
        return self.session is not None and self.session.phase != 'light'

    @property
    def force_backlight(self):
        return self.alarm_active and self.session.program['backlight']

    # ------------------------------------------------------------------
    # Ereignisse
    # ------------------------------------------------------------------

    def handle(self, event, value, monotonic):
        self.monotonic = monotonic
        text = None
        if event == 'left_rotate' and self.lamp is not None:
            text = self._lamp_dim(int(value))
        elif event == 'left_rotate':
            self.programs.override()
            text = self.browser.rotate(int(value), monotonic) if self.browser else None
            self._debug(f'Effekt: {text}')
        elif event == 'left_press':
            self.programs.override()
            text = self.browser.toggle_power() if self.browser else None
            self._debug(f'Licht: {text}')
        elif event == 'key':
            text = self._key(str(value))
        elif event == 'action':
            text = self.run_action(settings.validate_action(value))
        elif event == 'right_press':
            text = self._browse_play() if self.browse is not None else self._toggle_audio()
        elif event == 'right_hold':
            text = self._reset()
        elif event == 'right_rotate':
            if self.browse is not None:
                text = self._browse_move(int(value))
            elif self.session is not None and self.session.uses_alexa:
                text = self._alexa_volume(int(value))
            else:
                text = self._set_volume(self.player.volume + int(value) * config.VOLUME_STEP)
        elif event == 'right_press_rotate':
            text = self._alexa_volume(int(value))
        elif event == 'alexa_error':
            text = self._alexa_failed(value, monotonic)
        elif event == 'volume':
            text = self._set_volume(int(value))
        elif event == 'play_today':
            text = self._play(get_today_wake_item(store=self.store))
        elif event == 'play_random':
            text = self._play(get_random_item(self.store))
        elif event == 'play_file':
            path = settings.music_file(value)
            text = self._play({'file': path, 'message': path.rsplit('/', 1)[-1]})
        elif event == 'stop_audio':
            text = self._stop_audio()
        elif event == 'wake_test':
            self.stop()
            if self.now is not None:
                self._begin_alarm(TEST_ALARM, self.now, monotonic)
            text = 'Weck-Test'
        elif event == 'wake_stop':
            self.stop()
            text = 'Wecker gestoppt'
        elif event in ('notice', 'error'):
            print(value, flush=True)
            text = str(value)
        elif event == 'weather_result':
            self.weather_text = str(value)
            text = str(value) if not self.alarm_active else None
        elif event == 'legacy_press':
            if self.alarm_active:
                text = self._toggle_audio()
            else:
                self.backlight(toggle=True)
        if text:
            self._notify(text)

    def _key(self, key):
        session = self.session
        if session is not None and session.phase == 'music' and session.program['snooze_any_key']:
            self._debug(f'Taste {key} -> Schlummern')
            return self.snooze()
        action = self.store.get('keys').get(key, {'type': 'none'})
        if action['type'] != 'songs':
            self.browse = None
        self.lamp = None
        text = self.run_action(action)
        self._debug(f'Taste {key} -> {action["type"]}: {text}')
        return text

    def run_action(self, action):
        """Eine Tastenaktion ausfuehren; gibt den LCD-Text zurueck."""
        kind = action['type']
        if kind == 'none':
            return None
        if kind in ('effect', 'light'):
            self.programs.override()
        if kind == 'effect':
            effect = self.store.effect_by_id(action['effect'])
            if effect is None:
                return 'Effekt fehlt'
            self.send_light(effect['state'])
            if self.browser is not None:
                self.browser.power = effect['state'].get('on', True)
            return action.get('label') or effect['name']
        if kind == 'light':
            if self.browser is None:
                on = action['mode'] != 'off'
                self.send_light({'on': on})
                return 'Licht an' if on else 'Licht aus'
            if action['mode'] == 'toggle':
                return self.browser.toggle_power()
            return self.browser.set_power(action['mode'] == 'on')
        if kind == 'music':
            source = action['source']
            if source == 'today':
                return self._play(get_today_wake_item(store=self.store))
            if source == 'random':
                return self._play(get_random_item(self.store))
            if source == 'stop':
                return self._stop_audio()
            return self._toggle_audio()
        if kind == 'songs':
            return self._browse_start(action['source'])
        if kind == 'display':
            self.backlight(toggle=True)
            return action.get('label') or 'Display An/Aus'
        if kind == 'snooze':
            return self.snooze()
        if kind == 'wake_test':
            self.handle('wake_test', None, self.monotonic)
            return None
        if kind == 'alarm_toggle':
            enabled = not self.store.get('alarms_enabled')
            self.store.save('alarms_enabled', enabled)
            return 'Wecker an' if enabled else 'Wecker aus'
        if kind == 'weather':
            if self.weather is None:
                return 'Wetter nicht verfuegbar'
            cached = self.weather.cached(max_age=10 * 60)
            if cached:
                return cached
            if self.weather.request(lambda text: self.emit('notice', text)):
                return 'Wetter wird geladen'
            return 'Wetter: Ort fehlt (Web)'
        if kind in integrations.REMOTE_TYPES:
            entity = action.get('entity_id', '')
            if kind in ('ha_color', 'home_assistant') and entity.startswith('light.'):
                self.lamp = {'entity_id': entity, 'until': self.monotonic + LAMP_SECONDS}
                self.dimmer.prefetch(entity)
            return self.integration(action, lambda message: self.emit('notice', message))
        return None

    def _play(self, item):
        if self.alarm_active:
            self.stop()
        self.player.play(item['file'])
        self._debug(f'Abgespielt: {item["file"]}')
        return item['message']

    def _stop_audio(self):
        if self.alarm_active:
            self.stop()
            return 'Wecker gestoppt'
        self.player.stop()
        return 'Musik gestoppt'

    def _set_volume(self, percent):
        if self.session is not None:
            self.session.volume_manual = True
        volume = self.player.set_volume(percent)
        self._debug(f'Lautstaerke: {volume}%')
        return f'Lautstaerke: {volume}%'

    def _toggle_audio(self):
        """Ein Knopf fuer alles Hoerbare: Wecker aus, sonst Musik an bzw. aus."""
        if self.session is not None:
            self.stop()
            self._debug('Wecker manuell gestoppt')
            return 'Wecker gestoppt'
        if self.player.is_playing:
            self.player.stop()
            self._debug('Musik gestoppt')
            return 'Musik gestoppt'
        return self._play(get_today_wake_item(store=self.store))

    # ------------------------------------------------------------------
    # Alexa
    # ------------------------------------------------------------------

    def _alexa_volume(self, steps):
        """Rechter Knopf gedrueckt drehen: Alexa-Lautstaerke 1-10.

        Alexa meldet ihre Lautstaerke nicht zurueck; gezaehlt wird ab dem
        zuletzt hier (oder vom Weckprogramm) gesetzten Wert.
        """
        if not self.alexa.device():
            return 'Alexa-Echo fehlt (Web)'
        session = self.session
        if session is not None and session.uses_alexa:
            session.volume_manual = True
        level = ALEXA_DEFAULT_LEVEL if self.alexa_level is None else self.alexa_level
        self.alexa_level = max(1, min(10, level + steps))
        if session is not None and session.uses_alexa:
            session.alexa_level = self.alexa_level
        self._alexa_volume_due = self.monotonic + ALEXA_VOLUME_DELAY
        self._debug(f'Alexa-Lautstaerke: {self.alexa_level}')
        return f'Alexa Lautst. {self.alexa_level}'

    def _alexa_failed(self, message, monotonic):
        """Alexa-Befehl beim Wecken gescheitert: mit dem MP3-Tageslied weiterwecken."""
        print(f'Alexa Fehler: {message}', flush=True)
        session = self.session
        if session is None or not session.uses_alexa or session.phase != 'music':
            return f'Alexa: {message}'
        item = get_today_wake_item(store=self.store)
        self.active_item = {**item, 'message': self.active_item['message']}
        error = session.start_music(item, monotonic)
        if error:
            print(f'Audio Fehler: {error}', flush=True)
            return 'Audio Fehler!'
        return 'Alexa Fehler: MP3'

    def _lamp_dim(self, steps):
        """Linker Knopf nach einer Lampen-Taste: Helligkeit in 10er-Stufen, sofort senden."""
        lamp = self.lamp
        lamp['until'] = self.monotonic + LAMP_SECONDS
        level = self.dimmer.levels.get(lamp['entity_id'], LAMP_DEFAULT_PERCENT)
        percent = integrations.dim_step(level, steps)
        self.dimmer.set(lamp['entity_id'], percent)
        self._debug(f'Lampe {lamp["entity_id"]}: {percent}%')
        return f'Lampe {percent}%'

    # ------------------------------------------------------------------
    # Liederliste (Taste + rechter Drehknopf)
    # ------------------------------------------------------------------

    def _browse_entries(self, source):
        if source == 'alexa':
            return [{'alexa': entry['text'], 'file': None,
                     'name': entry['text'].removeprefix('spiele ').removeprefix('Spiele ')}
                    for entry in self.store.get('music')['alexa_songs']]
        return [{'file': path, 'name': path.rsplit('/', 1)[-1][:-4].replace('_', ' ').strip(' .')}
                for path in list_music()]

    def _browse_start(self, source):
        """Taste: Liederliste oeffnen, erneuter Druck = naechstes Lied."""
        if self.alarm_active:
            return None
        if self.browse is not None and self.browse['source'] == source:
            return self._browse_move(1)
        entries = self._browse_entries(source)
        if not entries:
            return 'Liederliste leer'
        self.browse = {'source': source, 'entries': entries, 'index': 0}
        return self._browse_move(0)

    def _browse_move(self, steps):
        browse = self.browse
        browse['index'] = (browse['index'] + steps) % len(browse['entries'])
        browse['until'] = self.monotonic + BROWSE_SECONDS
        entry = browse['entries'][browse['index']]
        text = f'{browse["index"] + 1}/{len(browse["entries"])} {entry["name"]}'
        self._notify(text, BROWSE_SECONDS)
        return text

    def _browse_play(self):
        entry = self.browse['entries'][self.browse['index']]
        self.browse = None
        if entry.get('alexa'):
            if not self.alexa.say(entry['alexa']):
                return 'Alexa-Echo fehlt (Web)'
            self.player.stop()
            return 'Alexa: ' + entry['name']
        return self._play({'file': entry['file'], 'message': entry['name']})

    def _reset(self):
        """Fluchttaste: Musik aus, Licht an, Display wieder automatisch.

        Kinder brauchen einen Weg zurueck, der nichts voraussetzt. Ein langer
        Druck stellt deshalb jeden Zustand her, aus dem heraus die Uhr wieder
        normal bedienbar ist.
        """
        self.stop()
        self.programs.override()
        if self.browser is not None:
            self.browser.set_power(True)
        self.backlight(reset=True)
        self._debug('Alles zurueckgesetzt')
        return 'Alles normal'

    # ------------------------------------------------------------------
    # Anzeige / Status
    # ------------------------------------------------------------------

    weather_text = None

    def _notify(self, text, seconds=None):
        if seconds is None:
            # Beim Blaettern bleibt der Eintrag stehen, bis die Liederliste zu ist.
            seconds = BROWSE_SECONDS if self.browse is not None else NOTICE_SECONDS
        self.notice = text
        self.notice_end = self.monotonic + seconds

    @staticmethod
    def _debug(message):
        if config.DEBUG:
            print(f'[Controller] {message}', flush=True)

    def message(self, monotonic, fallback):
        if monotonic < self.notice_end:
            return self.notice
        if self.session is not None and self.session.phase == 'snooze' and self.now is not None:
            remaining = max(0, int(self.session.snoozed_until - monotonic))
            return f'Schlummern {remaining // 60}:{remaining % 60:02d}'
        if self.active_item:
            text = self.active_item['message']
            if self.session is not None and self.session.program['show_weather'] and self.weather_text:
                text = f'{text} - {self.weather_text}'
            return text
        return fallback

    def status(self):
        """Momentaufnahme fuer die Weboberflaeche (aus dem ipc-Thread gelesen)."""
        session = self.session
        return {
            'phase': session.phase if session else None,
            'alarm': session.alarm.get('label') if session and session.alarm else None,
            'song': (self.active_item['file'] or self.active_item.get('alexa')
                     if self.active_item else None),
            'playing': self.player.is_playing,
            'volume': self.player.volume,
            'program': self.programs.label,
            'notice': self.notice if self.monotonic < self.notice_end else '',
        }
