"""Windows capture contracts and native Job Object integration tests."""

import codecs
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from src import process_output
from src.platform import windows_process
from src.process_output import CLEANUP_UNCERTAINTY, run_bounded


class FakeWindowsAPI:
    """Model bounded reads and failures, rather than mocking the runner itself."""

    legacy_encoding = 'cp437'

    def __init__(self, stdout=b'', stderr=b'', returncode=0):
        self.events = []
        self.output = {11: stdout, 13: stderr}
        self.next_handle = 11
        self.returncode = returncode
        self.failure = None
        self.active = 0
        self.hold_pipes = False
        self.read_sizes = []

    def event(self, name, *arguments):
        self.events.append((name, *arguments))
        if self.failure == name:
            raise OSError('fixture ' + name)

    def create_job(self):
        self.event('create_job')
        return 1

    def configure_job(self, job):
        self.event('configure_job', job)

    def create_pipe(self):
        self.event('create_pipe')
        reader = self.next_handle
        self.next_handle += 2
        return reader, reader + 1

    def protect_reader(self, reader):
        self.event('protect_reader', reader)

    def open_stdin(self):
        self.event('open_stdin')
        return 20

    def create_suspended(self, argv, env, stdin, stdout, stderr):
        self.event('create_suspended', tuple(argv), stdin, stdout, stderr)
        self.environment = env
        return 30, 31

    def assign(self, job, process):
        self.event('assign', job, process)

    def resume(self, thread):
        self.event('resume', thread)

    def available(self, handle):
        self.event('available', handle)
        if self.output[handle]:
            return len(self.output[handle])
        return 0 if self.hold_pipes else None

    def read(self, handle, size):
        self.event('read', handle, size)
        self.read_sizes.append(size)
        data = self.output[handle][:size]
        self.output[handle] = self.output[handle][size:]
        return data

    def poll(self, process):
        self.event('poll', process)
        return self.returncode

    def terminate_job(self, job):
        self.event('terminate_job', job)

    def terminate_process(self, process):
        self.event('terminate_process', process)
        self.returncode = 1

    def active_processes(self, job):
        self.event('active_processes', job)
        return self.active

    def close(self, handle):
        self.event('close', handle)


