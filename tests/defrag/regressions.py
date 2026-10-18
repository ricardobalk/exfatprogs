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
    ):
        started = time.monotonic()
        target = a.out / (name + '.img')
        expected, before = fixture.make_fixture(target, a.mkfs.resolve(), 7, 500,
                                                 max(512, sector), vendor or False, sector)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        proc = subprocess.run([str(a.binary.resolve()), '-f', str(target)], capture_output=True,
                              env=os.environ | {'LD_PRELOAD': str(a.fault.resolve())} | env, timeout=30)
        issue = None
        try:
            actual, after = fixture.Image(target).inspect()
            if actual != expected:
                issue = 'semantic manifest changed'
            elif not env and after:
                issue = 'fragmentation remains'
        except ValueError as e:
            issue = str(e)
        expected_status = 1 if name == 'fsync-status' else 130 if name == 'interrupted-directory-fat' else 0
        if proc.returncode != expected_status:
            issue = (issue + '; ' if issue else '') + f'exit {proc.returncode}, expected {expected_status}'
        passed = bool(issue) if a.baseline else issue is None
        item = dict(case=name, status='PASS' if passed else 'FAIL', baseline=a.baseline,
                    observed_failure=issue, exit=proc.returncode, before_breaks=before,
                    source_sha256=digest, seconds=round(time.monotonic()-started, 3))
        (a.out / (name + '.log')).write_bytes(proc.stdout + proc.stderr)
        results.append(item)
        (a.out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(item), flush=True)
        if passed:
            target.unlink()
    return int(any(r['status'] != 'PASS' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
