#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reproducible image qualification. Retain failing images and action logs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from fixture import workload, serialize, capacity_probe
from reader import Volume
import image_resize as host

CLI = [sys.executable, str(ROOT / 'resize/resize.exfat')]
FSCK = ROOT / 'fsck/fsck.exfat'
MKFS = ROOT / 'mkfs/mkfs.exfat'
TUNE = ROOT / 'tune/tune.exfat'


def command(argv, expect=(0,), env=None):
    r = subprocess.run([str(x) for x in argv], capture_output=True, text=True, env=env)
    if r.returncode not in expect:
        raise AssertionError(dict(command=[str(x) for x in argv], exit=r.returncode,
                                  output=r.stdout[-6000:], error=r.stderr[-6000:]))
    return r


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def validate(image, expected=None, length=None):
    r = command([FSCK, '-n', image])
    v = Volume(image)
    if expected is not None:
        assert v.snapshot() == expected, 'semantic metadata or content mismatch'
    if length is not None:
        assert v.length == length, ('wrong target geometry', v.length, length)
    return v


def template(path, sector=512, cluster=4096, compact=False):
    with open(path, 'wb') as f:
        f.truncate(8 << 20)
    command([MKFS, '-q', '-L', 'RESIZE', '-s', sector, '-c', cluster,
             *(['-b', str(sector)] if compact else []), path])
    # Pin the time-based mkfs identity so model images have repeatable bytes.
    command([TUNE, '-I', '0x52535a45', path])
    validate(path)


def resize(image, size, journal, **kwargs):
    args = CLI + [str(image), '--size', str(size) + 'B', '--journal', str(journal)]
    return command(args, **kwargs)


