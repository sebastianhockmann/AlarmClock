import errno
from datetime import date, datetime
import socket
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError
import integrations
import network
import programs
import scheduler
import school_calendar
import settings
from controller import ClockController
from helpers import TempSettingsTestCase

MORNING = {'label': 'Morgenlicht', 'start': '06:00', 'end': '06:40', 'days': [0, 1, 2, 3, 4],
           'calendar': 'school', 'effect': 'solid', 'brightness_start': 1, 'brightness_end': 81,
           'ramp_minutes': 20}
EVENING = {'label': 'Abendlicht', 'start': '20:30', 'end': '21:00', 'days': [0, 1, 2, 3, 4, 5, 6],
           'calendar': 'before_school', 'effect': 'abend_glut', 'brightness_start': 40,
           'brightness_end': 4, 'ramp_minutes': 30}


class CalendarTests(TempSettingsTestCase):
    def test_easter_and_thuringian_holidays(self):
        self.assertEqual(school_calendar.easter(2026), date(2026, 4, 5))
        self.assertEqual(school_calendar.easter(2027), date(2027, 3, 28))
        holidays = school_calendar.public_holidays(2026)
        self.assertEqual(holidays[date(2026, 5, 14)], 'Himmelfahrt')
        self.assertEqual(holidays[date(2026, 9, 20)], 'Weltkindertag')
        self.assertEqual(holidays[date(2026, 10, 31)], 'Reformationstag')
        self.assertEqual(len(holidays), 11)

    def test_free_reasons(self):
        self.assertIsNone(school_calendar.free_reason(date(2026, 11, 3)))  # Dienstag
        self.assertEqual(school_calendar.free_reason(date(2026, 11, 7)), 'Wochenende')
        self.assertEqual(school_calendar.free_reason(date(2026, 10, 14)), 'Herbstferien')
        self.assertEqual(school_calendar.free_reason(date(2026, 12, 25)), '1. Weihnachtstag')
        self.assertEqual(school_calendar.free_reason(date(2026, 5, 15)), 'Schulfreier Tag')
        settings.save('calendar', {'free_days': '2026-11-20, 2026-11-23'})
        self.assertEqual(settings.get('calendar')['free_days'], ['2026-11-20', '2026-11-23'])
        self.assertEqual(school_calendar.free_reason(date(2026, 11, 20)), 'Freier Tag')
        with self.assertRaises(ValueError):
            settings.save('calendar', {'free_days': ['20.11.2026']})

    def test_rules(self):
        friday, sunday = date(2026, 11, 6), date(2026, 11, 8)
        self.assertTrue(school_calendar.matches('school', friday))
        self.assertFalse(school_calendar.matches('before_school', friday))
        self.assertTrue(school_calendar.matches('before_school', sunday))
        self.assertTrue(school_calendar.matches('free', sunday))
        self.assertTrue(school_calendar.matches('all', sunday))
        # Letzter Ferientag (Sa 24.10.) -> Sonntagabend vor Schule.
        self.assertTrue(school_calendar.matches('before_school', date(2026, 10, 25)))
        self.assertFalse(school_calendar.matches('before_school', date(2026, 10, 18)))

    def test_cache_and_seed_are_merged(self):
        school_calendar.write_periods(school_calendar.CACHE_FILE, school_calendar.parse_periods(
            [{'startDate': '2029-02-05', 'endDate': '2029-02-10',
              'name': [{'language': 'DE', 'text': 'Winterferien'}]}]))
        self.assertEqual(school_calendar.free_reason(date(2029, 2, 6)), 'Winterferien')
        self.assertEqual(school_calendar.known_until(), date(2029, 2, 10))
        self.assertEqual(school_calendar.free_reason(date(2026, 10, 14)), 'Herbstferien')

    def test_refresh_failure_keeps_old_data(self):
        with patch('school_calendar.urlopen', side_effect=URLError(OSError(113, 'No route'))):
            ok, message = school_calendar.refresh(date(2026, 11, 3))
        self.assertFalse(ok)
        self.assertIn('nicht abrufbar', message)
        self.assertEqual(school_calendar.free_reason(date(2026, 10, 14)), 'Herbstferien')

    def test_school_alarm_skips_holidays(self):
        settings.save('alarms', [{'id': 'schule', 'label': 'Schule', 'time': '06:15',
                                  'days': [0, 1, 2, 3, 4], 'calendar': 'school'}])
        alarms = scheduler.AlarmScheduler()
        self.assertEqual(alarms.due(datetime(2026, 10, 12, 6, 15)), [])  # Herbstferien
        self.assertEqual(len(alarms.due(datetime(2026, 11, 2, 6, 15))), 1)
        moment, _ = scheduler.next_alarm(datetime(2026, 10, 10, 12, 0))
        self.assertEqual(moment, datetime(2026, 10, 26, 6, 15))
        self.assertEqual(scheduler.describe_days([0, 1, 2, 3, 4], 'school'), 'Mo-Fr, Schultage')


