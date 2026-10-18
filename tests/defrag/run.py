#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic rootless qualification; model operations are not driver calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from image import Image, make_fixture, require

ROOT = Path(__file__).resolve().parents[2]
CLI = [sys.executable, str(ROOT/'defrag/defrag.exfat')]


def sha(path):
    with open(path,'rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def command(args, expected=0, env=None):
    r = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=120,
                       env=os.environ | (env or {}))
    require(r.returncode == expected, f'{args}: exit {r.returncode}, expected {expected}\n{r.stdout}\n{r.stderr}')
    return r


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, default=ROOT/'build-defrag-tests')
    p.add_argument('--cases', type=int, default=8)
    p.add_argument('--operations', type=int, default=5000)
    p.add_argument('--start-seed', type=int, default=0)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--capacity', action='store_true', help='append full and one-free-cluster cases')
    a = p.parse_args()
    require(a.cases > 0 and a.operations > 0, 'positive cases and operations required')
    a.build, a.out = a.build.resolve(), a.out.resolve()
    a.out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', requested_seeds=a.cases, operations_per_seed=a.operations,
                  completed=0, model_iterations=0, effective_model_mutations=0,
                  linux_filesystem_syscalls=0, seconds=0)
    started = time.monotonic()
    cases = [(s,None) for s in range(a.start_seed,a.start_seed+a.cases)]
    if a.capacity:
        cases += [(100001,0),(100002,1)]
    try:
        for seed, remaining in cases:
            begin = time.monotonic()
            work = a.out/str(seed)
            work.mkdir()
            target, journal = work/'volume.img',work/'journal'
            stats = {}
            sector = (512,1024,2048,4096)[seed % 4]
            cluster = sector << ((seed//4) % 3)
            vendor = (False,'empty','populated',True)[(seed//12)%4]
            expected, breaks = make_fixture(target,a.build/'mkfs.exfat',seed,a.operations,cluster,
                                             vendor,sector,stats,work/'actions.jsonl',remaining,
                                             system_tail=(seed//48)%2 == 1)
            original = sha(target)
            oracle = Image(target)
            _, verified_breaks = oracle.inspect()
            extents = breaks + sum(bool(c) for c in oracle.allocations)
            del oracle
            require(breaks == verified_breaks and breaks > 0, 'fixture must be measurably fragmented')
            (work/'expected.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2)+'\n')
            command([a.build/'fsck.exfat','-n',target])
            base = CLI + [str(target),'--engine',str(a.build/'defrag.exfat'),'--fsck',str(a.build/'fsck.exfat')]
            plan = json.loads(command(base+['--dry-run']).stdout)
            require(sha(target) == original,'dry-run changed complete image')
            require(plan['discontinuities'] == breaks and plan['extents'] == extents,'assessment differs from oracle')
            result = json.loads(command(base+['--journal',journal]).stdout)
            actual, after = Image(target).inspect()
            require(actual == expected and after == 0,'independent semantic/fragmentation postcondition')
            command([a.build/'fsck.exfat','-n',target])
            done_hash = sha(target)
            second = json.loads(command(base+['--journal',journal]).stdout)
            require(second['status'] == 'no-op' and sha(target) == done_hash and not journal.exists(),
                    'second run must not write or create journal')
            item = dict(seed=seed,status='PASS',sector_bytes=sector,cluster_bytes=cluster,vendor=vendor,
                        free_clusters=remaining,system_tail=(seed//48)%2 == 1,before_discontinuities=breaks,
                        before_extents=extents,after_discontinuities=after,after_extents=result['after']['extents'],
                        content_and_metadata_equal=True,fsck_before=0,fsck_after=0,sanitizer='separate suite',
                        dry_run_sha256_equal=True,second_run_sha256_equal=True,seconds=round(time.monotonic()-begin,3),**stats)
            with (a.out/'cases.jsonl').open('a') as f:
                f.write(json.dumps(item)+'\n')
            report['completed'] += 1
            report['model_iterations'] += a.operations
            report['effective_model_mutations'] += stats['effective_model_mutations']
            report['seconds'] = round(time.monotonic()-started,3)
            (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
            for path in work.iterdir():
                path.unlink()
            work.rmdir()
            if report['completed'] % 25 == 0:
                print(json.dumps(report),flush=True)
        report['status'] = 'PASS'
    except BaseException as exc:
        report.update(status='FAIL',failed_seed=seed,error=str(exc))
        raise
    finally:
        report['seconds'] = round(time.monotonic()-started,3)
        (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
