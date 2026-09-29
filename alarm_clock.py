#!/usr/bin/env python3
"""Clock runtime. Importing this module never initializes hardware."""
from datetime import datetime
import importlib
import queue
import signal
import time
import config
import chime
import ipc
import settings
from audio import AudioPlayer
from controller import ClockController
from lighting import EffectBrowser, WLEDManager, browser_entries
from scheduler import get_greeting
from util import scrolling_text
from weather import WeatherService


def open_inputs(emit):
    """Eingabegeraete starten; Fehler melden, der Wecker laeuft ohne sie weiter."""
    inputs = []
    if config.INPUT_MODULE:
        try:
            adapter = importlib.import_module(config.INPUT_MODULE)
            inputs.append(adapter.open_controls(emit))
        except (ImportError, OSError) as error:
            print(f'Eingabemodul {config.INPUT_MODULE} nicht verfügbar: {error}. '
                  'Wecker läuft ohne Tastenfeld/Drehencoder weiter. '
                  'I2C-Verkabelung/Adressen pruefen oder inputs.module in '
                  'config/hardware.json leeren.', flush=True)
    elif config.LEGACY_BUTTON_ENABLED:
        try:
            from button import init_button
            inputs.append(init_button(lambda: emit('legacy_press'),
                                      lambda: emit('play_today'),
                                      lambda: emit('stop_audio')))
        except (ImportError, OSError) as error:
            print(f'GPIO-Taster an GPIO{config.BUTTON_PIN} nicht verfügbar: {error}. '
                  'Wecker läuft ohne diesen Taster weiter. GPIO-Treiber prüfen oder '
                  'inputs.legacy_button_enabled in config/hardware.json abschalten.',
                  flush=True)
    return inputs


def main():
    from lcd import lcd_show, lcd_set_backlight, lcd_close

    for message in settings.migrate_legacy():
        print(message, flush=True)

    events = queue.Queue(maxsize=128)

    def emit(event, value=None):
        try:
            events.put_nowait((event, value))
        except queue.Full:
            print('Eingabepuffer voll', flush=True)

    player = AudioPlayer()
    wled = WLEDManager(report=lambda message: print(message, flush=True))
    inputs = []
    server = None
    running = True

    def shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        # Linker Knopf: alle Effekte des Geraets; bis die Liste da ist, die eigene Bibliothek.
        browser = EffectBrowser(wled.send, wled.get_status,
                                browser_entries(settings.get('effects')),
                                fxdata=lambda: wled.fetch('fxdata'))
        browser.refresh()
        controller = ClockController(player, wled.send, browser=browser,
                                     backlight=lcd_set_backlight, emit=emit,
                                     weather=WeatherService(settings))
        inputs = open_inputs(emit)
        try:
            server = ipc.CommandServer(emit, controller.status)
        except OSError as error:
            print(f'Steuerkanal fuer die Weboberflaeche nicht verfuegbar: {error}', flush=True)
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
                if event == 'key':
                    chime.play_click()
                try:
                    controller.handle(event, value, monotonic)
                except (OSError, ValueError, TypeError) as error:
                    print(f'Eingabefehler bei {event}: {error}', flush=True)
                    controller.notice = 'Bedienfehler'
                    controller.notice_end = monotonic + 5
            greeting = get_greeting(now)
            force = controller.force_backlight
            lcd_set_backlight(state=True if force else greeting['backlight'], force=force)
            text = controller.message(monotonic, greeting['text'])
            if text != previous_text:
                previous_text, scroll_start = text, monotonic
            lcd_show(now, scrolling_text(text, config.LCD_COLS,
                                         int((monotonic - scroll_start) / 0.4)))
            time.sleep(0.02)
    finally:
        if server is not None:
            server.close()
        for device in inputs:
            device.close()
        player.stop()
        wled.close()
        lcd_close()


if __name__ == '__main__':
    main()
