"""Tests for Windows file actions (src/windows_file_actions.py)."""
import os
import tempfile
import unittest
from pathlib import Path

from src.windows_file_actions import (
    is_windows,
    get_user_home,
    normalize_windows_path,
    is_sensitive_windows_path,
    is_allowed_windows_path,
    is_privileged_windows_path,
    file_digest,
    preview_diff,
    make_backup,
    write_file_safe,
    read_file_preview,
    list_directory,
    delete_file_safe,
    get_file_info,
    WindowsFileActions,
)


class TestIsWindows(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIsInstance(is_windows(), bool)


class TestGetUserHome(unittest.TestCase):
    def test_returns_path(self):
        home = get_user_home()
        self.assertIsInstance(home, Path)
        self.assertTrue(home.exists())


class TestNormalizeWindowsPath(unittest.TestCase):
    def test_expands_tilde(self):
        result = normalize_windows_path("~/test.txt")
        self.assertNotIn("~", str(result))

    def test_expands_env_vars(self):
        # %USERPROFILE% or $USERPROFILE should be expanded
        result = normalize_windows_path("%USERPROFILE%\\test.txt")
        self.assertNotIn("%", str(result))

    def test_normalizes_slashes(self):
        result = normalize_windows_path("C:/Users/test/file.txt")
        # Should normalize to backslashes on Windows
        self.assertIn("file.txt", str(result))

    def test_resolves_relative(self):
        result = normalize_windows_path("./test.txt")
        self.assertTrue(os.path.isabs(str(result)))

    def test_removes_dot_segments(self):
        result = normalize_windows_path("C:\\Users\\..\\Users\\test.txt")
        self.assertNotIn("..", str(result))


class TestIsSensitiveWindowsPath(unittest.TestCase):
    def test_system32_blocked(self):
        self.assertTrue(is_sensitive_windows_path(r"C:\Windows\System32\test.dll"))

    def test_program_files_blocked(self):
        self.assertTrue(is_sensitive_windows_path(r"C:\Program Files\app\file.exe"))

    def test_registry_hive_blocked(self):
        self.assertTrue(is_sensitive_windows_path(r"C:\Windows\System32\config\SAM"))

    def test_pagefile_blocked(self):
        self.assertTrue(is_sensitive_windows_path(r"C:\pagefile.sys"))

    def test_ssh_dir_blocked(self):
        self.assertTrue(is_sensitive_windows_path(r"C:\Users\test\.ssh\id_rsa"))

    def test_gnupg_dir_blocked(self):
        self.assertTrue(is_sensitive_windows_path(r"C:\Users\test\.gnupg\secring.gpg"))

    def test_aws_credentials_blocked(self):
        self.assertTrue(is_sensitive_windows_path(r"C:\Users\test\.aws\credentials"))

    def test_user_file_allowed(self):
        self.assertFalse(is_sensitive_windows_path(r"C:\Users\test\Documents\file.txt"))

    def test_desktop_allowed(self):
        self.assertFalse(is_sensitive_windows_path(r"C:\Users\test\Desktop\file.txt"))

    def test_invalid_path_fails_closed(self):
        self.assertTrue(is_sensitive_windows_path(""))
        self.assertTrue(is_sensitive_windows_path(None))  # type: ignore
        self.assertTrue(is_sensitive_windows_path(123))  # type: ignore


class TestIsAllowedWindowsPath(unittest.TestCase):
    def test_home_allowed(self):
        home = get_user_home()
        path = str(home / "Documents" / "test.txt")
        self.assertTrue(is_allowed_windows_path(path))

    def test_outside_home_blocked(self):
        self.assertFalse(is_allowed_windows_path(r"C:\Windows\Temp\test.txt"))

    def test_allowed_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            self.assertTrue(is_allowed_windows_path(path, [tmpdir]))

    def test_sensitive_blocked_even_in_allowed(self):
        # Even if System32 is in allowed_dirs, sensitive check should block
        self.assertFalse(is_allowed_windows_path(
            r"C:\Windows\System32\test.dll",
            [r"C:\Windows\System32"]
        ))


class TestIsPrivilegedWindowsPath(unittest.TestCase):
    def test_home_not_privileged(self):
        home = get_user_home()
        path = str(home / "test.txt")
        self.assertFalse(is_privileged_windows_path(path))

    def test_outside_home_privileged(self):
        self.assertTrue(is_privileged_windows_path(r"C:\Windows\Temp\test.txt"))


class TestFileDigest(unittest.TestCase):
    def test_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test content")
            path = f.name
        try:
            digest = file_digest(path)
            self.assertIsNotNone(digest)
            self.assertEqual(len(digest), 64)  # SHA-256 hex
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        self.assertIsNone(file_digest(r"C:\nonexistent\file.txt"))


class TestPreviewDiff(unittest.TestCase):
    def test_new_file_returns_none(self):
        self.assertIsNone(preview_diff(r"C:\nonexistent\file.txt", "content"))

    def test_existing_file_returns_diff(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
            f.write("old content\n")
            path = f.name
        try:
            diff = preview_diff(path, "new content\n")
            self.assertIsNotNone(diff)
            self.assertIn("old content", diff)
            self.assertIn("new content", diff)
        finally:
            os.unlink(path)


class TestMakeBackup(unittest.TestCase):
    def test_creates_backup(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
            f.write("original")
            path = f.name
        try:
            backup = make_backup(path)
            self.assertIsNotNone(backup)
            self.assertTrue(os.path.exists(backup))
            with open(backup, "r") as bf:
                self.assertEqual(bf.read(), "original")
            os.unlink(backup)
        finally:
            os.unlink(path)

    def test_nonexistent_returns_none(self):
        self.assertIsNone(make_backup(r"C:\nonexistent\file.txt"))


class TestWriteFileSafe(unittest.TestCase):
    def test_write_new_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            success, message, backup = write_file_safe(path, "Hello, World!")
            self.assertTrue(success)
            self.assertIsNone(backup)  # No backup for new file
            with open(path, "r") as f:
                self.assertEqual(f.read(), "Hello, World!")

    def test_write_existing_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            with open(path, "w") as f:
                f.write("original")
            success, message, backup = write_file_safe(path, "updated")
            self.assertTrue(success)
            self.assertIsNotNone(backup)
            self.assertTrue(os.path.exists(backup))
            with open(path, "r") as f:
                self.assertEqual(f.read(), "updated")
            os.unlink(backup)

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "subdir", "nested", "test.txt")
            success, message, _backup = write_file_safe(path, "content")
            self.assertTrue(success)
            self.assertTrue(os.path.exists(path))


class TestReadFilePreview(unittest.TestCase):
    def test_read_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
            f.write("test content")
            path = f.name
        try:
            success, content, truncated = read_file_preview(path)
            self.assertTrue(success)
            self.assertEqual(content, "test content")
            self.assertFalse(truncated)
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        success, content, truncated = read_file_preview(r"C:\nonexistent.txt")
        self.assertFalse(success)

    def test_truncation(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
            f.write("x" * 2000)
            path = f.name
        try:
            success, content, truncated = read_file_preview(path, max_bytes=100)
            self.assertTrue(success)
            self.assertTrue(truncated)
            self.assertEqual(len(content), 100)
        finally:
            os.unlink(path)


class TestListDirectory(unittest.TestCase):
    def test_list_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files
            Path(tmpdir, "file1.txt").write_text("content")
            Path(tmpdir, "file2.txt").write_text("content")
            Path(tmpdir, "subdir").mkdir()

            success, items, error = list_directory(tmpdir)
            self.assertTrue(success)
            self.assertIsNone(error)
            self.assertEqual(len(items), 3)
            names = [item["name"] for item in items]
            self.assertIn("file1.txt", names)
            self.assertIn("subdir", names)

    def test_not_a_directory(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            success, items, error = list_directory(path)
            self.assertFalse(success)
            self.assertEqual(items, [])
        finally:
            os.unlink(path)


class TestDeleteFileSafe(unittest.TestCase):
    def test_delete_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            path = f.name
        success, message, backup = delete_file_safe(path)
        self.assertTrue(success)
        self.assertFalse(os.path.exists(path))
        self.assertIsNotNone(backup)
        if backup:
            os.unlink(backup)

    def test_nonexistent_file(self):
        success, message, backup = delete_file_safe(r"C:\nonexistent.txt")
        self.assertFalse(success)


class TestGetFileInfo(unittest.TestCase):
    def test_file_info(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test")
            path = f.name
        try:
            info = get_file_info(path)
            self.assertIsNotNone(info)
            self.assertTrue(info["is_file"])
            self.assertEqual(info["size"], 4)
            self.assertIsNotNone(info["digest"])
        finally:
            os.unlink(path)

    def test_nonexistent(self):
        self.assertIsNone(get_file_info(r"C:\nonexistent.txt"))


class TestWindowsFileActions(unittest.TestCase):
    def setUp(self):
        self.actions = WindowsFileActions()

    def test_is_allowed(self):
        home = get_user_home()
        path = str(home / "test.txt")
        self.assertTrue(self.actions.is_allowed(path))

    def test_write_file_cancelled(self):
        home = get_user_home()
        path = str(home / "test_cancel.txt")
        # Always return False (cancel)
        result, message = self.actions.write_file(
            path, "content",
            confirm_callback=lambda p, c, is_new: False
        )
        self.assertEqual(result, "cancelled")

    def test_write_file_confirmed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            actions = WindowsFileActions(allowed_dirs=[tmpdir])
            path = os.path.join(tmpdir, "test.txt")
            # Always return True (confirm)
            result, message = actions.write_file(
                path, "content",
                confirm_callback=lambda p, c, is_new: True
            )
            self.assertEqual(result, "written")
            with open(path, "r") as f:
                self.assertEqual(f.read(), "content")

    def test_write_file_not_allowed(self):
        result, message = self.actions.write_file(
            r"C:\Windows\System32\test.txt", "content"
        )
        self.assertEqual(result, "error")
        self.assertIn("not allowed", message.lower())

    def test_read_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
            f.write("test content")
            path = f.name
        try:
            actions = WindowsFileActions(allowed_dirs=[os.path.dirname(path)])
            success, content = actions.read_file(path)
            self.assertTrue(success)
            self.assertEqual(content, "test content")
        finally:
            os.unlink(path)

    def test_delete_file_cancelled(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            path = f.name
        try:
            actions = WindowsFileActions(allowed_dirs=[os.path.dirname(path)])
            result, message = actions.delete_file(
                path,
                confirm_callback=lambda p: False
            )
            self.assertEqual(result, "cancelled")
            self.assertTrue(os.path.exists(path))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
