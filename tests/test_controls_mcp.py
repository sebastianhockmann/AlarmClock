import threading
import time
import unittest
from unittest.mock import patch

import controls_mcp


class FakeBus:
    """Minimal SMBus stand-in for one MCP23017 and one PCF8574 keypad."""

    def __init__(self, port):
        self.mcp_registers = {}
        self.keypad_last_write = 0xFF
        self.pressed = None  # (row, col) or None
        self.read_byte_data_override = None

    def write_byte_data(self, address, register, value):
        self.mcp_registers[(address, register)] = value

    def read_byte_data(self, address, register):
        if self.read_byte_data_override:
            return self.read_byte_data_override(address, register)
        return self.mcp_registers.get((address, register), 0)

    def write_byte(self, address, value):
        self.keypad_last_write = value

    def read_byte(self, address):
        if self.pressed is None:
            return 0xFF
        row, col = self.pressed
        row_pin = controls_mcp.ROWS[row]
        if self.keypad_last_write == (0xFF & ~(1 << row_pin)):
            return 0xFF & ~(1 << controls_mcp.COLS[col])
        return 0xFF

    def close(self):
        pass

    def set_mcp_gpio(self, address, value):
        self.mcp_registers[(address, controls_mcp.GPIOA)] = value & 0xFF
        self.mcp_registers[(address, controls_mcp.GPIOB)] = (value >> 8) & 0xFF


class ControlsMCPTests(unittest.TestCase):
    def setUp(self):
        self.mcp_address, self.keypad_address = 0x21, 0x20
        self.bus = FakeBus(1)
        self.bus.set_mcp_gpio(self.mcp_address, 0xFFFF)  # idle: all inputs pulled high
        patcher = patch('controls_mcp.SMBus', return_value=self.bus)
        patcher.start()
        self.addCleanup(patcher.stop)
        for target, value in (('controls_mcp.config.INPUT_I2C_PORT', 1),
                              ('controls_mcp.config.MCP23017_ADDRESS', self.mcp_address),
                              ('controls_mcp.config.KEYPAD_ADDRESS', self.keypad_address),
                              ('controls_mcp.config.DEBUG', False)):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def open(self, emit):
        controls = controls_mcp.open_controls(emit)
        self.addCleanup(controls.close)
        return controls

    def test_left_rotation_emits_signed_steps(self):
        events, ready = [], threading.Event()

        def emit(event, value=None):
            events.append((event, value))
            if event == 'left_rotate':
                ready.set()

        self.open(emit)
        # Validated positive sequence (see rotary_clock.py): 11 -> 01 -> 00 -> 10 -> 11.
        for state in (0b01, 0b00, 0b10, 0b11):
            gpio = (0xFFFF & ~(0b11 << 14)) | (state << 14)
            self.bus.set_mcp_gpio(self.mcp_address, gpio)
            time.sleep(0.01)
        self.assertTrue(ready.wait(2))
        self.assertIn(('left_rotate', 1), events)
        self.assertNotIn(('right_rotate', 1), events)

    def test_key_press_emits_key_event(self):
        events, ready = [], threading.Event()

        def emit(event, value=None):
            events.append((event, value))
            if event == 'key':
                ready.set()

        self.open(emit)
        self.bus.pressed = (0, 0)  # top-left key: '1'
        self.assertTrue(ready.wait(2))
        self.assertIn(('key', '1'), events)

    def test_right_button_press_is_debounced(self):
        events, ready = [], threading.Event()

        def emit(event, value=None):
            events.append((event, value))
            if event == 'right_press':
                ready.set()

        self.open(emit)
        # Pull the right button (PA2, bit 2) low and hold it past the debounce window.
        self.bus.set_mcp_gpio(self.mcp_address, 0xFFFF & ~(1 << 2))
        self.assertTrue(ready.wait(2))
        self.assertEqual(events.count(('right_press', None)), 1)

    def test_i2c_error_is_reported_without_crashing_the_thread(self):
        events, ready = [], threading.Event()

        def emit(event, value=None):
            events.append((event, value))
            if event == 'error':
                ready.set()

        controls = self.open(emit)

        def failing(address, register):
            raise OSError('I2C down')

        self.bus.read_byte_data_override = failing
        self.assertTrue(ready.wait(2))
        self.assertTrue(controls.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
