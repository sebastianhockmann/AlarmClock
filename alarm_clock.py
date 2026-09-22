#!/usr/bin/env python3
"""Clock runtime. Importing this module never initializes hardware."""
from datetime import datetime
import importlib
import queue
import signal
import time
import config
from audio import AudioPlayer
from controller import ClockController
from lighting import EffectSelector, WLEDManager, load_effects
from scheduler import get_greeting
from util import scrolling_text


def main():
    from lcd import lcd_show, lcd_set_backlight, lcd_close

    events = queue.Queue(maxsize=128)

    def emit(event, value=None):
        try:
            events.put_nowait((event, value))
        except queue.Full:
            print('Eingabepuffer voll', flush=True)

    player = AudioPlayer()
    wled = WLEDManager(report=lambda message: print(message, flush=True))
    inputs = []
    running = True

    def shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        controller = ClockController(player, EffectSelector(load_effects(config.EFFECT_LIBRARY), wled.send))
        if config.INPUT_MODULE:
            try:
                adapter = importlib.import_module(config.INPUT_MODULE)
                inputs.append(adapter.open_controls(emit))
            except (ImportError, OSError) as error:
                print(f'Eingabemodul {config.INPUT_MODULE} nicht verfügbar: {error}. '
                      'Wecker läuft ohne Tastenfeld/Drehencoder weiter. '
                      'I2C-Verkabelung/Adressen pruefen oder INPUT_MODULE=None setzen.',
                      flush=True)
        elif config.LEGACY_BUTTON_ENABLED:
            try:
                from button import init_button
                inputs.append(init_button(lambda: emit('legacy_press'),
                                          lambda: emit('play_today'),
                                          lambda: emit('right_press')))
            except (ImportError, OSError) as error:
                print(f'GPIO-Taster an GPIO{config.BUTTON_PIN} nicht verfügbar: {error}. '
                      'Wecker läuft ohne diesen Taster weiter. '
                      'GPIO-Treiber prüfen oder LEGACY_BUTTON_ENABLED=False setzen.',
                      flush=True)
        previous_text, scroll_start = None, time.monotonic()
        while running:
            now, monotonic = datetime.now(), time.monotonic()
            controller.tick(now, monotonic)
            for _ in range(128):
                try:
                    event, value = events.get_nowait()
                except queue.Empty:
                    break
                if config.DEBUG and event != 'error':
                    print(f'[Event] {event} {value!r}', flush=True)
                try:
                    if event == 'legacy_press':
                        if controller.active_item:
                            controller.handle('right_press', None, monotonic)
                        else:
                            lcd_set_backlight(toggle=True)
                    elif event == 'error':
                        print(value, flush=True)
                        controller.notice = str(value)
                        controller.notice_end = monotonic + 5
                    else:
                        controller.handle(event, value, monotonic)
                except (OSError, ValueError) as error:
                    print(f'Eingabefehler: {error}', flush=True)
                    controller.notice = 'Bedienfehler'
                    controller.notice_end = monotonic + 5
            greeting = get_greeting(now)
            force = bool(controller.active_item and config.ALARM_BACKLIGHT)
            lcd_set_backlight(state=True if force else greeting['backlight'], force=force)
            text = controller.message(monotonic, greeting['text'])
            if text != previous_text:
                previous_text, scroll_start = text, monotonic
            lcd_show(now, scrolling_text(text, config.LCD_COLS,
                                        int((monotonic - scroll_start) / 0.4)))
            time.sleep(0.02)
    finally:
        for device in inputs:
            device.close()
        player.stop()
        wled.close()
        lcd_close()


if __name__ == '__main__':
    main()
