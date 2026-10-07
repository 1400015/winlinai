"""Windows file primitives with private ACLs and handles that refuse reparse points.

Imports are lazy so Linux never requires pywin32. Directory handles prevent parent
renames while a transaction is in progress. Private objects are created with a
protected DACL, rather than chmod (which only changes the read-only bit on Windows).
Windows has no supported equivalent of POSIX directory fsync. Publication renames
the verified source handle relative to a pinned parent handle and then flushes the
destination file. This does not promise that directory metadata survives a sudden
loss of power on every filesystem.
"""

from contextlib import contextmanager
import errno
import logging
import os
from pathlib import Path
import secrets
import stat

logger = logging.getLogger(__name__)


def _modules():
    if os.name != "nt":
        raise OSError(errno.ENOSYS, "Windows file primitives require Windows")
    try:
        import msvcrt
        import pywintypes
        import win32api
        import win32con
        import win32file
        import win32security
    except ImportError as error:
        raise OSError(errno.ENOSYS, "Secure Windows storage requires pywin32") from error
    return msvcrt, pywintypes, win32api, win32con, win32file, win32security


def _rights():
    _modules()
    import ntsecuritycon
    return ntsecuritycon


def _call(function, *args):
    """Make pywin32 failures obey the storage layer's OSError contract."""
    _, pywintypes, _, _, _, _ = _modules()
    try:
        return function(*args)
    except pywintypes.error as error:
        import ctypes
        raise ctypes.WinError(error.winerror) from error


class FilePublicationCommittedError(OSError):
    """A rename succeeded before closing its verification handles failed."""

    def __init__(self, cause):
        super().__init__(cause.errno, "The file was published, but completion could not be confirmed")


def _close_handle(handle):
    _call(handle.Close)


def _user_sid():
    _, _, api, con, _, security = _modules()
    token = _call(security.OpenProcessToken, api.GetCurrentProcess(), con.TOKEN_QUERY)
    try:
        return _call(security.GetTokenInformation, token, security.TokenUser)[0]
    finally:
        _close_handle(token)


def _trusted_sids():
    _, _, _, _, _, security = _modules()
    return (_user_sid(), security.CreateWellKnownSid(security.WinLocalSystemSid, None),
            security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid, None))


def _owner_sids():
    """An elevated token can create objects owned by its Administrators group."""
    _, _, _, _, _, security = _modules()
    user, unused_system, administrators = _trusted_sids()
    if _call(security.CheckTokenMembership, None, administrators):
        return user, administrators
    return (user,)


def _private_security(directory=False):
    _, pywintypes, _, con, _, security = _modules()
    owner, system, administrators = _trusted_sids()
    acl = security.ACL()
    flags = con.OBJECT_INHERIT_ACE | con.CONTAINER_INHERIT_ACE if directory else 0
    for sid in (owner, system, administrators):
        acl.AddAccessAllowedAceEx(security.ACL_REVISION_DS, flags, _rights().FILE_ALL_ACCESS, sid)
    descriptor = security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(owner, False)
    descriptor.SetSecurityDescriptorDacl(True, acl, False)
    descriptor.SetSecurityDescriptorControl(security.SE_DACL_PROTECTED, security.SE_DACL_PROTECTED)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


def _safe_path(path):
    raw = os.fspath(path)
    if raw.replace("/", "\\").startswith(("\\\\?\\", "\\\\.\\")):
        raise ValueError("Device paths are not accepted for private storage")
    path = Path(os.path.abspath(raw))
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update("{}{}".format(prefix, number) for prefix in ("COM", "LPT") for number in range(1, 10))
    for part in path.parts[1:]:
        if ":" in part or part.endswith((" ", ".")) or part.split(".", 1)[0].upper() in reserved:
            raise ValueError("Ambiguous Windows paths are not accepted for private storage")
    return path


