#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Factorial geometry/vendor/occupancy/depth coverage, separate from model totals."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import itertools
import json
from pathlib import Path
import shutil
import time
from image import Image,make_fixture,require
from run import ROOT,CLI,command,sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--jobs',type=int,default=4)
    a=p.parse_args();a.out=a.out.resolve();a.build=a.build.resolve();a.out.mkdir(parents=True,exist_ok=False)
    combinations=list(itertools.product((512,1024,2048,4096),range(3),(False,'empty','populated',True),(None,0,1),(1,8)))
    def one(index,parameters):
        sector,shift,vendor,free,depth=parameters;cluster=sector<<shift
        work=a.out/str(index);work.mkdir();image=work/'image.img';journal=work/'journal';stats={}
        row=dict(case=index,status='RUNNING',sector_bytes=sector,cluster_bytes=cluster,vendor=vendor,
                 free_clusters=free,directory_depth=depth,system_tail=bool(index%2))
        begin=time.monotonic()
        try:
            expected,before=make_fixture(image,a.build/'mkfs.exfat',index,31,cluster,vendor,sector,stats,
                work/'actions.jsonl',free,bool(index%2),depth)
            (work/'expected.json').write_text(json.dumps(expected,indent=2)+'\n')
            (work/'configuration.json').write_text(json.dumps(row,indent=2)+'\n')
            require(before>0,'matrix fixture not fragmented')
            command([a.build/'fsck.exfat','-n',image])
            command(CLI+[image,'--engine',a.build/'defrag.exfat','--fsck',a.build/'fsck.exfat','--journal',journal])
            actual,after=Image(image).inspect();require(actual==expected and after==0,'matrix postcondition')
            command([a.build/'fsck.exfat','-n',image])
            row.update(status='PASS',before_discontinuities=before,after_discontinuities=after,
                       fsck_before=0,fsck_after=0,manifest_equal=True,**stats)
            shutil.rmtree(work)
        except BaseException as exc:
            row.update(status='FAIL',error=str(exc))
        row['seconds']=round(time.monotonic()-begin,3)
        return row
    started=time.monotonic();results=[]
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futures=[pool.submit(one,i,parameters) for i,parameters in enumerate(combinations)]
        for future in as_completed(futures):
            row=future.result();results.append(row)
            with (a.out/'cases.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
            (a.out/'results.json').write_text(json.dumps(dict(status='RUNNING',completed=len(results),requested_cases=len(combinations)),indent=2)+'\n')
    report=dict(status='PASS' if all(r['status']=='PASS' for r in results) else 'FAIL',cases=len(results),
                requested_cases=len(combinations),model_iterations=sum(r.get('iterations',0) for r in results),
                linux_filesystem_syscalls=0,seconds=round(time.monotonic()-started,3))
    (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    return int(report['status']!='PASS')


if __name__=='__main__':raise SystemExit(main())
