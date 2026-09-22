import signal
import unittest
from unittest.mock import Mock, patch

import alarm_clock


class StartupTests(unittest.TestCase):
    def test_missing_button_backend_does_not_stop_clock(self):
        for error in (OSError(22, 'Invalid argument'), ImportError('No GPIO backend')):
            with self.subTest(error=error):
                lcd = Mock()
                handlers = {}
                def register(number, handler):
                    handlers[number] = handler
                def stop_after_tick(seconds):
                    handlers[signal.SIGTERM](signal.SIGTERM, None)
                with patch.dict('sys.modules', {'lcd': lcd}), \
                     patch('alarm_clock.config.INPUT_MODULE', None), \
                     patch('alarm_clock.config.LEGACY_BUTTON_ENABLED', True), \
                     patch('button.init_button', side_effect=error), \
                     patch('alarm_clock.signal.signal', side_effect=register), \
                     patch('alarm_clock.time.sleep', side_effect=stop_after_tick), \
                     patch('alarm_clock.AudioPlayer') as player, \
                     patch('alarm_clock.WLEDManager') as wled, \
                     patch('alarm_clock.ClockController') as controller, \
                     patch('builtins.print') as report:
                    controller.return_value.message.return_value = 'Guten Morgen'
                    alarm_clock.main()
                    controller.return_value.tick.assert_called_once()
                    lcd.lcd_show.assert_called_once()
                    lcd.lcd_close.assert_called_once()
                    player.return_value.stop.assert_called_once()
                    wled.return_value.close.assert_called_once()
                    self.assertIn('ohne diesen Taster', report.call_args.args[0])

    def test_missing_input_module_does_not_stop_clock(self):
        lcd = Mock()
        handlers = {}
        def register(number, handler):
            handlers[number] = handler
        def stop_after_tick(seconds):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
        with patch.dict('sys.modules', {'lcd': lcd}), \
             patch('alarm_clock.config.INPUT_MODULE', 'nonexistent_input_module'), \
             patch('alarm_clock.signal.signal', side_effect=register), \
             patch('alarm_clock.time.sleep', side_effect=stop_after_tick), \
             patch('alarm_clock.AudioPlayer') as player, \
             patch('alarm_clock.WLEDManager') as wled, \
             patch('alarm_clock.ClockController') as controller, \
             patch('builtins.print') as report:
            controller.return_value.message.return_value = 'Guten Morgen'
            alarm_clock.main()
            controller.return_value.tick.assert_called_once()
            lcd.lcd_close.assert_called_once()
            player.return_value.stop.assert_called_once()
            wled.return_value.close.assert_called_once()
            self.assertIn('nicht verfügbar', report.call_args.args[0])
