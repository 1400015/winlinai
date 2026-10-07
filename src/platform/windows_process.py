"""Bounded native Windows capture, without a shell or third-party bindings.

CreateProcess starts suspended; a non-breakaway, kill-on-close Job Object owns
the process before its first instruction. Only the three standard handles are
inherited. Descendants stay in the job, including after the leader exits.
PeekNamedPipe avoids blocking reads and reader threads. Retained output across
both streams is capped in bytes; the child's own memory is not limited.
Job Objects own Windows processes, not WSL guest processes started through a
broker. Interrupted wsl.exe commands therefore retain a cleanup warning even
when the Windows job is confirmed empty.

Output with a BOM is UTF-8/UTF-16. An unambiguous alternating-NUL prefix also
identifies BOM-less UTF-16 (as emitted by wsl.exe). Otherwise valid UTF-8 wins;
invalid UTF-8 falls back to Windows' OEM code page for legacy PowerShell 5.1.
Malformed/truncated characters are replaced. No command text is rewritten.
"""

import codecs
import ctypes
import ntpath
import subprocess
import time

from ..process_output import CLEANUP_UNCERTAINTY


_DWORD = ctypes.c_uint32
_BOOL = ctypes.c_int32
_HANDLE = ctypes.c_void_p
_SIZE_T = ctypes.c_size_t
_LARGE_INTEGER = ctypes.c_int64
_LPWSTR = ctypes.c_wchar_p

