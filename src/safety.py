"""Linux execution and filesystem boundaries shared by installer and helper."""
import contextlib
import fcntl
import os
from pathlib import Path
import pwd
import re
import secrets
import selectors
import signal
import stat
import subprocess
import time

UID = os.getuid()
HOME = Path(pwd.getpwuid(UID).pw_dir)
RUNTIME = Path('/run/user') / str(UID)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def trusted_system_file(path, executable=False):
    """Resolve only root-managed identities; never search PATH or user dirs."""
    path = Path(path)
    if not path.is_absolute() or not str(path).startswith('/usr/'):
        raise ValueError('Expected an absolute /usr path')
    resolved = path.resolve(strict=True)
    for part in [*reversed(resolved.parents), resolved]:
        info = part.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError(f'Untrusted system path: {part}')
    if not stat.S_ISREG(info.st_mode) or (executable and not info.st_mode & 0o111):
        raise PermissionError(f'Invalid system file: {resolved}')
    return str(resolved)


def clean_environment():
    env = {'HOME': str(HOME), 'PATH': '/usr/bin', 'LANG': 'C.UTF-8',
           'XDG_RUNTIME_DIR': str(RUNTIME), 'DBUS_SESSION_BUS_ADDRESS': f'unix:path={RUNTIME}/bus',
           'SYSTEMD_PAGER': '', 'SYSTEMD_COLORS': '0'}
    signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    if signature:
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', signature):
            raise ValueError('Invalid Hyprland instance signature')
        env['HYPRLAND_INSTANCE_SIGNATURE'] = signature
    return env


def run_command(argv, *, check=True, timeout=3, limit=16384):
    """Bound live output and wall time; kill the entire new process group.

    Includes descendants keeping a pipe open after the direct child exits.
    No shell, inherited environment, stdin, or unbounded communicate buffers.
    """
    executable = trusted_system_file(argv[0], executable=True)
    data = bytearray()
    process = subprocess.Popen([executable, *argv[1:]], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=clean_environment(),
        cwd='/', start_new_session=True, close_fds=True)
    old_term = signal.getsignal(signal.SIGTERM)
    def terminate(*_):
        raise InterruptedError('Interrupted while running child process')
    signal.signal(signal.SIGTERM, terminate)
    try:
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f'Command deadline exceeded: {argv[0]}')
                for key, _ in selector.select(min(remaining, 0.05)):
                    chunk = os.read(key.fd, min(4096, limit + 1 - len(data)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        data.extend(chunk)
                        if len(data) > limit:
                            raise RuntimeError(f'Command output limit exceeded: {argv[0]}')
            result = subprocess.CompletedProcess(argv, process.returncode, data.decode(errors='replace'), '')
            if check and result.returncode:
                raise subprocess.CalledProcessError(result.returncode, argv, result.stdout)
            return result
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.stdout.close()
        try:
            process.wait(timeout=1)
        finally:
            signal.signal(signal.SIGTERM, old_term)


def _directory_ok(fd, *, leaf=False):
    info = os.fstat(fd)
    # Root-owned sticky /tmp is allowed while reaching isolated test roots.
    sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
    if info.st_uid not in (0, UID) or (info.st_mode & 0o022 and not sticky_root):
        raise PermissionError('Directory is not owned/trusted or is writable by others')
    if leaf and (info.st_uid != UID or info.st_mode & 0o022):
        raise PermissionError('User directory must be owned by the current uid and not group/world writable')


def _file_ok(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != UID or info.st_nlink != 1 or info.st_mode & 0o022:
        raise PermissionError('Expected an owned, singly linked regular file, not writable by others')
    return info


class SafeDir:
    """Pinned directory fds; never resolve a symlink during user-file traversal."""
    def __init__(self, path, *, create=False):
        path = Path(path)
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('Expected an absolute non-traversing directory')
        fd = os.open('/', DIR_FLAGS)
        try:
            for name in path.parts[1:]:
                _directory_ok(fd)
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            _directory_ok(fd, leaf=True)
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    @contextlib.contextmanager
    def parent(self, relative, create=False):
        parts = Path(relative).parts
        if not parts or Path(relative).is_absolute() or any(x in ('.', '..') for x in parts):
            raise ValueError('Unsafe relative path')
        fd = os.dup(self.fd)
        try:
            for name in parts[:-1]:
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
                _directory_ok(fd, leaf=True)
            yield fd, parts[-1]
        finally:
            os.close(fd)

    def read(self, relative, *, limit=2*1024*1024):
        try:
            with self.parent(relative) as (directory, name):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
                try:
                    info = _file_ok(fd)
                    if info.st_size > limit:
                        raise ValueError('File exceeds size limit')
                    data = bytearray()
                    while chunk := os.read(fd, min(65536, limit + 1 - len(data))):
                        data.extend(chunk)
                        if len(data) > limit:
                            raise ValueError('File exceeds size limit')
                    return bytes(data), stat.S_IMODE(info.st_mode)
                finally:
                    os.close(fd)
        except FileNotFoundError:
            return None

    def write(self, relative, data, mode=0o600):
        with self.parent(relative, create=True) as (directory, name):
            # Refuse unsafe existing entries; replacement never follows one.
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
            except FileNotFoundError:
                pass
            else:
                try:
                    _file_ok(fd)
                finally:
                    os.close(fd)
            temp = '.legion-' + secrets.token_hex(16)
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fchmod(stream.fileno(), mode)
                    os.fsync(stream.fileno())
                os.replace(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temp, dir_fd=directory)
                except FileNotFoundError:
                    pass

    def unlink(self, relative):
        with self.parent(relative) as (directory, name):
            # unlinkat removes the entry, never follows a swapped symlink.
            os.unlink(name, dir_fd=directory)
            os.fsync(directory)

    @contextlib.contextmanager
    def lock(self, relative, *, timeout=0):
        with self.parent(relative, create=True) as (directory, name):
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=directory)
            try:
                _file_ok(fd)
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.02)
                yield fd
            finally:
                os.close(fd)
