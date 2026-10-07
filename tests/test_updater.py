"""Tests for the updater module (src/updater.py)."""
import unittest
from unittest.mock import Mock, patch

from src.updater import (
    is_windows,
    get_current_version,
    parse_version,
    is_newer_version,
    _safe_url,
    _is_windows_installer_asset,
    check_for_updates,
    verify_checksum,
    get_update_downloads_dir,
    GITHUB_REPO,
    ALLOWED_HOSTS,
)


class TestIsWindows(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIsInstance(is_windows(), bool)


class TestGetCurrentVersion(unittest.TestCase):
    def test_returns_string(self):
        version = get_current_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)


class TestParseVersion(unittest.TestCase):
    def test_simple_version(self):
        self.assertEqual(parse_version("1.4.2"), (1, 4, 2))

    def test_version_with_prerelease(self):
        self.assertEqual(parse_version("1.4.2-beta"), (1, 4, 2))
        self.assertEqual(parse_version("1.4.2-beta.1"), (1, 4, 2))

    def test_version_with_build(self):
        self.assertEqual(parse_version("1.4.2+build123"), (1, 4, 2))

    def test_invalid_version(self):
        self.assertEqual(parse_version("invalid"), (0,))
        self.assertEqual(parse_version("1.x.2"), (1, 0, 2))

    def test_empty_version(self):
        self.assertEqual(parse_version(""), (0,))


class TestIsNewerVersion(unittest.TestCase):
    def test_newer_patch(self):
        self.assertTrue(is_newer_version("1.4.2", "1.4.3"))

    def test_newer_minor(self):
        self.assertTrue(is_newer_version("1.4.2", "1.5.0"))

    def test_newer_major(self):
        self.assertTrue(is_newer_version("1.4.2", "2.0.0"))

    def test_same_version(self):
        self.assertFalse(is_newer_version("1.4.2", "1.4.2"))

    def test_older_version(self):
        self.assertFalse(is_newer_version("1.5.0", "1.4.2"))

    def test_prerelease_ignored(self):
        self.assertFalse(is_newer_version("1.4.2", "1.4.2-beta"))
        self.assertTrue(is_newer_version("1.4.2-beta", "1.4.3"))


class TestSafeUrl(unittest.TestCase):
    def test_github_allowed(self):
        self.assertTrue(_safe_url("https://github.com/1400015/winlinai/releases"))
        self.assertTrue(_safe_url("https://objects.githubusercontent.com/..."))
        self.assertTrue(_safe_url("https://api.github.com/repos/..."))

    def test_other_hosts_blocked(self):
        self.assertFalse(_safe_url("https://evil.com/malware.exe"))
        self.assertFalse(_safe_url("http://github.com.evil.com/"))
        self.assertFalse(_safe_url("file:///C:/Windows/System32/calc.exe"))

    def test_invalid_url(self):
        self.assertFalse(_safe_url("not a url"))
        self.assertFalse(_safe_url(""))


class TestIsWindowsInstallerAsset(unittest.TestCase):
    def test_setup_exe_accepted(self):
        self.assertTrue(_is_windows_installer_asset("WinLinAI-1.5.0-Setup.exe"))

    def test_windows_exe_accepted(self):
        self.assertTrue(_is_windows_installer_asset("WinLinAI-1.5.0-windows.exe"))

    def test_winlinai_exe_accepted(self):
        self.assertTrue(_is_windows_installer_asset("winlinai-setup.exe"))

    def test_case_insensitive(self):
        self.assertTrue(_is_windows_installer_asset("WINLINAI-SETUP.EXE"))

    def test_non_exe_rejected(self):
        self.assertFalse(_is_windows_installer_asset("WinLinAI-1.5.0-Setup.deb"))
        self.assertFalse(_is_windows_installer_asset("WinLinAI-1.5.0-Setup.dmg"))
        self.assertFalse(_is_windows_installer_asset("winlinai-setup.zip"))

    def test_random_exe_rejected(self):
        self.assertFalse(_is_windows_installer_asset("random-tool.exe"))
        self.assertFalse(_is_windows_installer_asset("malware.exe"))

    def test_non_string_rejected(self):
        self.assertFalse(_is_windows_installer_asset(None))
        self.assertFalse(_is_windows_installer_asset(123))

    def test_empty_rejected(self):
        self.assertFalse(_is_windows_installer_asset(""))


class TestCheckForUpdates(unittest.TestCase):
    def test_not_windows_returns_none(self):
        with patch('src.updater.is_windows', return_value=False):
            self.assertIsNone(check_for_updates())

    def test_api_failure_returns_none(self):
        with patch('src.updater.is_windows', return_value=True):
            with patch('urllib.request.urlopen', side_effect=Exception("network error")):
                self.assertIsNone(check_for_updates())

    def test_same_version_returns_none(self):
        with patch('src.updater.is_windows', return_value=True):
            with patch('src.updater.get_current_version', return_value="1.5.0"):
                mock_response = Mock()
                mock_response.read.return_value = b'{"tag_name": "v1.5.0"}'
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
                with patch('urllib.request.urlopen', return_value=mock_response):
                    self.assertIsNone(check_for_updates())


class TestVerifyChecksum(unittest.TestCase):
    def test_valid_checksum(self):
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test content")
            path = f.name
        try:
            import hashlib
            expected = hashlib.sha256(b"test content").hexdigest()
            self.assertTrue(verify_checksum(path, expected))
        finally:
            os.unlink(path)

    def test_invalid_checksum(self):
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test content")
            path = f.name
        try:
            self.assertFalse(verify_checksum(path, "0" * 64))
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        self.assertFalse(verify_checksum(r"C:\nonexistent.txt", "0" * 64))


class TestGetUpdateDownloadsDir(unittest.TestCase):
    def test_creates_directory(self):
        path = get_update_downloads_dir()
        self.assertTrue(path.exists())
        self.assertTrue(path.is_dir())
        self.assertIn("WinLinAI", str(path))
        self.assertIn("Updates", str(path))


class TestConstants(unittest.TestCase):
    def test_github_repo(self):
        self.assertEqual(GITHUB_REPO, "1400015/winlinai")

    def test_allowed_hosts(self):
        self.assertIn("github.com", ALLOWED_HOSTS)
        self.assertIn("objects.githubusercontent.com", ALLOWED_HOSTS)
        self.assertIn("api.github.com", ALLOWED_HOSTS)


if __name__ == "__main__":
    unittest.main()
