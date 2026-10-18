# SPDX-License-Identifier: GPL-2.0-or-later
"""Experimental offline image defrag with a durable full-image undo journal."""
import argparse
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

TOKEN = 'user.exfatprogs.defrag'
BLOCK = 1024 * 1024
cancelled = 0


class DefragError(Exception):
    pass


class Cancelled(DefragError):
    pass


def cancel(signum, frame):
    global cancelled
    cancelled = signum or signal.SIGINT


class Faults:
    """Explicit test interface. Trace records contain no file contents."""
    def __init__(self, spec=None, trace=None):
        self.mode, self.at = (spec.split(':') if spec else ('none', '0'))
        if self.mode not in ('none', 'kill', 'eio', 'enospc', 'short', 'eintr', 'cancel',
                             'eio-persistent', 'enospc-persistent', 'zero', 'sigint', 'sigterm'):
            raise DefragError('invalid test fault')
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
        if self.mode in ('cancel', 'sigint', 'sigterm'):
            os.kill(os.getpid(), signal.SIGTERM if self.mode == 'sigterm' else signal.SIGINT)
        return self.mode


def read_exact(fd, size, offset, faults=None, label='read'):
    chunks = []
    while size:
        try:
            action = faults.hit(label) if faults else None
            if action == 'eintr':
                raise InterruptedError(errno.EINTR, 'injected interruption')
            amount = max(1, min(size, BLOCK)//2) if action == 'short' else min(size, BLOCK)
            data = b'' if action == 'zero' else os.pread(fd, amount, offset)
        except InterruptedError:
            continue
        if not data:
            raise DefragError('short read at byte ' + str(offset))
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
            count = 0 if action == 'zero' else os.pwrite(fd, part, offset)
            if count <= 0:
                raise DefragError('zero-length write')
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
        raise DefragError('journal record is too large')
    try:
        item = json.loads(read_exact(fd, size, 0))
        if item['sha256'] != hashlib.sha256(canonical(item['payload'])).hexdigest():
            raise ValueError('checksum')
        return item['payload']
    except (KeyError, TypeError, ValueError) as e:
        raise DefragError('invalid journal record') from e


def token(fd):
    try:
        raw = os.getxattr(fd, TOKEN)
        return raw.decode('ascii') if re.fullmatch(b'[0-9a-f]{32}', raw) else '<invalid-token>'
    except OSError as e:
        if e.errno in (errno.ENODATA, errno.ENOTSUP):
            return None
        raise


def regular_open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
        os.close(fd)
        raise DefragError('only regular volume images with one link are supported')
    return fd


def check_loops(fd):
    """Reject an image attached to any visible Linux loop device, mounted or not."""
    if sys.platform != 'linux':
        raise DefragError('the experimental image host supports Linux only')
    identity = os.fstat(fd)
    for backing in Path('/sys/block').glob('loop*/loop/backing_file'):
        try:
            name = backing.read_text().strip()
            if not name:
                continue
            resolved = '/' + name.lstrip('/')
            if resolved == os.readlink('/proc/self/fd/' + str(fd)):
                raise DefragError('image is attached to a loop device')
            s = os.stat(resolved)
        except FileNotFoundError:
            # Unrelated host-namespace loops can name paths not visible here.
            # This cannot exclude a loop attachment in another namespace.
            continue
        if (s.st_dev, s.st_ino) == (identity.st_dev, identity.st_ino):
            raise DefragError('image is attached to a loop device')


class Image:
    def __init__(self, path, writable):
        self.fd = regular_open(path, os.O_RDWR if writable else os.O_RDONLY)
        try:
            fcntl.flock(self.fd, (fcntl.LOCK_EX if writable else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            check_loops(self.fd)
            self.size = os.fstat(self.fd).st_size
            if self.size < 512 or self.size > (256 << 20) or self.size % 512:
                raise DefragError('image must be a multiple of 512 bytes, within 512 bytes..256 MiB')
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
                raise DefragError('journal needs the full container size plus 1 MiB of free space')
            os.mkdir(self.path, 0o700)  # O_EXCL semantics. Never reuse a directory.
        try:
            self.dirfd = os.open(self.path, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            s = os.fstat(self.dirfd)
            if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
                raise DefragError('journal must be owned by this user with mode 0700')
            if create:
                self.prepare()
            else:
                self.load()
        except BaseException:
            self.close()
            raise

    def file(self, name, flags):
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=self.dirfd)
        s = os.fstat(fd)
        if (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or
                s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o600):
            os.close(fd)
            raise DefragError('unsafe journal file: ' + name)
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
                raise DefragError('cancelled before journal activation; image bytes are unchanged')
            data = read_exact(image.fd, min(BLOCK, image.size - offset), offset)
            h.update(data)
            write_exact(self.backup, data, offset, f, 'journal.preimage.write')
        sync(self.backup, f, 'journal.preimage.sync')
        s = os.fstat(image.fd)
        self.meta = dict(version=1, token=uuid.uuid4().hex, dev=s.st_dev, ino=s.st_ino,
                         size=image.size, serial=read_exact(image.fd, 4, 100).hex(), sha256=h.hexdigest())
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
        if (not isinstance(m, dict) or set(m) != {'version', 'token', 'dev', 'ino', 'size', 'serial', 'sha256'} or
                m['version'] != 1 or (m['dev'], m['ino'], m['size']) !=
                (s.st_dev, s.st_ino, self.image.size) or token(self.image.fd) != m['token']):
            raise DefragError('wrong, stale, or inactive journal; no recovery write is allowed')
        self.backup = self.file('preimage', os.O_RDONLY)
        if (os.fstat(self.backup).st_size != m['size'] or
                read_exact(self.backup, 4, 100).hex() != m['serial'] or
                digest(self.backup, m['size']) != m['sha256']):
            raise DefragError('corrupt preimage; no recovery write is allowed')

    def commit(self):
        value = dict(version=1, token=self.meta['token'],
                     sha256=digest(self.image.fd, self.image.size))
        self.save('commit.tmp', value)
        self.faults.hit('journal.commit.rename')
        os.rename('commit.tmp', 'commit', src_dir_fd=self.dirfd, dst_dir_fd=self.dirfd)
        sync(self.dirfd, self.faults, 'journal.commit.dir.sync')

    def restore(self):
        # A published commit must be resolved by recover(), never overwritten.
        try:
            os.stat('commit', dir_fd=self.dirfd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise DefragError('commit record is present; use recovery to select the state')
        # Also used after cancellation. Verify the full journal before any write.
        if digest(self.backup, self.image.size) != self.meta['sha256']:
            raise DefragError('corrupt preimage; recovery is blocked')
        for offset in range(0, self.image.size, BLOCK):
            write_exact(self.image.fd, read_exact(self.backup, min(BLOCK, self.image.size - offset),
                                                  offset), offset, self.faults, 'recovery.write')
        sync(self.image.fd, self.faults, 'recovery.sync')
        if digest(self.image.fd, self.image.size) != self.meta['sha256']:
            raise DefragError('rollback readback mismatch')

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
                raise DefragError('invalid commit or changed image; recovery is blocked')
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


def check_fsck(image_fd, program):
    result = subprocess.run([program, '-n', '/proc/self/fd/' + str(image_fd)],
                            pass_fds=(image_fd,), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise DefragError('fsck -n rejected image: ' + result.stdout.decode(errors='replace'))


def run_engine(image, program, faults):
    """C child is killed by Linux if its transaction host dies, before unlocking."""
    import ctypes
    parent = os.getpid()
    def parent_death():
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) or os.getppid() != parent:
            os._exit(125)
    faults.hit('engine.start')
    if cancelled:
        raise Cancelled('cancelled before starting C engine')
    engine_env = os.environ.copy()
    preload = engine_env.pop('EXFAT_DEFRAG_TEST_PRELOAD', None)
    if preload:
        runtime = engine_env.get('DEFRAG_ASAN_RUNTIME')
        engine_env['LD_PRELOAD'] = (runtime + ':' if runtime else '') + preload
    proc = subprocess.Popen([program, '-f', '/proc/self/fd/' + str(image.fd)],
                            pass_fds=(image.fd,), preexec_fn=parent_death, env=engine_env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    forwarded = False
    try:
        while True:
            if cancelled and not forwarded:
                proc.send_signal(cancelled)
                forwarded = True
            try:
                out, err = proc.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    faults.hit('engine.finished')
    if proc.returncode and proc.returncode not in (130, 143) and not (forwarded and proc.returncode in (-2, -15)):
        raise DefragError('engine exit ' + str(proc.returncode) + ': ' + err.decode(errors='replace'))
    if proc.returncode in (130, 143) or cancelled:
        if not cancelled:
            cancel(proc.returncode - 128, None)
        raise Cancelled('cancelled C engine')


def inspect(image, faults=None):
    from layout import Layout
    return Layout(read_exact(image.fd, image.size, 0, faults, 'image.inspect.read'))


def main(argv=None):
    global cancelled
    cancelled = 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--dry-run', '-a', action='store_true')
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--journal', help='new private journal directory; required for writes/recovery')
    parser.add_argument('--engine', default=str(Path(__file__).resolve().parents[1] / 'build-defrag-tests/defrag.exfat'))
    parser.add_argument('--fsck', default=str(Path(__file__).resolve().parents[1] / 'build-defrag-tests/fsck.exfat'))
    parser.add_argument('--test-fault', help='test only: mode:transition (see documentation)')
    parser.add_argument('--trace', help='test only: create a new JSONL transition trace')
    args = parser.parse_args(argv)
    if args.recover and (not args.journal or args.dry_run):
        parser.error('--recover requires --journal and excludes --dry-run')
    if not args.dry_run and not args.journal:
        parser.error('writes require --journal')
    if args.dry_run and args.journal:
        parser.error('--dry-run excludes --journal')
    signal.signal(signal.SIGINT, cancel)
    signal.signal(signal.SIGTERM, cancel)
    image = journal = None
    committed = False
    try:
        faults = Faults(args.test_fault, args.trace)
        image = Image(args.image, not args.dry_run)
        if args.recover:
            journal = Journal(args.journal, image, faults)
            state = journal.recover()
            print(json.dumps(dict(status='recovered', state=state, cancellation=cancelled or None)))
            return 128 + cancelled if cancelled else 0
        if token(image.fd) is not None:
            raise DefragError('active transaction: recover with the original journal')
        before = inspect(image, faults)
        check_fsck(image.fd, args.fsck)
        report = before.report()
        # No fragmentation within any allocation: avoid writes and journal creation.
        if args.dry_run or before.breaks == 0:
            print(json.dumps(dict(status='planned' if args.dry_run else 'no-op', **report), sort_keys=True))
            return 0
        if cancelled:
            return 128 + cancelled
        journal = Journal(args.journal, image, faults, create=True)
        try:
            run_engine(image, args.engine, faults)
            if cancelled:
                raise Cancelled('cancelled before commit')
            after = inspect(image, faults)
            if not before.equivalent(after) or after.breaks:
                raise DefragError('postcondition: content/metadata changed or target fragmentation remains')
            check_fsck(image.fd, args.fsck)
            sync(image.fd, faults, 'image.result.sync')
            if cancelled:
                raise Cancelled('cancelled before commit batch')
            journal.commit()
            committed = True
        except Cancelled:
            journal.restore()
            journal.cleanup()
            print('cancelled: original bytes restored', file=sys.stderr)
            return 128 + (cancelled or signal.SIGINT)
        journal.cleanup()
        print(json.dumps(dict(status='committed', before=report, after=after.report(), cancellation=cancelled or None), sort_keys=True))
        return 128 + cancelled if cancelled else 0
    except (OSError, DefragError, ValueError) as exc:
        try:
            active = image is not None and token(image.fd) is not None
        except OSError:
            active = True
        committed = committed or (journal is not None and journal.selected_state == 'new')
        status = 'committed; cleanup incomplete' if committed else 'recovery required' if active else 'stopped'
        print(status + ': ' + str(exc), file=sys.stderr)
        return 4 if committed else 3 if active else 128 + cancelled if cancelled else 1
    finally:
        errors = []
        for resource in (journal, image):
            if resource:
                try:
                    resource.close()
                except OSError as exc:
                    errors.append(str(exc))
        if errors:
            print('close failed; retain recovery files: ' + '; '.join(errors), file=sys.stderr)
            return 4 if committed else 3


if __name__ == '__main__':
    raise SystemExit(main())