class TestWindowsProcessContracts(unittest.TestCase):
    def execute(self, api, timeout=1, limit=4096, env=None, argv=None):
        with patch.object(windows_process, '_WindowsAPI', return_value=api), \
                patch.object(process_output.sys, 'platform', 'win32'):
            return run_bounded(argv or ['fixture.exe', 'space in argument'], timeout, limit, env=env)

    def test_job_is_assigned_before_any_child_instruction_and_cleanup_is_confirmed(self):
        api = FakeWindowsAPI(b'completed\n')
        self.assertEqual(self.execute(api), (0, 'completed\n', ''))
        names = [event[0] for event in api.events]
        self.assertLess(names.index('create_suspended'), names.index('assign'))
        self.assertLess(names.index('assign'), names.index('resume'))
        self.assertLess(names.index('terminate_job'), names.index('active_processes'))
        self.assertEqual(api.events[-1], ('close', 1))
        self.assertEqual(api.events[names.index('create_suspended')][1:],
                         (('fixture.exe', 'space in argument'), 20, 12, 14))

    def test_failed_job_assignment_never_resumes_the_suspended_child(self):
        api = FakeWindowsAPI()
        api.failure = 'assign'
        with self.assertRaisesRegex(OSError, 'fixture assign'):
            self.execute(api)
        names = [event[0] for event in api.events]
        self.assertNotIn('resume', names)
        self.assertIn('terminate_process', names)
        self.assertNotIn('terminate_job', names)
        self.assertEqual(api.events[-1], ('close', 1))

    def test_capture_budget_is_shared_and_no_read_can_accumulate_excess_output(self):
        api = FakeWindowsAPI(b'x' * 4096, b'y' * 4096)
        code, output, errors = self.execute(api, limit=5000)
        self.assertNotEqual(code, 0)
        self.assertEqual(output.split('\n')[0], 'x' * 4096)
        self.assertEqual(errors, 'y' * 904)
        self.assertIn('truncated at 5000 bytes', output)
        self.assertEqual(api.read_sizes, [4096, 905])

    def test_repeated_reads_are_bounded_even_when_the_retained_budget_is_large(self):
        api = FakeWindowsAPI(b'x' * 180000)
        code, output, errors = self.execute(api, limit=200000)
        self.assertEqual((code, output, errors), (0, 'x' * 180000, ''))
        self.assertLessEqual(max(api.read_sizes), 65536)

    def test_termination_error_cannot_turn_into_success_after_job_close(self):
        api = FakeWindowsAPI(b'completed')
        api.failure = 'terminate_job'
        code, output, errors = self.execute(api)
        self.assertNotEqual(code, 0)
        self.assertEqual(output, 'completed')
        self.assertIn(CLEANUP_UNCERTAINTY, errors)
        self.assertEqual(api.events[-1], ('close', 1))

    def test_observation_error_cannot_be_reported_as_confirmed_cleanup(self):
        api = FakeWindowsAPI()
        api.failure = 'active_processes'
        code, _, errors = self.execute(api)
        self.assertNotEqual(code, 0)
        self.assertIn(CLEANUP_UNCERTAINTY, errors)
        self.assertEqual(api.events[-1], ('close', 1))

    def test_job_close_error_is_reported_even_after_zero_active_processes(self):
        api = FakeWindowsAPI()
        original_close = api.close

        def close(handle):
            original_close(handle)
            if handle == 1:
                raise OSError('job close failed')

        api.close = close
        code, _, errors = self.execute(api)
        self.assertNotEqual(code, 0)
        self.assertIn(CLEANUP_UNCERTAINTY, errors)

    def test_resume_failure_still_terminates_and_closes_the_job(self):
        api = FakeWindowsAPI()
        api.failure = 'resume'
        with self.assertRaisesRegex(OSError, 'fixture resume'):
            self.execute(api)
        self.assertIn(('terminate_job', 1), api.events)
        self.assertEqual(api.events[-1], ('close', 1))

    def test_interrupt_during_cleanup_still_closes_the_job(self):
        api = FakeWindowsAPI()
        api.active = 1
        with patch.object(windows_process.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(api)
        self.assertEqual(api.events[-1], ('close', 1))

    def test_unconfirmed_active_descendant_cannot_be_reported_as_success(self):
        api = FakeWindowsAPI()
        api.active = 1
        with patch.object(windows_process, '_CLEANUP_TIMEOUT', 0):
            code, _, errors = self.execute(api)
        self.assertNotEqual(code, 0)
        self.assertIn(CLEANUP_UNCERTAINTY, errors)

    def test_timeout_retains_partial_output_and_diagnosis_if_cleanup_fails(self):
        api = FakeWindowsAPI(b'partial', b'diagnostic', returncode=None)
        api.hold_pipes = True
        api.failure = 'terminate_job'
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            self.execute(api, timeout=.02)
        self.assertEqual(raised.exception.output, 'partial')
        self.assertIn('diagnostic', raised.exception.stderr)
        self.assertIn(CLEANUP_UNCERTAINTY, raised.exception.stderr)
        self.assertEqual(raised.exception.cleanup_uncertainty, CLEANUP_UNCERTAINTY)

    def test_wsl_timeout_warns_about_guest_even_when_windows_job_is_empty(self):
        api = FakeWindowsAPI(b'partial', returncode=None)
        api.hold_pipes = True
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            self.execute(api, timeout=.02, argv=[r'C:\Windows\System32\WSL.EXE', '--exec', 'ip', 'route'])
        self.assertIn(CLEANUP_UNCERTAINTY, raised.exception.cleanup_uncertainty)
        self.assertIn('cannot confirm termination of processes inside WSL', raised.exception.stderr)
        self.assertIn(('active_processes', 1), api.events)

    def test_wsl_truncation_warns_about_guest_even_when_windows_job_is_empty(self):
        api = FakeWindowsAPI(b'x' * 10)
        code, output, errors = self.execute(api, limit=5, argv=['wsl.exe', '--exec', 'ip', 'route'])
        self.assertNotEqual(code, 0)
        self.assertIn('truncated at 5 bytes', output)
        self.assertIn('cannot confirm termination of processes inside WSL', errors)

    def test_completed_wsl_probe_preserves_success(self):
        api = FakeWindowsAPI(b'route')
        self.assertEqual(self.execute(api, argv=['wsl.exe', '--exec', 'ip', 'route']), (0, 'route', ''))

    def test_exited_leader_with_a_descendant_holding_pipes_still_times_out(self):
        api = FakeWindowsAPI(returncode=0)
        api.hold_pipes = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.execute(api, timeout=.02)
        self.assertIn(('terminate_job', 1), api.events)

    def test_closed_pipes_do_not_remove_the_leaders_deadline(self):
        api = FakeWindowsAPI(returncode=None)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.execute(api, timeout=.02)
        self.assertIn(('terminate_job', 1), api.events)

    def test_capture_error_preserves_its_identity_and_job_cleanup_warning(self):
        api = FakeWindowsAPI()
        original_event = api.event
        failure = OSError('capture unavailable')

        def event(name, *arguments):
            if name == 'available':
                raise failure
            original_event(name, *arguments)

        api.event = event
        api.failure = 'terminate_job'
        with self.assertRaises(OSError) as raised:
            self.execute(api)
        self.assertIs(raised.exception, failure)
        self.assertEqual(failure.cleanup_uncertainty, CLEANUP_UNCERTAINTY)

    def test_validation_precedes_native_api_access(self):
        with patch.object(windows_process, '_WindowsAPI') as api, \
                patch.object(process_output.sys, 'platform', 'win32'):
            for argv, timeout, limit in [([], 1, 1), (['ok'], True, 1), (['ok'], float('inf'), 1),
                                         (['ok'], 1, 0), (['ok'], 1, True), (['nul\0'], 1, 1)]:
                with self.subTest(argv=argv, timeout=timeout, limit=limit), self.assertRaises(ValueError):
                    run_bounded(argv, timeout, limit)
        api.assert_not_called()

    def test_environment_is_unicode_sorted_and_rejects_ambiguous_names(self):
        api = FakeWindowsAPI()
        self.execute(api, env={'z': 'ação', 'Alpha': 'space and = sign'})
        self.assertTrue(api.environment[:].startswith('Alpha=space and = sign\0z=ação\0\0'))
        with patch.object(windows_process, '_WindowsAPI') as native:
            for env in ({'Path': 'a', 'PATH': 'b'}, {'bad=name': 'x'}, {'key': 'bad\0value'}):
                with self.subTest(env=env), self.assertRaises(ValueError):
                    windows_process.run_bounded(['ok'], 1, 1, env)
        native.assert_not_called()

    def test_windows_64_bit_structures_use_fixed_width_windows_types(self):
        self.assertEqual(ctypes.sizeof(windows_process._DWORD), 4)
        self.assertEqual(ctypes.sizeof(windows_process._AccountingInformation), 48)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(windows_process._StartupInfo), 104)
            self.assertEqual(ctypes.sizeof(windows_process._StartupInfoEx), 112)
            self.assertEqual(ctypes.sizeof(windows_process._ExtendedLimitInformation), 144)


