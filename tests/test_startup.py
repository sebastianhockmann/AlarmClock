import signal
import unittest
from unittest.mock import Mock, patch

import alarm_clock
from helpers import TempSettingsTestCase


class StartupTests(TempSettingsTestCase):
    def run_main(self):
        lcd = Mock()
        handlers = {}

        def register(number, handler):
            handlers[number] = handler

        def stop_after_tick(seconds):
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        with patch.dict('sys.modules', {'lcd': lcd}), \
             patch('alarm_clock.signal.signal', side_effect=register), \
             patch('alarm_clock.time.sleep', side_effect=stop_after_tick), \
             patch('alarm_clock.AudioPlayer') as player, \
             patch('alarm_clock.WLEDManager') as wled, \
             patch('alarm_clock.ipc.CommandServer') as server, \
             patch('alarm_clock.ClockController') as controller, \
             patch('builtins.print') as report:
            controller.return_value.message.return_value = 'Guten Morgen'
            controller.return_value.force_backlight = False
            alarm_clock.main()
            controller.return_value.tick.assert_called_once()
            lcd.lcd_show.assert_called_once()
            lcd.lcd_close.assert_called_once()
            player.return_value.stop.assert_called_once()
            wled.return_value.close.assert_called_once()
            server.return_value.close.assert_called_once()
            return report

    def test_missing_button_backend_does_not_stop_clock(self):
        for error in (OSError(22, 'Invalid argument'), ImportError('No GPIO backend')):
            with self.subTest(error=error):
                with patch('alarm_clock.config.INPUT_MODULE', None), \
                     patch('alarm_clock.config.LEGACY_BUTTON_ENABLED', True), \
                     patch('button.init_button', side_effect=error):
                    report = self.run_main()
                self.assertIn('ohne diesen Taster', report.call_args.args[0])

    def test_missing_input_module_does_not_stop_clock(self):
        with patch('alarm_clock.config.INPUT_MODULE', 'nonexistent_input_module'):
            report = self.run_main()
        self.assertIn('nicht verfügbar', report.call_args.args[0])

    def test_events_are_routed_to_the_controller(self):
        with patch('alarm_clock.config.INPUT_MODULE', None), \
             patch('alarm_clock.chime.play_click') as click, \
             patch('alarm_clock.open_inputs', side_effect=lambda emit: (emit('key', '1'), [])[1]):
            self.run_main()
        click.assert_called_once()


if __name__ == '__main__':
    unittest.main()


class ControlsTests(unittest.TestCase):
    """Rechter Drehknopf ohne I2C: Treiberlogik mit einer eingespeisten Bitfolge."""

    def make(self):
        import controls_mcp
        controls = controls_mcp.MCPControls.__new__(controls_mcp.MCPControls)
        controls.events = []
        controls.emit = lambda event, value=None: controls.events.append((event, value))
        controls.right_button = controls_mcp._DebouncedButton(True)
        controls.right_pressed_at, controls.right_hold_fired, controls.right_turned = None, False, False
        controls.left_decoder = controls_mcp._QuadDecoder(0)
        controls.right_decoder = controls_mcp._QuadDecoder(0)
        controls.left_button = controls_mcp._DebouncedButton(True)
        return controls_mcp, controls

    def feed(self, controls_mcp, controls, states, pressed, now):
        # Encoderbits A/B plus Taster (aktiv low) als GPIO-Wort, links Ruhelage.
        left_idle = 1 << controls_mcp.LEFT['button']
        for state in states:
            word = left_idle | state | (0 if pressed else 1 << controls_mcp.RIGHT['button'])
            controls._read_mcp = lambda word=word: word
            with patch('controls_mcp.time.monotonic', return_value=now):
                controls._poll_encoders()
            now += 0.05
        return now

    def test_turning_while_pressed_is_its_own_event(self):
        controls_mcp, controls = self.make()
        turn = [0b01, 0b11, 0b10, 0b00]
        with patch('controls_mcp.config.RIGHT_REVERSE', False):
            now = self.feed(controls_mcp, controls, [0b00, 0b00], True, 0.0)   # druecken
            now = self.feed(controls_mcp, controls, turn, True, now)
            now = self.feed(controls_mcp, controls, [0b00, 0b00], False, now + 5)  # loslassen
            self.feed(controls_mcp, controls, turn, False, now)
        names = [event for event, _ in controls.events]
        self.assertIn('right_press_rotate', names)
        self.assertNotIn('right_press', names)
        self.assertNotIn('right_hold', names)
        self.assertEqual(names[-1], 'right_rotate')

    def test_direction_can_be_reversed(self):
        controls_mcp, controls = self.make()
        turn = [0b01, 0b11, 0b10, 0b00]
        with patch('controls_mcp.config.RIGHT_REVERSE', False):
            self.feed(controls_mcp, controls, turn, False, 0.0)
        with patch('controls_mcp.config.RIGHT_REVERSE', True):
            self.feed(controls_mcp, controls, turn, False, 1.0)
        values = [value for event, value in controls.events if event == 'right_rotate']
        half = len(values) // 2
        self.assertTrue(half and len(set(values[:half])) == 1)
        self.assertEqual(values[half:], [-value for value in values[:half]])

    def test_keypad_table_matches_the_measured_wiring(self):
        # Gemessen 2026-09-29: der Reihe nach gedrueckt 1 2 3 A 4 ... D, der Scan
        # meldete die Positionen, die mit der alten Tabelle "123A/456B/..." so hiessen:
        import controls_mcp
        old = ("123A", "456B", "789C", "*0#D")
        position = {old[r][c]: (r, c) for r in range(4) for c in range(4)}
        detected = [controls_mcp.KEYS[r][c] for r, c in (position[key] for key in 'DCBA#9630852*741')]
        self.assertEqual(''.join(detected), '123A456B789C*0#D')
