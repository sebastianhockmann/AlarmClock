import json
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import chime
import config
import scheduler
import smart_home
from audio import AudioPlayer
from controller import ClockController
from lighting import (EffectBrowser, EffectSelector, WLEDClient, WLEDManager,
                      browser_entries, load_effects)


class ClockTests(unittest.TestCase):
    def setUp(self):
        scheduler._last_alarm_day = None
        self.settings = patch('scheduler.alarm_time', return_value=(6, 15))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.mapping = patch('scheduler.read_json', return_value={})
        self.mapping.start()
        self.addCleanup(self.mapping.stop)

    def test_alarm_survives_next_loop_and_stops_at_deadline(self):
        player = Mock()
        clock = ClockController(player, Mock())
        now = datetime(2026, 9, 13, 6, 15)
        clock.tick(now, 100)
        item = clock.active_item
        clock.tick(now, 100.1)
        self.assertEqual(clock.active_item, item)
        player.play.assert_called_once_with(item['file'])
        player.stop.assert_not_called()
        clock.tick(now, 100 + config.ALARM_DURATION_SECONDS)
        self.assertIsNone(clock.active_item)
        player.stop.assert_called_once()

    def test_stop_does_not_retrigger_same_minute(self):
        clock = ClockController(Mock(), Mock())
        now = datetime(2026, 9, 13, 6, 15)
        clock.tick(now, 10)
        clock.handle('right_press', None, 11)
        clock.tick(now, 12)
        self.assertIsNone(clock.active_item)
        clock.player.play.assert_called_once()

    def test_full_date_used_for_trigger(self):
        self.assertTrue(scheduler.check_alarm(datetime(2026, 9, 13, 6, 15))[0])
        self.assertTrue(scheduler.check_alarm(datetime(2026, 10, 13, 6, 15))[0])

    def test_daily_rotation_and_date_override(self):
        self.assertNotEqual(scheduler.get_today_wake_item(date(2026, 9, 13))['file'],
                            scheduler.get_today_wake_item(date(2026, 9, 14))['file'])
        self.assertEqual(scheduler.get_today_wake_item(date(2026, 12, 11))['file'],
                         config.DATE_SONGS[0]['file'])
        for item in config.WAKE_ITEMS + config.DATE_SONGS:
            self.assertTrue((config.BASE_DIR / item['file']).is_file())

    def test_web_mapping_overrides_annual_song(self):
        with patch('scheduler.read_json', return_value={
            '2026-12-11': {'file': 'mp3/special.mp3', 'message': 'Hallo'},
            '12-11': 'annual.mp3',
        }):
            self.assertEqual(scheduler.get_today_wake_item(date(2026, 12, 11)),
                             {'file': 'mp3/special.mp3', 'message': 'Hallo'})
            self.assertEqual(scheduler.get_today_wake_item(date(2027, 12, 11))['file'],
                             'mp3/annual.mp3')

    def test_shared_settings_and_invalid_fallback(self):
        import settings
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            with patch('settings.SETTINGS_FILE', path):
                settings.write_json(path, {'hour': 8, 'minute': 30})
                self.assertEqual(settings.alarm_time(), (8, 30))
                settings.write_json(path, {'hour': 99, 'minute': 30})
                self.assertEqual(settings.alarm_time(), (config.ALARM_HOUR, config.ALARM_MINUTE))
                path.write_text('{broken')
                self.assertEqual(settings.alarm_time(), (config.ALARM_HOUR, config.ALARM_MINUTE))

    def test_audio_failure_keeps_alarm_message(self):
        player = Mock()
        player.play.side_effect = FileNotFoundError('missing')
        clock = ClockController(player, Mock())
        clock.tick(datetime(2026, 9, 13, 6, 15), 0)
        self.assertIsNotNone(clock.active_item)
        self.assertEqual(clock.message(1, ''), 'Audio Fehler!')

    def test_rotation_previews_press_and_key_apply(self):
        send = Mock()
        effects = load_effects(config.EFFECT_LIBRARY)
        selector = EffectSelector(effects, send)
        selector.rotate(-1)
        send.assert_not_called()
        self.assertEqual(selector.selected['id'], effects[-1]['id'])
        selector.confirm()
        send.assert_called_once_with(effects[-1]['state'])
        selector.select('key', '1')
        self.assertEqual(selector.selected['id'], 'solid')
        with self.assertRaises(ValueError):
            selector.select('key', 'unknown')

    def test_browser_previews_live_and_accelerates(self):
        send = Mock()
        entries = list(enumerate(['A', 'B', 'C', 'D', 'E']))
        browser = EffectBrowser(send, None, entries, fast_seconds=0.1, fast_steps=3)
        self.assertEqual(browser.rotate(1, 10.0), '2/5 B')
        send.assert_called_once_with({'on': True, 'seg': [{'id': 0, 'fx': 1}]})
        # Schnell nachgedreht: ein Rastschritt zaehlt dreifach.
        self.assertEqual(browser.rotate(1, 10.05), '5/5 E')
        # Langsam gedreht: wieder ein einzelner Schritt, mit Umlauf.
        self.assertEqual(browser.rotate(1, 20.0), '1/5 A')

    def test_browser_toggles_power_without_touching_brightness(self):
        send = Mock()
        browser = EffectBrowser(send, None, [(0, 'Solid')])
        self.assertEqual(browser.toggle_power(), 'Licht aus')
        send.assert_called_with({'on': False})
        self.assertEqual(browser.toggle_power(), 'Licht an')
        send.assert_called_with({'on': True})

    def test_browser_adopts_the_full_effect_list_from_the_device(self):
        status = Mock(return_value={'effects': ['Solid', 'Blink', 'Aurora'],
                                    'state': {'on': False, 'seg': [{'fx': 2}]}})
        browser = EffectBrowser(Mock(), status, [(0, 'Solid')])
        browser.refresh()
        browser._thread.join(2)
        self.assertTrue(browser.live)
        self.assertEqual(browser.entries, [(0, 'Solid'), (1, 'Blink'), (2, 'Aurora')])
        self.assertEqual(browser.index, 2)
        self.assertFalse(browser.power)

    def test_browser_keeps_working_when_the_device_is_silent(self):
        browser = EffectBrowser(Mock(), Mock(return_value=None), [(0, 'Solid'), (9, 'Rainbow')])
        browser.refresh()
        browser._thread.join(2)
        self.assertFalse(browser.live)
        self.assertEqual(browser.rotate(1, 1.0), '2/2 Rainbow')

    def test_browser_fallback_entries_come_from_the_library(self):
        entries = browser_entries(load_effects(config.EFFECT_LIBRARY))
        self.assertIn((9, 'Rainbow'), entries)
        # "Licht aus" hat keinen Effekt und taugt deshalb nicht zur Vorschau.
        self.assertNotIn('Licht aus', [name for _, name in entries])
        self.assertEqual(len(entries), len({fx for fx, _ in entries}))

    def test_left_knob_previews_live_and_press_toggles_the_strip(self):
        browser = Mock()
        browser.rotate.return_value = '3/180 Aurora'
        browser.toggle_power.return_value = 'Licht aus'
        clock = ClockController(Mock(), Mock(), browser=browser)
        clock.handle('left_rotate', 1, 5)
        browser.rotate.assert_called_once_with(1, 5)
        self.assertEqual(clock.notice, '3/180 Aurora')
        clock.handle('left_press', None, 5)
        browser.toggle_power.assert_called_once()
        self.assertEqual(clock.notice, 'Licht aus')

    def test_right_press_plays_and_stops_music_without_an_alarm(self):
        player = Mock()
        player.is_playing = False
        clock = ClockController(player, Mock())
        clock.handle('right_press', None, 0)
        player.play.assert_called_once()
        player.is_playing = True
        clock.handle('right_press', None, 1)
        player.stop.assert_called_once()
        self.assertEqual(clock.notice, 'Musik gestoppt')

    def test_right_hold_resets_music_light_and_backlight(self):
        player, browser, backlight = Mock(), Mock(), Mock()
        clock = ClockController(player, Mock(), browser=browser, backlight=backlight)
        clock.tick(datetime(2026, 9, 13, 6, 15), 0)
        self.assertIsNotNone(clock.active_item)
        clock.handle('right_hold', None, 1)
        self.assertIsNone(clock.active_item)
        player.stop.assert_called()
        browser.set_power.assert_called_once_with(True)
        backlight.assert_called_once_with(reset=True)
        self.assertEqual(clock.notice, 'Alles normal')

    def test_key_press_selects_effect_by_default(self):
        lights = Mock()
        lights.select.return_value = 'Solid'
        clock = ClockController(Mock(), lights)
        clock.handle('key', '1', 0)
        lights.select.assert_called_once_with('key', '1')
        self.assertEqual(clock.notice, 'Solid')

    def test_key_press_on_smart_home_key_skips_lights(self):
        lights = Mock()
        trigger = Mock(return_value='Deckenlampe')
        clock = ClockController(Mock(), lights, smart_home_trigger=trigger)
        with patch.dict(config.SMART_HOME_ACTIONS, {'A': {'label': 'Deckenlampe',
                                                           'service': 'light.toggle',
                                                           'entity_id': 'light.deckenlampe'}}):
            clock.handle('key', 'A', 0)
        trigger.assert_called_once_with(config.SMART_HOME_ACTIONS['A'])
        lights.select.assert_not_called()
        self.assertEqual(clock.notice, 'Deckenlampe')

    def test_smart_home_trigger_is_a_no_op_without_home_assistant_url(self):
        with patch('smart_home.config.HOME_ASSISTANT_URL', ''), \
             patch('smart_home.urlopen') as open_url:
            label = smart_home.trigger({'label': 'Deckenlampe', 'service': 'light.toggle',
                                        'entity_id': 'light.deckenlampe'})
            self.assertEqual(label, 'Deckenlampe')
            open_url.assert_not_called()

    def test_smart_home_trigger_calls_home_assistant_when_configured(self):
        import threading
        called = threading.Event()

        def response(*args, **kwargs):
            called.set()
            return Mock(__enter__=Mock(return_value=Mock()), __exit__=Mock(return_value=False))

        with patch('smart_home.config.HOME_ASSISTANT_URL', 'http://ha.local:8123'), \
             patch('smart_home.config.HOME_ASSISTANT_TOKEN', 'secret'), \
             patch('smart_home.urlopen', side_effect=response) as open_url:
            smart_home.trigger({'label': 'Deckenlampe', 'service': 'light.toggle',
                                'entity_id': 'light.deckenlampe'})
            self.assertTrue(called.wait(2))
            request = open_url.call_args.args[0]
            self.assertEqual(request.full_url, 'http://ha.local:8123/api/services/light/toggle')
            self.assertEqual(json.loads(request.data), {'entity_id': 'light.deckenlampe'})
            self.assertEqual(request.headers['Authorization'], 'Bearer secret')

    def test_chime_plays_click_via_aplay_without_touching_the_main_player(self):
        with patch('chime.subprocess.Popen') as spawn:
            chime.play_click()
            args = spawn.call_args.args[0]
            self.assertEqual(args[0], 'aplay')
            self.assertIn(str(chime.CLICK_SOUND), args)

    def test_chime_ignores_a_busy_audio_device(self):
        with patch('chime.subprocess.Popen', side_effect=OSError('busy')):
            chime.play_click()  # muss nicht werfen

    def test_duplicate_effect_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'effects.json'
            path.write_text(json.dumps([
                {'id': name, 'name': name, 'key': '1', 'state': {'on': True}}
                for name in ['a', 'b']]))
            with self.assertRaises(ValueError):
                load_effects(path)

    def test_audio_process_reaped(self):
        with patch('audio.subprocess.Popen') as spawn:
            process = spawn.return_value
            process.poll.return_value = None
            player = AudioPlayer('default')
            player.play(config.DEFAULT_SONG)
            player.stop()
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=1)
            self.assertFalse(player.is_playing)

    def test_audio_play_sends_silence_volume_and_load(self):
        with patch('audio.subprocess.Popen') as spawn:
            process = spawn.return_value
            process.poll.return_value = None
            player = AudioPlayer('default')
            player.play(config.DEFAULT_SONG)
            sent = process.stdin.write.call_args_list[0].args[0]
            self.assertIn('SILENCE', sent)
            self.assertIn('VOLUME 100', sent)
            self.assertIn(f'LOAD {config.BASE_DIR / config.DEFAULT_SONG}', sent)
            player.stop()

    def test_audio_set_volume_is_clamped_and_sent_live(self):
        with patch('audio.subprocess.Popen') as spawn:
            process = spawn.return_value
            process.poll.return_value = None
            player = AudioPlayer('default')
            player.play(config.DEFAULT_SONG)
            self.assertEqual(player.set_volume(150), 100)
            self.assertEqual(player.set_volume(-10), 0)
            self.assertEqual(player.set_volume(37), 37)
            process.stdin.write.assert_called_with('VOLUME 37\n')
            player.stop()

    def test_audio_is_playing_follows_status_lines(self):
        import threading
        import time
        hold = threading.Event()

        def stdout_lines():
            yield '@P 2\n'
            hold.wait(2)
            yield '@P 0\n'

        with patch('audio.subprocess.Popen') as spawn:
            process = spawn.return_value
            process.poll.return_value = None
            process.stdout = stdout_lines()
            player = AudioPlayer('default')
            player.play(config.DEFAULT_SONG)
            for _ in range(200):
                if player.is_playing:
                    break
                time.sleep(0.01)
            self.assertTrue(player.is_playing)
            hold.set()
            for _ in range(200):
                if not player.is_playing:
                    break
                time.sleep(0.01)
            self.assertFalse(player.is_playing)
            player.stop()

    def test_right_rotate_adjusts_volume(self):
        player = Mock()
        player.volume = 50
        player.set_volume.return_value = 55
        clock = ClockController(player, Mock())
        clock.handle('right_rotate', 1, 0)
        player.set_volume.assert_called_once_with(55)
        self.assertEqual(clock.notice, 'Lautstaerke: 55%')

    def test_wled_payload(self):
        import threading
        delivered = threading.Event()
        with patch('lighting.urlopen') as open_url:
            def response(*args, **kwargs):
                delivered.set()
                return Mock(__enter__=Mock(return_value=Mock(read=Mock(return_value=b'{"success":true}'))), __exit__=Mock(return_value=False))
            open_url.side_effect = response
            client = WLEDClient('http://wled.local', report=Mock())
            try:
                client.send({'ps': 1})
                self.assertTrue(delivered.wait(2))
            finally:
                client.close()
            request = open_url.call_args.args[0]
            self.assertEqual(request.full_url, 'http://wled.local/json/state')
            self.assertEqual(json.loads(request.data), {'ps': 1})

    def test_wled_hostnames_and_ipv4_are_supported(self):
        for host in ('wled.local', 'alarm-led.local', '192.168.178.50'):
            manager = WLEDManager(host=host, enabled=True, timeout=3)
            self.assertEqual(manager.base_url, f'http://{host}')
            self.assertEqual(manager.host, host)

    def test_wled_manager_handles_disabled_and_unavailable(self):
        manager = WLEDManager(host='alarm-led.local', enabled=False, timeout=3)
        self.assertFalse(manager.enabled)
        self.assertFalse(manager.is_available())

        with patch('lighting.urlopen', side_effect=TimeoutError('timeout')):
            manager = WLEDManager(host='alarm-led.local', enabled=True, timeout=3)
            self.assertFalse(manager.is_available())
            self.assertIsNone(manager.get_status())

    def test_wled_manager_builds_url_and_activates_preset(self):
        import threading
        delivered = threading.Event()
        with patch('lighting.urlopen') as open_url:
            response = Mock()
            response.read.return_value = b'{"success":true}'
            response.read.side_effect = lambda *args: (delivered.set() or b'{"success":true}')
            open_url.return_value.__enter__.return_value = response
            manager = WLEDManager(host='http://wled.local/', enabled=True, timeout=3)
            self.assertEqual(manager.base_url, 'http://wled.local')
            try:
                manager.activate_preset(3)
                self.assertTrue(delivered.wait(2))
                request = open_url.call_args.args[0]
                self.assertEqual(request.full_url, 'http://wled.local/json/state')
                self.assertEqual(json.loads(request.data), {'ps': 3})
            finally:
                manager.close()


if __name__ == '__main__':
    unittest.main()
