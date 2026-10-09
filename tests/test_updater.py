"""Tests for the updater module (src/updater.py)."""
import unittest
from unittest.mock import Mock, patch

from src.updater import (
    is_windows,
    get_current_version,
    parse_version,
    is_newer_version,
    _safe_url,
    official_release_url,
    _is_windows_installer_asset,
    check_for_updates,
    check_and_notify,
    GITHUB_REPO,
    GITHUB_RELEASES_URL,
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
        self.assertFalse(_safe_url("http://github.com/1400015/winlinai"))
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
    def test_not_windows_returns_unsupported(self):
        """Off Windows no check happens: neither failed nor 'up to date'."""
        with patch('src.updater.is_windows', return_value=False):
            result = check_for_updates()
        self.assertEqual(result["status"], "unsupported")

    def test_api_failure_returns_failed(self):
        """A network failure is 'failed', never 'current'."""
        with patch('src.updater.is_windows', return_value=True):
            with patch('urllib.request.urlopen', side_effect=Exception("network error")):
                result = check_for_updates()
        self.assertEqual(result["status"], "failed")

    def test_same_version_returns_current(self):
        with patch('src.updater.is_windows', return_value=True):
            with patch('src.updater.get_current_version', return_value="1.5.0"):
                mock_response = Mock()
                mock_response.read.return_value = b'{"tag_name": "v1.5.0"}'
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
                with patch('urllib.request.urlopen', return_value=mock_response):
                    result = check_for_updates()
        self.assertEqual(result["status"], "current")
        self.assertEqual(result["version"], "1.5.0")

    def test_newer_version_returns_available(self):
        with patch('src.updater.is_windows', return_value=True):
            with patch('src.updater.get_current_version', return_value="1.4.2"):
                mock_response = Mock()
                mock_response.read.return_value = (
                    b'{"tag_name": "v1.5.0",'
                    b' "html_url": "https://github.com/1400015/winlinai/releases/tag/v1.5.0",'
                    b' "assets": []}')
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
                with patch('urllib.request.urlopen', return_value=mock_response):
                    result = check_for_updates()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["version"], "1.5.0")
        self.assertEqual(
            result["url"],
            "https://github.com/1400015/winlinai/releases/tag/v1.5.0")

    def test_foreign_release_page_uses_the_official_url(self):
        with patch('src.updater.is_windows', return_value=True):
            with patch('src.updater.get_current_version', return_value="1.4.2"):
                mock_response = Mock()
                mock_response.read.return_value = (
                    b'{"tag_name": "v1.5.0", "html_url": "https://example.com/r",'
                    b' "assets": []}')
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
                with patch('urllib.request.urlopen', return_value=mock_response):
                    result = check_for_updates()
        self.assertEqual(result["url"], GITHUB_RELEASES_URL)

    def test_empty_tag_returns_failed(self):
        with patch('src.updater.is_windows', return_value=True):
            with patch('src.updater.get_current_version', return_value="1.4.2"):
                mock_response = Mock()
                mock_response.read.return_value = b'{"tag_name": ""}'
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
                with patch('urllib.request.urlopen', return_value=mock_response):
                    result = check_for_updates()
        self.assertEqual(result["status"], "failed")

    def test_bad_json_returns_failed(self):
        with patch('src.updater.is_windows', return_value=True):
            with patch('src.updater.get_current_version', return_value="1.4.2"):
                mock_response = Mock()
                mock_response.read.return_value = b'not json'
                mock_response.__enter__ = Mock(return_value=mock_response)
                mock_response.__exit__ = Mock(return_value=False)
                with patch('urllib.request.urlopen', return_value=mock_response):
                    result = check_for_updates()
        self.assertEqual(result["status"], "failed")


