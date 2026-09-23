"""Hardware-independent alarm lifetime and input handling."""
import config
import smart_home
from scheduler import check_alarm, get_today_wake_item


class ClockController:
    def __init__(self, player, lights, browser=None, backlight=None, smart_home_trigger=None):
        self.player = player
        self.lights = lights
        # Ohne Browser bleibt der linke Knopf bei der kuratierten Bibliothek
        # (Vorschau auf dem Display, Druck bestaetigt) - so laeuft der Wecker
        # auch ohne erreichbares WLED-Geraet bedienbar weiter.
        self.browser = browser
        self.backlight = backlight or (lambda **kwargs: None)
        self.smart_home_trigger = smart_home_trigger or smart_home.trigger
        self.active_item = None
        self.alarm_end = 0
        self.notice = ''
        self.notice_end = 0

    def stop(self):
        self.player.stop()
        self.active_item = None

    def tick(self, now, monotonic):
        triggered, item = check_alarm(now)
        if triggered:
            self.active_item = item
            self.alarm_end = monotonic + config.ALARM_DURATION_SECONDS
            self._debug(f'Alarm ausgeloest: {item["file"]}')
            try:
                self.player.play(item['file'])
            except (OSError, ValueError) as error:
                print(f'Audio Fehler: {error}', flush=True)
                self.notice = 'Audio Fehler!'
                self.notice_end = monotonic + 10
            if config.ALARM_EFFECT:
                try:
                    self.lights.select('id', config.ALARM_EFFECT)
                except ValueError as error:
                    print(error, flush=True)
        if self.active_item and monotonic >= self.alarm_end:
            self.stop()

    def handle(self, event, value, monotonic):
        if event == 'left_rotate':
            if self.browser is None:
                self.notice = self.lights.rotate(int(value))
            else:
                self.notice = self.browser.rotate(int(value), monotonic)
            self._debug(f'Effekt: {self.notice}')
        elif event == 'left_press':
            self.notice = (self.lights.confirm() if self.browser is None
                           else self.browser.toggle_power())
            self._debug(f'Licht: {self.notice}')
        elif event == 'key':
            key = str(value)
            action = config.SMART_HOME_ACTIONS.get(key)
            if action is not None:
                self.notice = self.smart_home_trigger(action)
                self._debug(f'Taste {key} -> Smart Home: {self.notice}')
            else:
                self.notice = self.lights.select('key', key)
                self._debug(f'Taste {key} -> Effekt gesendet: {self.notice}')
        elif event == 'right_press':
            self.notice = self._toggle_audio()
        elif event == 'right_hold':
            self.notice = self._reset()
        elif event == 'play_today':
            item = get_today_wake_item()
            self.player.play(item['file'])
            self.notice = item['message']
            self._debug(f'Tageslied abgespielt: {item["file"]}')
        elif event == 'right_rotate':
            volume = self.player.set_volume(self.player.volume + int(value) * config.VOLUME_STEP)
            self.notice = f'Lautstaerke: {volume}%'
            self._debug(self.notice)
        else:
            return
        self.notice_end = monotonic + 5

    def _toggle_audio(self):
        """Ein Knopf fuer alles Hoerbare: Wecker aus, sonst Musik an bzw. aus."""
        if self.active_item:
            self.stop()
            self._debug('Wecker manuell gestoppt')
            return 'Wecker gestoppt'
        if self.player.is_playing:
            self.player.stop()
            self._debug('Musik gestoppt')
            return 'Musik gestoppt'
        item = get_today_wake_item()
        self.player.play(item['file'])
        self._debug(f'Tageslied abgespielt: {item["file"]}')
        return item['message']

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

    @staticmethod
    def _debug(message):
        if config.DEBUG:
            print(f'[Controller] {message}', flush=True)

    def message(self, monotonic, fallback):
        if monotonic < self.notice_end:
            return self.notice
        return self.active_item['message'] if self.active_item else fallback