class ProgramTests(TempSettingsTestCase):
    def setUp(self):
        super().setUp()
        settings.save('programs', [MORNING, EVENING])
        self.send = Mock()
        self.runner = programs.ProgramRunner(self.send)

    def test_active_window_and_calendar(self):
        self.assertEqual(programs.active(datetime(2026, 11, 3, 6, 10))[0]['label'], 'Morgenlicht')
        self.assertIsNone(programs.active(datetime(2026, 11, 3, 6, 40)))
        self.assertIsNone(programs.active(datetime(2026, 10, 13, 6, 10)))  # Ferien
        self.assertIsNone(programs.active(datetime(2026, 11, 6, 20, 45)))  # Freitagabend
        self.assertEqual(programs.active(datetime(2026, 11, 8, 20, 45))[0]['label'], 'Abendlicht')
        upcoming = programs.upcoming(datetime(2026, 11, 6, 12, 0))
        self.assertEqual([start for start, _, _ in upcoming],
                         [datetime(2026, 11, 8, 20, 30), datetime(2026, 11, 9, 6, 0)])

    def test_window_across_midnight_uses_the_start_day(self):
        settings.save('programs', [{**EVENING, 'start': '23:30', 'end': '00:30'}])
        self.assertIsNotNone(programs.active(datetime(2026, 11, 9, 0, 10)))  # So 23:30 gestartet
        self.assertIsNone(programs.active(datetime(2026, 11, 7, 0, 10)))  # Fr 23:30: kein Schultag danach

    def test_ramp_then_off(self):
        self.assertEqual(self.runner.tick(datetime(2026, 11, 3, 6, 0), 0), 'start')
        first = self.send.call_args.args[0]
        self.assertEqual((first['bri'], first['on'], first['seg'][0]['fx']), (3, True, 0))
        self.runner.tick(datetime(2026, 11, 3, 6, 10), 600)  # halbe Rampe: 41 %
        self.assertEqual(self.send.call_args.args[0]['bri'], round(41 * 255 / 100))
        self.assertEqual(self.send.call_args.args[0]['tt'], 20)
        self.assertEqual(self.runner.label, 'Morgenlicht')
        self.assertEqual(self.runner.tick(datetime(2026, 11, 3, 6, 40), 2400), 'end')
        self.assertEqual(self.send.call_args.args[0], {'on': False, 'tt': 50})
        self.assertIsNone(self.runner.label)

    def test_evening_dims_down_and_restart_resumes(self):
        self.runner.tick(datetime(2026, 11, 8, 20, 45), 0)  # Neustart mitten im Fenster
        self.assertEqual(self.send.call_args.args[0]['bri'], round(22 * 255 / 100))
        self.runner.tick(datetime(2026, 11, 8, 20, 59), 840)
        self.assertEqual(self.send.call_args.args[0]['bri'], round(5.2 * 255 / 100))

    def test_manual_light_wins_but_end_still_switches_off(self):
        self.runner.tick(datetime(2026, 11, 3, 6, 0), 0)
        self.runner.override()
        self.send.reset_mock()
        self.runner.tick(datetime(2026, 11, 3, 6, 10), 600)
        self.send.assert_not_called()
        self.runner.tick(datetime(2026, 11, 3, 6, 40), 2400)
        self.send.assert_called_once_with({'on': False, 'tt': 50})

    def test_controller_pauses_for_wake_light_and_left_knob_overrides(self):
        settings.save('wake', {**settings.get('wake'), 'effect': 'morgenlicht'})
        settings.save('alarms', [{'label': 'Schule', 'time': '06:15', 'days': [1], 'calendar': 'school'}])
        clock = ClockController(Mock(volume=50, is_playing=False, finished=False), self.send,
                                emit=Mock())
        clock.tick(datetime(2026, 11, 3, 6, 5), 0)
        self.assertEqual(clock.notice, 'Morgenlicht')
        self.assertEqual(clock.status()['program'], 'Morgenlicht')
        clock.tick(datetime(2026, 11, 3, 6, 15), 600)  # Wecker mit eigenem Licht
        wake_state = self.send.call_args.args[0]
        clock.tick(datetime(2026, 11, 3, 6, 15, 5), 605)
        self.assertEqual(self.send.call_args.args[0]['seg'], wake_state['seg'])
        clock.handle('left_press', None, 606)
        self.assertTrue(clock.programs.manual)


