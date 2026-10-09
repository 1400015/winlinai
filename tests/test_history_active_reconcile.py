"""After a published write fails its sync, disk and memory must agree.

update_json publishes the document and only then syncs the directory.
When that sync fails, JsonWriteCommittedError carries the published
document in error.value: the disk already showed the new active session
while HistoryStore._session_id still held the old one, because the
callers assign self._session_id only after _transaction returns. The
store now rewrites the published document with the in-memory active id
restored (the new session stays in the file, just not active) and lets
the exception propagate.
"""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.history_store import HistoryStore
from src.storage import JsonWriteCommittedError, read_json


def _directory_sync_failure(after):
    """Fail the (after+1)-th directory fsync, as _sync_publication would."""
    real_fsync = os.fsync
    directory_calls = []

    def synchronize(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_calls.append(fd)
            if len(directory_calls) == after + 1:
                raise OSError('history durability uncertain')
        return real_fsync(fd)
    return synchronize


class TestHistoryActiveReconcile(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "history.json"
        self.store = HistoryStore(self.path)
        self.addCleanup(self.store.close)

    def _force_sync_failure_after_publication(self, after):
        return patch('src.storage.os.fsync',
                     side_effect=_directory_sync_failure(after))

    def test_create_session_keeps_disk_and_memory_active_equal(self):
        self.store.append("user", "question in the first session")
        self.assertTrue(self.store.flush(timeout=5))
        before = self.store.active_session_id
        with self._force_sync_failure_after_publication(0):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.create_session(select=True)
        disk = read_json(self.path, None)
        self.assertEqual(self.store.active_session_id, before)
        self.assertEqual(disk["active_session_id"], before)
        self.assertEqual(len(disk["sessions"]), 2)
        self.assertNotIn(disk["active_session_id"],
                         [s["id"] for s in disk["sessions"] if s["id"] != before])

    def test_select_session_keeps_disk_and_memory_active_equal(self):
        created = self.store.create_session(select=False)
        other = created["id"]
        before = self.store.active_session_id
        with self._force_sync_failure_after_publication(0):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.select_session(other)
        disk = read_json(self.path, None)
        self.assertEqual(self.store.active_session_id, before)
        self.assertEqual(disk["active_session_id"], before)
        self.assertEqual(len(disk["sessions"]), 2)

    def test_archive_session_keeps_disk_and_memory_active_equal(self):
        self.store.create_session(select=False)
        before = self.store.active_session_id
        with self._force_sync_failure_after_publication(0):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.archive_session(before)
        disk = read_json(self.path, None)
        self.assertEqual(self.store.active_session_id, before)
        self.assertEqual(disk["active_session_id"], before)
        archived = [s for s in disk["sessions"] if s["archived"]]
        self.assertEqual([s["id"] for s in archived], [before])
        self.assertEqual(len(disk["sessions"]), 2)

    def test_delete_session_keeps_disk_and_memory_active_equal(self):
        created = self.store.create_session(select=False)
        survivor = created["id"]
        before = self.store.active_session_id
        with self._force_sync_failure_after_publication(0):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.delete_session(before)
        disk = read_json(self.path, None)
        self.assertEqual(self.store.active_session_id, before)
        self.assertEqual(disk["active_session_id"], before)
        self.assertEqual(len(disk["sessions"]), 1)
        self.assertEqual(disk["sessions"][0]["id"], survivor)

    def test_second_write_sync_failure_publishes_reconciled_document(self):
        created = self.store.create_session(select=False)
        other = created["id"]
        before = self.store.active_session_id
        real_fsync = os.fsync
        directory_calls = []

        def synchronize(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                directory_calls.append(fd)
                if len(directory_calls) in (1, 2):
                    raise OSError('history durability uncertain')
            return real_fsync(fd)

        with patch('src.storage.os.fsync', side_effect=synchronize):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.select_session(other)
        disk = read_json(self.path, None)
        # The reconciliation write itself failed its sync after publishing,
        # and the document it published already carries the reconciled id.
        self.assertEqual(disk["active_session_id"], before)
        self.assertEqual(self.store.active_session_id, before)


if __name__ == "__main__":
    unittest.main()
