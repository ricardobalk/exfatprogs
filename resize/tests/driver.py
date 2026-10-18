#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Linux exFAT driver qualification. Create only private disposable loop images."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import CLI, MKFS, command, validate, sha
from reader import Volume


def driver_workload(mount, seed, iterations):
    rng = random.Random(seed)
    model = {}
    actions = []
    names = [f'{i:02d}_Δ猫_' + 'long_' * (i % 8) for i in range(64)]
    for i in range(iterations):
        name, op = rng.choice(names), rng.randrange(6)
        target = mount / name
        old = model.get(name, b'')
        data = rng.randbytes(rng.randrange(1, 1500))
        if op == 0:
            target.write_bytes(data)
            model[name] = data
        elif op == 1:
            with target.open('ab') as f:
                f.write(data[:200])
            model[name] = old + data[:200]
        elif op == 2:
            offset = rng.randrange(0, len(old) + 100)
            if not target.exists():
                target.touch()
            with target.open('r+b') as f:
                f.seek(offset)
                f.write(data[:100])
            model[name] = (old + bytes(max(0, offset - len(old))))[:offset] + data[:100] + old[offset + len(data[:100]):]
        elif op == 3:
            size = rng.randrange(2000)
            if not target.exists():
                target.touch()
            with target.open('r+b') as f:
                f.truncate(size)
            model[name] = old[:size] + bytes(max(0, size - len(old)))
        elif op == 4:
            other = rng.choice(names)
            if name in model and name != other:
                target.replace(mount / other)
                model[other] = model.pop(name)
            else:
                # Execute a real operation even when no rename source exists.
                target.stat() if target.exists() else mount.stat()
        else:
            target.unlink(missing_ok=True)
            model.pop(name, None)
        actions.append(dict(iteration=i, operation=op, path=name,
                            data_sha256=hashlib.sha256(data).hexdigest()))
    return model, actions


def compare(mount, model):
    assert {p.name for p in mount.iterdir()} == set(model)
    for name, expected in model.items():
        assert (mount / name).read_bytes() == expected, name


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', type=int, default=10)
    p.add_argument('--iterations', type=int, default=5000)
    p.add_argument('--require', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cap = int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines()
                   if line.startswith('CapEff:')), 16)
    report = dict(status='RUNNING', seeds=args.seeds, iterations=args.iterations, tests=[])
    if os.geteuid() != 0 or not cap & (1 << 21):
        report.update(status='NOT_RUN', reason='root and CAP_SYS_ADMIN are required for private loop mounts')
        (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(report['reason'])
        return 1 if args.require else 77
    try:
        for seed in range(args.seeds):
            # Keep a failed image and its log in the evidence directory. Cleanup
            # detaches only the loop device returned for this image.
            work = args.output / str(seed)
            work.mkdir()
            image, mount, journal = work / 'volume.img', work / 'mnt', work / 'journal'
            mount.mkdir()
            with open(image, 'wb') as f:
                f.truncate(64 << 20)
            command([MKFS, '-q', '-L', 'DRIVER', '-c', 4096, image])
            loop = None
            mounted = False
            def attach(readonly=False):
                nonlocal loop, mounted
                loop = command(['losetup', '--find', '--show', image]).stdout.strip()
                assert loop.startswith('/dev/loop')
                command(['mount', '-t', 'exfat', '-o', 'ro' if readonly else 'rw', loop, mount])
                mounted = True
            def detach():
                nonlocal loop, mounted
                if mounted:
                    command(['umount', mount])
                    mounted = False
                if loop:
                    command(['losetup', '-d', loop])
                    loop = None
            try:
                attach()
                with (mount / 'placement-filler').open('wb') as f:
                    for i in range(48):
                        f.write(b'P' * (1 << 20))
                model, actions = driver_workload(mount, seed, args.iterations)
                (mount / 'placement-filler').unlink()
                compare(mount, model)
                detach()
                (work / 'actions.jsonl').write_text(''.join(json.dumps(a) + '\n' for a in actions))
                source = validate(image)
                snapshot = source.snapshot()
                assert any(source.offset(c) >= 32 << 20 for c in source.owners), 'tail placement was not reached'
                sizes = (32 << 20, 96 << 20) if seed % 2 else (96 << 20, 32 << 20)
                outcomes = []
                for size in sizes:
                    old_length = Volume(image).length
                    if image.stat().st_size < size:
                        with open(image, 'r+b') as f:
                            f.truncate(size)
                    r = command(CLI + [image, '--size', str(size) + 'B', '--journal', journal])
                    outcomes.append(json.loads(r.stdout))
                    validate(image, snapshot, size)
                    attach(True)
                    compare(mount, model)
                    detach()
                    if size > old_length:
                        attach()
                        block = (b'Added capacity driver probe.\x00\xff' * 40000)[:1 << 20]
                        expected = hashlib.sha256()
                        with (mount / 'capacity-probe').open('wb') as f:
                            for i in range(80):
                                piece = block[:1 << 20]
                                f.write(piece)
                                expected.update(piece)
                            f.flush()
                            os.fsync(f.fileno())
                        with (mount / 'capacity-probe').open('rb') as f:
                            assert hashlib.file_digest(f, 'sha256').digest() == expected.digest()
                        detach()
                        probe = validate(image)
                        assert any(probe.offset(c) >= old_length for c, owner in probe.owners.items()
                                   if owner == '/capacity-probe'), 'driver did not use added capacity'
                        attach()
                        (mount / 'capacity-probe').unlink()
                        detach()
                        # Directory timestamps can change with an actual create/unlink.
                        snapshot = validate(image).snapshot()
                report['tests'].append(dict(seed=seed, iterations=args.iterations, status='PASS', resizes=outcomes))
            finally:
                detach()
            image.unlink()
        report['status'] = 'PASS'
    except BaseException as e:
        report.update(status='FAIL', error=repr(e))
        raise
    finally:
        (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
