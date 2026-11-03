import json
from datetime import date, datetime
import random
import threading
import time
import unittest
from unittest.mock import Mock, patch
import chime
import config
import scheduler
import settings
from audio import AudioPlayer
from controller import ClockController
from lighting import EffectBrowser, WLEDManager, browser_entries, default_palette, load_effects
from helpers import TempSettingsTestCase

MONDAY_0615 = datetime(2026, 9, 28, 6, 15)
ECHO = 'bff71067de175dbdf5c1836a959bf7e2'


def player_mock():
    player = Mock()
    player.volume = 50
    player.is_playing = False
    player.finished = False
    player.set_volume.side_effect = lambda value: max(0, min(100, int(value)))
    return player


class SchedulerTests(TempSettingsTestCase):
    def test_default_alarm_fires_once_per_day(self):
        alarms = scheduler.AlarmScheduler()
        self.assertEqual([kind for kind, _ in alarms.due(MONDAY_0615)], ['alarm'])
        self.assertEqual(alarms.due(MONDAY_0615.replace(second=30)), [])
        self.assertEqual(len(alarms.due(datetime(2026, 9, 29, 6, 15))), 1)

    def test_weekdays_and_master_switch(self):
        settings.save('alarms', [{'label': 'Werktags', 'time': '06:15', 'days': [0, 1, 2, 3, 4]},
                                 {'label': 'Wochenende', 'time': '08:00', 'days': [5, 6]}])
        alarms = scheduler.AlarmScheduler()
        self.assertEqual(len(alarms.due(MONDAY_0615)), 1)
        self.assertEqual(alarms.due(datetime(2026, 9, 26, 6, 15)), [])  # Samstag
        self.assertEqual(alarms.due(datetime(2026, 9, 26, 8, 0))[0][1]['label'], 'Wochenende')
        settings.save('alarms_enabled', False)
        self.assertEqual(alarms.due(datetime(2026, 9, 29, 6, 15)), [])

    def test_light_lead_fires_before_the_alarm_even_across_midnight(self):
        settings.save('alarms', [{'label': 'Frueh', 'time': '00:05', 'days': [0]}])
        wake = settings.get('wake')
        wake['light_lead_minutes'] = 10
        wake['effect'] = 'morgenlicht'
        settings.save('wake', wake)
        alarms = scheduler.AlarmScheduler()
        # Sonntag 23:55 -> Licht fuer Montag 00:05.
        self.assertEqual([kind for kind, _ in alarms.due(datetime(2026, 9, 27, 23, 55))], ['light'])
        self.assertEqual([kind for kind, _ in alarms.due(datetime(2026, 9, 28, 0, 5))], ['alarm'])

    def test_skip_cancels_todays_alarm(self):
        alarms = scheduler.AlarmScheduler()
        alarm_id = settings.get('alarms')[0]['id']
        alarms.skip(alarm_id, MONDAY_0615.date())
        self.assertEqual(alarms.due(MONDAY_0615), [])

    def test_next_alarm(self):
        settings.save('alarms', [{'label': 'A', 'time': '07:00', 'days': [2]}])
        moment, alarm = scheduler.next_alarm(MONDAY_0615)
        self.assertEqual(moment, datetime(2026, 9, 30, 7, 0))
        settings.save('alarms_enabled', False)
        self.assertIsNone(scheduler.next_alarm(MONDAY_0615))

    def test_song_priority_date_then_rotation(self):
        music = settings.get('music')
        music['dates'].append({'date': '2026-12-11', 'file': 'mp3/xmas/polar_express.mp3', 'message': 'Einmalig'})
        settings.save('music', music)
        self.assertEqual(scheduler.get_today_wake_item(date(2026, 12, 11))['message'], 'Einmalig')
        self.assertEqual(scheduler.get_today_wake_item(date(2027, 12, 11))['file'], 'mp3/xmas/maria.mp3')
        self.assertNotEqual(scheduler.get_today_wake_item(date(2026, 9, 13))['file'],
                            scheduler.get_today_wake_item(date(2026, 9, 14))['file'])

    def test_all_configured_songs_exist(self):
        music = settings.get('music')
        for entry in [{'file': music['default_song']}] + music['dates'] + music['rotation']:
            self.assertTrue((config.BASE_DIR / entry['file']).is_file(), entry['file'])

    def test_alexa_song_rotates_daily_and_falls_back_to_mp3(self):
        songs = settings.get('music')['alexa_songs']
        first = scheduler.wake_item('alexa', date(2026, 9, 28))
        second = scheduler.wake_item('alexa', date(2026, 9, 29))
        self.assertIn(first['alexa'], [song['text'] for song in songs])
        self.assertNotEqual(first['alexa'], second['alexa'])
        music = settings.get('music')
        music['alexa_songs'] = []
        settings.save('music', music)
        self.assertIsNone(scheduler.wake_item('alexa', date(2026, 9, 28)).get('alexa'))

    def test_random_song_comes_from_the_music_folder(self):
        item = scheduler.get_random_item(rng=random.Random(1))
        self.assertIn(item['file'], scheduler.list_music())
        self.assertTrue(item['message'].startswith('Zufall: '))

    def test_greeting_wraps_midnight(self):
        self.assertEqual(scheduler.get_greeting(datetime(2026, 9, 28, 23, 0))['text'], 'Gute Nacht')
        self.assertFalse(scheduler.get_greeting(datetime(2026, 9, 28, 3, 0))['backlight'])

    def test_describe_days(self):
        self.assertEqual(scheduler.describe_days([0, 1, 2, 3, 4]), 'Mo-Fr')
        self.assertEqual(scheduler.describe_days([1, 3]), 'Di,Do')