class TestWindowsOutputDecoding(unittest.TestCase):
    def test_bom_utf8_utf16_and_bomless_utf16_preserve_portuguese(self):
        expected = 'ligação Windows\r\n'
        for data in (codecs.BOM_UTF8 + expected.encode('utf-8'), expected.encode('utf-16'),
                     codecs.BOM_UTF16_BE + expected.encode('utf-16-be'),
                     expected.encode('utf-16-le'), expected.encode('utf-16-be')):
            with self.subTest(data=data):
                self.assertEqual(windows_process._decode_output(data, 'cp437'), expected)

    def test_valid_utf8_wins_and_legacy_oem_is_only_a_fallback(self):
        expected = 'Açores'
        self.assertEqual(windows_process._decode_output(expected.encode('utf-8'), 'cp850'), expected)
        self.assertEqual(windows_process._decode_output(expected.encode('cp850'), 'cp850'), expected)

    def test_utf16_cap_through_half_character_and_utf8_cap_replace_incomplete_character(self):
        self.assertEqual(windows_process._decode_output(b'\xff\xfeA\0B', 'cp437'), 'A�')
        self.assertEqual(windows_process._decode_output(b'Ol\xc3', 'cp437', truncated=True), 'Ol�')

    def test_binary_nuls_do_not_claim_to_be_utf16_without_an_alternating_prefix(self):
        self.assertEqual(windows_process._decode_output(b'abc\0def', 'cp437'), 'abc\0def')


