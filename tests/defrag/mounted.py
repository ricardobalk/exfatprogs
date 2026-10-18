#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Linux-exFAT workload on private images/devices, in a mount namespace."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
from image import Image, require
from run import CLI, ROOT, command, sha


def workload(mount, seed, iterations, log, cluster):
    rng, expected = random.Random(seed), {}
    calls, effective = 0, 0
    def call(function, *args):
        nonlocal calls
        calls += 1
        return function(*args)
    directories = ('album','album/disc','other','fragment')
    for name in directories:
        call(os.mkdir,mount/name)
    names = [f'{("album/" if n%3==0 else "album/disc/" if n%3==1 else "other/")}f{n:03d}_Δ猫.bin' for n in range(80)]
    with log.open('w') as actions:
        for i in range(iterations):
            name, op = rng.choice(names), rng.randrange(6)
            path = mount/name
            old = expected.get(name,b'')
            data = rng.randbytes(rng.randrange(1,8193))
            before = expected.copy()
            details = {}
            if op in (0,1,2,3):
                flags = os.O_RDWR | os.O_CREAT | (os.O_TRUNC if op == 0 else 0)
                fd = call(os.open,path,flags,0o600)
                try:
                    if op == 0:
                        require(call(os.write,fd,data) == len(data),'short driver write')
                        expected[name] = data
                    elif op == 1:
                        call(os.lseek,fd,0,os.SEEK_END)
                        part = data[:1024]
                        require(call(os.write,fd,part) == len(part),'short append')
                        expected[name] = old + part
                    elif op == 2:
                        offset = rng.randrange(len(old)+8193)
                        part = data[:1024]
                        require(call(os.pwrite,fd,part,offset) == len(part),'short offset write')
                        expected[name] = old.ljust(offset,b'\0')[:offset] + part + old[offset+len(part):]
                        details['offset'] = offset
                    else:
                        size = rng.choice((0,1,4095,4096,4097,rng.randrange(32769)))
                        call(os.ftruncate,fd,size)
                        expected[name] = old[:size].ljust(size,b'\0')
                        details['size'] = size
                finally:
                    call(os.close,fd)
            elif op == 4:
                other = rng.choice(names)
                details['target'] = other
                if name in expected and name != other:
                    call(os.replace,path,mount/other)
                    expected[other] = expected.pop(name)
                else:
                    call(os.stat,mount)
            else:
                if name in expected:
                    call(os.unlink,path)
                    expected.pop(name)
                else:
                    call(os.stat,mount)
            effective += before != expected
            actions.write(json.dumps(dict(iteration=i,path=name,operation=op,data_sha256=hashlib.sha256(data).hexdigest(),**details))+'\n')
        # Force interleaving through real allocation/flush calls.
        for i in range(64):
            name = f'fragment/f{i:03d}'
            data = rng.randbytes(cluster)
            fd = call(os.open,mount/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            require(call(os.write,fd,data)==len(data),'short fragmentation setup')
            call(os.fsync,fd)
            call(os.close,fd)
            expected[name] = data
        for i in range(64):
            name = f'fragment/f{i:03d}'
            data = rng.randbytes(cluster*2)
            fd = call(os.open,mount/name,os.O_WRONLY|os.O_APPEND)
            require(call(os.write,fd,data)==len(data),'short fragmentation growth')
            call(os.fsync,fd)
            call(os.close,fd)
            expected[name] += data
    return expected, dict(iterations=iterations,effective_model_mutations=effective,
                          linux_filesystem_syscalls=calls,extra_fragmentation_mutations=128)


def compare(mount, expected):
    actual = {str(p.relative_to(mount)):p.read_bytes() for p in mount.rglob('*') if p.is_file()}
    require(actual == expected,'Linux driver content differs from external model')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seeds',type=int,default=10)
    p.add_argument('--operations',type=int,default=5000)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    a.build, a.out = a.build.resolve(), a.out.resolve()
    a.out.mkdir(parents=True,exist_ok=False)
    report = dict(status='RUNNING',requested_seeds=a.seeds,operations_per_seed=a.operations,cases=[])
    started = time.monotonic()
    if os.geteuid() != 0:
        report.update(status='NOT_RUN',reason='root/CAP_SYS_ADMIN and Linux exFAT required')
        (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        return 77
    # Never propagate these disposable mounts into the surrounding namespace.
    libc = ctypes.CDLL(None,use_errno=True)
    if libc.unshare(0x20000):
        report.update(status='NOT_RUN',reason='private mount namespace unavailable')
        (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        return 77
    command(['mount','--make-rprivate','/'])
    try:
        for seed in range(a.seeds):
            begin = time.monotonic()
            work = a.out/str(seed)
            work.mkdir()
            image,mount,journal = work/'volume.img',work/'mnt',work/'journal'
            mount.mkdir()
            with image.open('xb') as f:
                f.truncate(64<<20)
            sector = (512,4096)[seed%2]
            cluster = sector << (seed//2%3)
            command([a.build/'mkfs.exfat','-s',sector,'-c',cluster,'-L','DRIVER_Δ',image])
            loop, mounted = None,False
            def attach(ro=False):
                nonlocal loop,mounted
                loop = command(['losetup','--find','--show','--sector-size',sector,image]).stdout.strip()
                require(loop.startswith('/dev/loop'),'unexpected loop device')
                before_hash = sha(image)
                command(CLI+[image,'--dry-run'],expected=1)
                command(CLI+[loop,'--dry-run'],expected=1)
                require(sha(image)==before_hash,'loop-attached rejection wrote image')
                command(['mount','-t','exfat','-o','ro' if ro else 'rw',loop,mount])
                mounted = True
            def detach():
                nonlocal loop,mounted
                if mounted:
                    command(['umount',mount])
                    mounted = False
                if loop:
                    command(['losetup','-d',loop])
                    loop = None
            try:
                attach()
                expected,stats = workload(mount,seed,a.operations,work/'actions.jsonl',cluster)
                compare(mount,expected)
                detach()
                command([a.build/'fsck.exfat','-n',image])
                before,breaks = Image(image).inspect()
                require(breaks > 0,'driver workload did not fragment image')
                (work/'expected.json').write_text(json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in expected.items()},indent=2)+'\n')
                result = command(CLI+[image,'--journal',journal,'--engine',a.build/'defrag.exfat','--fsck',a.build/'fsck.exfat'])
                after,remaining = Image(image).inspect()
                require(before == after and remaining == 0,'offline driver-image postcondition')
                command([a.build/'fsck.exfat','-n',image])
                attach(True)
                compare(mount,expected)
                detach()
                report['cases'].append(dict(seed=seed,status='PASS',sector_bytes=sector,cluster_bytes=cluster,
                    before_discontinuities=breaks,after_discontinuities=remaining,external_model_equal=True,
                    metadata_equal=True,attached_loop_and_device_rejected=True,fsck_before=0,fsck_after=0,seconds=round(time.monotonic()-begin,3),**stats))
                image.unlink()
                print(json.dumps(report['cases'][-1]),flush=True)
            finally:
                detach()
            (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        report['status'] = 'PASS'
    except BaseException as exc:
        report.update(status='FAIL',failed_seed=seed,error=str(exc))
        raise
    finally:
        report['seconds'] = round(time.monotonic()-started,3)
        (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