class ControllerTests(TempSettingsTestCase):
    def setUp(self):
        super().setUp()
        # Hier geht es ums Weckprogramm allein: mit eigenem Licht, ohne Lichtprogramme.
        settings.save('wake', {**settings.get('wake'), 'effect': 'morgenlicht', 'light_end': 'off'})
        settings.save('programs', [])

    def make(self, **kwargs):
        self.player = player_mock()
        self.send = Mock()
        self.emit = Mock()
        return ClockController(self.player, self.send, emit=self.emit, **kwargs)

    def test_alarm_ramps_volume_and_ends_after_the_song(self):
        clock = self.make()
        clock.tick(MONDAY_0615, 100)
        self.assertTrue(clock.alarm_active)
        self.player.set_volume.assert_any_call(20)
        self.player.play.assert_called_once_with(clock.active_item['file'])
        clock.tick(MONDAY_0615, 130)  # halbe Rampe: 20 -> 70 ueber 60 s
        self.player.set_volume.assert_called_with(45)
        self.player.finished = True
        clock.tick(MONDAY_0615, 140)
        self.assertFalse(clock.alarm_active)
        self.assertIsNone(clock.active_item)
        # Licht wird ausgeblendet (light_end = off).
        self.assertEqual(self.send.call_args.args[0], {'on': False, 'tt': 50})

    def test_light_starts_dim_and_brightens(self):
        clock = self.make()
        clock.tick(MONDAY_0615, 0)
        first = self.send.call_args_list[0].args[0]
        self.assertEqual(first['bri'], 8)  # 3 %
        self.assertEqual(first['seg'][0]['fx'], 0)
        clock.tick(MONDAY_0615, 60)  # halbe Licht-Rampe (2 min)
        self.assertEqual(self.send.call_args.args[0]['bri'], round(41.5 * 255 / 100))

    def test_alarm_stops_at_max_duration_without_song_end(self):
        clock = self.make()
        clock.tick(MONDAY_0615, 0)
        clock.tick(MONDAY_0615, 5 * 60)
        self.assertFalse(clock.alarm_active)
        self.player.stop.assert_called()

    def test_stop_does_not_retrigger_same_minute(self):
        clock = self.make()
        clock.tick(MONDAY_0615, 10)
        clock.handle('right_press', None, 11)
        clock.tick(MONDAY_0615, 12)
        self.assertFalse(clock.alarm_active)
        self.player.play.assert_called_once()

    def test_stop_during_light_lead_cancels_the_music(self):
        wake = settings.get('wake')
        wake['light_lead_minutes'] = 10
        settings.save('wake', wake)
        clock = self.make()
        clock.tick(datetime(2026, 9, 28, 6, 5), 0)
        self.assertEqual(clock.session.phase, 'light')
        self.assertFalse(clock.force_backlight)
        clock.handle('right_press', None, 1)
        clock.tick(MONDAY_0615, 600)
        self.assertIsNone(clock.session)
        self.player.play.assert_not_called()

    def test_any_key_snoozes_and_music_returns(self):
        clock = self.make()
        clock.tick(MONDAY_0615, 0)
        clock.handle('key', '5', 1)
        self.assertEqual(clock.session.phase, 'snooze')
        self.assertEqual(clock.notice, 'Schlummern bis 06:24')
        self.send.reset_mock()
        clock.tick(MONDAY_0615, 1 + 9 * 60)
        self.assertEqual(clock.session.phase, 'music')
        self.assertEqual(self.player.play.call_count, 2)

    def test_audio_failure_keeps_alarm_message(self):
        clock = self.make()
        self.player.play.side_effect = FileNotFoundError('missing')
        clock.tick(MONDAY_0615, 0)
        self.assertTrue(clock.alarm_active)
        self.assertEqual(clock.message(1, ''), 'Audio Fehler!')

    def test_light_only_program(self):
        wake = settings.get('wake')
        wake['music'] = 'none'
        settings.save('wake', wake)
        clock = self.make()
        clock.tick(MONDAY_0615, 0)
        self.player.play.assert_not_called()
        self.assertTrue(clock.alarm_active)

    def test_key_runs_configured_effect(self):
        clock = self.make()
        clock.handle('key', '1', 0)
        self.send.assert_called_once_with(settings.effect_by_id('solid')['state'])
        self.assertEqual(clock.notice, 'Solid')

    def test_key_actions_music_display_and_toggle(self):
        backlight = Mock()
        clock = self.make(backlight=backlight)
        clock.handle('key', '*', 0)  # Zufallssong
        self.assertIn(self.player.play.call_args.args[0], scheduler.list_music())
        clock.handle('key', 'D', 0)
        backlight.assert_called_once_with(toggle=True)
        clock.run_action({'type': 'alarm_toggle'})
        self.assertFalse(settings.get('alarms_enabled'))

    def test_remote_actions_report_failures_back_to_the_lcd(self):
        integration = Mock(return_value='Deckenlampe')
        clock = self.make(integration=integration)
        clock.handle('key', 'A', 0)
        action, report = integration.call_args.args
        self.assertEqual(action['entity_id'], 'light.deckenlampe')
        self.assertEqual(clock.notice, 'Deckenlampe')
        report('HTTP-Fehler 401')
        self.emit.assert_called_once_with('notice', 'HTTP-Fehler 401')
        clock.handle('notice', 'HTTP-Fehler 401', 1)
        self.assertEqual(clock.message(2, ''), 'HTTP-Fehler 401')

    def test_weather_key_shows_loading_then_result(self):
        weather = Mock()
        weather.cached.return_value = None
        weather.request.return_value = True
        clock = self.make(weather=weather)
        clock.handle('key', 'C', 0)
        self.assertEqual(clock.notice, 'Wetter wird geladen')
        weather.request.call_args.args[0]('Jetzt 12C')
        self.emit.assert_called_with('notice', 'Jetzt 12C')

    def test_left_knob_previews_live_and_press_toggles_the_strip(self):
        browser = Mock()
        browser.rotate.return_value = '3/180 Aurora'
        browser.toggle_power.return_value = 'Licht aus'
        clock = self.make(browser=browser)
        clock.handle('left_rotate', 1, 5)
        browser.rotate.assert_called_once_with(1, 5)
        self.assertEqual(clock.notice, '3/180 Aurora')
        clock.handle('left_press', None, 5)
        self.assertEqual(clock.notice, 'Licht aus')

    def test_right_press_plays_and_stops_music_without_an_alarm(self):
        clock = self.make()
        clock.handle('right_press', None, 0)
        self.player.play.assert_called_once()
        self.player.is_playing = True
        clock.handle('right_press', None, 1)
        self.player.stop.assert_called_once()
        self.assertEqual(clock.notice, 'Musik gestoppt')

    def test_right_hold_resets_music_light_and_backlight(self):
        browser, backlight = Mock(), Mock()
        clock = self.make(browser=browser, backlight=backlight)
        clock.tick(MONDAY_0615, 0)
        clock.handle('right_hold', None, 1)
        self.assertFalse(clock.alarm_active)
        browser.set_power.assert_called_once_with(True)
        backlight.assert_called_once_with(reset=True)
        self.assertEqual(clock.notice, 'Alles normal')

    def test_manual_volume_stops_the_ramp(self):
        clock = self.make()
        clock.tick(MONDAY_0615, 0)
        clock.handle('right_rotate', 1, 1)
        self.player.set_volume.assert_called_with(55)
        self.assertEqual(clock.notice, 'Lautstaerke: 55%')
        self.player.set_volume.reset_mock()
        clock.tick(MONDAY_0615, 30)
        self.player.set_volume.assert_not_called()

    def test_remote_play_file_is_limited_to_the_music_folder(self):
        clock = self.make()
        clock.handle('play_file', 'mp3/xmas/maria.mp3', 0)
        self.player.play.assert_called_once_with('mp3/xmas/maria.mp3')
        with self.assertRaises(ValueError):
            clock.handle('play_file', '../etc/passwd.mp3', 0)

    def test_wake_test_runs_the_program_now(self):
        clock = self.make()
        clock.tick(datetime(2026, 9, 28, 14, 0), 0)
        clock.handle('wake_test', None, 1)
        self.assertEqual(clock.session.phase, 'music')
        self.assertEqual(clock.status()['alarm'], 'Weck-Test')


    def alexa_mock(self, device=ECHO):
        alexa = Mock()
        alexa.device.return_value = device
        alexa.say.return_value = bool(device)
        return alexa

    def use_alexa_wake(self):
        wake = settings.get('wake')
        wake['music'] = 'alexa'
        settings.save('wake', wake)

    def said(self, alexa):
        return [call.args[0] for call in alexa.say.call_args_list]

    def test_alexa_wake_ramps_volume_in_steps_and_stops(self):
        self.use_alexa_wake()
        alexa = self.alexa_mock()
        clock = self.make(alexa=alexa)
        clock.tick(MONDAY_0615, 0)
        song = scheduler.get_alexa_item(MONDAY_0615.date())['alexa']
        self.assertEqual(self.said(alexa), ['Lautstärke 2', song])
        self.player.play.assert_not_called()
        clock.tick(MONDAY_0615, 30)   # 45 %
        clock.tick(MONDAY_0615, 31)   # 45,8 % -> Stufe 5
        clock.tick(MONDAY_0615, 60)   # 70 %
        self.assertEqual(self.said(alexa)[2:], ['Lautstärke 4', 'Lautstärke 5', 'Lautstärke 7'])
        clock.handle('right_press', None, 61)
        self.assertEqual(self.said(alexa)[-1], 'Stopp')
        self.assertFalse(clock.alarm_active)

    def test_alexa_wake_snooze_stops_and_restarts_the_song(self):
        self.use_alexa_wake()
        alexa = self.alexa_mock()
        clock = self.make(alexa=alexa)
        clock.tick(MONDAY_0615, 0)
        clock.handle('key', '5', 1)
        self.assertEqual(self.said(alexa)[-1], 'Stopp')
        clock.tick(MONDAY_0615, 1 + 9 * 60)
        self.assertEqual(self.said(alexa)[-2:], ['Lautstärke 2', self.said(alexa)[1]])

    def test_alexa_wake_falls_back_to_mp3(self):
        self.use_alexa_wake()
        clock = self.make(alexa=self.alexa_mock(device=''))
        clock.tick(MONDAY_0615, 0)
        self.player.play.assert_called_once()
        # Echo eingestellt, aber Home Assistant antwortet nicht:
        alexa = self.alexa_mock()
        clock = self.make(alexa=alexa)
        clock.tick(MONDAY_0615, 0)
        self.player.play.assert_not_called()
        alexa.say.call_args.kwargs['on_error']('Nicht erreichbar')
        self.emit.assert_called_with('alexa_error', 'Nicht erreichbar')
        clock.handle('alexa_error', 'Nicht erreichbar', 2)
        self.player.play.assert_called_once()
        self.assertEqual(clock.notice, 'Alexa Fehler: MP3')

    def test_pressed_right_knob_sets_alexa_volume_after_a_pause(self):
        alexa = self.alexa_mock()
        clock = self.make(alexa=alexa)
        clock.handle('right_press_rotate', 1, 0)
        clock.handle('right_press_rotate', 1, 0.2)
        self.assertEqual(clock.notice, 'Alexa Lautst. 6')
        clock.tick(MONDAY_0615.replace(hour=12), 0.5)
        alexa.say.assert_not_called()
        clock.tick(MONDAY_0615.replace(hour=12), 1.1)
        alexa.say.assert_called_once_with('Lautstärke 6')
        self.player.set_volume.assert_not_called()
        clock = self.make(alexa=self.alexa_mock(device=''))
        clock.handle('right_press_rotate', 1, 0)
        self.assertEqual(clock.notice, 'Alexa-Echo fehlt (Web)')

    def test_left_knob_dims_the_lamp_after_a_lamp_key(self):
        integration, browser, dimmer = Mock(return_value='Farbe Tiago'), Mock(), Mock()
        dimmer.levels = {'light.h60a1': 51}
        dimmer.set.side_effect = lambda entity, percent: dimmer.levels.update({entity: percent})
        clock = self.make(integration=integration, browser=browser, dimmer=dimmer)
        clock.run_action({'type': 'ha_color', 'entity_id': 'light.h60a1', 'colors': ['rot']})
        dimmer.prefetch.assert_called_once_with('light.h60a1')
        clock.handle('left_rotate', 1, 1)
        self.assertEqual(clock.notice, 'Lampe 60%')
        clock.handle('left_rotate', -1, 1.1)
        clock.handle('left_rotate', -1, 1.2)
        self.assertEqual(clock.notice, 'Lampe 40%')
        self.assertEqual([c.args[1] for c in dimmer.set.call_args_list], [60, 50, 40])
        browser.rotate.assert_not_called()
        # 10 s ohne Drehen: der Knopf blaettert wieder durch die Effekte.
        clock.tick(MONDAY_0615.replace(hour=12), 12)
        clock.handle('left_rotate', 1, 12)
        browser.rotate.assert_called_once()

    def test_song_list_browses_with_the_right_knob(self):
        clock = self.make()
        files = scheduler.list_music()
        clock.run_action({'type': 'songs', 'source': 'mp3'})
        self.assertTrue(clock.notice.startswith(f'1/{len(files)} '))
        clock.handle('right_rotate', 2, 1)
        self.assertTrue(clock.notice.startswith(f'3/{len(files)} '))
        self.player.set_volume.assert_not_called()
        clock.handle('right_press', None, 2)
        self.player.play.assert_called_once_with(files[2])
        self.assertIsNone(clock.browse)
        clock.handle('right_rotate', 1, 3)  # wieder Lautstaerke
        self.player.set_volume.assert_called_once()

    def test_alexa_song_list_times_out(self):
        alexa = self.alexa_mock()
        clock = self.make(alexa=alexa)
        songs = settings.get('music')['alexa_songs']
        clock.handle('action', {'type': 'songs', 'source': 'alexa'}, 0)
        clock.handle('action', {'type': 'songs', 'source': 'alexa'}, 1)  # nochmal = weiter
        self.assertTrue(clock.notice.startswith(f'2/{len(songs)} '))
        clock.handle('right_press', None, 2)
        alexa.say.assert_called_once_with(songs[1]['text'])
        clock.run_action({'type': 'songs', 'source': 'alexa'})
        clock.tick(MONDAY_0615.replace(hour=12), 2 + 11)
        self.assertIsNone(clock.browse)