@unittest.skipUnless(sys.platform == 'win32', 'native Windows process test')
class TestNativeWindowsProcess(unittest.TestCase):
    def test_unicode_argv_environment_closed_stdin_and_separate_stderr(self):
        script = ('import os,sys; '
                  'sys.stdout.buffer.write((sys.argv[1]+"|"+os.environ["WINLINAI_CAPTURE_TEST"]'
                  '+"|"+repr(sys.stdin.read())).encode("utf-8")); '
                  'sys.stderr.buffer.write("diagnóstico".encode("utf-8"))')
        code, output, errors = run_bounded(
            [sys.executable, '-c', script, 'argumento com espaços e ação'], 5, 4096,
            env=dict(os.environ, WINLINAI_CAPTURE_TEST='Açores'))
        self.assertEqual(code, 0, errors)
        self.assertEqual(output, "argumento com espaços e ação|Açores|''")
        self.assertEqual(errors, 'diagnóstico')

    def test_large_stdout_and_stderr_share_the_retained_budget(self):
        script = 'import os; os.write(1,b"x"*4096); os.write(2,b"y"*2000000)'
        code, output, errors = run_bounded([sys.executable, '-c', script], 5, 8192)
        self.assertNotEqual(code, 0)
        self.assertIn('truncated at 8192 bytes', output)
        self.assertEqual(output.split('\n')[0], 'x' * 4096)
        self.assertEqual(errors, 'y' * 4096)
        self.assertLess(len(output) + len(errors), 8300)
        self.assertNotIn(CLEANUP_UNCERTAINTY, errors)

    def test_timeout_is_bounded_and_keeps_output(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            run_bounded([sys.executable, '-c', 'import os,time; os.write(1,b"started"); time.sleep(30)'],
                        1, 4096)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(raised.exception.output, 'started')
        self.assertFalse(hasattr(raised.exception, 'cleanup_uncertainty'))

    def test_success_terminates_descendant_with_closed_capture_pipes(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / 'ready'
            effect = Path(directory) / 'survived'
            child = ('import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text("ready"); '
                     'time.sleep(.6); pathlib.Path(sys.argv[2]).write_text("unexpected")')
            parent = ('import pathlib,subprocess,sys,time; '
                      'subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2],sys.argv[3]],'
                      'stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                      'ready=pathlib.Path(sys.argv[2]); deadline=time.monotonic()+3; '
                      '\nwhile not ready.exists() and time.monotonic()<deadline: time.sleep(.01)\n'
                      'assert ready.exists()')
            code, _, errors = run_bounded(
                [sys.executable, '-c', parent, child, str(ready), str(effect)], 5, 4096)
            self.assertEqual(code, 0, errors)
            self.assertTrue(ready.exists(), 'descendant must have run before cleanup')
            time.sleep(.8)
            self.assertFalse(effect.exists())

    def test_exited_leader_and_descendant_holding_the_pipe_keep_deadline(self):
        parent = ('import subprocess,sys; '
                  'subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],'
                  'stdout=sys.stdout,stderr=sys.stderr)')
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            run_bounded([sys.executable, '-c', parent], 1, 4096)
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(hasattr(raised.exception, 'cleanup_uncertainty'))

    def test_closed_capture_pipes_do_not_remove_the_leaders_deadline(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            run_bounded([sys.executable, '-c', 'import os,time; os.close(1); os.close(2); time.sleep(30)'],
                        1, 4096)
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(hasattr(raised.exception, 'cleanup_uncertainty'))

    def test_native_capture_decodes_utf16_output(self):
        script = 'import sys; sys.stdout.buffer.write("ligação Windows".encode("utf-16"))'
        code, output, errors = run_bounded([sys.executable, '-c', script], 5, 4096)
        self.assertEqual((code, output, errors), (0, 'ligação Windows', ''))

    def test_failed_job_assignment_cannot_run_a_single_child_instruction(self):
        with tempfile.TemporaryDirectory() as directory:
            effect = Path(directory) / 'must-never-exist'
            script = 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("unexpected")'
            with patch.object(windows_process._WindowsAPI, 'assign', side_effect=OSError('assignment denied')):
                with self.assertRaisesRegex(OSError, 'assignment denied'):
                    run_bounded([sys.executable, '-c', script, str(effect)], 5, 4096)
            self.assertFalse(effect.exists())


if __name__ == '__main__':
    unittest.main()
