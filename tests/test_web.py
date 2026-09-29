import io
import json
import unittest
from unittest.mock import Mock, patch

import config
import settings
import webserver
from helpers import TempSettingsTestCase


class WebTests(TempSettingsTestCase):
    def setUp(self):
        super().setUp()
        self.client = webserver.app.test_client()
        self.ipc_status = patch('webserver.ipc.status', return_value=None).start()
        self.ipc_send = patch('webserver.ipc.send').start()
        self.addCleanup(patch.stopall)

    def put(self, section, value):
        return self.client.put(f'/api/settings/{section}', json=value)

    def test_page_and_state(self):
        self.assertIn('Weckprogramm', self.client.get('/').get_data(as_text=True))
        state = self.client.get('/api/state').json
        self.assertEqual(state['settings']['alarms'][0]['time'], '06:15')
        self.assertIn('mp3/xmas/maria.mp3', state['music_files'])
        self.assertIsNone(state['clock'])
        self.assertEqual(state['keypad'][3], ['*', '0', '#', 'D'])
        self.assertIn('days_text', state['alarms_view'][0])

    def test_save_and_validation(self):
        result = self.put('alarms', [{'label': 'Schule', 'time': '06:40', 'days': [0, 1, 2, 3, 4]}])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(settings.get('alarms')[0]['label'], 'Schule')
        result = self.put('alarms', [{'time': '99:99', 'days': [0]}])
        self.assertEqual(result.status_code, 400)
        self.assertIn('Uhrzeit', result.json['error'])
        self.assertEqual(self.put('unknown', {}).status_code, 404)
        self.assertEqual(self.client.put('/api/settings/wake', data='x').status_code, 400)

    def test_wled_validation(self):
        for value in ('NaN', 'inf', 'no', 0, 31, True):
            result = self.put('wled', {'enabled': True, 'host': 'wled.local', 'timeout': value})
            self.assertEqual(result.status_code, 400)
        for host in ('http://', 'bad host', 'wled.local/json', 'http://user@wled.local', 'wled.local:bad'):
            result = self.put('wled', {'enabled': True, 'host': host, 'timeout': 3})
            self.assertEqual(result.status_code, 400)
        self.assertFalse(self.settings_path.exists())

    def test_home_assistant_token_is_never_sent_back_and_kept_when_empty(self):
        self.put('home_assistant', {'url': 'http://ha.local:8123', 'token': 'geheim'})
        state = self.client.get('/api/state').json['settings']['home_assistant']
        self.assertEqual(state, {'url': 'http://ha.local:8123', 'token_set': True})
        self.put('home_assistant', {'url': 'http://ha2.local:8123', 'token': ''})
        self.assertEqual(settings.get('home_assistant')['token'], 'geheim')
        self.put('home_assistant', {'url': 'http://ha2.local:8123', 'clear_token': True})
        self.assertEqual(settings.get('home_assistant')['token'], '')

    def test_reset_section(self):
        self.put('alarms_enabled', False)
        self.assertEqual(self.client.delete('/api/settings/alarms_enabled').json['value'], True)

    def test_control_goes_to_the_clock_process(self):
        result = self.client.post('/api/control', json={'event': 'play_random'})
        self.assertEqual(result.status_code, 200)
        self.ipc_send.assert_called_once_with('play_random', None)
        self.assertEqual(self.client.post('/api/control', json={'event': 'shutdown'}).status_code, 400)
        self.ipc_send.side_effect = OSError('Wecker-Prozess nicht erreichbar')
        result = self.client.post('/api/control', json={'event': 'stop_audio'})
        self.assertEqual(result.status_code, 503)
        self.assertIn('alarmclock.service', result.json['error'])

    def test_action_test_validates_before_sending(self):
        self.assertEqual(self.client.post('/api/action/test', json={'type': 'rm'}).status_code, 400)
        self.client.post('/api/action/test', json={'type': 'effect', 'effect': 'solid'})
        self.ipc_send.assert_called_once_with('action', {'type': 'effect', 'effect': 'solid'})
        with patch('webserver.integrations.run_sync', return_value=(False, 'HTTP-Fehler 404')):
            result = self.client.post('/api/action/test?direct=1',
                                      json={'type': 'http', 'url': 'http://x.local/trigger'})
        self.assertFalse(result.json['success'])

    def test_upload_download_and_delete_music(self):
        target = config.MUSIC_DIR / 'unittest_upload.mp3'
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        result = self.client.post('/api/music', data={'file': (io.BytesIO(b'ID3'), 'unittest upload.mp3')},
                                  content_type='multipart/form-data')
        self.assertEqual(result.json['files'], ['mp3/unittest_upload.mp3'])
        again = self.client.post('/api/music', data={'file': (io.BytesIO(b'ID3'), 'unittest_upload.mp3')},
                                 content_type='multipart/form-data')
        self.assertEqual(again.status_code, 409)
        bad = self.client.post('/api/music', data={'file': (io.BytesIO(b'x'), 'x.exe')},
                               content_type='multipart/form-data')
        self.assertEqual(bad.status_code, 400)
        download = self.client.get('/api/music/file?file=mp3/unittest_upload.mp3')
        self.assertEqual(download.data, b'ID3')
        download.close()
        self.assertEqual(self.client.get('/api/music/file?file=config/hardware.json').status_code, 400)
        self.assertEqual(self.client.delete('/api/music?file=mp3/xmas/maria.mp3').status_code, 409)
        self.assertEqual(self.client.delete('/api/music?file=mp3/unittest_upload.mp3').status_code, 200)
        self.assertFalse(target.exists())

    def test_wled_test_and_effect_list(self):
        with patch('webserver.WLEDManager') as manager:
            manager.return_value.get_status.return_value = {'state': {}, 'info': {'ver': '16.0.1', 'leds': {'count': 264}}}
            result = self.client.get('/api/wled/test').json
            self.assertEqual((result['success'], result['version'], result['leds']), (True, '16.0.1', 264))
            manager.return_value.fetch.side_effect = lambda path: {
                'effects': ['Solid', 'RSVD', 'Gravimeter', 'GEQ'],
                'fxdata': ['', '', 'x;;;1v', 'x;;;2f']}[path]
            effects = self.client.get('/api/wled/effects').json['effects']
        self.assertEqual([(e['fx'], e['audio'], e['matrix']) for e in effects],
                         [(0, '', False), (2, 'v', False), (3, 'f', True)])

    def test_weather_search(self):
        response = Mock()
        response.read.return_value = json.dumps({'results': [
            {'name': 'Hamburg', 'admin1': 'Hamburg', 'country_code': 'DE', 'latitude': 53.55, 'longitude': 10.0}]}).encode()
        with patch('webserver.urlopen') as opener:
            opener.return_value.__enter__.return_value = response
            places = self.client.get('/api/weather/search?q=Hamburg').json['places']
        self.assertEqual(places, [{'name': 'Hamburg, Hamburg, DE', 'latitude': 53.55, 'longitude': 10.0}])


if __name__ == '__main__':
    unittest.main()