class LightingTests(TempSettingsTestCase):
    def test_library_is_valid_and_feeds_the_fallback_browser_list(self):
        effects = load_effects(config.EFFECTS_FILE)
        entries = browser_entries(effects)
        self.assertIn((9, 'Rainbow'), entries)
        self.assertNotIn('Licht aus', [name for _, name in entries])
        self.assertEqual(len(entries), len({fx for fx, _ in entries}))

    def test_duplicate_effect_ids_rejected(self):
        path = self.dir / 'effects.json'
        path.write_text(json.dumps([{'id': 'a', 'name': 'A', 'state': {'on': True}}] * 2))
        with self.assertRaises(ValueError):
            load_effects(path)

    def test_browser_previews_live_and_accelerates(self):
        send = Mock()
        browser = EffectBrowser(send, None, list(enumerate('ABCDE')), fast_seconds=0.1, fast_steps=3)
        self.assertEqual(browser.rotate(1, 10.0), '2/5 B')
        send.assert_called_once_with({'on': True, 'seg': [{'id': 0, 'fx': 1, 'fxdef': True, 'pal': 0}]})
        self.assertEqual(browser.rotate(1, 10.05), '5/5 E')
        self.assertEqual(browser.rotate(1, 20.0), '1/5 A')

    def test_browser_toggles_power_without_touching_brightness(self):
        send = Mock()
        browser = EffectBrowser(send, None, [(0, 'Solid')])
        self.assertEqual(browser.toggle_power(), 'Licht aus')
        send.assert_called_with({'on': False})

    def test_browser_adopts_the_full_effect_list_from_the_device(self):
        status = Mock(return_value={'effects': ['Solid', 'Blink', 'Aurora'],
                                    'state': {'on': False, 'seg': [{'fx': 2}]}})
        browser = EffectBrowser(Mock(), status, [(0, 'Solid')])
        browser.refresh()
        browser._thread.join(2)
        self.assertEqual(browser.entries, [(0, 'Solid'), (1, 'Blink'), (2, 'Aurora')])
        self.assertEqual(browser.index, 2)
        self.assertFalse(browser.power)

    def test_browser_resets_the_palette_to_the_effect_default(self):
        # Sonst bleibt z. B. "Aurora" (gruen) fuer alle folgenden Effekte stehen.
        self.assertEqual(default_palette('!,!;1,2,3;!;;sx=24,pal=50'), 50)
        self.assertEqual(default_palette('!,Size;;!'), 0)
        self.assertEqual(default_palette(''), 0)
        send = Mock()
        status = Mock(return_value={'effects': ['Solid', 'Rainbow', 'Aurora'], 'state': {}})
        fxdata = Mock(return_value=['', '!,Size;;!', '!,!;1,2,3;!;;sx=24,pal=50'])
        browser = EffectBrowser(send, status, [(0, 'Solid')], fxdata=fxdata)
        browser.refresh()
        browser._thread.join(2)
        browser.rotate(2, 10.0)
        self.assertEqual(send.call_args.args[0]['seg'][0], {'id': 0, 'fx': 2, 'fxdef': True, 'pal': 50})
        browser.rotate(-1, 20.0)
        self.assertEqual(send.call_args.args[0]['seg'][0]['pal'], 0)

    def test_library_effects_set_their_palette(self):
        for effect in load_effects(config.EFFECTS_FILE):
            for segment in effect['state'].get('seg', []):
                self.assertIn('pal', segment, effect['id'])

    def test_browser_keeps_working_when_the_device_is_silent(self):
        browser = EffectBrowser(Mock(), Mock(return_value=None), [(0, 'Solid'), (9, 'Rainbow')])
        browser.refresh()
        browser._thread.join(2)
        self.assertFalse(browser.live)
        self.assertEqual(browser.rotate(1, 1.0), '2/2 Rainbow')

    def test_wled_manager_builds_url_and_activates_preset(self):
        delivered = threading.Event()
        with patch('lighting.urlopen') as open_url:
            response = Mock()
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