_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x00000100
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_ERROR_BROKEN_PIPE = 109
_ERROR_PIPE_NOT_CONNECTED = 233
_CLEANUP_TIMEOUT = .5
_WSL_CLEANUP_UNCERTAINTY = (
    CLEANUP_UNCERTAINTY + ' A Windows job cannot confirm termination of processes inside WSL.'
)


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [('length', _DWORD), ('descriptor', ctypes.c_void_p), ('inherit', _BOOL)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ('cb', _DWORD), ('reserved', _LPWSTR), ('desktop', _LPWSTR), ('title', _LPWSTR),
        ('x', _DWORD), ('y', _DWORD), ('x_size', _DWORD), ('y_size', _DWORD),
        ('x_chars', _DWORD), ('y_chars', _DWORD), ('fill', _DWORD), ('flags', _DWORD),
        ('show', ctypes.c_uint16), ('reserved_size', ctypes.c_uint16),
        ('reserved_bytes', ctypes.c_void_p), ('stdin', _HANDLE),
        ('stdout', _HANDLE), ('stderr', _HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [('info', _StartupInfo), ('attributes', ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [('process', _HANDLE), ('thread', _HANDLE), ('pid', _DWORD), ('tid', _DWORD)]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ('process_time', _LARGE_INTEGER), ('job_time', _LARGE_INTEGER), ('flags', _DWORD),
        ('minimum_working_set', _SIZE_T), ('maximum_working_set', _SIZE_T),
        ('active_limit', _DWORD), ('affinity', _SIZE_T),
        ('priority', _DWORD), ('scheduling', _DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'read_operations', 'write_operations', 'other_operations',
        'read_bytes', 'write_bytes', 'other_bytes')]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ('basic', _BasicLimitInformation), ('io', _IoCounters),
        ('process_memory', _SIZE_T), ('job_memory', _SIZE_T),
        ('peak_process_memory', _SIZE_T), ('peak_job_memory', _SIZE_T),
    ]


class _AccountingInformation(ctypes.Structure):
    _fields_ = [
        ('user_time', _LARGE_INTEGER), ('kernel_time', _LARGE_INTEGER),
        ('period_user_time', _LARGE_INTEGER), ('period_kernel_time', _LARGE_INTEGER),
        ('page_faults', _DWORD), ('total_processes', _DWORD),
        ('active_processes', _DWORD), ('terminated_processes', _DWORD),
    ]


def _environment_block(env):
    if env is None:
        return None
    entries = []
    seen = set()
    for key, value in env.items():
        if (not isinstance(key, str) or not isinstance(value, str) or not key
                or '=' in key or '\0' in key or '\0' in value):
            raise ValueError('environment names and values must be valid strings')
        folded = key.casefold()
        if folded in seen:
            raise ValueError('duplicate case-insensitive Windows environment name')
        seen.add(folded)
        entries.append((folded, key + '=' + value))
    # Windows requires an ordered, double-NUL-terminated Unicode block.
    return ctypes.create_unicode_buffer('\0'.join(value for _, value in sorted(entries)) + '\0\0')


def _decode_output(data, legacy_encoding, truncated=False):
    data = bytes(data)
    if data.startswith(codecs.BOM_UTF8):
        return data.decode('utf-8-sig', errors='replace')
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode('utf-16', errors='replace')
    prefix = data[:64]
    # Require at least two non-NUL characters, all with a zero high byte.
    # A trailing half code unit is possible when the output cap is reached.
    pairs = len(prefix) // 2
    if pairs >= 2:
        low, high = prefix[:pairs * 2:2], prefix[1:pairs * 2:2]
        if all(low) and not any(high):
            return data.decode('utf-16-le', errors='replace')
        if not any(low) and all(high):
            return data.decode('utf-16-be', errors='replace')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError as error:
        if truncated and error.reason == 'unexpected end of data':
            return data.decode('utf-8', errors='replace')
        return data.decode(legacy_encoding, errors='replace')


class _WindowsAPI:
    """Thin checked Win32 calls; kept separate from the capture state machine."""

    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': (_HANDLE, [ctypes.c_void_p, _LPWSTR]),
            'SetInformationJobObject': (_BOOL, [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD]),
            'QueryInformationJobObject': (_BOOL, [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD, ctypes.c_void_p]),
            'CreatePipe': (_BOOL, [ctypes.POINTER(_HANDLE), ctypes.POINTER(_HANDLE), ctypes.c_void_p, _DWORD]),
            'SetHandleInformation': (_BOOL, [_HANDLE, _DWORD, _DWORD]),
            'CreateFileW': (_HANDLE, [_LPWSTR, _DWORD, _DWORD, ctypes.c_void_p, _DWORD, _DWORD, _HANDLE]),
            'InitializeProcThreadAttributeList': (_BOOL, [ctypes.c_void_p, _DWORD, _DWORD, ctypes.POINTER(_SIZE_T)]),
            'UpdateProcThreadAttribute': (_BOOL, [ctypes.c_void_p, _DWORD, _SIZE_T, ctypes.c_void_p, _SIZE_T,
                                                ctypes.c_void_p, ctypes.c_void_p]),
            'DeleteProcThreadAttributeList': (None, [ctypes.c_void_p]),
            'CreateProcessW': (_BOOL, [_LPWSTR, _LPWSTR, ctypes.c_void_p, ctypes.c_void_p, _BOOL,
                                     _DWORD, ctypes.c_void_p, _LPWSTR, ctypes.c_void_p,
                                     ctypes.POINTER(_ProcessInformation)]),
            'AssignProcessToJobObject': (_BOOL, [_HANDLE, _HANDLE]),
            'ResumeThread': (_DWORD, [_HANDLE]),
            'PeekNamedPipe': (_BOOL, [_HANDLE, ctypes.c_void_p, _DWORD, ctypes.c_void_p,
                                     ctypes.POINTER(_DWORD), ctypes.c_void_p]),
            'ReadFile': (_BOOL, [_HANDLE, ctypes.c_void_p, _DWORD, ctypes.POINTER(_DWORD), ctypes.c_void_p]),
            'WaitForSingleObject': (_DWORD, [_HANDLE, _DWORD]),
            'GetExitCodeProcess': (_BOOL, [_HANDLE, ctypes.POINTER(_DWORD)]),
            'TerminateJobObject': (_BOOL, [_HANDLE, _DWORD]),
            'TerminateProcess': (_BOOL, [_HANDLE, _DWORD]),
            'CloseHandle': (_BOOL, [_HANDLE]),
            'GetOEMCP': (_DWORD, []),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.kernel, name)
            function.restype = result
            function.argtypes = arguments
        self.security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        self.legacy_encoding = 'cp{}'.format(self.kernel.GetOEMCP())

    @staticmethod
    def _check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def create_job(self):
        return self._check(self.kernel.CreateJobObjectW(None, None))

    def configure_job(self, job):
        limits = _ExtendedLimitInformation()
        limits.basic.flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self._check(self.kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))

    def create_pipe(self):
        reader, writer = _HANDLE(), _HANDLE()
        self._check(self.kernel.CreatePipe(ctypes.byref(reader), ctypes.byref(writer),
                                          ctypes.byref(self.security), 0))
        return reader.value, writer.value

    def protect_reader(self, handle):
        self._check(self.kernel.SetHandleInformation(handle, 1, 0))

    def open_stdin(self):
        handle = self.kernel.CreateFileW('NUL', 0x80000000, 3, ctypes.byref(self.security), 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def create_suspended(self, argv, env, stdin, stdout, stderr):
        size = _SIZE_T()
        self.kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        if not size.value:
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = ctypes.create_string_buffer(size.value)
        self._check(self.kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)))
        try:
            handles = (_HANDLE * 3)(stdin, stdout, stderr)
            self._check(self.kernel.UpdateProcThreadAttribute(
                attributes, 0, _PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles, ctypes.sizeof(handles), None, None))
            startup = _StartupInfoEx()
            startup.info.cb = ctypes.sizeof(startup)
            startup.info.flags = _STARTF_USESTDHANDLES
            startup.info.stdin, startup.info.stdout, startup.info.stderr = stdin, stdout, stderr
            startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
            information = _ProcessInformation()
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            flags = (_CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT
                     | _EXTENDED_STARTUPINFO_PRESENT | _CREATE_NO_WINDOW)
            self._check(self.kernel.CreateProcessW(
                None, command, None, None, True, flags, env, None,
                ctypes.byref(startup), ctypes.byref(information)))
            return information.process, information.thread
        finally:
            self.kernel.DeleteProcThreadAttributeList(attributes)

    def assign(self, job, process):
        self._check(self.kernel.AssignProcessToJobObject(job, process))

    def resume(self, thread):
        if self.kernel.ResumeThread(thread) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())

    def available(self, handle):
        amount = _DWORD()
        if not self.kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(amount), None):
            error = ctypes.get_last_error()
            if error in (_ERROR_BROKEN_PIPE, _ERROR_PIPE_NOT_CONNECTED):
                return None
            raise ctypes.WinError(error)
        return amount.value

    def read(self, handle, size):
        data, amount = ctypes.create_string_buffer(size), _DWORD()
        self._check(self.kernel.ReadFile(handle, data, size, ctypes.byref(amount), None))
        return data.raw[:amount.value]

    def poll(self, process):
        status = self.kernel.WaitForSingleObject(process, 0)
        if status == _WAIT_TIMEOUT:
            return None
        if status != _WAIT_OBJECT_0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = _DWORD()
        self._check(self.kernel.GetExitCodeProcess(process, ctypes.byref(code)))
        return code.value

    def terminate_job(self, job):
        self._check(self.kernel.TerminateJobObject(job, 1))

    def terminate_process(self, process):
        self._check(self.kernel.TerminateProcess(process, 1))

    def active_processes(self, job):
        info = _AccountingInformation()
        self._check(self.kernel.QueryInformationJobObject(job, 1, ctypes.byref(info), ctypes.sizeof(info), None))
        return info.active_processes

    def close(self, handle):
        self._check(self.kernel.CloseHandle(handle))


