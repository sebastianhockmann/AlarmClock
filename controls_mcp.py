"""Two rotary encoders + button on a MCP23017, and a 4x4 keypad on a PCF8574.

Wiring is validated against real hardware measurements, see rotary_clock.py.
Runs its own polling thread; emit() only enqueues events, matching the
INPUT_MODULE contract documented in config.py.
"""
import threading
import time
from smbus2 import SMBus
import config

IODIRA, IODIRB = 0x00, 0x01
GPPUA, GPPUB = 0x0C, 0x0D
GPIOA, GPIOB = 0x12, 0x13

# Bit positions in the 16-bit GPIOA|GPIOB<<8 word.
LEFT = {'a': 14, 'b': 15, 'button': 13}   # PB6, PB7, PB5
RIGHT = {'a': 0, 'b': 1, 'button': 2}     # PA0, PA1, PA2

KEYS = ("123A", "456B", "789C", "*0#D")
ROWS = (0, 1, 2, 3)
COLS = (4, 5, 6, 7)

# Quadrature table: 00 -> 01 -> 11 -> 10 -> 00
TRANSITIONS = (0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0)

BUTTON_DEBOUNCE = 0.03
KEY_DEBOUNCE = 0.04
POLL_INTERVAL = 0.005


class _QuadDecoder:
    def __init__(self, initial, steps=2):
        self.previous = initial & 0b11
        self.steps = steps
        self.partial = 0

    def update(self, current):
        current &= 0b11
        previous, self.previous = self.previous, current
        if previous ^ current == 0b11:
            # Both bits changed: direction is ambiguous, discard the partial step.
            self.partial = 0
            return 0
        self.partial += TRANSITIONS[(previous << 2) | current]
        if abs(self.partial) >= self.steps:
            direction = 1 if self.partial > 0 else -1
            self.partial = 0
            return direction
        return 0


class _DebouncedButton:
    """Entprellter Taster; meldet 'press'/'release', sonst None (aktiv low)."""

    def __init__(self, initial_high):
        self.stable = self.candidate = initial_high
        self.changed_at = time.monotonic()

    def update(self, is_high, now):
        if is_high != self.candidate:
            self.candidate, self.changed_at = is_high, now
        if self.candidate != self.stable and now - self.changed_at >= BUTTON_DEBOUNCE:
            self.stable = self.candidate
            return 'release' if self.stable else 'press'  # gedrueckt = auf GND gezogen
        return None


class MCPControls:
    def __init__(self, emit):
        self.emit = emit
        self.bus = SMBus(config.INPUT_I2C_PORT)
        self.mcp_address = config.MCP23017_ADDRESS
        self.keypad_address = config.KEYPAD_ADDRESS
        self.bus.write_byte_data(self.mcp_address, IODIRA, 0xFF)
        self.bus.write_byte_data(self.mcp_address, IODIRB, 0xFF)
        self.bus.write_byte_data(self.mcp_address, GPPUA, 0xFF)
        self.bus.write_byte_data(self.mcp_address, GPPUB, 0xFF)
        self.bus.write_byte(self.keypad_address, 0xFF)

        gpio = self._read_mcp()
        self.left_decoder = _QuadDecoder(self._encoder_state(gpio, LEFT))
        self.right_decoder = _QuadDecoder(self._encoder_state(gpio, RIGHT))
        self.left_button = _DebouncedButton(bool((gpio >> LEFT['button']) & 1))
        self.right_button = _DebouncedButton(bool((gpio >> RIGHT['button']) & 1))
        self.right_pressed_at = None
        self.right_hold_fired = False
        self.candidate_key = self.stable_key = None
        self.key_changed_at = time.monotonic()

        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @staticmethod
    def _encoder_state(gpio, pins):
        return ((gpio >> pins['a']) & 1) | (((gpio >> pins['b']) & 1) << 1)

    def _read_mcp(self):
        a = self.bus.read_byte_data(self.mcp_address, GPIOA)
        b = self.bus.read_byte_data(self.mcp_address, GPIOB)
        return a | (b << 8)

    def _scan_keypad(self):
        pressed = set()
        try:
            for row, pin in enumerate(ROWS):
                self.bus.write_byte(self.keypad_address, 0xFF & ~(1 << pin))
                time.sleep(0.001)
                value = self.bus.read_byte(self.keypad_address)
                for col, col_pin in enumerate(COLS):
                    if not value & (1 << col_pin):
                        pressed.add((row, col))
        finally:
            self.bus.write_byte(self.keypad_address, 0xFF)
        if len(pressed) != 1:
            return None
        row, col = next(iter(pressed))
        return KEYS[row][col]

    def _debug(self, message):
        if config.DEBUG:
            print(f'[Eingabe] {message}', flush=True)

    def _poll_encoders(self):
        gpio = self._read_mcp()
        now = time.monotonic()

        left_delta = self.left_decoder.update(self._encoder_state(gpio, LEFT))
        if left_delta:
            self._debug(f'Drehknopf links: {left_delta:+d}')
            self.emit('left_rotate', left_delta)

        right_delta = self.right_decoder.update(self._encoder_state(gpio, RIGHT))
        if right_delta:
            self._debug(f'Drehknopf rechts: {right_delta:+d}')
            self.emit('right_rotate', right_delta)

        # Links hat keine Halte-Funktion und loest deshalb sofort beim Druck aus.
        if self.left_button.update(bool((gpio >> LEFT['button']) & 1), now) == 'press':
            self._debug('Taster links gedrueckt')
            self.emit('left_press')

        self._poll_right_button(bool((gpio >> RIGHT['button']) & 1), now)

    def _poll_right_button(self, is_high, now):
        """Kurz = right_press (beim Loslassen), lang = right_hold (nach Ablauf)."""
        event = self.right_button.update(is_high, now)
        if event == 'press':
            self.right_pressed_at, self.right_hold_fired = now, False
        elif event == 'release':
            if not self.right_hold_fired:
                self._debug('Taster rechts gedrueckt')
                self.emit('right_press')
            self.right_pressed_at = None
        if (self.right_pressed_at is not None and not self.right_hold_fired
                and now - self.right_pressed_at >= config.BUTTON_HOLD_SECONDS):
            self.right_hold_fired = True
            self._debug('Taster rechts gehalten')
            self.emit('right_hold')

    def _poll_keypad(self):
        key = self._scan_keypad()
        now = time.monotonic()
        if key != self.candidate_key:
            self.candidate_key, self.key_changed_at = key, now
        if self.candidate_key != self.stable_key and now - self.key_changed_at >= KEY_DEBOUNCE:
            self.stable_key = self.candidate_key
            if self.stable_key:
                self._debug(f'Taste: {self.stable_key}')
                self.emit('key', self.stable_key)

    def _run(self):
        while not self.stopping.wait(POLL_INTERVAL):
            try:
                self._poll_encoders()
                self._poll_keypad()
            except OSError as error:
                self.emit('error', f'I2C-Eingabefehler (Tastenfeld/Encoder): {error}')
                time.sleep(0.5)

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=1)
        self.bus.close()


def open_controls(emit):
    return MCPControls(emit)
