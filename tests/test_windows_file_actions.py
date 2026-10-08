"""Tests for Windows file actions (src/windows_file_actions.py)."""
import os
import shutil
import tempfile
import unittest
import unittest.mock
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
        # %USERPROFILE% expands to the variable defined in this test
        with unittest.mock.patch.dict(os.environ, {"USERPROFILE": "C:\\Users\\test"}):
            result = normalize_windows_path("%USERPROFILE%\\test.txt")
        self.assertEqual(str(result), "C:\\Users\\test\\test.txt")

    def test_unknown_env_var_keeps_token_and_fails_closed(self):
        # An undefined %VAR% must not be silently emptied into another path
        env = {k: v for k, v in os.environ.items() if k != "WINLINAI_MISSING_VAR"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(is_sensitive_windows_path(r"%WINLINAI_MISSING_VAR%\\test.txt"))
            self.assertFalse(is_allowed_windows_path(r"%WINLINAI_MISSING_VAR%\\test.txt"))

    def test_home_containment_is_case_insensitive(self):
        home = str(get_user_home())
        variant = "".join(
            c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(home))
        self.assertTrue(is_allowed_windows_path(os.path.join(variant, "Documents", "f.txt")))
        self.assertFalse(is_privileged_windows_path(os.path.join(variant, "docs.txt")))

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
            success, message, backup = write_file_safe(path, "Hello, World!",
                                                       allowed_dirs=[tmpdir])
            self.assertTrue(success)
            self.assertIsNone(backup)  # No backup for new file
            with open(path, "r") as f:
                self.assertEqual(f.read(), "Hello, World!")

    def test_write_existing_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            with open(path, "w") as f:
                f.write("original")
            success, message, backup = write_file_safe(path, "updated",
                                                       allowed_dirs=[tmpdir])
            self.assertTrue(success)
            self.assertIsNotNone(backup)
            self.assertTrue(os.path.exists(backup))
            with open(path, "r") as f:
                self.assertEqual(f.read(), "updated")
            os.unlink(backup)

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "subdir", "nested", "test.txt")
            success, message, _backup = write_file_safe(path, "content",
                                                        allowed_dirs=[tmpdir])
            self.assertTrue(success)
            self.assertTrue(os.path.exists(path))


class TestReadFilePreview(unittest.TestCase):
    def test_read_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
            f.write("test content")
            path = f.name
        try:
            success, content, truncated = read_file_preview(
                path, allowed_dirs=[os.path.dirname(path)])
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
            success, content, truncated = read_file_preview(
                path, max_bytes=100, allowed_dirs=[os.path.dirname(path)])
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
        success, message, backup = delete_file_safe(
            path, allowed_dirs=[os.path.dirname(path)])
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


