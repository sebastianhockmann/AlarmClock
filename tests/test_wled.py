import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import settings
from lighting import WLEDManager
from helpers import TempSettingsTestCase


class WLEDTests(TempSettingsTestCase):
    def setUp(self):
        super().setUp()
        self.http = patch('lighting.urlopen').start()
        self.addCleanup(patch.stopall)
        self.http.return_value.__enter__.return_value.read.return_value = b'{"state":{"on":true}}'

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

    def test_invalid_response_is_unavailable(self):
        for body in (b'', b'<html>error</html>', b'[]', b'{}', b'{"state":false}'):
            self.http.return_value.__enter__.return_value.read.return_value = body
            self.assertFalse(WLEDManager(host='wled.local').is_available())

    def test_disabled_never_opens_network(self):
        manager = WLEDManager(host='wled.local', enabled=False)
        self.assertFalse(manager.is_available())
        self.assertIsNone(manager._request({'on': True}))
        self.assertIsNone(manager.fetch('effects'))
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


if __name__ == '__main__':
    unittest.main()
