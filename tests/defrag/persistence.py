#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit persistence replay: loss, reordering and tears before durable commit.

We replay actual worker writes into a disposable image after the host's durable
journal activation. Volatile data writes can be lost, reordered or torn. The
journal's flushed bytes/namespace and xattr binding survive. Successful image
fsync preserves all earlier writes. This is a file-host storage model, not a
claim about arbitrary physical hardware or host-filesystem crash behavior.
"""
import argparse
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import time
from image import Image, make_fixture, require
from run import ROOT, CLI, command, sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.build=a.build.resolve();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=False)
    source=a.out/'source.img'
    expected,before=make_fixture(source,a.build/'mkfs.exfat',3,10,512,True,system_tail=True,log=a.out/'fixture-actions.jsonl')
    (a.out/'fixture.json').write_text(json.dumps(dict(seed=3,iterations=10,sector_bytes=512,cluster_bytes=512,expected=expected),indent=2)+'\n')
    original=source.read_bytes();original_sha=sha(source)
    replay=a.out/'complete.img';shutil.copyfile(source,replay)
    binary=a.out/'writes.bin'
    command([a.build/'defrag.exfat','-f',replay],env={'LD_PRELOAD':(os.environ.get('DEFRAG_ASAN_RUNTIME','')+':' if os.environ.get('DEFRAG_ASAN_RUNTIME') else '')+str(a.build/'fault.so'),'EXFAT_TEST_PERSIST_LOG':str(binary)})
    raw=binary.read_bytes();i=0;writes=[];syncs=0
    while i<len(raw):
        kind=raw[i:i+1];offset,size=struct.unpack_from('<QQ',raw,i+1);i+=17
        require(kind in (b'W',b'S') and size<=len(raw)-i,'truncated persistence trace')
        if kind==b'W':writes.append((offset,raw[i:i+size]))
        else:syncs+=1
        i+=size
    require(syncs==1 and writes,'expected final worker fsync')
    require(Image(replay).inspect()==(expected,0),'recorded worker invalid')
    choices=[('prefix-'+str(n),writes[:n]) for n in range(len(writes)+1)]
    choices += [('reverse',list(reversed(writes))),('even-reverse',list(reversed(writes[::2]))),
                ('odd-reverse',list(reversed(writes[1::2])))]
    choices += [('torn-'+str(n),writes[:n]+[(writes[n][0],writes[n][1][:max(1,len(writes[n][1])//2)])]) for n in range(len(writes))]
    rng=random.Random(0xdefa6)
    for seed in range(16):
        subset=[w for w in writes if rng.randrange(2)];rng.shuffle(subset)
        choices.append(('reordered-subset-'+str(seed),subset))
    results=[];started=time.monotonic()
    base=CLI+['--engine',str(a.build/'defrag.exfat'),'--fsck',str(a.build/'fsck.exfat')]
    try:
        for name,selected in choices:
            work=a.out/name;work.mkdir();image=work/'image.img';journal=work/'journal'
            shutil.copyfile(source,image)
            command(base+[image,'--journal',journal,'--test-fault','kill:24'],expected=-9)
            # Simulate the bytes which actually survive the modeled storage crash.
            with image.open('r+b') as f:
                for offset,data in selected:
                    f.seek(offset);f.write(data)
                f.flush();os.fsync(f.fileno())
            command(base+[image,'--journal',journal,'--recover'])
            require(sha(image)==original_sha and Image(image).inspect()==(expected,before),'persistence rollback mismatch')
            command([a.build/'fsck.exfat','-n',image])
            row=dict(case=name,status='PASS',surviving_writes=len(selected),recovered_state='old',
                     sha256_equal=True,manifest_equal=True,fsck=0)
            results.append(row)
            with (a.out/'cases.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
            shutil.rmtree(work)
    except BaseException as exc:
        with (a.out/'cases.jsonl').open('a') as f:f.write(json.dumps(dict(case=name,status='FAIL',error=str(exc)))+'\n')
        raise
    finally:
        (a.out/'results.json').write_text(json.dumps(dict(status='PASS' if len(results)==len(choices) else 'FAIL',
            model='durable journal and token; arbitrary volatile image write loss/reordering/tears before commit',
            worker_writes=len(writes),worker_flushes=syncs,cases=len(results),requested_cases=len(choices),
            seconds=round(time.monotonic()-started,3)),indent=2)+'\n')
    source.unlink();replay.unlink()


if __name__=='__main__':main()
