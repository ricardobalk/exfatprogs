# SPDX-License-Identifier: GPL-2.0-or-later
"""Image transaction host. C callbacks cannot write without a durable undo log."""
import argparse
import ctypes as C
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import uuid

TOKEN = 'user.exfatprogs.resize'
BLOCK = 1024 * 1024
cancelled = False


class ResizeError(Exception):
    pass


def cancel(signum, frame):
    global cancelled
    cancelled = True


class Faults:
    """Explicit test interface. Trace records contain no file contents."""
    def __init__(self, spec=None, trace=None):
        self.mode, self.at = (spec.split(':') if spec else ('none', '0'))
        if self.mode not in ('none', 'kill', 'eio', 'enospc', 'short', 'eintr', 'cancel',
                             'eio-persistent', 'enospc-persistent'):
            raise ResizeError('invalid test fault')
        self.at = int(self.at)
        self.count = 0
        self.trace = trace
        self.written = 0
        if trace:
            # A trace must never append to an image, journal, or existing file.
            fd = os.open(trace, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)

    def hit(self, label):
        self.count += 1
        reached = self.count == self.at or (self.mode.endswith('-persistent') and self.count >= self.at)
        if self.trace:
            with open(self.trace, 'a', encoding='utf-8') as log:
                log.write(json.dumps(dict(position=self.count, event=label,
                                          injected=self.mode if reached else None)) + '\n')
                log.flush()
                os.fsync(log.fileno())
        if not reached:
            return None
        if self.mode == 'kill':
            os.kill(os.getpid(), signal.SIGKILL)
        if self.mode in ('eio', 'enospc', 'eio-persistent', 'enospc-persistent'):
            code = errno.EIO if self.mode.startswith('eio') else errno.ENOSPC
            raise OSError(code, self.mode + ' at ' + label)
        if self.mode == 'cancel':
            cancel(0, None)
        return self.mode


def read_exact(fd, size, offset):
    chunks = []
    while size:
        try:
            data = os.pread(fd, min(size, BLOCK), offset)
        except InterruptedError:
            continue
        if not data:
            raise ResizeError('short read at byte ' + str(offset))
        chunks.append(data)
        offset += len(data)
        size -= len(data)
    return b''.join(chunks)


def write_exact(fd, data, offset, faults, label):
    view = memoryview(data)
    while view:
        try:
            action = faults.hit(label)
            if action == 'eintr':
                raise InterruptedError(errno.EINTR, 'injected interruption')
            part = view[:max(1, len(view) // 2)] if action == 'short' else view
            count = os.pwrite(fd, part, offset)
            if count <= 0:
                raise ResizeError('zero-length write')
        except InterruptedError:
            continue
        if label == 'source.write':
            faults.written += count
        view = view[count:]
        offset += count


def sync(fd, faults, label):
    while True:
        try:
            action = faults.hit(label)
            if action == 'eintr':
                raise InterruptedError(errno.EINTR, 'injected interruption')
            os.fsync(fd)
            return
        except InterruptedError:
            continue


def digest(fd, size):
    h = hashlib.sha256()
    for offset in range(0, size, BLOCK):
        h.update(read_exact(fd, min(BLOCK, size - offset), offset))
    return h.hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':')).encode('ascii')


def record(data):
    return canonical(dict(payload=data, sha256=hashlib.sha256(canonical(data)).hexdigest()))


def read_record(fd):
    size = os.fstat(fd).st_size
    if size > 65536:
        raise ResizeError('journal record is too large')
    try:
        item = json.loads(read_exact(fd, size, 0))
        if item['sha256'] != hashlib.sha256(canonical(item['payload'])).hexdigest():
            raise ValueError('checksum')
        return item['payload']
    except (KeyError, TypeError, ValueError) as e:
        raise ResizeError('invalid journal record') from e


def token(fd):
    try:
        raw = os.getxattr(fd, TOKEN)
        return raw.decode('ascii') if re.fullmatch(b'[0-9a-f]{32}', raw) else '<invalid-token>'
    except OSError as e:
        if e.errno in (errno.ENODATA, errno.ENOTSUP):
            return None
        raise


def regular_open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC)
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
        os.close(fd)
        raise ResizeError('only regular volume images with one link are supported')
    return fd


