"""ipc (Steuerkanal), integrations (HTTP/Home Assistant/Alexa) und weather."""
import json
import stat
import threading
import time
import unittest
from unittest.mock import Mock, patch

import integrations
import ipc
import settings
import weather
from helpers import TempSettingsTestCase


class IpcTests(unittest.TestCase):
    def test_round_trip_status_and_whitelist(self):
        received = []
        server = ipc.CommandServer(lambda event, value=None: received.append((event, value)),
                                   status=lambda: {'playing': True}, host='127.0.0.1', port=0)
        self.addCleanup(server.close)
        ipc.send('play_file', 'mp3/a.mp3', address=server.address)
        self.assertEqual(received, [('play_file', 'mp3/a.mp3')])
        self.assertEqual(ipc.status(address=server.address), {'playing': True})
        with self.assertRaises(ValueError):
            ipc.send('right_hold', address=server.address)

    def test_unreachable_clock(self):
        self.assertIsNone(ipc.status(timeout=0.1, address=('127.0.0.1', 9)))
        with self.assertRaises(OSError):
            ipc.send('stop_audio', timeout=0.1, address=('127.0.0.1', 9))


class IntegrationTests(TempSettingsTestCase):
    def ok_response(self, opener):
        response = Mock(status=200)
        opener.return_value.__enter__.return_value = response

    def test_http_trigger(self):
        with patch('integrations.urlopen') as opener:
            self.ok_response(opener)
            self.assertEqual(integrations.run_sync({'type': 'http', 'url': 'https://trigger.example/x',
                                                    'method': 'GET'}), (True, 'HTTP 200'))
            self.assertEqual(opener.call_args.args[0].full_url, 'https://trigger.example/x')

    def test_home_assistant_needs_url_and_sends_token(self):
        action = {'type': 'home_assistant', 'service': 'light.toggle', 'entity_id': 'light.deckenlampe'}
        with patch('integrations.urlopen') as opener:
            self.assertEqual(integrations.run_sync(action), (False, 'Home Assistant nicht eingerichtet'))
            opener.assert_not_called()
            settings.save('home_assistant', {'url': 'http://ha.local:8123/', 'token': 'secret'})
            self.ok_response(opener)
            self.assertTrue(integrations.run_sync(action)[0])
            request = opener.call_args.args[0]
        self.assertEqual(request.full_url, 'http://ha.local:8123/api/services/light/toggle')
        self.assertEqual(json.loads(request.data), {'entity_id': 'light.deckenlampe'})
        self.assertEqual(request.headers['Authorization'], 'Bearer secret')

    def test_ha_color_cycles_from_current_lamp_color(self):
        integrations._last_color.clear()
        settings.save('home_assistant', {'url': 'http://ha.local:8123', 'token': 'secret'})
        action = settings.validate_action({'type': 'ha_color', 'entity_id': 'light.h60a1',
                                           'colors': 'rot, gelb, Warmweiss'})
        self.assertEqual(action['colors'], ['rot', 'gelb', 'warmweiss'])
        calls = []

        def fake_state(state, **attributes):
            return patch('integrations.home_assistant_state',
                         return_value=({'state': state, 'attributes': attributes}, ''))

        with patch('integrations.home_assistant',
                   side_effect=lambda *args: calls.append(args) or (True, 'HTTP 200')):
            # gelb (leicht abweichend gemeldet) -> naechste ist 2700K
            with fake_state('on', color_mode='rgb', rgb_color=[255, 250, 3]):
                self.assertEqual(integrations.run_sync(action), (True, 'warmweiss'))
            # Weisston -> wieder von vorn
            with fake_state('on', color_mode='color_temp', color_temp_kelvin=2702):
                self.assertEqual(integrations.run_sync(action), (True, 'rot'))
            # aus: Home Assistant meldet keine Farbe, weiter nach der zuletzt gesetzten
            with fake_state('off'):
                self.assertEqual(integrations.run_sync(action), (True, 'gelb'))
        self.assertEqual(calls, [
            ('light.turn_on', 'light.h60a1', {'color_temp_kelvin': 2700}),
            ('light.turn_on', 'light.h60a1', {'rgb_color': [255, 0, 0]}),
            ('light.turn_on', 'light.h60a1', {'rgb_color': [255, 255, 0]}),
        ])

    def test_ha_color_steps_on_when_pressed_quickly(self):
        # Die Lampe meldet kurz nach dem Umschalten noch die alte Farbe (rot).
        integrations._last_color.clear()
        action = {'type': 'ha_color', 'entity_id': 'light.y', 'colors': ['rot', 'gelb', 'blau']}
        stale = ({'state': 'on', 'attributes': {'color_mode': 'rgb', 'rgb_color': [255, 0, 0]}}, '')
        with patch('integrations.home_assistant_state', return_value=stale) as state, \
             patch('integrations.home_assistant', return_value=(True, 'HTTP 200')):
            results = [integrations.run_sync(action)[1] for _ in range(3)]
            self.assertEqual(state.call_count, 1)
            # Nach laengerer Pause zaehlt wieder die gemeldete Farbe.
            with patch('integrations.time.monotonic',
                       return_value=integrations._last_color['light.y'][1] + 60):
                results.append(integrations.run_sync(action)[1])
        self.assertEqual(results, ['gelb', 'blau', 'rot', 'gelb'])

    def test_ha_color_rejects_unknown_colors(self):
        with self.assertRaises(ValueError):
            settings.validate_action({'type': 'ha_color', 'entity_id': 'light.x', 'colors': 'rot, lachs'})

    def test_ha_alexa_sends_text_command_to_device(self):
        settings.save('home_assistant', {'url': 'http://ha.local:8123', 'token': 'secret'})
        action = settings.validate_action({'type': 'ha_alexa', 'device_id': 'bff71067de175dbdf5c1836a959bf7e2',
                                           'text': 'Stopp'})
        with patch('integrations.urlopen') as opener:
            self.ok_response(opener)
            self.assertTrue(integrations.run_sync(action)[0])
            request = opener.call_args.args[0]
        self.assertEqual(request.full_url, 'http://ha.local:8123/api/services/alexa_devices/send_text_command')
        self.assertEqual(json.loads(request.data), {'device_id': 'bff71067de175dbdf5c1836a959bf7e2',
                                                    'text_command': 'Stopp'})
        with self.assertRaises(ValueError):
            settings.validate_action({'type': 'ha_alexa', 'device_id': 'Maus', 'text': 'Stopp'})

    def test_alexa_uses_script_without_shell(self):
        script = self.dir / 'alexa.sh'
        script.write_text('#!/bin/sh\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        settings.save('alexa', {'default_device': 'Echo Kinderzimmer'})
        with patch('integrations.config.ALEXA_SCRIPT', str(script)), \
             patch('integrations.subprocess.run') as run:
            run.return_value = Mock(returncode=0, stdout='', stderr='')
            ok, _ = integrations.run_sync({'type': 'alexa', 'device': '', 'command': 'text',
                                           'text': 'spiele Amazon Music; rm -rf /'})
            self.assertTrue(ok)
            self.assertEqual(run.call_args.args[0], [str(script), '-d', 'Echo Kinderzimmer', '-e',
                                                     'textcommand:spiele Amazon Music; rm -rf /'])
            integrations.run_sync({'type': 'alexa', 'device': 'Echo Wohnzimmer', 'command': 'weather', 'text': ''})
            self.assertEqual(run.call_args.args[0][2:], ['Echo Wohnzimmer', '-e', 'weather'])

    def test_alexa_without_script_reports_it(self):
        with patch('integrations.config.ALEXA_SCRIPT', '/nonexistent/alexa.sh'):
            self.assertEqual(integrations.run_sync({'type': 'alexa', 'command': 'weather'}),
                             (False, 'alexa_remote_control.sh fehlt'))

    def test_run_reports_failures_in_the_background(self):
        reported = threading.Event()
        messages = []
        with patch('integrations.run_sync', return_value=(False, 'HTTP-Fehler 500')):
            label = integrations.run({'type': 'http', 'url': 'http://x', 'label': 'Lampe'},
                                     lambda message: (messages.append(message), reported.set()))
            self.assertTrue(reported.wait(2))
        self.assertEqual(label, 'Lampe')
        self.assertEqual(messages, ['HTTP-Fehler 500'])


class LampDimTests(TempSettingsTestCase):
    def test_steps_are_round_and_never_switch_off(self):
        self.assertEqual(integrations.dim_step(51, 1), 60)
        self.assertEqual(integrations.dim_step(21, -1), 10)
        self.assertEqual(integrations.dim_step(10, -1), 1)
        self.assertEqual(integrations.dim_step(1, -3), 1)
        self.assertEqual(integrations.dim_step(1, 1), 10)
        self.assertEqual(integrations.dim_step(0, 1), 10)   # aus -> 10 %
        self.assertEqual(integrations.dim_step(95, 2), 100)

    def test_dimmer_sends_only_the_newest_value(self):
        sent, done = [], threading.Event()
        release = threading.Event()

        def slow(service, entity_id, data):
            release.wait(2)
            sent.append(data['brightness_pct'])
            if data['brightness_pct'] == 40:
                done.set()
            return True, 'HTTP 200'

        with patch('integrations.home_assistant', side_effect=slow):
            dimmer = integrations.LampDimmer()
            dimmer.set('light.x', 10)   # wird gerade gesendet
            time.sleep(0.05)
            for percent in (20, 30, 40):
                dimmer.set('light.x', percent)
            release.set()
            self.assertTrue(done.wait(2))
        self.assertEqual(sent, [10, 40])
        self.assertEqual(dimmer.levels['light.x'], 40)


class AlexaSpeakerTests(TempSettingsTestCase):
    def test_commands_go_out_in_order_and_failures_are_reported(self):
        failed = threading.Event()
        sent, errors = [], []

        def send(device_id, text):
            sent.append((device_id, text))
            if text == 'spiele X':
                return False, 'Nicht erreichbar'
            return True, 'HTTP 200'

        speaker = integrations.AlexaSpeaker(send=send)
        self.assertFalse(speaker.say('Lautstärke 2'))  # kein Echo eingestellt
        echo = 'bff71067de175dbdf5c1836a959bf7e2'
        settings.save('alexa', {'default_device': '', 'ha_device_id': echo})
        self.assertTrue(speaker.say('Lautstärke 2'))
        self.assertTrue(speaker.say('spiele X', on_error=lambda m: (errors.append(m), failed.set())))
        self.assertTrue(failed.wait(2))
        self.assertEqual(sent, [(echo, 'Lautstärke 2'), (echo, 'spiele X')])
        self.assertEqual(errors, ['Nicht erreichbar'])


class WeatherTests(TempSettingsTestCase):
    SAMPLE = {'current': {'temperature_2m': 11.6, 'weather_code': 3},
              'daily': {'temperature_2m_min': [8.9], 'temperature_2m_max': [18.6],
                        'precipitation_probability_max': [40], 'weather_code': [61]}}

    def test_summary(self):
        self.assertEqual(weather.summary(self.SAMPLE), 'Jetzt 12C, heute 9-19C, Regenrisiko 40%, Regen')
        with self.assertRaises(ValueError):
            weather.summary({})

    def test_service_needs_a_location_and_caches(self):
        service = weather.WeatherService(settings, fetcher=Mock(return_value=self.SAMPLE))
        done = Mock()
        self.assertFalse(service.request(done))
        done.assert_called_once_with('Wetter: Ort fehlt (Web)')
        settings.save('weather', {'location': 'Hamburg', 'latitude': 53.55, 'longitude': 10.0})
        finished = threading.Event()
        self.assertTrue(service.request(lambda text: finished.set()))
        self.assertTrue(finished.wait(2))
        self.assertTrue(service.cached().startswith('Jetzt 12C'))
        service.fetcher.assert_called_once_with(53.55, 10.0)


if __name__ == '__main__':
    unittest.main()
