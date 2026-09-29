"""Hardware-independent alarm lifetime and input handling.

Laeuft ausschliesslich auf dem Haupt-Thread: Eingabegeraete, Weboberflaeche
(ipc.py) und Hintergrund-Threads (Wetter, Alexa, ...) legen Ereignisse in
die Warteschlange, alarm_clock.main() reicht sie an handle() weiter.
"""
from datetime import timedelta
import config
import integrations
import settings
from scheduler import AlarmScheduler, get_random_item, get_today_wake_item, wake_item
from wake import WakeSession

NOTICE_SECONDS = 5
TEST_ALARM = {'id': 'test', 'label': 'Weck-Test'}


class ClockController:
    def __init__(self, player, send_light, browser=None, backlight=None, emit=None,
                 store=settings, alarm_scheduler=None, weather=None, integration=None):
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

    def _new_session(self, alarm, now):
        program = self.store.get('wake')
        effect = self.store.effect_by_id(program['effect']) if program['effect'] else None
        if program['effect'] and effect is None:
            print(f'Weck-Lichteffekt "{program["effect"]}" fehlt in der Effektliste', flush=True)
        return WakeSession(program, self.player, self.send_light, effect, alarm, now.date())

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
        if event == 'left_rotate':
            text = self.browser.rotate(int(value), monotonic) if self.browser else None
            self._debug(f'Effekt: {text}')
        elif event == 'left_press':
            text = self.browser.toggle_power() if self.browser else None
            self._debug(f'Licht: {text}')
        elif event == 'key':
            text = self._key(str(value))
        elif event == 'action':
            text = self.run_action(settings.validate_action(value))
        elif event == 'right_press':
            text = self._toggle_audio()
        elif event == 'right_hold':
            text = self._reset()
        elif event == 'right_rotate':
            text = self._set_volume(self.player.volume + int(value) * config.VOLUME_STEP)
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
        text = self.run_action(action)
        self._debug(f'Taste {key} -> {action["type"]}: {text}')
        return text

    def run_action(self, action):
        """Eine Tastenaktion ausfuehren; gibt den LCD-Text zurueck."""
        kind = action['type']
        if kind == 'none':
            return None
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

    def _reset(self):
        """Fluchttaste: Musik aus, Licht an, Display wieder automatisch.

        Kinder brauchen einen Weg zurueck, der nichts voraussetzt. Ein langer
        Druck stellt deshalb jeden Zustand her, aus dem heraus die Uhr wieder
        normal bedienbar ist.
        """
        self.stop()
        if self.browser is not None:
            self.browser.set_power(True)
        self.backlight(reset=True)
        self._debug('Alles zurueckgesetzt')
        return 'Alles normal'

    # ------------------------------------------------------------------
    # Anzeige / Status
    # ------------------------------------------------------------------

    weather_text = None

    def _notify(self, text, seconds=NOTICE_SECONDS):
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
            'song': self.active_item['file'] if self.active_item else None,
            'playing': self.player.is_playing,
            'volume': self.player.volume,
            'notice': self.notice if self.monotonic < self.notice_end else '',
        }