def check_loops(fd):
    """Reject an image attached to any visible Linux loop device, mounted or not."""
    if sys.platform != 'linux':
        raise ResizeError('the experimental image host supports Linux only')
    identity = os.fstat(fd)
    for backing in Path('/sys/block').glob('loop*/loop/backing_file'):
        try:
            name = backing.read_text().strip()
            if not name:
                continue
            resolved = '/' + name.lstrip('/')
            if resolved == os.readlink('/proc/self/fd/' + str(fd)):
                raise ResizeError('image is attached to a loop device')
            s = os.stat(resolved)
        except FileNotFoundError:
            # Unrelated host-namespace loops can name paths not visible here.
            # This cannot exclude a loop attachment in another namespace.
            continue
        if (s.st_dev, s.st_ino) == (identity.st_dev, identity.st_ino):
            raise ResizeError('image is attached to a loop device')


class Image:
    def __init__(self, path, writable):
        self.fd = regular_open(path, os.O_RDWR if writable else os.O_RDONLY)
        try:
            fcntl.flock(self.fd, (fcntl.LOCK_EX if writable else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            check_loops(self.fd)
            self.size = os.fstat(self.fd).st_size
            if self.size < 512 or self.size % 512:
                raise ResizeError('image length must be a positive multiple of 512 bytes')
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)


class Journal:
    def __init__(self, path, image, faults, create=False):
        self.path = Path(path).absolute()
        self.image = image
        self.faults = faults
        self.dirfd = None
        self.backup = None
        self.meta = None
        self.selected_state = None
        if create:
            available = shutil.disk_usage(self.path.parent).free
            if available < image.size + BLOCK:
                raise ResizeError('journal needs the full container size plus 1 MiB of free space')
            os.mkdir(self.path, 0o700)  # O_EXCL semantics. Never reuse a directory.
        try:
            self.dirfd = os.open(self.path, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            s = os.fstat(self.dirfd)
            if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
                raise ResizeError('journal must be owned by this user with mode 0700')
            if create:
                self.prepare()
            else:
                self.load()
        except BaseException:
            self.close()
            raise

    def file(self, name, flags):
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.dirfd)
        s = os.fstat(fd)
        if (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or
                s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o600):
            os.close(fd)
            raise ResizeError('unsafe journal file: ' + name)
        return fd

    def save(self, name, data):
        fd = self.file(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            write_exact(fd, record(data), 0, self.faults, 'journal.' + name + '.write')
            sync(fd, self.faults, 'journal.' + name + '.sync')
        finally:
            os.close(fd)

    def prepare(self):
        image, f = self.image, self.faults
        self.backup = self.file('preimage', os.O_RDWR | os.O_CREAT | os.O_EXCL)
        h = hashlib.sha256()
        for offset in range(0, image.size, BLOCK):
            if cancelled:
                raise ResizeError('cancelled before journal activation; image bytes are unchanged')
            data = read_exact(image.fd, min(BLOCK, image.size - offset), offset)
            h.update(data)
            write_exact(self.backup, data, offset, f, 'journal.preimage.write')
        sync(self.backup, f, 'journal.preimage.sync')
        s = os.fstat(image.fd)
        self.meta = dict(version=1, token=uuid.uuid4().hex, dev=s.st_dev, ino=s.st_ino,
                         size=image.size, sha256=h.hexdigest())
        self.save('manifest', self.meta)
        sync(self.dirfd, f, 'journal.prepare.dir.sync')
        parent = os.open(self.path.parent, os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            sync(parent, f, 'journal.prepare.parent.sync')
        finally:
            os.close(parent)
        f.hit('image.token.set')
        os.setxattr(image.fd, TOKEN, self.meta['token'].encode(), os.XATTR_CREATE)
        sync(image.fd, f, 'image.token.sync')
        # The caller opens the source-write gate only after this sync succeeds.

    def load(self):
        fd = self.file('manifest', os.O_RDONLY)
        try:
            self.meta = read_record(fd)
        finally:
            os.close(fd)
        m, s = self.meta, os.fstat(self.image.fd)
        if (not isinstance(m, dict) or set(m) != {'version', 'token', 'dev', 'ino', 'size', 'sha256'} or
                m['version'] != 1 or (m['dev'], m['ino'], m['size']) !=
                (s.st_dev, s.st_ino, self.image.size) or token(self.image.fd) != m['token']):
            raise ResizeError('wrong, stale, or inactive journal; no recovery write is allowed')
        self.backup = self.file('preimage', os.O_RDONLY)
        if os.fstat(self.backup).st_size != m['size'] or digest(self.backup, m['size']) != m['sha256']:
            raise ResizeError('corrupt preimage; no recovery write is allowed')

    def commit(self):
        value = dict(version=1, token=self.meta['token'],
                     sha256=digest(self.image.fd, self.image.size))
        self.save('commit.tmp', value)
        self.faults.hit('journal.commit.rename')
        os.rename('commit.tmp', 'commit', src_dir_fd=self.dirfd, dst_dir_fd=self.dirfd)
        sync(self.dirfd, self.faults, 'journal.commit.dir.sync')

    def restore(self):
        # Also used after cancellation. Verify the full journal before any write.
        if digest(self.backup, self.image.size) != self.meta['sha256']:
            raise ResizeError('corrupt preimage; recovery is blocked')
        for offset in range(0, self.image.size, BLOCK):
            write_exact(self.image.fd, read_exact(self.backup, min(BLOCK, self.image.size - offset),
                                                  offset), offset, self.faults, 'recovery.write')
        sync(self.image.fd, self.faults, 'recovery.sync')
        if digest(self.image.fd, self.image.size) != self.meta['sha256']:
            raise ResizeError('rollback readback mismatch')

    def recover(self):
        try:
            fd = self.file('commit', os.O_RDONLY)
        except FileNotFoundError:
            self.restore()
            state = 'old'
        else:
            try:
                c = read_record(fd)
            finally:
                os.close(fd)
            if (not isinstance(c, dict) or set(c) != {'version', 'token', 'sha256'} or c['version'] != 1 or
                    c['token'] != self.meta['token'] or
                    c['sha256'] != digest(self.image.fd, self.image.size)):
                raise ResizeError('invalid commit or changed image; recovery is blocked')
            state = 'new'
        self.selected_state = state
        self.cleanup()
        return state

    def cleanup(self):
        self.faults.hit('image.token.remove')
        os.removexattr(self.image.fd, TOKEN)
        sync(self.image.fd, self.faults, 'image.token.remove.sync')
        # No more source writes are allowed after token removal. Leftover files
        # are stale if cleanup fails. Never follow unexpected directory contents.
        for name in ('commit.tmp', 'commit', 'manifest', 'preimage'):
            self.faults.hit('journal.cleanup.' + name)
            try:
                os.unlink(name, dir_fd=self.dirfd)
            except FileNotFoundError:
                pass
        sync(self.dirfd, self.faults, 'journal.cleanup.dir.sync')
        self.faults.hit('journal.cleanup.rmdir')
        os.rmdir(self.path)
        parent = os.open(self.path.parent, os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            sync(parent, self.faults, 'journal.cleanup.parent.sync')
        finally:
            os.close(parent)

    def close(self):
        errors = []
        for field in ('backup', 'dirfd'):
            fd = getattr(self, field)
            if fd is not None:
                setattr(self, field, None)
                try:
                    os.close(fd)
                except OSError as e:
                    errors.append(e)
        if errors:
            raise errors[0]


READ = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint64, C.c_uint32, C.c_void_p)
WRITE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint64, C.c_uint32, C.c_void_p)
SYNC = C.CFUNCTYPE(C.c_int, C.c_void_p)
CANCEL = C.CFUNCTYPE(C.c_int, C.c_void_p)
EVENT = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)


class Device(C.Structure):
    _fields_ = [('context', C.c_void_p), ('sector_size', C.c_uint32),
                ('sector_count', C.c_uint64), ('read', READ), ('write', WRITE), ('sync', SYNC)]


class Monitor(C.Structure):
    _fields_ = [('context', C.c_void_p), ('cancel', CANCEL), ('event', EVENT)]


class Plan(C.Structure):
    _fields_ = [(k, C.c_uint64) for k in ('target_bytes', 'cluster_bytes', 'moved_clusters')] + [
        (k, C.c_uint32) for k in ('cluster_count', 'heap_sector', 'fat_sectors', 'used_clusters')]


ERRORS = ('success', 'invalid size or argument', 'invalid device', 'invalid filesystem',
          'target exceeds backing storage', 'integer overflow', 'I/O failure', 'workspace too small',
          'internal invariant failure', 'out of memory', 'unsupported revision', 'multiple FATs',
          'dirty volume', 'media failure flag', 'growth is too small for new bitmap', 'cluster limit',
          'vendor allocation', 'unknown critical entry', 'unknown allocated entry',
          'bad cluster conflicts with expanded FAT', 'unsupported sectors', 'cancelled',
          'not enough retained free clusters for shrink (including full source bitmap)')


class Engine:
    def __init__(self, image, faults, library=None):
        self.image, self.faults = image, faults
        here = Path(__file__).resolve().parent
        library = library or os.environ.get('RESIZE_LIBRARY')
        library = library or str(here / ('.libs/libresize-image.so' if (here / '.libs').exists()
                                       else 'libresize-image.so'))
        self.lib = C.CDLL(library)
        self.lib.image_inspect.argtypes = [C.POINTER(Device), C.c_uint64, C.POINTER(Plan)]
        self.lib.image_resize.argtypes = [C.POINTER(Device), C.c_uint64,
                                         C.POINTER(Monitor), C.POINTER(C.c_int)]
        self.active = False
        self.error = None
        self.callbacks = (READ(self.read), WRITE(self.write), SYNC(self.flush))
        self.device = Device(None, 512, image.size // 512, *self.callbacks)

    def read(self, ctx, sector, count, ptr):
        try:
            data = read_exact(self.image.fd, count * 512, sector * 512)
            C.memmove(ptr, data, len(data))
            return 0
        except BaseException as e:
            self.error = str(e)
            return 1

    def write(self, ctx, sector, count, ptr):
        try:
            if not self.active:
                raise ResizeError('source write without active journal')
            write_exact(self.image.fd, C.string_at(ptr, count * 512), sector * 512,
                        self.faults, 'source.write')
            return 0
        except BaseException as e:
            self.error = str(e)
            return 1

    def flush(self, ctx):
        try:
            if not self.active:
                raise ResizeError('unexpected preflight sync')
            sync(self.image.fd, self.faults, 'source.sync')
            return 0
        except BaseException as e:
            self.error = str(e)
            return 1

    def inspect(self, target):
        plan = Plan()
        code = self.lib.image_inspect(C.byref(self.device), target, C.byref(plan))
        if code:
            raise ResizeError('preflight: ' + ERRORS[code] + (': ' + self.error if self.error else ''))
        return {name: getattr(plan, name) for name, _ in plan._fields_}

    def resize(self, target):
        callbacks = (CANCEL(lambda ctx: int(cancelled)), EVENT(lambda ctx, event: None))
        monitor = Monitor(None, *callbacks)
        stage = C.c_int()
        code = self.lib.image_resize(C.byref(self.device), target, C.byref(monitor), C.byref(stage))
        if code:
            raise ResizeError(ERRORS[code] + ' at engine stage ' + str(stage.value) +
                              (': ' + self.error if self.error else ''))


def size_bytes(value):
    m = re.fullmatch(r'([0-9]+)(B|KiB|MiB|GiB|TiB)', value)
    if not m:
        raise argparse.ArgumentTypeError('use an unsigned integer with B, KiB, MiB, GiB, or TiB')
    n = int(m[1]) * 1024 ** ('B', 'KiB', 'MiB', 'GiB', 'TiB').index(m[2])
    if not 0 < n <= 0x7fffffffffffffff:
        raise argparse.ArgumentTypeError('size is outside 1..INT64_MAX bytes')
    return n


def check_fsck(image_fd):
    local = Path(__file__).resolve().parent.parent / 'fsck/fsck.exfat'
    program = os.environ.get('EXFAT_RESIZE_FSCK') or (str(local) if local.is_file() else shutil.which('fsck.exfat'))
    if not program:
        raise ResizeError('fsck.exfat is required for independent preflight and final checks')
    result = subprocess.run([program, '-n', '/proc/self/fd/' + str(image_fd)], pass_fds=(image_fd,), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise ResizeError('fsck.exfat -n rejected the image (exit ' + str(result.returncode) +
                          '); run the checker separately for details')


def main(argv=None):
    global cancelled
    cancelled = False
    parser = argparse.ArgumentParser(description='Experimental offline exFAT volume-image resize')
    parser.add_argument('image')
    parser.add_argument('--size', type=size_bytes)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--info', action='store_true')
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--journal', help='new private journal directory; required for writes/recovery')
    parser.add_argument('--test-fault', help='test only: kill|eio|enospc|short|eintr|cancel:position')
    parser.add_argument('--trace', help='test only: create a new JSONL I/O transition trace')
    args = parser.parse_args(argv)
    if args.recover:
        if not args.journal or args.size or args.dry_run or args.info:
            parser.error('--recover requires --journal and excludes --size, --dry-run, --info')
    elif args.info:
        if args.size or args.dry_run or args.journal:
            parser.error('--info excludes --size, --dry-run, --journal')
    elif args.size is None or (not args.dry_run and not args.journal):
        parser.error('resize requires --size and writing requires --journal')
    signal.signal(signal.SIGINT, cancel)
    signal.signal(signal.SIGTERM, cancel)
    image = journal = None
    committed = False
    try:
        faults = Faults(args.test_fault, args.trace)
        image = Image(args.image, not (args.dry_run or args.info))
        if args.recover:
            journal = Journal(args.journal, image, faults)
            state = journal.recover()
            print(json.dumps(dict(status='recovered', state=state)))
            return 0
        if token(image.fd) is not None:
            raise ResizeError('active transaction: use --recover with the original journal')
        boot = read_exact(image.fd, 512, 0)
        if boot[3:11] != b'EXFAT   ' or boot[64:72] != b'\0' * 8:
            raise ResizeError('only an exFAT volume at byte zero with PartitionOffset=0 is supported')
        if not 9 <= boot[108] <= 12:
            raise ResizeError('invalid sector size')
        current = int.from_bytes(boot[72:80], 'little') << boot[108]
        target = current if args.info else args.size
        check_fsck(image.fd)
        engine = Engine(image, faults)
        plan = engine.inspect(target)
        plan.update(current_bytes=current, backing_bytes=image.size, journal_bytes=image.size,
                    moved_bytes_bound=plan['moved_clusters'] * plan['cluster_bytes'],
                    mode='shrink' if plan['target_bytes'] < current else
                         'grow' if plan['target_bytes'] > current else 'no-op')
        if args.dry_run or args.info or plan['mode'] == 'no-op':
            print(json.dumps(dict(status='planned', **plan), sort_keys=True))
            return 0
        if cancelled:
            return 130
        journal = Journal(args.journal, image, faults, create=True)
        engine.active = True
        try:
            engine.resize(target)
            if cancelled:
                raise ResizeError('cancelled before journal commit')
            engine.inspect(target)
            check_fsck(image.fd)
            sync(image.fd, faults, 'image.result.sync')
            journal.commit()
            committed = True
        except BaseException:
            engine.active = False
            # Preserve evidence for I/O failure. Only cooperative cancellation
            # rolls back automatically, after all C callbacks have returned.
            if cancelled:
                journal.restore()
                journal.cleanup()
                print('cancelled: original image restored', file=sys.stderr)
                return 130
            raise
        engine.active = False
        journal.cleanup()
        print(json.dumps(dict(status='committed', source_bytes_written=faults.written, **plan),
                         sort_keys=True))
        return 0
    except (OSError, ResizeError, ValueError) as e:
        active = image is not None and token(image.fd) is not None
        committed = committed or (journal is not None and journal.selected_state == 'new')
        status = 'committed; cleanup incomplete' if committed else 'recovery required' if active else 'stopped'
        print(status + ': ' + str(e), file=sys.stderr)
        return 4 if committed else 3 if active else 130 if cancelled else 1
    finally:
        close_errors = []
        for resource in (journal, image):
            if resource:
                try:
                    resource.close()
                except OSError as e:
                    close_errors.append(str(e))
        if close_errors:
            status = 'committed; close failed' if committed else 'stopped; close failed; retain recovery files'
            print(status + ': ' + '; '.join(close_errors), file=sys.stderr)
            return 4 if committed else 3
