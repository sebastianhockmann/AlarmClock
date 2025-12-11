# button.py
from gpiozero import Button
import time
import threading
import config

# Klick-Zeitfenster in Sekunden
MULTI_CLICK_TIMEOUT = 0.6  # Reaktionsfenster für Mehrfachklicks
BOUNCE_TIME = 0.05         # Muss für pigpio <= 0.3 sein


def init_button(on_single_click, on_double_click, on_triple_click):
    button = Button(config.BUTTON_PIN, pull_up=True, bounce_time=BOUNCE_TIME)

    state = {
        "clicks": 0,
        "timer": None
    }
    lock = threading.Lock()

    def _finish_clicks():
        with lock:
            count = state["clicks"]

            if count == 1:
                on_single_click()

            elif count == 2:
                on_double_click()

            elif count == 3:
                on_triple_click()

            # Reset
            state["clicks"] = 0
            state["timer"] = None

    def handle_press():
        with lock:
            state["clicks"] += 1

            if state["clicks"] == 1:
                # Timer für Mehrfachklick starten
                t = threading.Timer(MULTI_CLICK_TIMEOUT, _finish_clicks)
                state["timer"] = t
                t.start()

            else:
                # Bei jedem neuen Klick prüfen wir, ob der Timer noch aktiv ist
                if state["timer"] is not None:
                    # verlängern? nein — Click-Fenster gilt ab dem ersten Klick
                    pass

    button.when_pressed = handle_press
    return button
