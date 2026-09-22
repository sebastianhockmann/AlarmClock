"""Legacy GPIO button; callbacks only enqueue runtime events."""
import threading
import time
import config


class MultiClickButton:
    def __init__(self, callbacks):
        from gpiozero import Button
        self.button = Button(config.BUTTON_PIN, pull_up=True, bounce_time=0.05)
        self.callbacks = callbacks
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.count = 0
        self.last = 0
        self.button.when_pressed = self._pressed
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _pressed(self):
        with self.lock:
            self.count += 1
            self.last = time.monotonic()

    def _run(self):
        while not self.stopping.wait(0.01):
            count = 0
            with self.lock:
                if self.count and time.monotonic() - self.last >= 0.4:
                    count, self.count = self.count, 0
            if count:
                self.callbacks[min(count, 3) - 1]()

    def close(self):
        self.button.close()
        self.stopping.set()
        self.thread.join(timeout=1)


def init_button(on_single, on_double, on_triple):
    return MultiClickButton((on_single, on_double, on_triple))
