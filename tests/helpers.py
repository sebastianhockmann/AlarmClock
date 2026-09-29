"""Gemeinsame Test-Hilfen: Einstellungen in ein temporaeres Verzeichnis umleiten."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class TempSettingsTestCase(unittest.TestCase):
    """Jeder Test bekommt eine leere config/settings.json im Temp-Verzeichnis.

    defaults.json und effects.json bleiben die echten, versionierten Dateien -
    so pruefen die Tests nebenbei, dass sie gueltig sind.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.dir = Path(temporary.name)
        self.settings_path = self.dir / 'settings.json'
        for target, value in (('config.SETTINGS_FILE', self.settings_path),
                              ('config.LEGACY_SETTINGS_FILE', self.dir / 'legacy_settings.json'),
                              ('config.LEGACY_MAPPING_FILE', self.dir / 'legacy_mapping.json')):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
