#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Preflight rejection must leave the entire source unchanged."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import struct
import time
from image import Image, make_fixture, checksum, u32, u64, require
from run import ROOT, CLI, command, sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out=a.out.resolve();a.build=a.build.resolve();a.out.mkdir(parents=True,exist_ok=False)
    source=a.out/'source.img';make_fixture(source,a.build/'mkfs.exfat',7,100,512,True)
    original=source.read_bytes();base_image=Image(source);base_image.inspect()
    fat,root,heap=base_image.fat,base_image.root,base_image.heap
    # Flatten directories only for the test's mutation address mapping.
    # Files, nested files and vendor entries all participate independently.
    flattened=bytearray();positions=[];sets=[];queue=[(root,None,False)]
    while queue:
        start,size,nofat=queue.pop(0)
        chain=base_image.chain(start,size,nofat)
        part=base_image.content(chain,len(chain)*512)
        base=len(flattened);flattened.extend(part)
        positions.extend(base_image.offset(c)+j for c in chain for j in range(512))
        i=0
        while i<len(part) and part[i]:
            if part[i]==0x85:
                length=(part[i+1]+1)*32;entry=part[i:i+length]
                sets.append((base+i,entry))
                if struct.unpack_from('<H',entry,4)[0]&0x10:
                    queue.append((u32(entry,52),u64(entry,56),bool(entry[33]&2)))
                i+=length
            else:i+=32
    raw=bytes(flattened)
    def physical(at):return positions[at]
    ordinary=[(at,e) for at,e in sets if not struct.unpack_from('<H',e,4)[0]&0x10 and u64(e,56)>0]
    def update_entry(data,at,entry):
        struct.pack_into('<H',entry,2,checksum(entry,skip=(2,3)))
        for j in range(len(entry)):data[physical(at+j)]=entry[j]
    def mutate(name,data):
        if name=='invalid-end-marker':struct.pack_into('<I',data,fat+4*root,0xfffffff8)
        elif name=='root-cycle':struct.pack_into('<I',data,fat+4*root,root)
        elif name=='crosslink':
            at,e=ordinary[1];entry=bytearray(e);other=ordinary[0][1]
            entry[33]=other[33];entry[40:48]=other[40:48];entry[52:64]=other[52:64]
            update_entry(data,at,entry)
        elif name=='chain-too-long':
            at,e=ordinary[0];entry=bytearray(e);entry[33]&=~2
            struct.pack_into('<Q',entry,56,1);struct.pack_into('<Q',entry,40,1)
            update_entry(data,at,entry)
        elif name in ('unknown-allocation','bad-cluster'):
            free=next(c for c in range(2,base_image.count+2) if all(c not in chain for chain in base_image.allocations))
            bitmap=u32(raw,20);offset=base_image.offset(bitmap)+(free-2)//8
            data[offset]|=1<<((free-2)%8)
            if name=='bad-cluster':struct.pack_into('<I',data,fat+4*free,0xfffffff7)
        elif name=='missing-bitmap-bit':
            bitmap=u32(raw,20);data[base_image.offset(bitmap)+(root-2)//8]&=~(1<<((root-2)%8))
        elif name=='unknown-vendor':
            at,e=next((at,e) for at,e in sets if any(e[j]==0xe1 and u64(e,j+24)>0 for j in range(64,len(e),32)))
            entry=bytearray(e);v=next(j for j in range(64,len(e),32) if e[j]==0xe1 and u64(e,j+24)>0)
            entry[v+2:v+18]=b'unknownGUIDbytes';update_entry(data,at,entry)
        elif name=='unknown-primary':data[physical(0)]=0xa1
        elif name=='checksum':data[physical(sets[0][0])+2]^=1
        elif name=='vdl-overflow':
            at,e=ordinary[0];entry=bytearray(e);struct.pack_into('<Q',entry,40,0xffffffffffffffff);update_entry(data,at,entry)
        elif name=='stream-size-overflow':
            at,e=ordinary[0];entry=bytearray(e);struct.pack_into('<Q',entry,56,0xffffffffffffffff);update_entry(data,at,entry)
        elif name=='two-fats':data[110]=2
        elif name=='dirty':data[106]=2
        elif name=='sector-shift-overflow':data[108]=63
        elif name=='cluster-shift-overflow':data[109]=255
        elif name=='fat-offset-overflow':struct.pack_into('<I',data,80,0xffffffff)
        elif name=='fat-size-overflow':struct.pack_into('<I',data,84,0xffffffff)
        elif name=='heap-offset-overflow':struct.pack_into('<I',data,88,0xffffffff)
        elif name=='cluster-count-overflow':struct.pack_into('<I',data,92,0xffffffff)
        elif name=='volume-length-overflow':struct.pack_into('<Q',data,72,0xffffffffffffffff)
        elif name=='partition-offset':struct.pack_into('<Q',data,64,2048)
        elif name=='trailing-container':data.extend(bytes(512))
        elif name=='truncated-container':del data[-512:]
        elif name=='partition-bootcode':data[446]=0x80
        else:raise ValueError(name)
        # Make header mutations checksum-valid when geometry still admits it.
        if name not in ('sector-shift-overflow','cluster-shift-overflow'):
            data[12*512:23*512]=data[:11*512]
            for start in (0,12*512):
                value=checksum(data[start:start+11*512],32,(106,107,112))
                data[start+11*512:start+12*512]=struct.pack('<I',value)*128
        return data
    names=('invalid-end-marker','root-cycle','crosslink','chain-too-long','unknown-allocation','bad-cluster','missing-bitmap-bit',
           'unknown-vendor','unknown-primary','checksum','vdl-overflow','stream-size-overflow','two-fats',
           'dirty','sector-shift-overflow','cluster-shift-overflow','fat-offset-overflow','fat-size-overflow',
           'heap-offset-overflow','cluster-count-overflow','volume-length-overflow','partition-offset',
           'trailing-container','truncated-container','partition-bootcode')
    results=[];started=time.monotonic()
    try:
        for name in names:
            image=a.out/(name+'.img');image.write_bytes(mutate(name,bytearray(original)))
            before=sha(image);journal=a.out/(name+'-journal')
            r=command(CLI+[image,'--journal',journal,'--engine',a.build/'defrag.exfat','--fsck',a.build/'fsck.exfat'],expected=1)
            require(sha(image)==before and not journal.exists(),'preflight wrote rejected source')
            row=dict(case=name,status='PASS',exit=r.returncode,sha256_equal=True,diagnostic=r.stderr.strip())
            results.append(row);image.unlink()
        # Same-inode advisory lock conflict, symlinks, hard links, stale marker.
        fd=os.open(source,os.O_RDONLY);fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        before=sha(source)
        r=command(CLI+[source,'--journal',a.out/'busy-journal'],expected=1)
        require(sha(source)==before,'busy image changed');os.close(fd)
        results.append(dict(case='advisory-lock-conflict',status='PASS',exit=1,sha256_equal=True))
        fifo=a.out/'named-pipe';os.mkfifo(fifo)
        command(CLI+[fifo,'--dry-run'],expected=1);fifo.unlink()
        results.append(dict(case='nonregular-fifo',status='PASS',exit=1,rejected_without_blocking=True))
        for mode in ('symlink','hardlink'):
            target=a.out/(mode+'.img')
            os.symlink(source,target) if mode=='symlink' else os.link(source,target)
            command(CLI+[target,'--dry-run'],expected=1)
            require(sha(source)==before,'linked image changed');target.unlink()
            results.append(dict(case=mode,status='PASS',exit=1,sha256_equal=True))
    except BaseException as exc:
        results.append(dict(case=name,status='FAIL',error=str(exc)))
        raise
    finally:
        (a.out/'results.json').write_text(json.dumps(dict(status='PASS' if len(results)==len(names)+4 and all(r['status']=='PASS' for r in results) else 'FAIL',
            cases=results,seconds=round(time.monotonic()-started,3)),indent=2)+'\n')


if __name__=='__main__':main()
