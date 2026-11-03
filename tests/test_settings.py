import json
import unittest
import config
import settings
from helpers import TempSettingsTestCase


class SettingsTests(TempSettingsTestCase):
    def test_versioned_defaults_are_valid(self):
        defaults = settings.defaults()
        for section, validate in settings.VALIDATORS.items():
            with self.subTest(section=section):
                validate(defaults[section], strict=True)

    def test_keys_reference_existing_effects(self):
        ids = {effect['id'] for effect in settings.get('effects')}
        for key, action in settings.get('keys').items():
            if action['type'] == 'effect':
                self.assertIn(action['effect'], ids, key)
        self.assertIn(settings.get('wake')['effect'] or 'off', ids)
        for program in settings.get('programs'):
            self.assertIn(program['effect'], ids, program['label'])

    def test_overrides_merge_dicts_and_replace_lists(self):
        settings.save('wake', {**settings.get('wake'), 'volume_end': 40})
        self.assertEqual(settings.get('wake')['volume_end'], 40)
        self.assertEqual(settings.get('wake')['snooze_minutes'], 9)
        stored = json.loads(self.settings_path.read_text())
        self.assertEqual(list(stored), ['wake'])
        settings.save('alarms', [{'label': 'Nur einer', 'time': '7:05', 'days': [4, 0, 0]}])
        alarms = settings.get('alarms')
        self.assertEqual(len(alarms), 1)
        self.assertEqual(alarms[0]['time'], '07:05')
        self.assertEqual(alarms[0]['days'], [0, 4])
        self.assertTrue(alarms[0]['id'])

    def test_save_rejects_invalid_values_with_german_messages(self):
        cases = [
            ('alarms', [{'time': '25:00', 'days': [0]}], 'Uhrzeit'),
            ('alarms', [{'time': '06:00', 'days': [7]}], 'Wochentage'),
            ('wake', {**settings.get('wake'), 'brightness_end': 0}, 'Helligkeit Ende'),
            ('wake', {**settings.get('wake'), 'music': 'loud'}, 'music'),
            ('wled', {'enabled': True, 'host': 'bad host', 'timeout': 3}, 'Hostname'),
            ('keys', {'1': {'type': 'http', 'url': 'ftp://x'}}, 'Taste 1'),
            ('keys', {'A': {'type': 'home_assistant', 'service': 'toggle', 'entity_id': 'x'}}, 'Service'),
            ('keys', {'B': {'type': 'alexa', 'command': 'text', 'text': ''}}, 'Taste B'),
            ('music', {**settings.get('music'), 'default_song': '../../etc/passwd.mp3'}, 'Musikordner'),
            ('effects', [], 'Mindestens'),
        ]
        for section, value, fragment in cases:
            with self.subTest(section=section, fragment=fragment):
                with self.assertRaises(ValueError) as caught:
                    settings.save(section, value)
                self.assertIn(fragment, str(caught.exception))
        self.assertFalse(self.settings_path.exists())

    def test_broken_or_invalid_file_falls_back_per_field(self):
        self.settings_path.write_text('{broken')
        self.assertEqual(settings.get('wled')['host'], 'wled.local')
        self.settings_path.write_text(json.dumps({
            'wled': {'enabled': False, 'host': 'bad host', 'timeout': 'NaN'},
            'alarms': [{'time': '07:00', 'days': [0]}, {'time': 'kaputt'}],
            'keys': {'1': {'type': 'unknown'}},
        }))
        self.assertEqual(settings.get('wled'), {'enabled': False, 'host': 'wled.local', 'timeout': 3.0})
        alarms = settings.get('alarms')
        self.assertEqual([alarm['time'] for alarm in alarms], ['07:00'])
        self.assertEqual(settings.get('keys')['1'], {'type': 'none'})

    def test_reset_restores_defaults(self):
        settings.save('greetings', [{'start': '00:00', 'end': '00:00', 'text': 'Hallo', 'backlight': True}])
        self.assertEqual(settings.get('greetings')[0]['text'], 'Hallo')
        settings.reset('greetings')
        self.assertEqual(settings.get('greetings')[0]['text'], 'Guten Morgen')

    def test_cache_notices_external_writes(self):
        self.assertTrue(settings.get('alarms_enabled'))
        settings.write_json(self.settings_path, {'alarms_enabled': False})
        self.assertFalse(settings.get('alarms_enabled'))

    def test_migrates_legacy_settings_and_mapping(self):
        settings.write_json(config.LEGACY_SETTINGS_FILE, {
            'hour': 7, 'minute': 30, 'enabled': False,
            'wled': {'enabled': True, 'host': '10.150.1.50', 'timeout': 3.0}})
        settings.write_json(config.LEGACY_MAPPING_FILE, {
            '12-11': {'file': 'mp3/xmas/polar_express.mp3', 'message': 'Neu'},
            '2026-01-01': 'xmas/maria.mp3'})
        messages = settings.migrate_legacy()
        self.assertEqual(len(messages), 2)
        alarm = settings.get('alarms')[0]
        self.assertEqual((alarm['time'], alarm['enabled']), ('07:30', False))
        self.assertEqual(settings.get('wled')['host'], '10.150.1.50')
        dates = {entry['date']: entry for entry in settings.get('music')['dates']}
        self.assertEqual(dates['12-11']['message'], 'Neu')
        self.assertEqual(dates['2026-01-01']['file'], 'mp3/xmas/maria.mp3')
        self.assertIn('12-12', dates)
        self.assertFalse(config.LEGACY_SETTINGS_FILE.exists())
        self.assertTrue(config.LEGACY_SETTINGS_FILE.with_name('legacy_settings.json.migrated').exists())
        self.assertEqual(settings.migrate_legacy(), [])

    def test_action_labels_and_unknown_fields(self):
        action = settings.validate_action({'type': 'music', 'source': 'random', 'label': ' Zufall ',
                                           'evil': 1})
        self.assertEqual(action, {'type': 'music', 'source': 'random', 'label': 'Zufall'})


if __name__ == '__main__':
    unittest.main()
