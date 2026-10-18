#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Directed on-disk regressions. --baseline requires the old defects to fail."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import image as fixture


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('binary', 'mkfs', 'fault', 'out'):
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--baseline', action='store_true')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    results = []
    for name, vendor, sector, env in (
        ('empty-vendor-index', 'empty', 512, {}),
        ('vendor-checksum', 'populated', 512, {}),
        ('interrupted-directory-fat', None, 512, {'EXFAT_TEST_SIGNAL_AT': '7', 'EXFAT_TEST_SIGNAL': str(signal.SIGINT)}),
        ('logical-boot-sector', None, 4096, {}),
        ('fsync-status', None, 512, {'EXFAT_TEST_FSYNC_ERROR': '1'}),
        ('eintr-read', None, 512, {'EXFAT_TEST_READ_EINTR_AT': '1'}),
        ('directory-flush', None, 512, {'EXFAT_TEST_DIRECTORY_EIO': '1'}),
        ('partial-system-relocation', None, 512, {'EXFAT_TEST_SIGNAL_AT':'7', 'EXFAT_TEST_SIGNAL':str(signal.SIGINT)}),
        ('unowned-allocation', None, 512, {}),
    ):
        started = time.monotonic()
        target = a.out / (name + '.img')
        expected, before = fixture.make_fixture(target, a.mkfs.resolve(), 7, 500,
                                                 max(512, sector), vendor or False, sector, system_tail=name=='partial-system-relocation',log=a.out/(name+'.actions.jsonl'))
        (a.out/(name+'.expected.json')).write_text(json.dumps(expected,indent=2)+'\n')
        if name == 'unowned-allocation':
            reader = fixture.Image(target,mutable=True)
            reader.inspect()
            used = set(c for chain in reader.allocations for c in chain)
            unused = next(c for c in range(2,reader.count+2) if c not in used)
            root = reader.content(reader.chain(reader.root),reader.cluster)
            bitmap = fixture.u32(root,20)
            reader.data[reader.offset(bitmap)+(unused-2)//8] |= 1 << ((unused-2)%8)
            target.write_bytes(reader.data)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        proc = subprocess.run([str(a.binary.resolve()), '-a' if name=='unowned-allocation' else '-f', str(target)], capture_output=True,
                              env=os.environ | {'LD_PRELOAD': (os.environ.get('DEFRAG_ASAN_RUNTIME','') + ':' if os.environ.get('DEFRAG_ASAN_RUNTIME') else '') + str(a.fault.resolve())} | env, timeout=30)
        issue = None
        try:
            actual, after = fixture.Image(target).inspect()
            if actual != expected:
                issue = 'semantic manifest changed'
            elif not env and after:
                issue = 'fragmentation remains'
        except ValueError as e:
            issue = str(e)
        if name == 'directory-flush':
            issue = None  # Raw worker promises error propagation, not rollback.
        if name == 'unowned-allocation':
            issue = None if hashlib.sha256(target.read_bytes()).hexdigest()==digest else 'rejected image changed'
        expected_status = 1 if name in ('fsync-status','directory-flush','unowned-allocation') else 130 if name in ('interrupted-directory-fat','partial-system-relocation') else 0
        if proc.returncode != expected_status:
            issue = (issue + '; ' if issue else '') + f'exit {proc.returncode}, expected {expected_status}'
        if any(marker in proc.stderr.decode(errors='replace') for marker in ('AddressSanitizer','LeakSanitizer','runtime error:')):
            issue = 'sanitizer diagnostic'
        passed = bool(issue) if a.baseline else issue is None
        item = dict(case=name, seed=7, iterations=500, sector_bytes=sector,cluster_bytes=max(512,sector), status='PASS' if passed else 'FAIL', baseline=a.baseline,
                    observed_failure=issue, exit=proc.returncode, before_breaks=before,
                    source_sha256=digest, seconds=round(time.monotonic()-started, 3))
        (a.out / (name + '.log')).write_bytes(proc.stdout + proc.stderr)
        results.append(item)
        (a.out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(item), flush=True)
        if passed and not a.baseline:
            target.unlink()
    return int(any(r['status'] != 'PASS' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
