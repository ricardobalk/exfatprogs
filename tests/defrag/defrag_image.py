#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Copy, journaled defrag, independent verification, no-replace publication."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'defrag'))
from image_defrag import Image as LockedImage, Faults, read_exact, write_exact, sync, token
from image import Image as Oracle


class PublishedError(RuntimeError):
    pass


def run_tool(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} exit {result.returncode}: {result.stderr}')


def defrag_image(source, output, binary, fsck, faults, corrupt=False):
    output = Path(output)
    published = False
    image = LockedImage(source, False)
    try:
        if token(image.fd) is not None:
            raise ValueError('source has an unresolved journal')
        if os.path.lexists(output):
            raise FileExistsError(output)
        before_stat = os.fstat(image.fd)
        source_hash = hashlib.sha256()
        directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with tempfile.TemporaryDirectory(prefix='.defrag-', dir=output.parent) as work:
                candidate = Path(work)/'candidate.img'
                fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    for offset in range(0, image.size, 1 << 20):
                        data = read_exact(image.fd, min(1 << 20, image.size-offset), offset, faults, 'wrapper.source.read')
                        source_hash.update(data)
                        write_exact(fd, data, offset, faults, 'wrapper.copy.write')
                    sync(fd, faults, 'wrapper.candidate.sync')
                finally:
                    os.close(fd)
                now = os.fstat(image.fd)
                if (before_stat.st_size, before_stat.st_mtime_ns, before_stat.st_ctime_ns) != (now.st_size, now.st_mtime_ns, now.st_ctime_ns):
                    raise RuntimeError('source changed during copy')
                before, breaks = Oracle(candidate).inspect()
                host = Path(__file__).resolve().parents[2]/'defrag/defrag.exfat'
                run_tool([host, candidate, '--engine', binary, '--fsck', fsck, '--journal', Path(work)/'journal'])
                if corrupt:
                    data = Oracle(candidate)
                    with candidate.open('r+b') as stream:
                        stream.seek(data.heap)
                        stream.write(b'corrupt')
                run_tool([fsck, '-n', candidate])
                after, remaining = Oracle(candidate).inspect()
                if before != after or remaining:
                    raise RuntimeError('independent verification rejected the candidate')
                # Detect non-cooperating source changes throughout the operation.
                h = hashlib.sha256()
                for offset in range(0, image.size, 1 << 20):
                    h.update(read_exact(image.fd, min(1 << 20, image.size-offset), offset))
                if h.digest() != source_hash.digest():
                    raise RuntimeError('source changed before publication')
                with candidate.open('rb') as stream:
                    sync(stream.fileno(), faults, 'wrapper.validated.sync')
                faults.hit('wrapper.publish.link')
                os.link(candidate, output)  # Atomic no-replace; private candidate on same filesystem.
                published = True
                sync(directory, faults, 'wrapper.publish.dir.sync')
            sync(directory, faults, 'wrapper.cleanup.dir.sync')
        finally:
            os.close(directory)
        return breaks
    except BaseException as exc:
        if published:
            raise PublishedError('output is visible; publication/cleanup durability incomplete: ' + str(exc)) from exc
        raise
    finally:
        image.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--defrag', type=Path, required=True)
    p.add_argument('--fsck', type=Path, required=True)
    p.add_argument('--test-fault')
    p.add_argument('--trace')
    p.add_argument('--test-corrupt', action='store_true')
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    def stop(signum, frame):
        raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        count = defrag_image(a.source, a.output, a.defrag.resolve(), a.fsck.resolve(),
                             Faults(a.test_fault, a.trace), a.test_corrupt)
    except PublishedError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except KeyboardInterrupt as exc:
        return 128 + int(exc.args[0])
    except (OSError, ValueError, RuntimeError) as exc:
        print('candidate rejected: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(dict(status='published', before_breaks=count, after_breaks=0)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
