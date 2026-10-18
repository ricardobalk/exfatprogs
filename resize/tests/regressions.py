#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run existing fsck fixtures and preserve each checker exit status."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from run import ROOT, command, FSCK, sha


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--sanitize', action='store_true')
    args = p.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    checker = FSCK
    env = os.environ.copy()
    env['PATH'] = str(ROOT / 'mkfs') + ':' + str(ROOT / 'dump') + ':' + env['PATH']
    if args.sanitize:
        checker = args.output / 'fsck.exfat'
        command(['gcc', '-g', '-O1', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-fno-omit-frame-pointer', '-I' + str(ROOT / 'include'),
                 '-include', ROOT / 'config.h', ROOT / 'fsck/fsck.c', ROOT / 'fsck/repair.c',
                 *[ROOT / ('lib/' + s + '.c') for s in ('libexfat', 'exfat_fs', 'utils', 'exfat_dir')],
                 '-o', checker])
        env.update(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1')
    cases = sorted((ROOT / 'tests').glob('*/exfat.img.tar.xz')) + sorted((ROOT / 'tests').glob('*/[0-9]*.sh'))
    results = dict(status='RUNNING', sanitizer=args.sanitize, checker_sha256=sha(checker), tests=[])
    try:
        for i, case in enumerate(cases):
            work = args.output / str(i)
            work.mkdir()
            image = work / 'exfat.img'
            if case.suffix == '.xz':
                command(['tar', '-xf', case, '-C', work])
            else:
                command([case, image], env=env)
            detection = subprocess.run([checker, '-n', image], capture_output=True, text=True, env=env)
            (work / 'detection.log').write_text(detection.stdout + detection.stderr)
            assert detection.returncode == 4, (str(case), detection.returncode)
            repair = command([checker, '-y', '-s', image], expect=(0, 1), env=env)
            (work / 'repair.log').write_text(repair.stdout + repair.stderr)
            final = command([checker, '-n', image], env=env)
            (work / 'final.log').write_text(final.stdout + final.stderr)
            results['tests'].append(dict(case=str(case.relative_to(ROOT)), detection_exit=detection.returncode,
                                         repair_exit=repair.returncode, final_exit=final.returncode, status='PASS'))
            image.unlink()
        results['status'] = 'PASS'
    except BaseException as e:
        results.update(status='FAIL', error=repr(e))
        raise
    finally:
        (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(results['status'], len(results['tests']), 'fsck cases')
    return 0


if __name__ == '__main__':
    sys.exit(main())
