# watchdog.py
import time
from log import log

class Watchdog:
    def __init__(self, audio_player_ref, button_ref, special_ref):
        self.audio = audio_player_ref
        self.button = button_ref
        self.special = special_ref

        # Zeitstempel für Überwachung
        self.last_loop = time.time()
        self.last_button_event = time.time()

        self.max_loop_delay = 0.5       # Sekunden
        self.max_special_time = 20      # Sekunden, falls Modus hängen bleibt

    # Muss in der Hauptschleife GANZ am ANFANG aufgerufen werden.
    def beat(self):
        now = time.time()
        delay = now - self.last_loop

        if delay > self.max_loop_delay:
            log("[WD] WARNUNG: Loop hängt! Delay:", round(delay, 3))

        self.last_loop = now

        # Spezialmodus überwachen
        special_mode = self.special["mode"]
        end_time = self.special["end"]

        if special_mode not in (None, "snow", "countdown", "manual"):
            log("[WD] Unbekannter special_mode → reset:", special_mode)
            self.special["mode"] = None

        if special_mode and now > end_time + self.max_special_time:
            log("[WD] special_mode hängt → reset:", special_mode)
            self.special["mode"] = None

        # Audio überwachen
        try:
            if self.audio.thread and not self.audio.thread.is_alive():
                log("[WD] Audio-Thread tot → cleanup()")
                self.audio.stop()
        except Exception as e:
            log("[WD] Fehler beim Audio-Check", e)

    # Vom Button aufgerufen
    def notify_button_event(self):
        self.last_button_event = time.time()

    # Buttons überwachen
    def check_buttons(self):
        now = time.time()
        if now - self.last_button_event > 10:
            log("[WD] WARNUNG: Keine Button-Events >10s → möglicher Fehler")
