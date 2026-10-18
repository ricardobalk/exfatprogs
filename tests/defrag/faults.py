#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reached transition faults, all worker writes, repeated recovery and publication."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from image import Image, make_fixture, require
from run import ROOT, CLI, command, sha
sys.path.insert(0,str(ROOT/'defrag'))
from image_defrag import TOKEN


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--smoke',action='store_true')
    a=p.parse_args()
    a.build,a.out=a.build.resolve(),a.out.resolve()
    a.out.mkdir(parents=True,exist_ok=False)
    source=a.out/'source.img'
    expected,before=make_fixture(source,a.build/'mkfs.exfat',3,10,512,True,system_tail=True,log=a.out/'fixture-actions.jsonl')
    (a.out/'fixture.json').write_text(json.dumps(dict(seed=3,iterations=10,sector_bytes=512,cluster_bytes=512,expected=expected),indent=2)+'\n')
    original=sha(source)
    started=time.monotonic()
    summary=dict(status='RUNNING',cases=0,hit_faults=0,seconds=0,worker_write_boundaries=0)
    base=CLI+['--engine',str(a.build/'defrag.exfat'),'--fsck',str(a.build/'fsck.exfat')]
    preload={'EXFAT_DEFRAG_TEST_PRELOAD':str(a.build/'fault.so')}

    def execute(args,env=None):
        result = subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=60,env=os.environ|(env or {}))
        require(not any(s in result.stderr for s in ('AddressSanitizer','LeakSanitizer','runtime error:')), 'sanitizer diagnostic: '+result.stderr)
        return result
    def active(image):
        try:
            return os.getxattr(image,TOKEN) is not None
        except OSError as e:
            if e.errno==61:
                return False
            raise
    def validate(image):
        actual,breaks=Image(image).inspect()
        require(actual==expected,'fault changed semantic manifest')
        command([a.build/'fsck.exfat','-n',image])
        return breaks
    def prepare(work):
        image,journal=work/'image.img',work/'journal'
        shutil.copyfile(source,image)
        return image,journal
    def settle(image,journal):
        state=None
        if active(image):
            r=execute(base+[image,'--journal',journal,'--recover'])
            require(r.returncode==0,'recovery failed: '+r.stderr)
            state=json.loads(r.stdout)['state']
        breaks=validate(image)
        if state=='old':
            require(sha(image)==original,'undo must restore every original byte')
        if state=='new':
            require(breaks==0,'committed state must be fully defragmented')
        require(not active(image),'transaction still active')
        return state,breaks
    def case(name,fn):
        work=a.out/name
        work.mkdir()
        begin=time.monotonic()
        row=dict(case=name,status='RUNNING')
        try:
            row.update(fn(work) or {})
            row['status']='PASS'
        except BaseException as exc:
            row.update(status='FAIL',error=str(exc))
            summary['status']='FAIL'
            raise
        finally:
            row['seconds']=round(time.monotonic()-begin,3)
            with (a.out/'cases.jsonl').open('a') as f:
                f.write(json.dumps(row)+'\n')
            summary['cases']+=1
            summary['hit_faults']+=row.get('hit_faults',0)
            summary['seconds']=round(time.monotonic()-started,3)
            (a.out/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
        if row['status']=='PASS':
            shutil.rmtree(work)
        if summary['cases']%50==0:
            print(json.dumps(summary),flush=True)

    work=a.out/'count'
    work.mkdir()
    image,journal=prepare(work)
    trace,worker=work/'host.jsonl',work/'worker.jsonl'
    r=execute(base+[image,'--journal',journal,'--trace',trace],preload|{'EXFAT_TEST_LOG':str(worker)})
    require(r.returncode==0,r.stderr)
    events=[json.loads(s) for s in trace.read_text().splitlines()]
    worker_events=[json.loads(s) for s in worker.read_text().splitlines()]
    nwrites=max(e['position'] for e in worker_events if e['event']=='write')
    summary['worker_write_boundaries']=nwrites
    # These order assertions connect the host persistence contract to the worker.
    labels=[e['event'] for e in events]
    require(labels.index('journal.preimage.sync')<labels.index('journal.prepare.dir.sync')<
            labels.index('image.token.sync')<labels.index('engine.start')<labels.index('image.result.sync')<
            labels.index('journal.commit.rename')<labels.index('image.token.remove'),'durability order')
    (a.out/'host-boundaries.json').write_text(json.dumps(events,indent=2)+'\n')
    (a.out/'worker-boundaries.json').write_text(json.dumps(worker_events,indent=2)+'\n')

    try:
        selected=events if not a.smoke else [e for e in events if e['position'] in (1,9,23,24,25,35,38,39,47)]
        for event in selected:
            pos,label=event['position'],event['event']
            modes=['kill','eio','enospc-persistent','sigint','sigterm']
            if label.endswith(('.write','.read')):
                modes+=['short','eintr','zero']
            elif label.endswith('.sync'):
                modes+=['eintr']
            for mode in modes:
                def host_fault(work,pos=pos,label=label,mode=mode):
                    image,journal=prepare(work)
                    trace=work/'trace.jsonl'
                    r=execute(base+[image,'--journal',journal,'--trace',trace,'--test-fault',f'{mode}:{pos}'])
                    hit=[json.loads(s) for s in trace.read_text().splitlines() if json.loads(s)['injected']]
                    require(hit and hit[0]['position']==pos,'planned host fault not reached')
                    require(r.returncode in (0,1,3,4,130,143,-9),'unexpected host fault status')
                    if mode in ('sigint','sigterm'):
                        require(r.returncode==(130 if mode=='sigint' else 143),'cancellation status not preserved')
                    state,breaks=settle(image,journal)
                    if r.returncode==0:
                        require(breaks==0,'success left target fragmentation')
                    return dict(mode=mode,planned_position=pos,event=label,hit_faults=1,exit=r.returncode,
                                recovered_state=state,after_discontinuities=breaks,manifest_equal=True)
                case(f'host-{mode}-{pos}',host_fault)

        cuts=range(1,nwrites+1) if not a.smoke else sorted({1,2,7,nwrites//2,nwrites})
        for cut in cuts:
            for mode in ('kill','eio','sigint','sigterm'):
                def engine_fault(work,cut=cut,mode=mode):
                    image,journal=prepare(work)
                    trace=work/'worker.jsonl'
                    settings={'EXFAT_TEST_LOG':str(trace)}
                    if mode=='eio':
                        settings['EXFAT_TEST_EIO_AFTER']=str(cut)
                    else:
                        settings.update(EXFAT_TEST_SIGNAL_AT=str(cut),EXFAT_TEST_SIGNAL=str(
                            signal.SIGKILL if mode=='kill' else signal.SIGINT if mode=='sigint' else signal.SIGTERM))
                    r=execute(base+[image,'--journal',journal],preload|settings)
                    hits=[json.loads(s) for s in trace.read_text().splitlines() if json.loads(s)['injected']]
                    require(hits and hits[0]['position']==cut,'planned worker fault not reached')
                    require(r.returncode==(130 if mode=='sigint' else 143 if mode=='sigterm' else 3),
                            'incorrect worker fault exit '+str(r.returncode)+': '+r.stderr)
                    state,breaks=settle(image,journal)
                    require(sha(image)==original,'cancel/crash/error rollback not byte-identical')
                    return dict(mode=mode,planned_position=cut,hit_faults=1,exit=r.returncode,
                                recovered_state=state,after_discontinuities=breaks,sha256_equal=True)
                case(f'worker-{mode}-{cut}',engine_fault)

        for setting in ('EXFAT_TEST_SHORT_AT','EXFAT_TEST_EINTR_AT','EXFAT_TEST_READ_SHORT_AT',
                        'EXFAT_TEST_READ_EINTR_AT','EXFAT_TEST_READ_ZERO_AT','EXFAT_TEST_ZERO_AT',
                        'EXFAT_TEST_ENOSPC_AT','EXFAT_TEST_FSYNC_ERROR','EXFAT_TEST_FSYNC_EINTR_AT'):
            def io_fault(work,setting=setting):
                image,journal=prepare(work)
                log=work/'worker.jsonl'
                r=execute(base+[image,'--journal',journal],preload|{setting:'1','EXFAT_TEST_LOG':str(log)})
                hits=[json.loads(s) for s in log.read_text().splitlines() if json.loads(s)['injected']]
                require(hits,'I/O fault not reached')
                failure=any(s in setting for s in ('ZERO','ENOSPC','FSYNC_ERROR'))
                require(r.returncode==(3 if failure else 0),'incorrect I/O error propagation: '+r.stderr)
                state,breaks=settle(image,journal)
                require(sha(image)==original if failure else breaks==0,'I/O postcondition')
                return dict(setting=setting,hit_faults=1,exit=r.returncode,recovered_state=state)
            case('io-'+setting.lower(),io_fault)

        # A recovery process can itself die at each source-write/durability boundary.
        def interrupted(work,cut=None,fault=None):
            image,journal=prepare(work)
            r=execute(base+[image,'--journal',journal,'--test-fault','kill:25'])
            require(r.returncode==-9 and active(image),'failed to arm interrupted transaction')
            args=base+[image,'--journal',journal,'--recover']
            if cut:
                args+=['--test-fault',f'{fault}:{cut}','--trace',work/'recovery.jsonl']
            else:
                args+=['--trace',work/'recovery.jsonl']
            r=execute(args)
            if cut:
                rows=[json.loads(s) for s in (work/'recovery.jsonl').read_text().splitlines()]
                require(any(x['injected'] for x in rows),'recovery fault not reached')
                if fault in ('sigint','sigterm'):
                    require(r.returncode==(130 if fault=='sigint' else 143),'recovery cancellation status')
                settle(image,journal)
            else:
                require(r.returncode==0,r.stderr)
            require(sha(image)==original,'repeated recovery did not restore original bytes')
            return dict(hit_faults=int(cut is not None),exit=r.returncode)
        recovery=a.out/'recovery-count'
        recovery.mkdir()
        interrupted(recovery)
        rev=[json.loads(s) for s in (recovery/'recovery.jsonl').read_text().splitlines()]
        for ev in rev:
            if ev['event'].startswith('recovery.'):
                for fault in ('kill','eio-persistent','enospc-persistent','sigint','sigterm'):
                    case(f'recovery-{fault}-{ev["position"]}',lambda w,ev=ev,fault=fault:interrupted(w,ev['position'],fault))

        # Wrong inode, missing/corrupt preimage and corrupt commit must fail closed.
        for damage in ('wrong-inode','missing','checksum','commit','stale-token'):
            def invalid_journal(work,damage=damage):
                image,journal=prepare(work)
                require(execute(base+[image,'--journal',journal,'--test-fault','kill:25']).returncode==-9,'arm')
                if damage=='wrong-inode':
                    other=work/'other.img';shutil.copy2(image,other);image=other
                elif damage=='missing':
                    (journal/'preimage').unlink()
                elif damage=='checksum':
                    with (journal/'preimage').open('r+b') as f:f.write(b'broken')
                elif damage=='commit':
                    (journal/'commit').write_text('broken')
                    (journal/'commit').chmod(0o600)
                else:
                    os.setxattr(image,TOKEN,b'0'*32)
                before_hash=sha(image)
                r=execute(base+[image,'--journal',journal,'--recover'])
                require(r.returncode!=0 and sha(image)==before_hash,'untrusted recovery modified image')
                return dict(exit=r.returncode,rejected_without_writes=True)
            case('untrusted-'+damage,invalid_journal)
        summary['status']='PASS'
    finally:
        summary['seconds']=round(time.monotonic()-started,3)
        (a.out/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    main()
