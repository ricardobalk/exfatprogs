#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reproduce the upstream contiguous-system-stream assumption."""
import argparse
import json
from pathlib import Path
import shutil
import sys
from fixture import serialize, workload
from run import template, command, validate, sha, FSCK
from reader import Volume


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original, image = args.output / 'template.img', args.output / 'fragmented.img'
    template(original, 512, 4096)
    files, _ = workload(0, 5000)
    serialize(original, image, files, 0, True)
    baseline = command([args.baseline.resolve(), '-n', image], expect=(4,))
    after = command([FSCK, '-n', image])
    validate(image)
    (args.output / 'before.log').write_text(baseline.stdout + baseline.stderr)
    (args.output / 'after.log').write_text(after.stdout + after.stderr)
    report = dict(status='PASS', case='fragmented-upcase-fat-chain',
                  baseline_commit='1647ed54299ae8c4343a5edf40b892307f7e6459',
                  baseline_binary_sha256=sha(args.baseline), image_sha256=sha(image),
                  before_exit=baseline.returncode, after_exit=after.returncode)
    # Exercise the related repair path. New system clusters need real FAT links.
    for name, checker in [('baseline-repair', args.baseline.resolve()), ('fixed-repair', FSCK)]:
        candidate = args.output / (name + '.img')
        shutil.copyfile(original, candidate)
        v = Volume(candidate)
        upcase_cluster = int.from_bytes(v.systems[0x82]['raw'][20:24], 'little')
        with candidate.open('r+b') as f:
            f.seek(v.offset(upcase_cluster))
            f.write(b'\x7f')
        command([checker, '-y', '-s', candidate], expect=(0, 1))
        valid = True
        try:
            Volume(candidate)
        except AssertionError:
            valid = False
        report[name] = dict(independent_valid=valid, image_sha256=sha(candidate))
    assert not report['baseline-repair']['independent_valid']
    assert report['fixed-repair']['independent_valid']
    (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