def _check_handle(handle, directory=False):
    _, _, _, con, file, _ = _modules()
    attributes = _call(file.GetFileInformationByHandle, handle)[0]
    if attributes & con.FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError(errno.ELOOP, "Reparse points are not accepted for private storage")
    if (bool(attributes & con.FILE_ATTRIBUTE_DIRECTORY) != directory
            or _call(file.GetFileType, handle) != con.FILE_TYPE_DISK):
        raise ValueError("Storage input must be a regular {}".format("directory" if directory else "file"))


def _directory_handle(path, write_acl=False):
    _, _, _, con, file, _ = _modules()
    access = (_rights().FILE_READ_ATTRIBUTES | _rights().FILE_TRAVERSE | con.READ_CONTROL
              | (con.WRITE_DAC if write_acl else 0))
    handle = _call(file.CreateFile, str(path), access,
                   con.FILE_SHARE_READ, None, con.OPEN_EXISTING,
                   con.FILE_FLAG_BACKUP_SEMANTICS | file.FILE_FLAG_OPEN_REPARSE_POINT, None)
    try:
        _check_handle(handle, directory=True)
    except BaseException:
        _close_handle(handle)
        raise
    return handle


@contextmanager
def guarded_path(path, create_parents=False):
    """Pin parents against renames and concurrent writes to reparse metadata."""
    _, _, _, _, file, _ = _modules()
    path = _safe_path(path)
    handles = []
    try:
        current = Path(path.anchor)
        handles.append(_directory_handle(current))
        for part in path.parent.parts[1:]:
            current /= part
            try:
                handle = _directory_handle(current)
            except FileNotFoundError:
                if not create_parents:
                    raise
                try:
                    _call(file.CreateDirectory, str(current), _private_security(directory=True))
                except FileExistsError:
                    pass
                handle = _directory_handle(current)
            handles.append(handle)
        yield path, handles[-1]
    finally:
        close_error = None
        for handle in reversed(handles):
            try:
                _close_handle(handle)
            except OSError as error:
                close_error = close_error or error
        if close_error is not None:
            raise close_error


