#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Deliver actual SIGINT/SIGTERM to private-image operations and recovery."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from fixture import workload, serialize
from run import ROOT, MKFS, TUNE, CLI, command, validate, sha, active, events


def interrupt(argv, trace, event, signum):
    process = subprocess.Popen([str(x) for x in argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    sent = None
    deadline = time.monotonic() + 30
    try:
        while process.poll() is None and time.monotonic() < deadline:
            if trace.exists():
                try:
                    rows = events(trace)
                except json.JSONDecodeError:
                    rows = []  # The writer can be between data and newline.
                match = next((r for r in rows if r['event'] == event), None)
                if match:
                    sent = dict(signal=signal.Signals(signum).name,
                                observed_position=match['position'], event=event,
                                last_observed_position=rows[-1]['position'],
                                sent_monotonic=time.monotonic())
                    os.kill(process.pid, signum)
                    break
            time.sleep(0.002)
        if sent is None:
            raise AssertionError('the signal trigger was not reached before exit or timeout')
        out, err = process.communicate(timeout=30)
        return process.returncode, out, err, sent
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    original, source = work / 'original.img', work / 'template.img'
    image, journal = work / 'candidate.img', work / 'journal'
    with source.open('wb') as f:
        f.truncate(128 << 20)
    command([MKFS, '-q', '-L', 'SIGNALS', '-c', 4096, source])
    command([TUNE, '-I', '0x52535a45', source])
    files, actions = workload(81, 5000)
    files['!large'] = bytes(range(256)) * 32768
    serialize(source, original, files, 81, system_tail=True)
    expected = validate(original).snapshot()
    original_hash = sha(original)
    report = dict(status='RUNNING', code_commit=command(['git', '-C', ROOT, 'rev-parse', 'HEAD']).stdout.strip(),
                  seed=81, iterations=5000, bytes=128 << 20,
                  script_sha256=sha(Path(__file__).resolve()), tests=[])
    try:
        for name, event, sig in [('journal-copy', 'journal.preimage.write', signal.SIGINT),
                                 ('mutation', 'source.write', signal.SIGTERM)]:
            shutil.copyfile(original, image)
            trace = work / (name + '.jsonl')
            code, out, err, sent = interrupt(CLI + [image, '--size', '80MiB', '--journal', journal,
                                                   '--trace', trace], trace, event, sig)
            assert code == 130, (code, out, err)
            assert not active(image)
            assert sha(image) == original_hash
            validate(image, expected, 128 << 20)
            report['tests'].append(dict(case=name, exit=code, state='old', status='PASS', **sent))
            image.unlink()
            if journal.exists():
                shutil.rmtree(journal)  # An inactive, interrupted preparation log.
        # Interrupt actual recovery with SIGTERM. Rollback must finish, even
        # though the signal asks for cancellation during its write loop.
        write_position = next(r['position'] for r in events(work / 'mutation.jsonl') if r['event'] == 'source.write') + 2
        shutil.copyfile(original, image)
        command(CLI + [image, '--size', '80MiB', '--journal', journal,
                       '--test-fault', f'kill:{write_position}'], expect=(-9,))
        assert sha(image) != original_hash, 'the killed mutation must change source bytes'
        trace = work / 'recovery.jsonl'
        code, out, err, sent = interrupt(CLI + [image, '--recover', '--journal', journal,
                                               '--trace', trace], trace, 'recovery.write', signal.SIGTERM)
        assert code == 0 and json.loads(out)['state'] == 'old', (code, out, err)
        assert not active(image) and sha(image) == original_hash
        validate(image, expected, 128 << 20)
        report['tests'].append(dict(case='recovery', exit=code, state='old', status='PASS', **sent))
        image.unlink()
        source.unlink()
        original.unlink()
        report['status'] = 'PASS'
    except BaseException as e:
        report.update(status='FAIL', error=repr(e))
        raise
    finally:
        (work / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(report['status'], len(report['tests']), 'actual Unix signal cases')
    return 0


if __name__ == '__main__':
    sys.exit(main())
