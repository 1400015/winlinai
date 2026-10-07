"""Portable routing tests and Windows-native security/IPC persistence checks."""

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from src.history_store import HistoryStore
from src.platform import windows_files
from src.storage import JsonLimitError, JsonWriteCommittedError, atomic_json_write, read_json, update_json


class TestWindowsStorageRouting(unittest.TestCase):
    """Exercise the Windows transaction contract even in the Linux test job."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / 'document.json'
        self.path.write_text('{"count": 1}', encoding='utf-8')

    @contextmanager
    def backend(self, publication_error=None, lock_error=None):
        @contextmanager
        def guard(path, create_parents=False):
            yield Path(path), None

        @contextmanager
        def lock(path):
            yield
            if lock_error is not None:
                raise lock_error

        def temporary(parent, prefix, suffix=''):
            return tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=str(parent))

        def publish(source, target):
            os.replace(source, target)
            if publication_error is not None:
                raise windows_files.FilePublicationCommittedError(publication_error)

        with patch('src.storage._WINDOWS', True), \
                patch.object(windows_files, 'guarded_path', side_effect=guard), \
                patch.object(windows_files, 'open_regular', side_effect=lambda path: os.open(path, os.O_RDONLY)), \
                patch.object(windows_files, 'private_temporary', side_effect=temporary), \
                patch.object(windows_files, 'publish_temporary', side_effect=publish), \
                patch.object(windows_files, 'sync_publication') as synchronized, \
                patch.object(windows_files, 'sync_directory'), \
                patch.object(windows_files, 'file_lock', side_effect=lock):
            yield synchronized

    def test_bounded_input_and_atomic_publication_use_windows_backend(self):
        with self.backend() as synchronized:
            self.assertEqual(read_json(self.path, 128), {'count': 1})
            self.assertEqual(update_json(self.path, lambda previous: {'count': previous['count'] + 1}, {}),
                             {'count': 2})
            synchronized.assert_called_once_with(self.path)
        self.assertEqual(json.loads(self.path.read_text()), {'count': 2})

    def test_limit_refusal_never_publishes_or_quarantines(self):
        original = self.path.read_bytes()
        with self.backend():
            with self.assertRaises(JsonLimitError):
                update_json(self.path, lambda previous: [], [], max_bytes=3)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.directory.glob('*.corrupt-*')), [])

    def test_failure_after_windows_rename_retains_commit_metadata(self):
        cause = OSError(errno.EIO, 'verification handle close failed')
        value = {'count': 2}
        with self.backend(publication_error=cause):
            with self.assertRaises(JsonWriteCommittedError) as raised:
                atomic_json_write(self.path, value)
        self.assertIs(raised.exception.value, value)
        self.assertIsInstance(raised.exception.__cause__, windows_files.FilePublicationCommittedError)
        self.assertEqual(json.loads(self.path.read_text()), value)
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    def test_lock_completion_failure_retains_committed_value(self):
        failure = OSError(errno.EIO, 'lock release failed')
        with self.backend(lock_error=failure):
            with self.assertRaises(JsonWriteCommittedError) as raised:
                update_json(self.path, lambda previous: {'count': 2}, {})
        self.assertEqual(raised.exception.value, {'count': 2})
        self.assertIs(raised.exception.__cause__, failure)

    def test_recovery_preserves_all_bytes_via_windows_private_backend(self):
        original = b'{"version":999,"future":true}'
        self.path.write_bytes(original)
        with self.backend():
            backup = HistoryStore.recover_file(self.path, confirmed=True)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(json.loads(self.path.read_text())['version'], 1)


class TestWindowsHandleContracts(unittest.TestCase):
    def test_native_lock_and_unlock_use_one_byte_and_close_on_failure(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'lock'
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            parent = object()
            overlap = object()
            file = SimpleNamespace(LockFileEx=Mock(), UnlockFileEx=Mock())
            modules = (SimpleNamespace(get_osfhandle=lambda fd: fd),
                       SimpleNamespace(OVERLAPPED=lambda: overlap), None,
                       SimpleNamespace(LOCKFILE_EXCLUSIVE_LOCK=2), file, None)

            @contextmanager
            def guard(path, create_parents=False):
                yield path, parent

            with patch.object(windows_files, '_modules', return_value=modules), \
                    patch.object(windows_files, '_call', side_effect=lambda function, *args: function(*args)), \
                    patch.object(windows_files, 'guarded_path', side_effect=guard), \
                    patch.object(windows_files, '_check_owned') as owned, \
                    patch.object(windows_files, 'open_regular', return_value=descriptor) as opened:
                with self.assertRaisesRegex(ValueError, 'transaction refused'):
                    with windows_files.file_lock(path):
                        raise ValueError('transaction refused')
            owned.assert_called_once_with(parent)
            opened.assert_called_once_with(path, writable=True, create=True, private=True, deny_delete=True)
            file.LockFileEx.assert_called_once_with(descriptor, 2, 1, 0, overlap)
            file.UnlockFileEx.assert_called_once_with(descriptor, 1, 0, overlap)
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_publication_renames_the_verified_handle_relative_to_the_pinned_parent(self):
        source, target = Path('/private/temporary'), Path('/private/document')
        handle = SimpleNamespace(Close=Mock())
        parent = object()
        con = SimpleNamespace(GENERIC_READ=1, READ_CONTROL=2, DELETE=4, FILE_SHARE_READ=8,
                              FILE_SHARE_DELETE=16, OPEN_EXISTING=3, FILE_ATTRIBUTE_NORMAL=32)
        file = SimpleNamespace(CreateFile=Mock(return_value=handle), FILE_FLAG_OPEN_REPARSE_POINT=64,
                               FileRenameInfo=3, SetFileInformationByHandle=Mock())
        modules = (None, None, None, con, file, None)

        @contextmanager
        def guard(path):
            yield path, parent

        with patch.object(windows_files, '_modules', return_value=modules), \
                patch.object(windows_files, '_call', side_effect=lambda function, *args: function(*args)), \
                patch.object(windows_files, 'guarded_path', side_effect=guard), \
                patch.object(windows_files, '_safe_path', side_effect=lambda path: path), \
                patch.object(windows_files, '_check_handle') as regular, \
                patch.object(windows_files, '_check_owned') as owned:
            windows_files.publish_temporary(source, target)
        regular.assert_called_once_with(handle)
        self.assertEqual(owned.call_args_list[-1].args, (handle,))
        self.assertEqual(owned.call_args_list[-1].kwargs, {'private': True})
        file.SetFileInformationByHandle.assert_called_once_with(
            handle, 3, {'ReplaceIfExists': True, 'RootDirectory': parent, 'FileName': target.name})
        handle.Close.assert_called_once_with()


@unittest.skipUnless(os.name == 'nt', 'Requires native Windows handles and ACLs')
class TestNativeWindowsStorage(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        windows_files.ensure_private_directory(self.directory)
        self.path = self.directory / 'document.json'

    def assert_private(self, path):
        import win32security
        descriptor = win32security.GetNamedSecurityInfo(
            str(path), win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION)
        self.assertEqual(descriptor.GetSecurityDescriptorOwner(), windows_files._user_sid())
        self.assertTrue(descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED)
        trusted = windows_files._trusted_sids()
        acl = descriptor.GetSecurityDescriptorDacl()
        self.assertIsNotNone(acl)
        self.assertEqual(acl.GetAceCount(), 3)
        for index in range(acl.GetAceCount()):
            ace = acl.GetAce(index)
            self.assertIn(ace[2], trusted)

    def junction(self, path, target):
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(path), str(target)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(path.rmdir)

    def test_atomic_write_lock_and_recovery_have_private_protected_acls(self):
        update_json(self.path, lambda previous: {'count': 1}, {})
        self.assertEqual(read_json(self.path, 128), {'count': 1})
        self.assert_private(self.path)
        self.assert_private(Path(str(self.path) + '.lock'))
        original = b'{"version":999,"future":true}'
        self.path.write_bytes(original)
        backup = HistoryStore.recover_file(self.path, confirmed=True)
        self.assertEqual(backup.read_bytes(), original)
        self.assert_private(backup)
        self.assert_private(self.path)

    def test_utf8_serialized_byte_limit_matches_native_lf_output(self):
        value = {'text': 'é\n'}
        expected = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
        atomic_json_write(self.path, value, max_bytes=len(expected))
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertEqual(read_json(self.path, len(expected)), value)
        with self.assertRaises(JsonLimitError):
            atomic_json_write(self.path, value, max_bytes=len(expected) - 1)
        self.assertEqual(self.path.read_bytes(), expected)

    def test_pinned_parent_denies_concurrent_reparse_metadata_write_handles(self):
        import win32con
        import win32file
        with windows_files.guarded_path(self.path):
            with self.assertRaises(OSError):
                windows_files._call(win32file.CreateFile, str(self.directory), win32con.GENERIC_WRITE,
                                    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                                    None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_BACKUP_SEMANTICS, None)

    def test_owned_directory_preserves_an_existing_readable_parent_acl(self):
        import ntsecuritycon
        import win32security
        descriptor = win32security.GetNamedSecurityInfo(str(self.directory), win32security.SE_FILE_OBJECT,
                                                      win32security.DACL_SECURITY_INFORMATION)
        acl = descriptor.GetSecurityDescriptorDacl()
        everyone = win32security.CreateWellKnownSid(win32security.WinWorldSid, None)
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS, 0, ntsecuritycon.FILE_GENERIC_READ, everyone)
        win32security.SetNamedSecurityInfo(str(self.directory), win32security.SE_FILE_OBJECT,
                                          win32security.DACL_SECURITY_INFORMATION, None, None, acl, None)
        before = [acl.GetAce(index) for index in range(acl.GetAceCount())]
        windows_files.ensure_owned_directory(self.directory)
        atomic_json_write(self.path, {'private': True})
        after = win32security.GetNamedSecurityInfo(str(self.directory), win32security.SE_FILE_OBJECT,
                                                  win32security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
        self.assertEqual(before, [after.GetAce(index) for index in range(after.GetAceCount())])
        self.assert_private(self.path)

    def test_corrupt_quarantine_is_private_and_complete_before_reset(self):
        original = b'{broken'
        self.path.write_bytes(original)
        update_json(self.path, lambda previous: {'recovered': True}, {})
        backup, = self.directory.glob('document.json.corrupt-*')
        self.assertEqual(backup.read_bytes(), original)
        self.assert_private(backup)
        self.assert_private(self.path)

    def test_reparse_final_and_parent_are_refused(self):
        target = self.directory / 'real-directory'
        target.mkdir()
        (target / 'secret.json').write_text('{"secret": true}', encoding='utf-8')
        link = self.directory / 'junction'
        self.junction(link, target)
        with self.assertRaises(OSError):
            read_json(link, 128)
        with self.assertRaises(OSError):
            read_json(link / 'secret.json', 128)
        with self.assertRaises(OSError):
            update_json(link / 'secret.json', lambda previous: {}, {})
        self.assertEqual((target / 'secret.json').read_text(), '{"secret": true}')

    def test_owned_text_is_bounded_and_identity_checks_reject_external_edits(self):
        self.path.write_text('KEY=\n', encoding='utf-8')
        text, identity = windows_files.read_owned_text(self.path, 128)
        self.assertEqual(text, 'KEY=\n')
        self.assertEqual(windows_files.owned_identity(self.path), identity)
        with self.assertRaises(ValueError):
            windows_files.read_owned_text(self.path, 2)
        descriptor, name = windows_files.private_temporary(self.directory, 'edit-')
        with os.fdopen(descriptor, 'wb') as target:
            target.write(b'NEW=value\n')
        self.addCleanup(lambda: Path(name).unlink(missing_ok=True))
        self.path.write_text('EXTERNAL=value\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            windows_files.publish_temporary(name, self.path, expected_identity=identity)
        self.assertEqual(self.path.read_text(), 'EXTERNAL=value\n')

    def test_owned_text_refuses_acl_with_other_principal_write_access(self):
        import win32con
        import win32security
        self.path.write_text('KEY=\n', encoding='utf-8')
        descriptor = win32security.GetNamedSecurityInfo(str(self.path), win32security.SE_FILE_OBJECT,
                                                      win32security.DACL_SECURITY_INFORMATION)
        acl = descriptor.GetSecurityDescriptorDacl()
        everyone = win32security.CreateWellKnownSid(win32security.WinWorldSid, None)
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS, 0, win32con.GENERIC_WRITE, everyone)
        win32security.SetNamedSecurityInfo(str(self.path), win32security.SE_FILE_OBJECT,
                                          win32security.DACL_SECURITY_INFORMATION, None, None, acl, None)
        with self.assertRaises(ValueError):
            windows_files.read_owned_text(self.path, 128)

    def test_native_interprocess_lock_waits_until_the_holder_releases_it(self):
        code = '''
import sys
from src.storage import json_lock
print('started', flush=True)
with json_lock(sys.argv[1]):
    print('acquired', flush=True)
'''
        acquired = threading.Event()
        with windows_files.file_lock(str(self.path) + '.lock'):
            child = subprocess.Popen([sys.executable, '-c', code, str(self.path)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.addCleanup(lambda: child.kill() if child.poll() is None else None)
            self.assertEqual(child.stdout.readline().strip(), 'started')

            def observe():
                if child.stdout.readline().strip() == 'acquired':
                    acquired.set()

            reader = threading.Thread(target=observe, daemon=True)
            reader.start()
            self.assertFalse(acquired.wait(0.3), 'A second process acquired the held sidecar lock')
        self.assertTrue(acquired.wait(10), 'Lock was not released for the waiting process')
        self.assertEqual(child.wait(timeout=10), 0, child.stderr.read())
        reader.join(timeout=1)
        child.stdout.close()
        child.stderr.close()

    def test_native_post_publication_failure_is_reported_as_committed(self):
        value = {'count': 2}
        atomic_json_write(self.path, {'count': 1})
        with patch.object(windows_files, 'sync_publication', side_effect=OSError(errno.EIO, 'flush failed')):
            with self.assertRaises(JsonWriteCommittedError) as raised:
                update_json(self.path, lambda previous: value, {})
        self.assertEqual(raised.exception.value, value)
        self.assertEqual(read_json(self.path, 128), value)


if __name__ == '__main__':
    unittest.main()