def model_case(seed, iterations, run_dir):
    work = run_dir / ('seed-' + str(seed))
    work.mkdir()
    source, image, journal = (work / x for x in ('template.img', 'image.img', 'journal'))
    geometries = [(s, c) for s in (512, 4096) for c in (4096, 8192, 16384)] + [(512, 512)]
    sector, cluster = geometries[seed % len(geometries)]
    compact = bool((seed // 14) % 2)
    template(source, sector, cluster, compact)
    files, actions = workload(seed, iterations)
    (work / 'actions.jsonl').write_text(''.join(json.dumps(a) + '\n' for a in actions))
    measured, expected_files = serialize(source, image, files, seed, system_tail=bool((seed // 6) % 2))
    before = validate(image).snapshot()
    full_hash = sha(image)
    planned = command(CLI + [image, '--size', '6MiB', '--dry-run'])
    assert sha(image) == full_hash
    # Rejected size, no-op, and invalid syntax must leave all image bytes intact.
    command(CLI + [image, '--size', '512KiB', '--dry-run'], expect=(1,))
    command(CLI + [image, '--size', '999999999999999999999TiB', '--dry-run'], expect=(2,))
    command(CLI + [image, '--size', '8MiB', '--journal', journal])
    assert sha(image) == full_hash and not journal.exists()
    results = []
    # Grow->shrink and shrink->grow both occur in each case. Original container
    # length remains available for undo, even when filesystem length is smaller.
    with open(image, 'r+b') as f:
        f.truncate(16 << 20)
    for size in (16 << 20, 6 << 20, 12 << 20, 5 << 20, 16 << 20):
        r = resize(image, size, journal)
        results.append(json.loads(r.stdout))
        validate(image, before, size)
        assert image.stat().st_size == 16 << 20
    probe_at = capacity_probe(image, 8 << 20)
    probe_snapshot = validate(image).snapshot()
    resize(image, 6 << 20, journal)
    validate(image, probe_snapshot, 6 << 20)
    # Hash and measurements are retained, but successful temporary images are removed.
    result = dict(case='model', seed=seed, iterations=iterations, sector=sector,
                  cluster=cluster, compact=compact, measurements=measured, external_files=len(expected_files),
                  probe_offset=probe_at, resizes=results, status='PASS', final_sha256=sha(image))
    source.unlink()
    image.unlink()
    return result


def libraries(run_dir, sanitize=False):
    v = ROOT / 'resize/vendor'
    build = run_dir / 'c-tests'
    build.mkdir()
    library = Path(os.environ.get('RESIZE_LIBRARY', ROOT / 'resize/.libs/libresize-image.so')).resolve()
    flags = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-sanitize-recover=all'] if sanitize else []
    if sanitize:
        library = build / 'libresize-image.so'
        command(['gcc', '-std=c11', '-shared', '-fPIC', '-g', '-O1', *flags,
                 '-I' + str(v / 'include'), '-I' + str(v / 'lib'),
                 *sorted((v / 'lib').glob('*.c')), ROOT / 'resize/bridge.c', '-o', library])
    sources = sorted((v / 'tests/library').glob('unit/*.c')) + sorted((v / 'tests/library').glob('integration/*.c'))
    results = []
    for src in sources:
        binary = build / src.stem
        command(['gcc', '-std=c11', '-g', '-O1', '-Wall', '-Wextra', *flags,
                 '-I' + str(v / 'include'), '-I' + str(v / 'lib'), '-I' + str(v / 'tests/library'),
                 src, *sorted((v / 'tests/library/support').glob('*.c')), library,
                 '-Wl,-rpath,' + str(library.parent), '-o', binary])
        env = os.environ.copy()
        if sanitize:
            env.update(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1')
        r = command([binary], env=env)
        (build / (src.stem + '.log')).write_text(r.stdout + r.stderr)
        results.append(dict(case=src.stem, status='PASS', sanitizer=sanitize,
                            log=str((build / (src.stem + '.log')).relative_to(run_dir))))
    return results


def edge_cases(run_dir):
    work = run_dir / 'edges'
    work.mkdir()
    source, image = work / 'template.img', work / 'image.img'
    template(source)
    v = Volume(source)
    measured, _ = serialize(source, image, {}, 81, fill_bytes=(v.count - 10) * v.cluster)
    before = validate(image).snapshot()
    original = sha(image)
    for size in ('1MiB', '6MiB', '8389120B', '9223372036854775807B'):
        command(CLI + [image, '--size', size, '--dry-run'], expect=(1,))
        assert sha(image) == original
    command(CLI + [image, '--size', '8388609B', '--dry-run'])
    assert sha(image) == original
    # A nearly full volume can grow without full defragmentation.
    with image.open('r+b') as f:
        f.truncate(16 << 20)
    resize(image, 16 << 20, work / 'journal')
    validate(image, before, 16 << 20)
    grown = bytearray(image.read_bytes())
    # Corrupt checksums and bitmap ownership separately. Both must fail closed.
    for label, offset in [('boot-checksum', 119), ('bitmap', Volume(image).offset(
            int.from_bytes(Volume(image).systems[0x81]['raw'][20:24], 'little')))]:
        damaged = bytearray(grown)
        damaged[offset] ^= 1
        image.write_bytes(damaged)
        hashed = sha(image)
        command(CLI + [image, '--size', '6MiB', '--journal', work / 'must-not-exist'], expect=(1,))
        assert sha(image) == hashed and not (work / 'must-not-exist').exists()
    image.unlink()
    source.unlink()
    return [dict(case='nearly-full-overflow-rounding-corrupt-input', status='PASS', measurements=measured)]


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def active(image):
    fd = os.open(image, os.O_RDONLY)
    try:
        return host.token(fd) is not None
    finally:
        os.close(fd)


def fault_cases(run_dir):
    work = run_dir / 'faults'
    work.mkdir()
    source, original = work / 'template.img', work / 'original.img'
    template(source, 512, 4096)
    files, actions = workload(773, 80)
    serialize(source, original, files, 773, system_tail=True)
    expected = validate(original).snapshot()
    old_hash = sha(original)
    results = []
    # Faults for both geometry paths. A transition is counted only if its trace
    # confirms that the process reached the requested position.
    for direction, size in (('shrink', 6 << 20), ('grow', 16 << 20)):
        base = work / ('base-' + direction + '.img')
        shutil.copyfile(original, base)
        if direction == 'grow':
            with open(base, 'r+b') as f:
                f.truncate(16 << 20)
        baseline_hash = sha(base)
        image, journal = work / 'candidate.img', work / 'journal'
        baseline_trace = work / (direction + '-baseline.jsonl')
        shutil.copyfile(base, image)
        command(CLI + [image, '--size', str(size) + 'B', '--journal', journal,
                       '--trace', baseline_trace])
        validate(image, expected, size)
        trace = events(baseline_trace)
        for mode in ('kill', 'eio', 'enospc', 'short', 'eintr', 'cancel'):
            for entry in trace:
                label, pos = entry['event'], entry['position']
                if mode in ('short', 'eintr') and not (label.endswith('.write') or
                                                        (mode == 'eintr' and label.endswith('.sync'))):
                    continue
                if journal.exists():
                    shutil.rmtree(journal)
                image.unlink(missing_ok=True)
                shutil.copyfile(base, image)
                log = work / f'{direction}-{mode}-{pos}.jsonl'
                r = command(CLI + [image, '--size', str(size) + 'B', '--journal', journal,
                                   '--test-fault', f'{mode}:{pos}', '--trace', log],
                            expect=(0, 1, 3, 4, 130, -9))
                reached = [e for e in events(log) if e['injected']]
                assert len(reached) == 1 and reached[0]['position'] == pos, 'fault was not reached'
                recovered = False
                if active(image):
                    command(CLI + [image, '--recover', '--journal', journal])
                    recovered = True
                v = validate(image, expected)
                state = 'old' if v.length == 8 << 20 else 'new'
                assert v.length in (8 << 20, size)
                if state == 'old':
                    assert sha(image) == baseline_hash, 'rollback did not restore all container bytes'
                results.append(dict(case='fault', direction=direction, mode=mode, position=pos,
                                    event=label, reached=True, exit=r.returncode, recovered=recovered,
                                    state=state, status='PASS'))
        image.unlink()
        base.unlink()
        if journal.exists():
            shutil.rmtree(journal)
    # Repeated interruption while restoring the same uncommitted source.
    baseline = events(work / 'shrink-baseline.jsonl')
    source_write = next(e['position'] for e in baseline if e['event'] == 'source.write')
    image, journal = work / 'recovery.img', work / 'journal'
    shutil.copyfile(original, image)
    command(CLI + [image, '--size', '6MiB', '--journal', journal,
                   '--test-fault', f'kill:{source_write}'], expect=(-9,))
    log = work / 'recovery-baseline.jsonl'
    command(CLI + [image, '--recover', '--journal', journal, '--trace', log])
    restore_trace = events(log)
    for mode in ('kill', 'eio', 'enospc', 'short', 'eintr'):
        for e in restore_trace:
            if mode in ('short', 'eintr') and not (e['event'].endswith('.write') or
                                                    (mode == 'eintr' and e['event'].endswith('.sync'))):
                continue
            if journal.exists():
                shutil.rmtree(journal)
            image.unlink()
            shutil.copyfile(original, image)
            command(CLI + [image, '--size', '6MiB', '--journal', journal,
                           '--test-fault', f'kill:{source_write}'], expect=(-9,))
            fault_log = work / f'recovery-{mode}-{e["position"]}.jsonl'
            r = command(CLI + [image, '--recover', '--journal', journal,
                               '--test-fault', f'{mode}:{e["position"]}', '--trace', fault_log],
                        expect=(0, 1, 3, 4, -9))
            assert any(x['injected'] for x in events(fault_log))
            if active(image):
                command(CLI + [image, '--recover', '--journal', journal])
            assert sha(image) == old_hash
            validate(image, expected, 8 << 20)
            results.append(dict(case='recovery-fault', mode=mode, **e, reached=True,
                                exit=r.returncode, state='old', status='PASS'))
    for mode in ('eio-persistent', 'enospc-persistent'):
        if journal.exists():
            shutil.rmtree(journal)
        image.unlink()
        shutil.copyfile(original, image)
        trace_path = work / (mode + '.jsonl')
        command(CLI + [image, '--size', '6MiB', '--journal', journal,
                       '--test-fault', f'{mode}:{source_write}', '--trace', trace_path], expect=(3,))
        assert any(e['injected'] == mode for e in events(trace_path))
        command(CLI + [image, '--recover', '--journal', journal,
                       '--test-fault', mode + ':1'], expect=(3,))
        assert active(image)
        command(CLI + [image, '--recover', '--journal', journal])
        assert sha(image) == old_hash
        validate(image, expected, 8 << 20)
        results.append(dict(case='persistent-storage-error', mode=mode, status='PASS', reached=True))
    # A durable commit with corrupt or mismatched metadata cannot authorize writes.
    if journal.exists():
        shutil.rmtree(journal)
    image.unlink()
    shutil.copyfile(original, image)
    committed_position = next(e['position'] for e in baseline if e['event'] == 'image.token.remove')
    command(CLI + [image, '--size', '6MiB', '--journal', journal,
                   '--test-fault', f'kill:{committed_position}'], expect=(-9,))
    committed_hash = sha(image)
    commit_path = journal / 'commit'
    saved_commit = commit_path.read_bytes()
    commit_path.write_bytes(saved_commit[:-1] + b'x')
    command(CLI + [image, '--recover', '--journal', journal], expect=(3,))
    assert sha(image) == committed_hash
    payload = json.loads(saved_commit)['payload']
    payload['token'] = '0' * 32
    commit_path.write_bytes(host.record(payload))
    command(CLI + [image, '--recover', '--journal', journal], expect=(3,))
    assert sha(image) == committed_hash
    commit_path.write_bytes(saved_commit)
    command(CLI + [image, '--recover', '--journal', journal])
    validate(image, expected, 6 << 20)
    results.append(dict(case='corrupt-and-wrong-commit', status='PASS'))
    # Missing, wrong-target, and corrupt journals must never change image bytes.
    if journal.exists():
        shutil.rmtree(journal)
    image.unlink()
    shutil.copyfile(original, image)
    command(CLI + [image, '--size', '6MiB', '--journal', journal,
                   '--test-fault', f'kill:{source_write}'], expect=(-9,))
    stopped_hash = sha(image)
    command(CLI + [image, '--recover', '--journal', work / 'missing'], expect=(3,))
    assert sha(image) == stopped_hash
    wrong = work / 'wrong.img'
    shutil.copyfile(image, wrong)
    wrong_hash = sha(wrong)
    command(CLI + [wrong, '--recover', '--journal', journal], expect=(1,))
    assert sha(wrong) == wrong_hash
    manifest = journal / 'manifest'
    saved = manifest.read_bytes()
    manifest.write_bytes(saved[:-1] + b'x')
    command(CLI + [image, '--recover', '--journal', journal], expect=(3,))
    assert sha(image) == stopped_hash
    manifest.write_bytes(saved)
    preimage = journal / 'preimage'
    with open(preimage, 'r+b') as f:
        byte = f.read(1)
        f.seek(0)
        f.write(bytes([byte[0] ^ 1]))
    command(CLI + [image, '--recover', '--journal', journal], expect=(3,))
    assert sha(image) == stopped_hash
    with open(preimage, 'r+b') as f:
        f.write(byte)
    saved_journal = work / 'stale'
    shutil.copytree(journal, saved_journal)
    command(CLI + [image, '--recover', '--journal', journal])
    restored_hash = sha(image)
    command(CLI + [image, '--recover', '--journal', saved_journal], expect=(1,))
    assert sha(image) == restored_hash == old_hash
    results.append(dict(case='missing-wrong-corrupt-stale-journal', status='PASS'))
    for p in work.glob('*.img'):
        p.unlink()
    if journal.exists():
        shutil.rmtree(journal)
    shutil.rmtree(saved_journal)
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', type=int, default=12)
    p.add_argument('--iterations', type=int, default=5000)
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--faults', action='store_true')
    p.add_argument('--library-only', action='store_true')
    p.add_argument('--sanitize', action='store_true')
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    run_dir = (args.output or ROOT / 'resize/evidence' / time.strftime('%Y%m%d-%H%M%S')).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    identity = subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], capture_output=True, text=True)
    report = dict(schema=1, status='RUNNING', parameters=vars(args) | {'output': str(run_dir)},
                  base_commit='1647ed54299ae8c4343a5edf40b892307f7e6459',
                  head=identity.stdout.strip() if identity.returncode == 0 else None,
                  platform=platform.platform(), python=sys.version, compiler=command(['gcc', '--version']).stdout.splitlines()[0],
                  source_sha256={str(x.relative_to(ROOT)): sha(x) for x in
                                 [ROOT / 'resize/image_resize.py', ROOT / 'resize/bridge.c',
                                  ROOT / 'resize/vendor/include/exfat_resize.h', ROOT / 'fsck/fsck.c',
                                  *sorted((ROOT / 'resize/vendor/lib').glob('*.[ch]')),
                                  *sorted(HERE.glob('*.py'))]}, tests=[])
    start = time.monotonic()
    try:
        report['tests'] += libraries(run_dir, args.sanitize)
        r = command([sys.executable, '-m', 'unittest', 'discover', '-s', HERE, '-p', 'test_host.py'])
        (run_dir / 'host.log').write_text(r.stdout + r.stderr)
        report['tests'].append(dict(case='host-unit', status='PASS'))
        if not args.library_only:
            report['tests'] += edge_cases(run_dir)
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = [pool.submit(model_case, seed, args.iterations, run_dir)
                           for seed in range(args.seeds)]
                by_future = {future: seed for seed, future in enumerate(futures)}
                for count, future in enumerate(as_completed(futures), 1):
                    try:
                        report['tests'].append(future.result())
                    except Exception:
                        report['tests'].append(dict(case='model', seed=by_future[future],
                                                    status='FAIL', failure=traceback.format_exc()))
                    if count % 20 == 0 or report['tests'][-1]['status'] == 'FAIL':
                        print('completed model cases', count, 'last seed', by_future[future],
                              report['tests'][-1]['status'], flush=True)
                        (run_dir / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
            if args.faults:
                report['tests'] += fault_cases(run_dir)
        report['status'] = 'FAIL' if any(t['status'] != 'PASS' for t in report['tests']) else 'PASS'
    except BaseException:
        report['status'] = 'FAIL'
        report['failure'] = traceback.format_exc()
        print(report['failure'], file=sys.stderr)
    finally:
        report['seconds'] = time.monotonic() - start
        (run_dir / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(report['status'], 'cases:', len(report['tests']), 'results:', run_dir / 'results.json', flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
