#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Heuristic prefix reduction of a model failure; retains the required diagnostic."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from run import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',type=int,required=True)
    p.add_argument('--operations',type=int,required=True)
    p.add_argument('--match',required=True,help='required failure diagnostic; avoids shrinking unrelated failures')
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    attempts=[];best=None
    candidates=[];n=a.operations
    while n>=1:
        candidates.append(n);n//=2
    for operations in candidates:
        out=a.out/str(operations)
        r=subprocess.run([sys.executable,str(ROOT/'tests/defrag/run.py'),'--build',str(a.build),
            '--cases','1','--start-seed',str(a.seed),'--operations',str(operations),'--out',str(out)],
            capture_output=True,text=True)
        (a.out/(str(operations)+'.log')).write_text(r.stdout+r.stderr)
        same=r.returncode!=0 and a.match in r.stdout+r.stderr
        attempts.append(dict(seed=a.seed,iterations=operations,exit=r.returncode,same_diagnostic=same))
        if same:best=operations
        (a.out/'results.json').write_text(json.dumps(dict(best_prefix=best,globally_minimal=False,attempts=attempts),indent=2)+'\n')
    return 0 if best is not None else 1


if __name__=='__main__':raise SystemExit(main())