class TestOfficialReleaseUrl(unittest.TestCase):
    def test_keeps_this_repository(self):
        url = "https://github.com/1400015/winlinai/releases/tag/v1.5.0"
        self.assertEqual(official_release_url(url), url)

    def test_rejects_a_lookalike_repository(self):
        self.assertEqual(
            official_release_url("https://github.com/1400015/winlinai-evil/releases"),
            GITHUB_RELEASES_URL)

    def test_rejects_plain_http(self):
        self.assertEqual(
            official_release_url("http://github.com/1400015/winlinai/releases"),
            GITHUB_RELEASES_URL)

    def test_rejects_a_path_that_leaves_the_repository(self):
        escaped = (
            "https://github.com/1400015/winlinai/releases/tag/v1.5.0"
            "/../../evil")
        encoded = "https://github.com/1400015/winlinai/%2e%2e/%2e%2e/evil"
        with_user = "https://user@github.com/1400015/winlinai/releases"
        self.assertEqual(official_release_url(escaped), GITHUB_RELEASES_URL)
        self.assertEqual(official_release_url(encoded), GITHUB_RELEASES_URL)
        self.assertEqual(official_release_url(with_user), GITHUB_RELEASES_URL)


class TestCheckAndNotify(unittest.TestCase):
    def test_available_is_stored_and_announced(self):
        config = Mock()
        update = {
            "status": "available",
            "version": "9.9.9",
            "url": GITHUB_RELEASES_URL,
        }
        with patch("src.updater.check_for_updates", return_value=update):
            result = check_and_notify(config)
        self.assertEqual(result["status"], "available")
        config.set.assert_any_call("update.available", True)
        config.set.assert_any_call("update.version", "9.9.9")
        config.set.assert_any_call("update.url", GITHUB_RELEASES_URL)

    def test_current_clears_a_stale_update(self):
        config = Mock()
        with patch("src.updater.check_for_updates",
                   return_value={"status": "current", "version": "1.4.2"}):
            result = check_and_notify(config)
        self.assertEqual(result["status"], "current")
        config.set.assert_called_once_with("update.available", False)

    def test_failed_and_unsupported_leave_the_stored_update(self):
        for status in ("failed", "unsupported"):
            with self.subTest(status=status):
                config = Mock()
                with patch("src.updater.check_for_updates",
                           return_value={"status": status}):
                    result = check_and_notify(config)
                self.assertEqual(result["status"], status)
                config.set.assert_not_called()


class TestConstants(unittest.TestCase):
    def test_github_repo(self):
        self.assertEqual(GITHUB_REPO, "1400015/winlinai")

    def test_allowed_hosts(self):
        self.assertIn("github.com", ALLOWED_HOSTS)
        self.assertIn("objects.githubusercontent.com", ALLOWED_HOSTS)
        self.assertIn("api.github.com", ALLOWED_HOSTS)


if __name__ == "__main__":
    unittest.main()


class TestUpdateStatusPhrase(unittest.TestCase):
    """The pure phrase chooser: a failure is never 'up to date'."""

    def _phrase(self, update):
        from src.qt_dialogs import update_status_phrase
        return update_status_phrase(update, current_version="1.4.2")

    def test_failed_phrase_is_never_up_to_date(self):
        phrase = self._phrase({"status": "failed"})
        self.assertNotIn("up to date", phrase.lower())
        self.assertIn("could not check", phrase.lower())

    def test_current_phrase_says_up_to_date(self):
        phrase = self._phrase({"status": "current", "version": "1.4.2"})
        self.assertIn("up to date", phrase.lower())
        self.assertIn("1.4.2", phrase)

    def test_available_phrase_carries_the_new_version(self):
        phrase = self._phrase({"status": "available", "version": "9.9.9"})
        self.assertIn("9.9.9", phrase)
        self.assertIn("available", phrase.lower())

    def test_unsupported_is_neutral(self):
        phrase = self._phrase({"status": "unsupported"})
        self.assertNotIn("up to date", phrase.lower())

    def test_none_result_is_neutral(self):
        phrase = self._phrase(None)
        self.assertNotIn("up to date", phrase.lower())