class NetworkTests(TempSettingsTestCase):
    def test_not_connected_errors(self):
        self.assertTrue(network.not_connected(URLError(OSError(errno.EHOSTUNREACH, 'No route'))))
        self.assertTrue(network.not_connected(URLError(socket.gaierror(-3, 'DNS'))))
        self.assertFalse(network.not_connected(URLError(socket.timeout('timed out'))))
        self.assertFalse(network.not_connected(TimeoutError()))
        self.assertEqual(network.endpoint('http://10.150.1.31:8123/api'), ('10.150.1.31', 8123))
        self.assertEqual(network.endpoint('https://example.org'), ('example.org', 443))

    def test_wait_reachable_polls_until_timeout(self):
        probe = Mock(side_effect=[False, False, True])
        self.assertTrue(network.wait_reachable('h', 80, 10, probe=probe, sleep=Mock()))
        self.assertFalse(network.wait_reachable('h', 80, 0, probe=Mock(return_value=False),
                                                sleep=Mock()))

    def test_http_call_waits_for_the_network_after_errno_113(self):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        unreachable = URLError(OSError(errno.EHOSTUNREACH, 'No route to host'))
        with patch('integrations.urlopen', side_effect=[unreachable, response]) as opener, \
             patch('integrations.network.wait_reachable', return_value=True) as wait:
            self.assertEqual(integrations.http_call('http://ha.local:8123/api'), (True, 'HTTP 200'))
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(wait.call_args.args[:2], ('ha.local', 8123))

    def test_http_call_does_not_repeat_after_a_timeout(self):
        with patch('integrations.urlopen', side_effect=URLError(socket.timeout('timed out'))) as opener, \
             patch('integrations.network.wait_reachable') as wait:
            ok, message = integrations.http_call('http://ha.local:8123/api', 'POST', '{}')
        self.assertFalse(ok)
        self.assertEqual(opener.call_count, 1)
        wait.assert_not_called()

    def test_http_call_gives_up_when_the_network_stays_away(self):
        unreachable = URLError(OSError(errno.EHOSTUNREACH, 'No route to host'))
        with patch('integrations.urlopen', side_effect=unreachable), \
             patch('integrations.network.wait_reachable', return_value=False):
            ok, message = integrations.http_call('http://ha.local:8123/api')
        self.assertFalse(ok)
        self.assertIn('No route', message)

    def test_monitor_reports_outage_and_recovery(self):
        report = Mock()
        states = iter([True, False, True])
        with patch('network.threading.Thread'):
            monitor = network.NetworkMonitor(lambda: [('ha', 8123)], report=report,
                                             probe=lambda host, port: next(states))
        self.assertTrue(monitor.check())
        report.assert_not_called()
        self.assertFalse(monitor.check())
        self.assertIn('Netzwerk weg', report.call_args.args[0])
        self.assertTrue(monitor.check())
        self.assertIn('wieder da', report.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
