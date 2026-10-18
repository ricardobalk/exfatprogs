#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail closed on MBR hybrid volumes and complete partitioned disk images."""
import argparse
import json
import os
from pathlib import Path
import sys
from run import ROOT, command, CLI, MKFS, FSCK, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    before = ROOT / 'resize/tests/baselines/image-host-before-container-check.py'
    env = os.environ.copy()
    env.update(RESIZE_LIBRARY=str(ROOT / 'resize/.libs/libresize-image.so'),
               EXFAT_RESIZE_FSCK=str(FSCK))
    baseline = [sys.executable, '-c',
                'import runpy,sys; sys.exit(runpy.run_path(sys.argv.pop(1))["main"]())', str(before)]
    report = dict(status='RUNNING', baseline_sha256=sha(before), tests=[])
    try:
        for kind in ('none', 'mbr', 'gpt'):
            image = work / (kind + '.img')
            with image.open('wb') as f:
                f.truncate(8 << 20)
            command([MKFS, '-q', '-P', kind, image])
            original_hash = sha(image)
            old = command(baseline + [image, '--size', '6MiB', '--dry-run'],
                          expect=(1,) if kind == 'gpt' else (0,), env=env)
            assert sha(image) == original_hash
            expect = (0,) if kind == 'none' else (1,)
            new = command(CLI + [image, '--size', '6MiB', '--dry-run'], expect=expect)
            assert sha(image) == original_hash
            if kind != 'none':
                command(CLI + [image, '--size', '6MiB', '--journal', work / 'forbidden'], expect=(1,))
                assert sha(image) == original_hash and not (work / 'forbidden').exists()
            report['tests'].append(dict(layout=kind, before_exit=old.returncode,
                                        after_exit=new.returncode, unchanged=True,
                                        image_sha256=original_hash, status='PASS'))
        report['status'] = 'PASS'
    except BaseException as e:
        report.update(status='FAIL', error=repr(e))
        raise
    finally:
        (work / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(report['status'], len(report['tests']), 'container-boundary cases')
    return 0


if __name__ == '__main__':
    sys.exit(main())
