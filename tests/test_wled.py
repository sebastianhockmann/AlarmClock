import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import settings
import webserver
from lighting import WLEDManager


class WLEDTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'settings.json'
        for target in ('settings.SETTINGS_FILE', 'webserver.SETTINGS_FILE'):
            patcher = patch(target, self.path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.http = patch('lighting.urlopen').start()
        self.addCleanup(patch.stopall)
        self.http.return_value.__enter__.return_value.read.return_value = b'{"state":{"on":true}}'
        self.client = webserver.app.test_client()

    def test_status_hosts_and_timeout(self):
        for host in ('wled.local', 'alarm-led.local', '192.168.178.50'):
            manager = WLEDManager(host=host, timeout=2)
            self.assertTrue(manager.is_available())
            self.assertEqual(self.http.call_args.args[0].full_url, f'http://{host}/json')
            self.assertEqual(self.http.call_args.kwargs['timeout'], 2)
            self.assertIsNone(manager.last_error)

    def test_failures_and_recovery(self):
        manager = WLEDManager(host='wled.local')
        for error, message in (
                (URLError('DNS failure'), 'Connection failed'),
                (ConnectionRefusedError(), 'Connection failed'),
                (TimeoutError(), 'Connection timeout'),
                (URLError(TimeoutError()), 'Connection timeout'),
                (HTTPError('http://wled.local/json', 503, 'busy', {}, None), 'HTTP error 503')):
            self.http.side_effect = error
            self.assertFalse(manager.is_available())
            self.assertEqual(manager.last_error, message)
        self.http.side_effect = None
        self.assertTrue(manager.is_available())
        self.assertIsNone(manager.last_error)

    def test_invalid_response_is_unavailable(self):
        for body in (b'', b'<html>error</html>', b'[]', b'{}', b'{"state":false}'):
            self.http.return_value.__enter__.return_value.read.return_value = body
            self.assertFalse(WLEDManager(host='wled.local').is_available())

    def test_disabled_never_opens_network(self):
        manager = WLEDManager(host='wled.local', enabled=False)
        self.assertFalse(manager.is_available())
        self.assertIsNone(manager._request({'on': True}))
        self.http.assert_not_called()

    def test_live_configuration_reload(self):
        manager = WLEDManager()
        settings.save_wled_settings(True, 'alarm-led.local', 1.5)
        self.assertTrue(manager.is_available())
        self.assertEqual(self.http.call_args.args[0].full_url, 'http://alarm-led.local/json')
        self.assertEqual(self.http.call_args.kwargs['timeout'], 1.5)
        settings.save_wled_settings(False, 'alarm-led.local', 1.5)
        self.http.reset_mock()
        self.assertFalse(manager.is_available())
        self.http.assert_not_called()

    def test_commands_do_not_block_and_queue_keeps_latest(self):
        entered, release, final = threading.Event(), threading.Event(), threading.Event()
        states = []
        def open_url(request, **kwargs):
            states.append(json.loads(request.data))
            entered.set()
            release.wait(2)
            if len(states) == 2:
                final.set()
            return original
        original = self.http.return_value
        self.http.side_effect = open_url
        manager = WLEDManager(host='wled.local')
        try:
            manager.set_power(True)
            self.assertTrue(entered.wait(1))
            manager.set_brightness(80)
            manager.activate_preset(3)
            self.assertEqual(manager.commands.qsize(), 1)
            release.set()
            self.assertTrue(final.wait(1))
            self.assertEqual(states, [{'on': True}, {'ps': 3}])
        finally:
            release.set()
            manager.close()

    def test_web_persistence_and_alarm_preservation(self):
        settings.write_json(self.path, {'hour': 7, 'minute': 15, 'extra': 42})
        result = self.client.post('/api/wled/settings', data={'host': 'alarm-led.local', 'timeout': '1.5'})
        self.assertEqual(result.status_code, 302)
        self.assertFalse(settings.wled_settings()['enabled'])
        self.assertEqual(settings.alarm_time(), (7, 15))
        self.client.post('/set_alarm', data={'hour': '8', 'minute': '30'})
        self.assertEqual(settings.wled_settings()['host'], 'alarm-led.local')
        self.assertEqual(settings.read_json(self.path)['extra'], 42)
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('deaktiviert', page)

    def test_web_validation(self):
        for value in ('NaN', 'inf', 'no', 0, 31, True):
            result = self.client.post('/api/wled/settings', json={'enabled': True, 'host': 'wled.local', 'timeout': value})
            self.assertEqual(result.status_code, 400)
        for host in ('http://', 'bad host', 'wled.local/json', 'http://user@wled.local', 'wled.local:bad'):
            result = self.client.post('/api/wled/settings', json={'enabled': True, 'host': host, 'timeout': 3})
            self.assertEqual(result.status_code, 400)
        self.assertFalse(self.path.exists())

    def test_web_connection_results(self):
        settings.save_wled_settings(True, 'alarm-led.local', 3)
        self.assertEqual(self.client.get('/api/wled/test').json, {'success': True, 'host': 'alarm-led.local'})
        self.http.side_effect = TimeoutError('private details')
        result = self.client.get('/api/wled/test').json
        self.assertEqual(result, {'success': False, 'host': 'alarm-led.local', 'error': 'Connection timeout'})
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('nicht geprüft', page)

    def test_invalid_file_values_fall_back(self):
        settings.write_json(self.path, {'wled': {'enabled': False, 'host': 'bad host', 'timeout': 'NaN'}})
        self.assertEqual(settings.wled_settings(), {'enabled': False, 'host': 'wled.local', 'timeout': 3})

    def test_alarm_enabled_toggle_persists_and_defaults_true(self):
        self.assertTrue(settings.alarm_enabled())
        result = self.client.post('/set_alarm', data={'hour': '7', 'minute': '0'})
        self.assertEqual(result.status_code, 302)
        self.assertFalse(settings.alarm_enabled())
        self.client.post('/set_alarm', data={'hour': '7', 'minute': '0', 'enabled': 'on'})
        self.assertTrue(settings.alarm_enabled())

    def test_mapping_display_and_delete(self):
        mapping_path = Path(self.path).parent / 'mp3_mapping.json'
        with patch('webserver.MAPPING_FILE', mapping_path):
            self.client.post('/set_mapping', data={'date': '12-11', 'filename': 'xmas/maria.mp3',
                                                    'message': 'Hallo Welt'})
            page = self.client.get('/').get_data(as_text=True)
            self.assertIn('mp3/xmas/maria.mp3', page)
            self.assertIn('Hallo Welt', page)
            self.assertNotIn("{&#39;file&#39;", page)
            self.client.post('/delete_mapping', data={'date': '12-11'})
            self.assertNotIn('12-11', settings.read_json(mapping_path))
