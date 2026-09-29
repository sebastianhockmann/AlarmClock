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