class AudioTests(unittest.TestCase):
    def test_audio_process_reaped(self):
        with patch('audio.subprocess.Popen') as spawn:
            process = spawn.return_value
            process.poll.return_value = None
            player = AudioPlayer('default')
            player.play('mp3/xmas/default.mp3')
            player.stop()
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=1)
            self.assertFalse(player.is_playing)

    def test_audio_play_sends_silence_volume_and_load(self):
        with patch('audio.subprocess.Popen') as spawn:
            process = spawn.return_value
            process.poll.return_value = None
            player = AudioPlayer('default')
            player.set_volume(30)
            player.play('mp3/xmas/default.mp3')
            sent = process.stdin.write.call_args_list[0].args[0]
            self.assertIn('SILENCE', sent)
            self.assertIn('VOLUME 30', sent)
            self.assertIn(f'LOAD {config.BASE_DIR / "mp3/xmas/default.mp3"}', sent)
            self.assertEqual(player.set_volume(150), 100)
            process.stdin.write.assert_called_with('VOLUME 100\n')
            player.stop()

    def test_finished_follows_status_lines(self):
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
            player.play('mp3/xmas/default.mp3')
            self.assertFalse(player.finished)
            for _ in range(200):
                if player.is_playing:
                    break
                time.sleep(0.01)
            self.assertTrue(player.is_playing)
            self.assertFalse(player.finished)
            hold.set()
            for _ in range(200):
                if player.finished:
                    break
                time.sleep(0.01)
            self.assertTrue(player.finished)
            self.assertFalse(player.is_playing)
            player.stop()


class ChimeTests(unittest.TestCase):
    def test_chime_plays_click_via_aplay(self):
        with patch('chime.subprocess.Popen') as spawn:
            chime.play_click()
            args = spawn.call_args.args[0]
            self.assertEqual(args[0], 'aplay')
            self.assertIn(str(chime.CLICK_SOUND), args)

    def test_chime_ignores_a_busy_audio_device(self):
        with patch('chime.subprocess.Popen', side_effect=OSError('busy')):
            chime.play_click()


if __name__ == '__main__':
    unittest.main()
