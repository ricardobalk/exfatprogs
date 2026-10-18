#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Source immutability and observable publication/dir-flush failure states."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from image import Image,make_fixture,require
from run import ROOT,command,sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.build=a.build.resolve();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=False)
    source=a.out/'source.img';expected,before=make_fixture(source,a.build/'mkfs.exfat',7,100,512,True,log=a.out/'fixture-actions.jsonl')
    (a.out/'fixture.json').write_text(json.dumps(dict(seed=7,iterations=100,sector_bytes=512,cluster_bytes=512,expected=expected),indent=2)+'\n')
    original=sha(source);results=[];started=time.monotonic()
    wrapper=[sys.executable,str(ROOT/'tests/defrag/defrag_image.py'),'--defrag',str(a.build/'defrag.exfat'),'--fsck',str(a.build/'fsck.exfat')]
    def run(work,extra=(),env=None):
        output=work/'output.img';trace=work/'trace.jsonl'
        r=subprocess.run([str(x) for x in wrapper+[source,output,'--trace',trace]+list(extra)],capture_output=True,text=True,
                         timeout=60,env=os.environ|(env or {}))
        require(sha(source)==original,'copy wrapper changed source bytes')
        return r,output,trace
    try:
        work=a.out/'count';work.mkdir();r,output,trace=run(work)
        require(r.returncode==0 and Image(output).inspect()==(expected,0),'verified publication failed')
        events=[json.loads(s) for s in trace.read_text().splitlines()]
        (a.out/'boundaries.json').write_text(json.dumps(events,indent=2)+'\n')
        # Existing output must survive an attempted publication with the same name.
        digest=sha(output)
        r=subprocess.run([str(x) for x in wrapper+[source,output]],capture_output=True)
        require(r.returncode==1 and sha(output)==digest,'existing output overwritten')
        results.append(dict(case='existing-output',status='PASS',source_sha256_equal=True))
        # Force a creator to win the race after the wrapper's existence check.
        # The real link syscall must return EEXIST and preserve those exact bytes.
        import defrag_image as workflow
        sys.path.insert(0,str(ROOT/'defrag'))
        from image_defrag import Faults
        race=a.out/'concurrent-output';race.mkdir();race_output=race/'output.img'
        original_link=os.link
        def concurrent_link(candidate,destination):
            fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            os.write(fd,b'concurrent creator wins');os.fsync(fd);os.close(fd)
            return original_link(candidate,destination)
        os.link=concurrent_link
        try:
            try:
                workflow.defrag_image(source,race_output,a.build/'defrag.exfat',a.build/'fsck.exfat',Faults())
            except FileExistsError:
                pass
            else:
                raise RuntimeError('no-replace link overwrote concurrent creator')
        finally:
            os.link=original_link
        require(race_output.read_bytes()==b'concurrent creator wins' and sha(source)==original,'publication race lost existing bytes')
        results.append(dict(case='concurrent-no-replace',status='PASS',real_link_eexist=True,source_sha256_equal=True))
        for event in events:
            pos,label=event['position'],event['event']
            # Every wrapper boundary is hit by a crash and a permanent write/flush error.
            for mode in ('kill','eio','enospc-persistent'):
                work=a.out/f'{mode}-{pos}';work.mkdir()
                r,output,trace=run(work,('--test-fault',f'{mode}:{pos}'))
                hits=[json.loads(s) for s in trace.read_text().splitlines() if json.loads(s)['injected']]
                require(hits and hits[0]['position']==pos,'publication fault not reached')
                visible=output.exists()
                after_link=label in ('wrapper.publish.dir.sync','wrapper.cleanup.dir.sync')
                require(visible==after_link,'incorrect publication visibility')
                require(r.returncode==(-9 if mode=='kill' else 4 if after_link else 1),'incorrect publication exit')
                if visible:require(Image(output).inspect()==(expected,0),'visible candidate invalid')
                results.append(dict(case=f'{mode}-{pos}',status='PASS',planned_position=pos,event=label,
                    hit_faults=1,exit=r.returncode,output_visible=visible,source_sha256_equal=True))
                shutil.rmtree(work)
        for name,extra,env in (
            ('candidate-corruption',('--test-corrupt',),{}),
            ('worker-kill',(),{'EXFAT_DEFRAG_TEST_PRELOAD':str(a.build/'fault.so'),'EXFAT_TEST_SIGNAL_AT':'7','EXFAT_TEST_SIGNAL':'9'}),
            ('worker-eio',(),{'EXFAT_DEFRAG_TEST_PRELOAD':str(a.build/'fault.so'),'EXFAT_TEST_EIO_AFTER':'7'}),
        ):
            work=a.out/name;work.mkdir();r,output,trace=run(work,extra,env)
            require(r.returncode==1 and not output.exists(),'invalid candidate published')
            results.append(dict(case=name,status='PASS',exit=r.returncode,source_sha256_equal=True,output_visible=False))
            shutil.rmtree(work)
    except BaseException as exc:
        results.append(dict(status='FAIL',error=str(exc)))
        raise
    finally:
        (a.out/'results.json').write_text(json.dumps(dict(status='PASS' if results and all(r['status']=='PASS' for r in results) else 'FAIL',
            cases=results,seconds=round(time.monotonic()-started,3)),indent=2)+'\n')


if __name__=='__main__':main()
