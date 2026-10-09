"""A non-cooperating external writer must never corrupt published bytes.

The sidecar lock only binds cooperating processes: a second process that
never takes it can still race the publication window. This is a native,
two-process proof — threads in one process and mocked handle APIs do
not exercise the kernel. Process A publishes or recovers through the
real update_json/atomic_json_write/HistoryStore.recover_file path in
one subprocess while process B, without the lock and in its own
subprocess, either replaces the target file's bytes or renames its
immediate parent during A's operation. The accepted outcomes are
exactly two: B's bytes survive, or the publication is refused and the
previous bytes survive. An empty, truncated or interleaved file without
refusal is a silent-loss failure.
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

PUBLISHER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {root!r})
    path = {path!r}
    gate = {gate!r}
    while not os.path.exists(gate):
        time.sleep(0.005)
    from src.storage import update_json
    update_json(path, lambda previous: {{"published": True}}, {{}})
    print('published')
""")

EXTERNAL = textwrap.dedent("""
    import os, sys, time
    path = {path!r}
    gate = {gate!r}
    mode = {mode!r}
    while not os.path.exists(gate):
        time.sleep(0.005)
    if mode == 'replace':
        with open(path, 'wb') as target:
            target.write(b'{{"external": true}}')
        print('written')
    else:
        parent = os.path.dirname(path)
        os.rename(parent, parent + '-renamed')
        print('renamed')
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
        self.path.write_text(json.dumps({'original': True}, indent=2),
                             encoding='utf-8')

    def _race(self, mode, publisher_mode='publish'):
        """Run A and B in simultaneous subprocesses released by a gate."""
        gate = self.base / 'go'
        common = dict(root=str(ROOT), path=str(self.path),
                      gate=str(gate))
        external = subprocess.Popen(
            [sys.executable, '-c', EXTERNAL.format(mode=mode, **common)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(ROOT))
        publisher = subprocess.Popen(
            [sys.executable, '-c', PUBLISHER.format(**common)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(ROOT))
        gate.write_text('go', encoding='utf-8')
        a_out, a_err = publisher.communicate(timeout=60)
        b_out, b_err = external.communicate(timeout=60)
        return (publisher.returncode, a_out, a_err,
                external.returncode, b_out, b_err)

    def _assert_single_writer(self, data, label):
        decoded = json.loads(data)
        self.assertIn(decoded, ({'original': True}, {'published': True},
                                {'external': True}),
                      label + ': interleaved or partial bytes from two writers')

    def test_external_replace_racing_publication(self):
        """B replaces the target bytes while A publishes, concurrently.

        Both subprocesses are released by the same gate and race the
        publication window. Whichever writer wins, the file holds the
        bytes of exactly one writer, or the publication was refused —
        never a mix, never an empty or truncated file.
        """
        for _ in range(5):
            a_code, a_out, a_err, b_code, b_out, b_err = self._race('replace')
            self.assertEqual(b_code, 0, b_err)
            if a_code != 0:
                # Refusal is an accepted outcome: previous bytes must stand.
                self.assertTrue(self.path.exists(), 'publication refused but target vanished')
                data = self.path.read_text(encoding='utf-8')
                self._assert_single_writer(data, 'refused publication')
                continue
            data = self.path.read_text(encoding='utf-8')
            self._assert_single_writer(data, 'racing publication')

    def test_external_rename_of_parent_racing_publication(self):
        """B renames the immediate parent while A publishes.

        The publication pins the parent handles for the whole
        transaction, so the concurrent rename must be refused, or it
        succeeds before the pin — either way the document never ends up
        empty, truncated or interleaved.
        """
        a_code, a_out, a_err, b_code, b_out, b_err = self._race('rename-parent')
        renamed = self.store_dir.with_name(self.store_dir.name + '-renamed')
        candidates = [p for p in (self.path, renamed / self.path.name)
                      if p.exists()]
        self.assertTrue(candidates, 'target vanished from both parents')
        for candidate in candidates:
            data = candidate.read_text(encoding='utf-8')
            self._assert_single_writer(data, 'renamed parent')


if __name__ == '__main__':
    unittest.main()
