"""Native Windows configuration, credentials and privilege observation contracts."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.config_manager import ConfigManager, _CONFIG_MAX_BYTES
from src.system_utils import SystemUtils


@unittest.skipUnless(os.name == 'nt', 'Native Windows configuration requires Windows')
class TestNativeWindowsConfiguration(unittest.TestCase):
    def setUp(self):
        from src.platform import windows_files
        self.files = windows_files
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'private configuration with spaces'
        self.files.ensure_private_directory(self.directory)
        self.path = self.directory / 'config.json'
        self.managers = []
        self.addCleanup(self.flush_managers)

    def flush_managers(self):
        for manager in self.managers:
            manager.flush()

    def manager(self):
        manager = ConfigManager(str(self.path))
        self.managers.append(manager)
        return manager

    def write_private(self, path, contents):
        descriptor = self.files.open_regular(path, writable=True, create=True, exclusive=True, private=True)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(contents)

    def test_initial_configuration_without_dotenv_and_credential_roundtrip(self):
        manager = self.manager()
        self.assertIsNone(manager.last_save_error)
        manager.set_api_key('openrouter', 'synthetic-windows-key')
        manager.set('ui.font_size', 17)
        self.assertTrue(manager.flush())
        reloaded = self.manager()
        self.assertEqual(reloaded.get_stored_api_key('openrouter'), 'synthetic-windows-key')
        self.assertEqual(reloaded.get_config_value('ui.font_size'), 17)
        # Validation of the native ACL is part of opening a private object.
        descriptor = self.files.open_regular(self.path, private=True)
        os.close(descriptor)

    def test_empty_dotenv_edit_preserves_bytes_and_updates_process_override(self):
        name = ConfigManager._env_name('api.providers.openrouter.api_key')
        original = ('# comentário\r\n' + name + '=\r\nOTHER_SETTING=retained\r\n').encode('utf-8')
        dotenv = self.directory / '.env'
        self.write_private(dotenv, original)
        with patch.dict(os.environ):
            os.environ.pop(name, None)
            manager = self.manager()
            self.assertEqual(os.environ.get(name), '')
            self.assertTrue(manager.can_remove_empty_api_key_override('openrouter'))
            manager.remove_empty_api_key_override('openrouter')
            self.assertEqual(dotenv.read_bytes(), '# comentário\r\nOTHER_SETTING=retained\r\n'.encode('utf-8'))
            self.assertNotIn(name, os.environ)
            self.assertFalse(manager.can_remove_empty_api_key_override('openrouter'))

    def test_failed_publication_keeps_previous_configuration(self):
        manager = self.manager()
        before = self.path.read_bytes()
        manager.set('ui.font_size', 19)
        with patch('src.platform.windows_files.publish_temporary', side_effect=OSError('publication denied')):
            self.assertFalse(manager.flush())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNotNone(manager.last_save_error)
        self.assertEqual(list(self.directory.glob('config.json.*.tmp')), [])
        self.assertTrue(manager.flush())
        self.assertEqual(json.loads(self.path.read_bytes())['ui']['font_size'], 19)

    def test_corrupt_private_configuration_is_preserved_before_recovery(self):
        self.write_private(self.path, b'{invalid json')
        manager = self.manager()
        self.assertIsNone(manager.last_save_error)
        backups = list(self.directory.glob('config.json.corrupt-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'{invalid json')
        self.assertIsInstance(json.loads(self.path.read_bytes()), dict)

    def test_size_limit_keeps_previous_configuration_loadable(self):
        manager = self.manager()
        original = self.path.read_bytes()
        manager.set('app.name', 'x' * _CONFIG_MAX_BYTES)
        self.assertFalse(manager.flush())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.directory.glob('config.json.*.tmp')), [])
        manager.set('app.name', 'WinLinAI')
        self.assertTrue(manager.flush())

    def test_verification_failure_reports_publication_without_losing_new_snapshot(self):
        manager = self.manager()
        manager.set('ui.font_size', 18)
        with patch('src.platform.windows_files.sync_publication', side_effect=OSError('verification failed')):
            self.assertFalse(manager.flush())
        self.assertIn('published', manager.last_save_error)
        self.assertEqual(json.loads(self.path.read_bytes())['ui']['font_size'], 18)
        self.assertTrue(manager.flush())

    def test_system_utilities_construct_without_unix_identity_calls(self):
        utilities = SystemUtils(self.manager())
        self.assertIsInstance(utilities.is_root, bool)
        self.assertTrue(utilities.username)


if __name__ == '__main__':
    unittest.main()
