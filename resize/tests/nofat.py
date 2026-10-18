#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-image counterexamples for inactive FAT entries in NoFatChain streams."""
import argparse
import json
import hashlib
import importlib.util
from pathlib import Path
import sys
from fixture import workload, serialize
from reader import Volume
from run import template, validate, resize, command, CLI


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    baseline = Path(__file__).resolve().parent / 'baselines/reader-before.py'
    spec = importlib.util.spec_from_file_location('reader_before', baseline)
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)
    report = dict(status='RUNNING', baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(), tests=[])
    try:
        # The old reader accepted legacy EOFs and misread inactive bad markers.
        fake = Volume.__new__(Volume)
        fake.count, fake.cluster, fake.heap = 4, 512, 1024
        fake.fat = lambda c: 0xfffffff8
        rejected = False
        try:
            fake.chain(2, 512)
        except AssertionError:
            rejected = True
        assert rejected, 'legacy FAT32 EOC is invalid in an exFAT chain'
        old_fake = before.Volume.__new__(before.Volume)
        old_fake.count, old_fake.cluster, old_fake.heap = 4, 512, 1024
        old_fake.fat = lambda c: 0xfffffff8
        assert old_fake.chain(2, 512) == [2], 'the recorded baseline must reproduce the defect'
        for index, (sector, cluster) in enumerate([(512, 512), (512, 4096), (4096, 4096), (4096, 16384)]):
            case = work / str(index)
            case.mkdir()
            source, image = case / 'template.img', case / 'image.img'
            template(source, sector, cluster, compact=True)
            files, actions = workload(index + 37, 5000)
            measured, expected = serialize(source, image, files, index + 37,
                                            system_tail=True, inactive_fat=True)
            snapshot = validate(image).snapshot()
            old_reader = case / 'input.img'
            old_reader.write_bytes(image.read_bytes())
            old_rejected = False
            try:
                before.Volume(old_reader)
            except AssertionError:
                old_rejected = True
            assert old_rejected, 'the old reader must reject this valid inactive-FAT fixture'
            # Keep the input counterexample. Its FAT contains inactive bad,
            # out-of-range, and free values for valid contiguous streams.
            with image.open('r+b') as f:
                f.truncate(16 << 20)
            for size in (16 << 20, 6 << 20, 12 << 20):
                resize(image, size, case / 'journal')
                validate(image, snapshot, size)
            report['tests'].append(dict(seed=index + 37, sector=sector, cluster=cluster,
                                        measurements=measured, before_rejected_valid_input=old_rejected, after_valid=True, status='PASS'))
            image.unlink()
            source.unlink()
        report['status'] = 'PASS'
    except BaseException as e:
        report.update(status='FAIL', error=repr(e))
        raise
    finally:
        (work / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(report['status'], len(report['tests']), 'inactive-FAT image cases')
    return 0


if __name__ == '__main__':
    sys.exit(main())