def _check_owned(handle, private=False):
    _, _, _, con, _, security = _modules()
    descriptor = _call(security.GetSecurityInfo, handle, security.SE_FILE_OBJECT,
                       security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
    trusted = _trusted_sids()
    if descriptor.GetSecurityDescriptorOwner() not in _owner_sids():
        raise ValueError("The storage object must be owned by the current user")
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        raise ValueError("An unrestricted storage ACL is not accepted")
    rights = _rights()
    unsafe = (rights.FILE_WRITE_DATA | rights.FILE_APPEND_DATA | rights.FILE_WRITE_EA | rights.FILE_WRITE_ATTRIBUTES
              | rights.FILE_DELETE_CHILD | con.DELETE | con.WRITE_DAC | con.WRITE_OWNER
              | con.GENERIC_WRITE | con.GENERIC_ALL)
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        kind, flags = ace[0]
        if flags & con.INHERIT_ONLY_ACE:
            continue
        if kind == security.ACCESS_DENIED_ACE_TYPE:
            continue  # Ignoring deny entries can only make this check stricter.
        if kind != security.ACCESS_ALLOWED_ACE_TYPE:
            raise ValueError("An unsupported storage ACL cannot be verified")
        mask, sid = ace[1], ace[2]
        if sid not in trusted and (private or mask & unsafe):
            # Diagnostics only: identify the rejected ACE (SID, type, flags,
            # mask) without logging file contents or credentials. The policy
            # itself is unchanged until a native test shows the actual ACE.
            logger.warning(
                "Rejected storage ACE: sid=%s type=%s flags=%s mask=%s private=%s",
                sid, kind, flags, hex(mask), private)
            raise ValueError("The storage ACL grants access to another principal")


def ensure_owned_directory(path):
    """Create missing directories privately; validate existing ACLs without editing them."""
    path = _safe_path(path)
    with guarded_path(path / '.directory-check', create_parents=True) as (unused_path, parent):
        _check_owned(parent)
    return path


def ensure_private_directory(path):
    """Create a private directory, or restrict an existing current-user directory."""
    _, _, _, _, file, security = _modules()
    with guarded_path(path, create_parents=True) as (path, unused_parent):
        try:
            _call(file.CreateDirectory, str(path), _private_security(directory=True))
        except FileExistsError:
            pass
        handle = _directory_handle(path, write_acl=True)
        try:
            descriptor = _call(security.GetSecurityInfo, handle, security.SE_FILE_OBJECT,
                               security.OWNER_SECURITY_INFORMATION)
            if descriptor.GetSecurityDescriptorOwner() not in _owner_sids():
                raise ValueError("The private directory must be owned by the current user")
            _, _, _, con, _, _ = _modules()
            _check_handle(handle, directory=True)
            owner, system, administrators = _trusted_sids()
            acl = security.ACL()
            flags = con.OBJECT_INHERIT_ACE | con.CONTAINER_INHERIT_ACE
            for sid in (owner, system, administrators):
                acl.AddAccessAllowedAceEx(security.ACL_REVISION_DS, flags, _rights().FILE_ALL_ACCESS, sid)
            _call(security.SetSecurityInfo, handle, security.SE_FILE_OBJECT,
                  security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
                  None, None, acl, None)
            _check_owned(handle, private=True)
        finally:
            _close_handle(handle)
    return path


def open_regular(path, writable=False, create=False, exclusive=False, private=False, deny_write=False, deny_delete=False):
    """Return an owned CRT descriptor; reject final and ancestor reparse points."""
    msvcrt, _, _, con, file, _ = _modules()
    descriptor = None
    try:
        with guarded_path(path, create_parents=create) as (path, unused_parent):
            access = con.GENERIC_READ | con.READ_CONTROL
            if writable:
                access |= con.GENERIC_WRITE
            disposition = con.CREATE_NEW if exclusive else con.OPEN_ALWAYS if create else con.OPEN_EXISTING
            share = con.FILE_SHARE_READ | (0 if deny_delete else con.FILE_SHARE_DELETE)
            if not deny_write:
                share |= con.FILE_SHARE_WRITE
            handle = _call(file.CreateFile, str(path), access, share,
                           _private_security() if create else None, disposition,
                           con.FILE_ATTRIBUTE_NORMAL | file.FILE_FLAG_OPEN_REPARSE_POINT, None)
            try:
                _check_handle(handle)
                if private:
                    _check_owned(handle, private=True)
                flags = os.O_BINARY | (os.O_RDWR if writable else os.O_RDONLY)
                # open_osfhandle takes ownership after successful conversion.
                descriptor = msvcrt.open_osfhandle(int(handle), flags)
                handle.Detach()
                handle = None
            finally:
                if handle is not None:
                    _close_handle(handle)
        return descriptor
    except BaseException as error:
        # A parent-handle close failure must not leak the descriptor that would
        # otherwise have been returned to the caller.
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as cleanup_error:
                error.descriptor_cleanup_error = cleanup_error
        raise


def private_temporary(parent, prefix, suffix=""):
    """Create with its final protected ACL, never with an initially public ACL."""
    parent = Path(parent)
    for unused in range(100):
        path = parent / (prefix + secrets.token_hex(12) + suffix)
        try:
            return open_regular(path, writable=True, create=True, exclusive=True, private=True), str(path)
        except FileExistsError:
            continue
    raise FileExistsError(errno.EEXIST, "Could not allocate a private temporary file")


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def owned_identity(path):
    """Revalidate the parent ACL and file identity without following links."""
    with guarded_path(path) as (path, parent):
        _check_owned(parent)
        parent_info = os.stat(path.parent, follow_symlinks=False)
        descriptor = open_regular(path, private=False, deny_write=True)
        try:
            msvcrt, _, _, _, _, _ = _modules()
            _check_owned(msvcrt.get_osfhandle(descriptor))
            info = os.fstat(descriptor)
            return (parent_info.st_dev, parent_info.st_ino, *_identity(info))
        finally:
            os.close(descriptor)


def read_owned_text(path, max_bytes):
    """Read bounded UTF-8 and return the same parent/file identity as POSIX dotenv."""
    with guarded_path(path) as (path, parent):
        _check_owned(parent)
        parent_info = os.stat(path.parent, follow_symlinks=False)
        descriptor = open_regular(path, deny_write=True)
        try:
            msvcrt, _, _, _, _, _ = _modules()
            _check_owned(msvcrt.get_osfhandle(descriptor))
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                raise ValueError("The environment file cannot be safely changed")
            chunks = bytearray()
            while len(chunks) <= max_bytes:
                block = os.read(descriptor, min(8192, max_bytes + 1 - len(chunks)))
                if not block:
                    break
                chunks.extend(block)
            if len(chunks) > max_bytes or _identity(os.fstat(descriptor)) != _identity(before):
                raise ValueError("The environment file cannot be safely changed")
            return chunks.decode("utf-8"), (parent_info.st_dev, parent_info.st_ino, *_identity(before))
        finally:
            os.close(descriptor)


def publish_temporary(source, target, expected_identity=None):
    """Atomically rename the verified private source handle into its pinned parent.

    The optional identity protects edits to an existing owned file; callers must
    serialize cooperating writers with file_lock for a whole read/edit transaction.
    """
    _, _, _, con, file, _ = _modules()
    published = False
    try:
        with guarded_path(target) as (target, parent):
            _check_owned(parent)
            source = _safe_path(source)
            if source.parent != target.parent:
                raise ValueError("Atomic publication requires a sibling temporary file")
            handle = _call(file.CreateFile, str(source), con.GENERIC_READ | con.READ_CONTROL | con.DELETE,
                           con.FILE_SHARE_READ | con.FILE_SHARE_DELETE, None, con.OPEN_EXISTING,
                           con.FILE_ATTRIBUTE_NORMAL | file.FILE_FLAG_OPEN_REPARSE_POINT, None)
            try:
                _check_handle(handle)
                _check_owned(handle, private=True)
                if expected_identity is not None and owned_identity(target) != expected_identity:
                    raise ValueError("The original file changed before publication")
                # SetFileInformationByHandle's current implementation converts
                # the name via RtlDosPathNameToNtPathName and passes RootDirectory
                # through unchanged: a non-NULL RootDirectory with a relative
                # FileName is rejected with WinError 87. The supported form is a
                # fully qualified FileName with a NULL RootDirectory. The parent
                # handles pinned by guarded_path are still held for the whole
                # transaction, so the parent cannot be renamed underneath us.
                _call(file.SetFileInformationByHandle, handle, file.FileRenameInfo,
                      {"ReplaceIfExists": True, "RootDirectory": None, "FileName": str(target)})
                published = True
            finally:
                _close_handle(handle)
    except OSError as error:
        if published:
            raise FilePublicationCommittedError(error) from error
        raise


def sync_publication(path):
    """Verify completion after rename; failures mean publication already occurred."""
    descriptor = open_regular(path, writable=True, private=True)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync_directory(path):
    """Validate the directory; Windows does not support POSIX directory fsync."""
    with guarded_path(Path(path) / ".directory-check"):
        pass


@contextmanager
def file_lock(path):
    """Lock a byte of a stable sidecar across processes, retaining its handle."""
    msvcrt, pywintypes, _, con, file, _ = _modules()
    with guarded_path(path, create_parents=True) as (path, parent):
        _check_owned(parent)
        descriptor = open_regular(path, writable=True, create=True, private=True, deny_delete=True)
        handle = msvcrt.get_osfhandle(descriptor)
        overlap = pywintypes.OVERLAPPED()
        locked = False
        try:
            _call(file.LockFileEx, handle, con.LOCKFILE_EXCLUSIVE_LOCK, 1, 0, overlap)
            locked = True
            yield
        finally:
            try:
                if locked:
                    _call(file.UnlockFileEx, handle, 1, 0, overlap)
            finally:
                os.close(descriptor)
