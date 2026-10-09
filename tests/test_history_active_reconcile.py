"""After a published write fails its sync, disk and memory must agree.

update_json publishes the document and only then syncs the directory.
When that sync fails, JsonWriteCommittedError carries the published
document in error.value. The store rewrites the published document with
the in-memory active id restored when that id still names an existing,
unarchived session; when it does not (the transaction archived or
deleted it), the valid id _ensure_active published is kept and adopted
in memory. The file must stay readable by _document: no dead or
archived active id may be left behind.
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

    def _assert_active_is_valid(self, disk_id):
        disk = read_json(self.path, None)
        self.assertEqual(disk["active_session_id"], disk_id)
        active = [s for s in disk["sessions"]
                  if s["id"] == disk_id and not s["archived"]]
        self.assertEqual(len(active), 1)
        return disk

    def test_create_session_keeps_disk_and_memory_active_equal(self):
        self.store.append("user", "question in the first session")
        self.assertTrue(self.store.flush(timeout=5))
        before = self.store.active_session_id
        with self._force_sync_failure_after_publication(0):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.create_session(select=True)
        self.assertEqual(self.store.active_session_id, before)
        disk = self._assert_active_is_valid(before)
        self.assertEqual(len(disk["sessions"]), 2)

    def test_select_session_keeps_disk_and_memory_active_equal(self):
        created = self.store.create_session(select=False)
        other = created["id"]
        before = self.store.active_session_id
        with self._force_sync_failure_after_publication(0):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.select_session(other)
        self.assertEqual(self.store.active_session_id, before)
        disk = self._assert_active_is_valid(before)
        self.assertEqual(len(disk["sessions"]), 2)

    def test_archive_active_session_leaves_a_valid_active_id(self):
        self.store.append("user", "question in the first session")
        self.assertTrue(self.store.flush(timeout=5))
        created = self.store.create_session(select=False)
        survivor = created["id"]
        victim = self.store.active_session_id
        with self._force_sync_failure_after_publication(0):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.archive_session(victim)
        # Memory adopts the valid id; the archived session stays archived
        # and is not active; memory and disk agree.
        self.assertEqual(self.store.active_session_id, survivor)
        disk = self._assert_active_is_valid(survivor)
        archived = [s for s in disk["sessions"] if s["archived"]]
        self.assertEqual([s["id"] for s in archived], [victim])
        # The stored file stays readable: a fresh store lists sessions.
        reopened = HistoryStore(self.path)
        self.addCleanup(reopened.close)
        sessions = reopened.list_sessions(include_archived=True)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(reopened.active_session_id, survivor)

    def test_delete_active_session_leaves_a_valid_active_id(self):
        self.store.append("user", "question in the first session")
        self.assertTrue(self.store.flush(timeout=5))
        created = self.store.create_session(select=False)
        survivor = created["id"]
        victim = self.store.active_session_id
        with self._force_sync_failure_after_publication(0):
            with self.assertRaises(JsonWriteCommittedError):
                self.store.delete_session(victim)
        # Memory adopts the valid id; the deleted session does not return.
        self.assertEqual(self.store.active_session_id, survivor)
        disk = self._assert_active_is_valid(survivor)
        self.assertEqual([s["id"] for s in disk["sessions"]], [survivor])
        # The stored file stays readable: a fresh store lists sessions.
        reopened = HistoryStore(self.path)
        self.addCleanup(reopened.close)
        sessions = reopened.list_sessions(include_archived=True)
        self.assertEqual([s["id"] for s in sessions], [survivor])
        self.assertEqual(reopened.active_session_id, survivor)

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
        # The reconciliation write itself failed its sync after publishing,
        # and the document it published already carries the reconciled id;
        # memory follows what the disk now shows.
        self.assertEqual(self.store.active_session_id, before)
        self._assert_active_is_valid(before)


if __name__ == "__main__":
    unittest.main()
