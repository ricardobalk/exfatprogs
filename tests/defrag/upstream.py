#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run existing corruption fixtures in a private directory; preserve failures."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from run import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.build=a.build.resolve();a.out=a.out.resolve()
    a.out.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();results=[]
    report=dict(status='RUNNING',sanitizers=os.environ.get('ASAN_OPTIONS'),cases=results)
    env=os.environ|{'PATH':str(a.build)+':'+os.environ['PATH']}
    fixtures=sorted((ROOT/'tests').glob('*/exfat.img.tar.xz'))+sorted((ROOT/'tests/upcase_table').glob('[0-9]*.sh'))
    for fixture in fixtures:
        name=fixture.parent.name+('-'+fixture.stem if fixture.suffix=='.sh' else '')
        work=a.out/name;work.mkdir()
        row=dict(case=str(fixture.relative_to(ROOT)),status='RUNNING')
        try:
            if fixture.suffix=='.sh':
                subprocess.run(['sh',str(fixture),'exfat.img'],cwd=work,env=env,check=True,capture_output=True)
            else:
                subprocess.run(['tar','-xf',str(fixture)],cwd=work,check=True,capture_output=True)
            for step,flags,allowed in (('detect',['-n'],(4,)),('repair',['-y','-s'],(0,1)),('verify',['-n'],(0,))):
                r=subprocess.run([str(a.build/'fsck.exfat')]+flags+['exfat.img'],cwd=work,env=env,
                                 capture_output=True,text=True,timeout=120)
                (work/(step+'.log')).write_text(r.stdout+r.stderr)
                row[step+'_exit']=r.returncode
                if r.returncode not in allowed:
                    raise RuntimeError(step+' exit '+str(r.returncode))
                if 'Sanitizer' in r.stderr or 'runtime error:' in r.stderr:
                    raise RuntimeError('sanitizer diagnostic in '+step)
            row['status']='PASS'
            (work/'exfat.img').unlink()
        except BaseException as exc:
            row.update(status='FAIL',error=str(exc))
        results.append(row)
        report['seconds']=round(time.monotonic()-started,3)
        (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(row),flush=True)
    report['status']='PASS' if all(r['status']=='PASS' for r in results) else 'FAIL'
    (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    return int(report['status']!='PASS')


if __name__=='__main__':
    raise SystemExit(main())
