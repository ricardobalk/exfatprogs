#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reproduce cancellation + commit flush error + interrupted unsafe undo."""
import argparse
import errno
import contextlib
import io
from unittest.mock import patch
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sys
from run import ROOT, CLI, FSCK, command, template, validate, sha, events
from fixture import workload, serialize


def worker(host_path, image, journal, trace):
    spec = importlib.util.spec_from_file_location('fault_host', host_path)
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    original = host.Faults
    class Combined(original):
        rollback_writes = 0
        def hit(self, label):
            result = super().hit(label)
            if label == 'journal.commit.dir.sync':
                host.cancel(signal.SIGTERM, None)
                raise OSError(errno.EIO, 'injected commit flush error with cancellation')
            if label == 'recovery.write':
                self.rollback_writes += 1
                if self.rollback_writes == 2:
                    os.kill(os.getpid(), signal.SIGKILL)
            return result
    host.Faults = Combined
    return host.main([str(image), '--size', '6MiB', '--journal', str(journal), '--trace', str(trace)])


def unreadable_state(host_path):
    spec = importlib.util.spec_from_file_location('state_host', host_path)
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    class Image:
        fd = -1
        def close(self):
            pass
    output = io.StringIO()
    with patch.object(host, 'Image', return_value=Image()), patch.object(host, 'token',
            side_effect=OSError(errno.EIO, 'unreadable transaction metadata')), \
            patch.object(host.signal, 'signal'), contextlib.redirect_stderr(output):
        try:
            code = host.main(['controlled.img', '--info'])
        except OSError:
            return dict(raised=True, exit=None)
        return dict(raised=False, exit=code, concrete_state='transaction state unavailable' in output.getvalue())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', nargs=4)
    args = parser.parse_args()
    if args.worker:
        return worker(*args.worker)
    if args.output is None:
        parser.error('--output is required')
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    source, original = work / 'template.img', work / 'original.img'
    template(source)
    files, _ = workload(773, 80)
    serialize(source, original, files, 773, system_tail=True)
    expected = validate(original).snapshot()
    env = os.environ.copy()
    env.update(RESIZE_LIBRARY=str(ROOT / 'resize/.libs/libresize-image.so'), EXFAT_RESIZE_FSCK=str(FSCK))
    report = dict(status='RUNNING', tests=[])
    try:
        for name, host_path in [('before', ROOT / 'resize/tests/baselines/image-host-before-cancel-fix.py'),
                                 ('after', ROOT / 'resize/image_resize.py')]:
            case = work / name
            case.mkdir()
            image, journal, trace = case / 'image.img', case / 'journal', case / 'trace.jsonl'
            shutil.copyfile(original, image)
            r = command([sys.executable, Path(__file__).resolve(), '--worker', host_path, image, journal, trace],
                        expect=(-9,) if name == 'before' else (3,), env=env)
            rows = events(trace)
            assert any(row['event'] == 'journal.commit.dir.sync' for row in rows)
            reached_undo = sum(row['event'] == 'recovery.write' for row in rows)
            stopped_hash = sha(image)
            if name == 'before':
                assert reached_undo == 2
                committed_hash = json.loads((journal / 'commit').read_text())['payload']['sha256']
                assert stopped_hash != committed_hash
                # The old path cannot recover after its own interrupted undo.
                recovery = command(CLI + [image, '--recover', '--journal', journal], expect=(3,))
                assert sha(image) == stopped_hash
            else:
                assert reached_undo == 0
                assert 'commit flush error' in r.stderr
                recovery = command(CLI + [image, '--recover', '--journal', journal])
                assert json.loads(recovery.stdout)['state'] == 'new'
                validate(image, expected, 6 << 20)
                assert sha(image) == stopped_hash
            report['tests'].append(dict(version=name, host_sha256=sha(host_path), exit=r.returncode,
                                        commit_fault_reached=True, rollback_writes_reached=reached_undo,
                                        recovery_exit=recovery.returncode, status='PASS'))
        before_state = unreadable_state(ROOT / 'resize/tests/baselines/image-host-before-cancel-fix.py')
        after_state = unreadable_state(ROOT / 'resize/image_resize.py')
        assert before_state['raised']
        assert not after_state['raised'] and after_state['exit'] == 3 and after_state['concrete_state']
        report['tests'].append(dict(case='unreadable-transaction-state', before=before_state,
                                    after=after_state, status='PASS'))
        report['status'] = 'PASS'
    except BaseException as e:
        report.update(status='FAIL', error=repr(e))
        raise
    finally:
        (work / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(report['status'], 'compound cancellation/commit regression')
    return 0


if __name__ == '__main__':
    sys.exit(main())