def _cleanup(api, job, process, assigned, handles):
    """Terminate and confirm the whole job is empty before releasing ownership."""
    uncertain = False
    try:
        if process is not None:
            try:
                if assigned:
                    api.terminate_job(job)
                else:
                    # Assignment failed: this process is still suspended and has
                    # never been allowed to create any descendants.
                    api.terminate_process(process)
                deadline = time.monotonic() + _CLEANUP_TIMEOUT
                while True:
                    empty = api.active_processes(job) == 0 if assigned else api.poll(process) is not None
                    if empty:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        uncertain = True
                        break
                    time.sleep(min(.01, remaining))
            except OSError:
                uncertain = True
    finally:
        # Closing the job is the kill-on-close fallback, even if explicit
        # termination or observation failed or cleanup was interrupted.
        # Never report this fallback as confirmed cleanup.
        for handle in reversed(handles):
            try:
                api.close(handle)
            except OSError:
                uncertain = True
    return CLEANUP_UNCERTAINTY if uncertain else ''


def run_bounded(argv, timeout, limit, env=None):
    """Windows backend for the validated public process_output.run_bounded API."""
    if any('\0' in argument for argument in argv):
        raise ValueError('embedded null byte in argv')
    environment = _environment_block(env)
    api = _WindowsAPI()
    handles = []
    job = process = None
    assigned = False
    output = {'stdout': bytearray(), 'stderr': bytearray()}
    failure = None
    total = 0
    truncated = False
    returncode = None
    deadline = time.monotonic() + timeout
    try:
        job = api.create_job()
        handles.append(job)
        api.configure_job(job)
        pipes = {}
        writers = []
        for name in output:
            reader, writer = api.create_pipe()
            handles.extend((reader, writer))
            api.protect_reader(reader)
            pipes[name] = reader
            writers.append(writer)
        stdin = api.open_stdin()
        handles.append(stdin)
        process, thread = api.create_suspended(argv, environment, stdin, *writers)
        handles.extend((process, thread))
        api.assign(job, process)
        assigned = True
        # Close parent-side writers before resuming so EOF only depends on
        # the child and its descendants; none can execute before assignment.
        for handle in writers + [stdin]:
            api.close(handle)
            handles.remove(handle)
        api.resume(thread)
        api.close(thread)
        handles.remove(thread)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            read_any = False
            for name, handle in list(pipes.items()):
                available = api.available(handle)
                if available is None:
                    del pipes[name]
                    continue
                if available:
                    chunk = api.read(handle, min(available, 65536, limit - total + 1))
                    output[name].extend(chunk[:max(0, limit - total)])
                    total += len(chunk)
                    read_any = True
                    if total > limit:
                        truncated = True
                        break
            if truncated:
                break
            returncode = api.poll(process)
            if not pipes and returncode is not None:
                break
            if not read_any:
                time.sleep(min(.01, remaining))
    except BaseException as error:
        failure = error
        raise
    finally:
        warning = _cleanup(api, job, process, assigned, handles)
        if (ntpath.basename(argv[0]).casefold() in ('wsl', 'wsl.exe')
                and (truncated or isinstance(failure, subprocess.TimeoutExpired))):
            warning = _WSL_CLEANUP_UNCERTAINTY
        if failure is not None:
            if warning:
                failure.cleanup_uncertainty = warning
            if isinstance(failure, subprocess.TimeoutExpired):
                failure.output = _decode_output(output['stdout'], api.legacy_encoding)
                failure.stderr = _decode_output(output['stderr'], api.legacy_encoding)
                if warning:
                    failure.stderr += '\n' + warning
    decoded = {name: _decode_output(data, api.legacy_encoding, truncated=truncated)
               for name, data in output.items()}
    if truncated:
        decoded['stdout'] += '\n... (output truncated at {} bytes)'.format(limit)
    if warning:
        decoded['stderr'] += '\n' + warning
    code = 1 if truncated or returncode is None else returncode
    if warning and code == 0:
        code = 1
    return code, decoded['stdout'], decoded['stderr']
