"""A non-cooperating external writer must never be silently overwritten.

The sidecar lock only binds cooperating processes: a second process
that never takes it can still race the publication window. This is a
native, two-process proof — threads in one process and mocked handle
APIs do not exercise the kernel. Process A publishes through the real
update_json path in one subprocess; its update callback runs inside the
transaction, creates a marker file and only then waits, so process B —
without the lock, in its own subprocess — performs its write strictly
inside A's transaction, after waiting for that marker. B either
replaces the target file's bytes or renames its immediate parent.

The editor must reach update_json: its output shows the line printed
from inside the transaction, and a NameError in either subprocess is a
test failure, not a refusal. A non-zero exit alone proves nothing.

Accepted outcomes for the in-transaction byte replacement: the final
file is exactly the external bytes, or the publication was refused and
the file is exactly the original or exactly the external bytes. The
publication reporting success over the external write — leaving
{"published": true} standing — is silent loss and fails the proof.

Accepted outcomes for the in-transaction parent rename: the rename is
refused and the document stays whole in the original parent, or the
rename happens and the document stays whole in exactly one parent. It
must never vanish, be empty, or mix two writers' bytes.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ORIGINAL_BYTES = json.dumps({'original': True}, indent=2).encode('utf-8')
EXTERNAL_BYTES = b'{"external": true}'

PUBLISHER = textwrap.dedent("""
    import os, sys, time
    sys.path.insert(0, {root!r})
    path = {path!r}
    marker = {marker!r}
    from src.storage import update_json

    def update(previous):
        # Runs inside the publication transaction, under the sidecar lock.
        with open(marker, 'w', encoding='utf-8') as handle:
            handle.write('go')
        print('in-transaction', flush=True)
        time.sleep(0.25)
        return {{"published": True}}

    update_json(path, update, {{}})
    print('published', flush=True)
""")

EXTERNAL_REPLACE = textwrap.dedent("""
    import os, sys, time
    path = {path!r}
    marker = {marker!r}
    while not os.path.exists(marker):
        time.sleep(0.005)
    with open(path, 'wb') as target:
        target.write(b'{{"external": true}}')
    print('written', flush=True)
""")

EXTERNAL_RENAME = textwrap.dedent("""
    import os, sys, time
    path = {path!r}
    marker = {marker!r}
    while not os.path.exists(marker):
        time.sleep(0.005)
    parent = os.path.dirname(path)
    try:
        os.rename(parent, parent + '-renamed')
    except OSError as error:
        print('rename-refused:' + type(error).__name__, flush=True)
    else:
        print('renamed', flush=True)
""")


@unittest.skipUnless(os.name == 'nt', 'native two-process proof requires Windows')
class TestExternalWriterRace(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.store_dir = self.base / 'store'
        self.store_dir.mkdir()
        self.path = self.store_dir / 'document.json'
        self.path.write_bytes(ORIGINAL_BYTES)
        self.marker = self.base / 'marker'

    def _spawn(self, script, **subs):
        return subprocess.Popen(
            [sys.executable, '-c', script.format(root=str(ROOT), **subs)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(ROOT))

    def _race(self, external_script):
        common = dict(path=str(self.path), marker=str(self.marker))
        external = self._spawn(external_script, **common)
        publisher = self._spawn(PUBLISHER, **common)
        a_out, a_err = publisher.communicate(timeout=60)
        b_out, b_err = external.communicate(timeout=60)
        return (publisher.returncode, a_out, a_err,
                external.returncode, b_out, b_err)

    def _assert_editor_reached_update_json(self, a_out, a_err, b_out, b_err):
        combined = a_out + a_err + b_out + b_err
        self.assertNotIn('NameError', combined,
                         'the editor died before reaching update_json')
        self.assertIn('in-transaction', a_out,
                     'update_json never ran the update callback')

    def test_external_replace_racing_publication(self):
        """B replaces the target bytes inside A's transaction.

        Both subprocesses overlap: the marker exists, B prints that it
        wrote, and A's callback line proves the transaction was open.
        """
        a_code, a_out, a_err, b_code, b_out, b_err = self._race(EXTERNAL_REPLACE)
        self._assert_editor_reached_update_json(a_out, a_err, b_out, b_err)
        self.assertEqual(b_code, 0, b_err)
        self.assertIn('written', b_out, 'the external writer never wrote')
        data = self.path.read_bytes()
        if 'published' in a_out:
            # The publication reported success after the external write
            # landed inside the transaction: only the external bytes may
            # stand; the publication overwriting them is silent loss.
            self.assertEqual(data, EXTERNAL_BYTES)
        else:
            # A genuine refusal: a non-zero exit alone is not one, the
            # update callback must have run and the file must hold one
            # writer's bytes exactly.
            self.assertNotEqual(a_code, 0, 'update_json neither published nor refused')
            self.assertIn(data, (ORIGINAL_BYTES, EXTERNAL_BYTES))
        json.loads(data.decode('utf-8'))

    def test_external_rename_of_parent_racing_publication(self):
        """B renames the immediate parent inside A's transaction.

        The rename is attempted only after the marker; the editor must
        reach update_json and survive without a NameError. Either the
        rename is refused and the document stays whole in the original
        parent, or it happens and the document stays whole in exactly
        one parent.
        """
        a_code, a_out, a_err, b_code, b_out, b_err = self._race(EXTERNAL_RENAME)
        self._assert_editor_reached_update_json(a_out, a_err, b_out, b_err)
        renamed = self.store_dir.with_name(self.store_dir.name + '-renamed')
        if 'renamed' in b_out:
            self.assertFalse(self.store_dir.exists(),
                             'the publication resurrected the renamed parent')
            target = renamed / self.path.name
            self.assertTrue(target.exists(), 'the document vanished with its parent')
            self.assertEqual(target.read_bytes(), ORIGINAL_BYTES)
        else:
            self.assertIn('rename-refused', b_out,
                          'the external process died without a rename verdict')
            self.assertTrue(self.path.exists())
            self.assertEqual(self.path.read_bytes(), ORIGINAL_BYTES)


if __name__ == '__main__':
    unittest.main()