class TestWriteBoundarySecurity(unittest.TestCase):
    """The write boundary: planted links, failed backups, racing destinations."""

    def _make_symlink(self, target, link):
        """Create a symlink, skipping only when the OS itself refuses.

        On Linux (the core and GTK gates) symlink creation always works, so
        no skip ever happens there; on Windows without the developer mode
        privilege the OS refuses creation and the case cannot be exercised.
        """
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest("The OS refused to create the symlink: " + str(error))

    def _allowed_dir(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: os.rmdir(directory)
                        if os.path.isdir(directory) and not os.listdir(directory) else None)
        return directory

    def test_intermediate_directory_link_is_refused(self):
        """A subdirectory that is a link out of the allowed directory."""
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        allowed = self._allowed_dir()
        # sub -> outside; the OS-specific link type the system accepts.
        sub = os.path.join(allowed, "sub")
        self._make_directory_link(outside, sub)
        def cleanup_link():
            if os.path.islink(sub):
                os.unlink(sub)
            elif os.path.isdir(sub):
                os.rmdir(sub)
        self.addCleanup(cleanup_link)
        exterior = os.path.join(outside, "leaked.txt")

        # write through the linked subdirectory must not create the file.
        success, message, _backup = write_file_safe(
            os.path.join(sub, "file.txt"), "attacker", allowed_dirs=[allowed])
        self.assertFalse(success, message)
        self.assertIn("link", message.lower())
        self.assertFalse(os.path.exists(exterior))

        # a pre-existing exterior file reached through the sub link
        with open(exterior, "w") as handle:
            handle.write("exterior secret")

        # read through the linked subdirectory is refused
        success, _content, _truncated = read_file_preview(
            os.path.join(sub, "leaked.txt"), allowed_dirs=[allowed])
        self.assertFalse(success)

        # delete through the linked subdirectory is refused
        success, _message, _backup = delete_file_safe(
            os.path.join(sub, "leaked.txt"), allowed_dirs=[allowed])
        self.assertFalse(success)
        self.assertTrue(os.path.exists(exterior))

    def _make_directory_link(self, target, link):
        """Create a directory link, preferring a junction on Windows.

        On Linux a symlink to a directory always works, so the test never
        skips there. On Windows, try a junction first (no privilege needed)
        and fall back to a symlink; skip only when the OS refuses both.
        """
        if os.name == "nt":
            import subprocess
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", link, target],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                check=False)
            if result.returncode == 0:
                return
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest("The OS refused to create the directory link: " + str(error))

    def test_missing_component_above_link_is_refused(self):
        """sub/novo/file.txt with novo missing: the walk must reach sub."""
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        allowed = self._allowed_dir()
        sub = os.path.join(allowed, "sub")
        self._make_directory_link(outside, sub)

        def cleanup_link():
            if os.path.islink(sub):
                os.unlink(sub)
            elif os.path.isdir(sub):
                os.rmdir(sub)
        self.addCleanup(cleanup_link)
        # 'novo' does not exist yet; the write must not create it through sub.
        target = os.path.join(sub, "novo", "file.txt")

        # write: refused, nothing created outside
        success, message, _backup = write_file_safe(
            target, "attacker", allowed_dirs=[allowed])
        self.assertFalse(success, message)
        self.assertFalse(os.path.exists(os.path.join(outside, "novo")))

        # read and delete through the same path: refused
        success, _content, _truncated = read_file_preview(
            target, allowed_dirs=[allowed])
        self.assertFalse(success)
        success, _message, _backup = delete_file_safe(
            target, allowed_dirs=[allowed])
        self.assertFalse(success)

    def test_preview_diff_refuses_linked_ancestors(self):
        """Exterior content must never appear in a diff through a link."""
        from src.windows_file_actions import preview_diff
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        exterior = os.path.join(outside, "leaked.txt")
        with open(exterior, "w") as handle:
            handle.write("exterior secret line\n")
        allowed = self._allowed_dir()
        sub = os.path.join(allowed, "sub")
        self._make_directory_link(outside, sub)

        def cleanup_link():
            if os.path.islink(sub):
                os.unlink(sub)
            elif os.path.isdir(sub):
                os.rmdir(sub)
        self.addCleanup(cleanup_link)
        # The exterior file exists behind the link; the diff must refuse it.
        diff = preview_diff(os.path.join(sub, "leaked.txt"), "new content\n")
        self.assertIsNone(diff)

    def test_planted_temporary_symlink_is_refused(self):
        # target.txt.tmp as a link to a file outside the allowed directory.
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        outside_file = os.path.join(outside, "outside.txt")
        with open(outside_file, "w") as handle:
            handle.write("untouched")
        allowed = self._allowed_dir()
        target = os.path.join(allowed, "target.txt")
        # The legacy predictable temporary name, planted as a link.
        self._make_symlink(outside_file, target + ".tmp")
        self.addCleanup(lambda: os.unlink(target + ".tmp")
                        if os.path.islink(target + ".tmp") else None)
        success, message, _backup = write_file_safe(target, "attacker content",
                                                    allowed_dirs=[allowed])
        # Either the operation is refused, or it completes through a new,
        # exclusive, non-link temporary - never through the planted link.
        if success:
            # Published through a fresh regular file, not the link.
            self.assertFalse(os.path.islink(target))
            with open(target) as handle:
                self.assertEqual(handle.read(), "attacker content")
        else:
            self.assertFalse(os.path.exists(target))
        # In both cases the exterior file is intact and the planted link was
        # never followed.
        with open(outside_file) as handle:
            self.assertEqual(handle.read(), "untouched")
        self.assertTrue(os.path.islink(target + ".tmp"))

    def test_random_exclusive_temporary_is_not_a_link(self):
        allowed = self._allowed_dir()
        target = os.path.join(allowed, "new.txt")
        success, message, _backup = write_file_safe(target, "safe content",
                                                    allowed_dirs=[allowed])
        self.assertTrue(success, message)
        with open(target) as handle:
            self.assertEqual(handle.read(), "safe content")
        self.assertFalse(os.path.islink(target))
        # No leftover temporaries.
        leftovers = [name for name in os.listdir(allowed) if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_failed_backup_aborts_and_preserves_original(self):
        from unittest.mock import patch
        allowed = self._allowed_dir()
        target = os.path.join(allowed, "keep.txt")
        with open(target, "w") as handle:
            handle.write("original")
        with patch("src.windows_file_actions.make_backup", return_value=None):
            success, message, _backup = write_file_safe(target, "new content",
                                                        allowed_dirs=[allowed])
        self.assertFalse(success)
        self.assertIn("Backup failed", message)
        with open(target) as handle:
            self.assertEqual(handle.read(), "original")
        leftovers = [name for name in os.listdir(allowed)
                     if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_changed_destination_is_not_overwritten(self):
        from unittest.mock import patch
        from src.windows_file_actions import _file_identity
        allowed = self._allowed_dir()
        target = os.path.join(allowed, "raced.txt")
        with open(target, "w") as handle:
            handle.write("original")
        original_identity = _file_identity(target)

        # The destination is replaced between the backup snapshot and the
        # publication rename: the writer saw the original identity, but the
        # revalidation must see what is actually on disk by then.
        def fake_identity(path):
            if path != target:
                return _file_identity(path)
            if not hasattr(fake_identity, "reads"):
                fake_identity.reads = 0
            fake_identity.reads += 1
            if fake_identity.reads == 1:
                # First read: the pre-race snapshot.
                return original_identity
            # Revalidation: the destination was replaced meanwhile.
            with open(target, "w") as racer:
                racer.write("raced content")
            return _file_identity(path)

        with patch("src.windows_file_actions._file_identity",
                   side_effect=fake_identity):
            success, message, _backup = write_file_safe(
                target, "attacker content", allowed_dirs=[allowed])
        self.assertFalse(success)
        self.assertIn("Destination changed", message)
        # The raced content is still in the file: the stale write was not
        # published over it.
        with open(target) as handle:
            self.assertEqual(handle.read(), "raced content")

    def test_destination_symlink_refused(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        outside_file = os.path.join(outside, "outside.txt")
        with open(outside_file, "w") as handle:
            handle.write("untouched")
        allowed = self._allowed_dir()
        target = os.path.join(allowed, "link-target.txt")
        self._make_symlink(outside_file, target)
        self.addCleanup(lambda: os.unlink(target) if os.path.islink(target) else None)
        success, message, _backup = write_file_safe(target, "attacker",
                                                    allowed_dirs=[allowed])
        self.assertFalse(success)
        self.assertIn("link", message.lower())
        with open(outside_file) as handle:
            self.assertEqual(handle.read(), "untouched")

    def test_delete_and_read_refuse_links_and_disallowed_paths(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        outside_file = os.path.join(outside, "outside.txt")
        with open(outside_file, "w") as handle:
            handle.write("secret")
        allowed = self._allowed_dir()
        link = os.path.join(allowed, "planted-link.txt")
        self._make_symlink(outside_file, link)
        self.addCleanup(lambda: os.unlink(link) if os.path.islink(link) else None)
        # Reads refuse to follow the link.
        success, _content, _truncated = read_file_preview(link, allowed_dirs=[allowed])
        self.assertFalse(success)
        # Deletes refuse to remove the link (or follow it).
        success, _message, _backup = delete_file_safe(link, allowed_dirs=[allowed])
        self.assertFalse(success)
        self.assertTrue(os.path.exists(outside_file))
        # Sensitive paths are refused outright.
        success, _message, _backup = write_file_safe(
            r"C:\Windows\System32\test.dll", "x", allowed_dirs=[allowed])
        self.assertFalse(success)
