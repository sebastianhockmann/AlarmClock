"""Hardware-independent alarm lifetime and input handling."""
import config
from scheduler import check_alarm, get_today_wake_item


class ClockController:
    def __init__(self, player, lights):
        self.player = player
        self.lights = lights
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
            self.notice = self.lights.rotate(int(value))
            self._debug(f'Effekt-Vorschau: {self.notice}')
        elif event == 'left_press':
            self.notice = self.lights.confirm()
            self._debug(f'Effekt gesendet: {self.notice}')
        elif event == 'key':
            self.notice = self.lights.select('key', str(value))
            self._debug(f'Taste {value} -> Effekt gesendet: {self.notice}')
        elif event == 'right_press':
            self.stop()
            self.notice = 'Wecker gestoppt'
            self._debug('Wecker manuell gestoppt')
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

    @staticmethod
    def _debug(message):
        if config.DEBUG:
            print(f'[Controller] {message}', flush=True)

    def message(self, monotonic, fallback):
        if monotonic < self.notice_end:
            return self.notice
        return self.active_item['message'] if self.active_item else fallback
