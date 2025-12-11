from gpiozero import Button
import config
import time
from log import log

CLICK_TIMEOUT = 0.40  # Zeitfenster für Mehrfachklick (ms genau getestet)
MAX_CLICKS = 3

def init_button(on_single, on_double, on_triple):
    button = Button(config.BUTTON_PIN, pull_up=True, bounce_time=0.05)

    state = {
        "count": 0,
        "last_time": 0,
        "waiting": False
    }

    def handle_click():
        now = time.time()

        # Neue Klickserie beginnen?
        if not state["waiting"]:
            state["count"] = 1
            state["last_time"] = now
            state["waiting"] = True
            return

        # Innerhalb des Klickfensters → weiterer Klick
        if now - state["last_time"] <= CLICK_TIMEOUT:
            state["count"] += 1
            state["last_time"] = now
        else:
            # Zu spät -> Neue Klickserie
            state["count"] = 1
            state["last_time"] = now

    def check_clicks():
        # Wird permanent gepollt
        while True:
            if state["waiting"] and time.time() - state["last_time"] > CLICK_TIMEOUT:
                # Entscheidung treffen
                c = state["count"]
                state["waiting"] = False
                state["count"] = 0

                if c == 1:
                    log("[Button] Single-Klick erkannt")
                    on_single()
                elif c == 2:
                    log("[Button] Doppelklick erkannt")
                    on_double()
                elif c >= 3:
                    log("[Button] Triple-Klick erkannt")
                    on_triple()

            time.sleep(0.01)

    # Buttons verbinden
    button.when_pressed = handle_click

    # Hintergrund-Thread starten
    import threading
    threading.Thread(target=check_clicks, daemon=True).start()

    return button
