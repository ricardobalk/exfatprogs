#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""One short smoke run or the full local experimental qualification program."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from run import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--full',action='store_true')
    p.add_argument('--driver',action='store_true',help='use sudo -n for 10 private Linux loop-image seeds')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--jobs',type=int,default=4)
    a=p.parse_args();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',scope='experimental Linux images; block devices remain unqualified',steps=[])
    native=a.out/'native';asan=a.out/'asan';started=time.monotonic()
    def step(name,args,env=None,allowed=(0,)):
        begin=time.monotonic()
        with (a.out/(name+'.log')).open('w') as log:
            r=subprocess.run([str(x) for x in args],stdout=log,stderr=subprocess.STDOUT,env=os.environ|(env or {}))
        report['steps'].append(dict(name=name,argv=[str(x) for x in args],exit=r.returncode,
            status='PASS' if r.returncode==0 else 'NOT_RUN' if r.returncode==77 else 'FAIL',seconds=round(time.monotonic()-begin,3)))
        (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        if r.returncode not in allowed:raise RuntimeError(name+' failed; see '+str(a.out/(name+'.log')))
    def script(name,*args):return [sys.executable,ROOT/'tests/defrag'/name,*args]
    try:
        step('build',script('build.py','--baseline','--out',native))
        for baseline in (True,False):
            name='baseline' if baseline else 'regressions'
            step(name,script('regressions.py','--binary',native/('defrag.original' if baseline else 'defrag.exfat'),
                '--mkfs',native/'mkfs.exfat','--fault',native/'fault.so','--out',a.out/name,*(['--baseline'] if baseline else [])))
        step('negative',script('negative.py','--build',native,'--out',a.out/'negative'))
        if not a.full:
            step('model',script('run.py','--build',native,'--cases','3','--operations','100',
                '--out',a.out/'model'))
        else:
            step('model',script('parallel.py','--build',native,'--cases','1000','--operations','5000',
                 '--jobs',str(a.jobs),'--out',a.out/'model'))
            for name in ('faults','persistence','publication','transaction_regressions','upstream','metadata','matrix'):
                step(name,script(name+'.py','--build',native,'--out',a.out/name))
            if a.driver:
                step('driver',['sudo','-n',sys.executable,ROOT/'tests/defrag/mounted.py','--build',native,
                    '--seeds','10','--operations','5000','--out',a.out/'driver'],allowed=(0,77))
            else:
                report['steps'].append(dict(name='driver',status='NOT_RUN',reason='--driver not selected'))
            step('build-sanitizers',script('build.py','--sanitize','--out',asan))
            san={'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1',
                 'DEFRAG_ASAN_RUNTIME':subprocess.check_output([os.environ.get('CC','cc'),'-print-file-name=libasan.so'],text=True).strip()}
            step('sanitizer-regressions',script('regressions.py','--binary',asan/'defrag.exfat',
                 '--mkfs',asan/'mkfs.exfat','--fault',asan/'fault.so','--out',a.out/'sanitizer-regressions'),san)
            step('sanitizer-model',script('parallel.py','--build',asan,'--cases','1000','--operations','5000',
                 '--jobs',str(a.jobs),'--out',a.out/'sanitizer-model'),san)
            for name in ('faults','persistence','publication','transaction_regressions','negative','upstream','metadata','matrix'):
                step('sanitizer-'+name,script(name+'.py','--build',asan,'--out',a.out/('sanitizer-'+name)),san)
        report['status']='PASS_WITH_BLOCKERS' if any(r['status']=='NOT_RUN' for r in report['steps']) else 'PASS'
    except BaseException as exc:
        report.update(status='FAIL',error=str(exc))
        raise
    finally:
        report['seconds']=round(time.monotonic()-started,3)
        (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
