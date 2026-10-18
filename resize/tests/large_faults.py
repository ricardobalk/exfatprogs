#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Sample actual I/O faults on larger real images. These are not driver tests."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
from fixture import serialize, workload
from run import command, CLI, MKFS, TUNE, validate, sha, events, active, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    source = work / 'template.img'
    original = work / 'original.img'
    image = work / 'candidate.img'
    journal = work / 'journal'
    with source.open('wb') as f:
        f.truncate(128 << 20)
    command([MKFS, '-q', '-L', 'LARGE', '-s', 4096, '-c', 16384, '-b', 4096, source])
    command([TUNE, '-I', '0x52535a45', source])
    files, actions = workload(1935, 5000)
    files['!large'] = bytes(range(256)) * 32768  # 8 MiB, stored in the external model.
    measured, external = serialize(source, original, files, 1935, system_tail=True)
    expected = validate(original).snapshot()
    (work / 'actions.jsonl').write_text(''.join(json.dumps(a) + '\n' for a in actions))
    report = dict(status='RUNNING', seed=1935, iterations=5000, source_bytes=128 << 20,
                  sector=4096, cluster=16384, large_file_bytes=len(files['!large']),
                  measurements=measured, source_sha256={str(p.relative_to(ROOT)): sha(p) for p in
                      [Path(__file__).resolve(), ROOT / 'resize/image_resize.py', ROOT / 'resize/tests/fixture.py']},
                  tests=[])
    start = time.monotonic()
    try:
        for direction, target in [('shrink', 80 << 20), ('grow', 192 << 20)]:
            base = work / ('base-' + direction + '.img')
            shutil.copyfile(original, base)
            if direction == 'grow':
                with base.open('r+b') as f:
                    f.truncate(target)
            base_hash = sha(base)
            baseline_log = work / (direction + '-baseline.jsonl')
            shutil.copyfile(base, image)
            command(CLI + [image, '--size', str(target) + 'B', '--journal', journal,
                           '--trace', baseline_log])
            validate(image, expected, target)
            full = events(baseline_log)
            selected = {}
            for label in ('journal.preimage.write', 'source.write', 'source.sync'):
                positions = [e for e in full if e['event'] == label]
                if positions:
                    for index in (0, len(positions) // 2, len(positions) - 1):
                        selected[positions[index]['position']] = positions[index]
            for e in full:
                if e['event'] in ('image.result.sync', 'journal.commit.tmp.write',
                                  'journal.commit.rename', 'journal.commit.dir.sync',
                                  'image.token.remove', 'journal.cleanup.parent.sync'):
                    selected[e['position']] = e
            for mode in ('kill', 'eio', 'enospc', 'short', 'eintr', 'cancel'):
                for pos, e in sorted(selected.items()):
                    if mode in ('short', 'eintr') and not (e['event'].endswith('.write') or
                            (mode == 'eintr' and e['event'].endswith('.sync'))):
                        continue
                    if journal.exists():
                        shutil.rmtree(journal)
                    image.unlink(missing_ok=True)
                    shutil.copyfile(base, image)
                    log = work / f'{direction}-{mode}-{pos}.jsonl'
                    r = command(CLI + [image, '--size', str(target) + 'B', '--journal', journal,
                                       '--test-fault', f'{mode}:{pos}', '--trace', log],
                                expect=(0, 1, 3, 4, 130, -9))
                    injected = [event for event in events(log) if event['injected']]
                    assert len(injected) == 1 and injected[0]['position'] == pos
                    recovered = active(image)
                    if recovered:
                        command(CLI + [image, '--recover', '--journal', journal])
                    volume = validate(image, expected)
                    assert volume.length in (128 << 20, target)
                    state = 'old' if volume.length == 128 << 20 else 'new'
                    if state == 'old':
                        assert sha(image) == base_hash
                    report['tests'].append(dict(direction=direction, mode=mode, position=pos,
                                                event=e['event'], reached=True, exit=r.returncode,
                                                recovered=recovered, state=state, status='PASS'))
                    (work / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
            image.unlink()
            base.unlink()
            if journal.exists():
                shutil.rmtree(journal)
        report['status'] = 'PASS'
        source.unlink()
        original.unlink()
    except BaseException as e:
        report.update(status='FAIL', error=repr(e))
        raise
    finally:
        report['seconds'] = time.monotonic() - start
        (work / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(report['status'], len(report['tests']), 'large-image reached fault cases')
    return 0


if __name__ == '__main__':
    sys.exit(main())
