#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent seed partitions; combine actual case records without inflating counts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from run import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cases',type=int,default=1000)
    p.add_argument('--operations',type=int,default=5000)
    p.add_argument('--jobs',type=int,default=4)
    a=p.parse_args();a.out=a.out.resolve();a.build=a.build.resolve();a.out.mkdir(parents=True,exist_ok=False)
    if not 1<=a.jobs<=a.cases:p.error('jobs must be within 1..cases')
    children=[];started=time.monotonic();next_seed=0
    report=dict(status='RUNNING',requested_seeds=a.cases,operations_per_seed=a.operations,completed=0,jobs=a.jobs)
    report['source_sha256']={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for folder in ('defrag','tests/defrag') for f in sorted((ROOT/folder).iterdir()) if f.suffix in ('.py','.c','.h') or f.name=='defrag.exfat'}
    report['worker_sha256']=hashlib.sha256((a.build/'defrag.exfat').read_bytes()).hexdigest()
    try:
        for job in range(a.jobs):
            n=a.cases//a.jobs+int(job<a.cases%a.jobs)
            out=a.out/str(job);log=(a.out/(str(job)+'.log')).open('w')
            args=[sys.executable,str(ROOT/'tests/defrag/run.py'),'--build',str(a.build),'--cases',str(n),
                  '--operations',str(a.operations),'--start-seed',str(next_seed),'--out',str(out)]
            if job==0:args+=['--capacity']
            children.append((subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT),out,log))
            next_seed+=n
        while any(proc.poll() is None for proc,_,_ in children):
            completed=0
            for _,out,_ in children:
                try:
                    completed+=json.loads((out/'results.json').read_text())['completed']
                except (FileNotFoundError,json.JSONDecodeError):
                    pass  # A partition may be atomically replacing or updating its report.
            report['completed']=completed
            report['seconds']=round(time.monotonic()-started,3)
            temp=a.out/'results.tmp';temp.write_text(json.dumps(report,indent=2)+'\n');temp.replace(a.out/'results.json')
            time.sleep(.5)
        items=[]
        for proc,out,log in children:
            log.close()
            if (out/'cases.jsonl').exists():items.extend(json.loads(s) for s in (out/'cases.jsonl').read_text().splitlines())
        items.sort(key=lambda r:r['seed'])
        (a.out/'cases.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in items))
        report.update(status='PASS' if all(proc.returncode==0 for proc,_,_ in children) and len(items)==a.cases+2 else 'FAIL',
            completed=len(items),model_iterations=sum(r['iterations'] for r in items),
            effective_model_mutations=sum(r['effective_model_mutations'] for r in items),linux_filesystem_syscalls=0)
    except BaseException as exc:
        report.update(status='FAIL',error=str(exc))
        raise
    finally:
        for proc,_,log in children:
            if proc.poll() is None:proc.terminate();proc.wait()
            log.close()
        report['seconds']=round(time.monotonic()-started,3)
        (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    return int(report['status']!='PASS')


if __name__=='__main__':raise SystemExit(main())
