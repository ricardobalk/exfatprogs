#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Directory flush rollback and parent death while a worker owns the lock."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from image import make_fixture,require
from run import ROOT,CLI,command,sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.build=a.build.resolve();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=False)
    source=a.out/'source.img';make_fixture(source,a.build/'mkfs.exfat',7,500,512,True)
    old=sha(source);results=[]
    base=CLI+['--engine',a.build/'defrag.exfat','--fsck',a.build/'fsck.exfat']
    env={'EXFAT_DEFRAG_TEST_PRELOAD':str(a.build/'fault.so')}
    for mode in ('directory-flush','parent-kill','journal-fifo'):
        work=a.out/mode;work.mkdir();image=work/'image.img';journal=work/'journal'
        shutil.copyfile(source,image);trace=work/'worker.jsonl'
        settings={'EXFAT_TEST_LOG':str(trace)}
        settings.update({'EXFAT_TEST_DIRECTORY_EIO':'1'} if mode=='directory-flush' else {'EXFAT_TEST_PAUSE_AT':'1'} if mode=='parent-kill' else {'EXFAT_TEST_SIGNAL_AT':'1','EXFAT_TEST_SIGNAL':'9'})
        proc=subprocess.Popen([str(x) for x in base+[image,'--journal',journal]],env=os.environ|env|settings,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            if mode=='parent-kill':
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if trace.exists() and any(json.loads(s)['event']=='write' for s in trace.read_text().splitlines()):break
                    time.sleep(.01)
                else:raise RuntimeError('worker pause not reached')
                os.kill(proc.pid,signal.SIGKILL)
            out,err=proc.communicate(timeout=10)
            require(proc.returncode==(-9 if mode=='parent-kill' else 3),'incorrect transaction status: '+err)
            if mode=='journal-fifo':
                backup=work/'saved-preimage';shutil.copyfile(journal/'preimage',backup)
                (journal/'preimage').unlink();os.mkfifo(journal/'preimage',0o600)
                stopped_hash=sha(image)
                command(base+[image,'--journal',journal,'--recover'],expected=3)
                require(sha(image)==stopped_hash,'FIFO journal rejection wrote source')
                (journal/'preimage').unlink();shutil.copyfile(backup,journal/'preimage');(journal/'preimage').chmod(0o600)
            # The worker inherited the flock. Recovery succeeds only once it dies.
            command(base+[image,'--journal',journal,'--recover'])
            require(sha(image)==old,'transaction rollback changed bytes')
            results.append(dict(case=mode,status='PASS',exit=proc.returncode,sha256_equal=True))
        except BaseException as exc:
            results.append(dict(case=mode,status='FAIL',error=str(exc)))
            raise
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
            (a.out/'results.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':main()
