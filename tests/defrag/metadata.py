#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Attributes/times/VDL and non-root boot bytes survive real relocation."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
from image import Image,make_fixture,checksum,u32,u64,require
from run import ROOT,CLI,command,sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build-defrag-tests')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.build=a.build.resolve();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=False)
    results=[]
    try:
        for sector in (512,4096):
            target=a.out/(str(sector)+'.img');make_fixture(target,a.build/'mkfs.exfat',7,100,sector,True,sector)
            image=Image(target,mutable=True);count=0
            queue=[(image.root,None,False)]
            while queue:
                start,length,nofat=queue.pop(0);chain=image.chain(start,length,nofat)
                raw=image.content(chain,len(chain)*image.cluster);i=0
                while i<len(raw) and raw[i]:
                    if raw[i]!=0x85:i+=32;continue
                    n=(raw[i+1]+1)*32;entry=bytearray(raw[i:i+n]);directory=bool(entry[4]&0x10)
                    entry[4]|=count%8  # read-only, hidden and system combinations.
                    entry[20:25]=bytes((199,198,0x80,0x84,0xfc))
                    struct.pack_into('<H',entry,2,checksum(entry,skip=(2,3)))
                    for j,byte in enumerate(entry):
                        pos=i+j;image.data[image.offset(chain[pos//image.cluster])+pos%image.cluster]=byte
                    if directory:queue.append((u32(entry,52),u64(entry,56),bool(entry[33]&2)))
                    count+=1;i+=n
            for base in (0,12*sector):
                image.data[base+200:base+216]=b'keep-boot-bytes!!'[:16]
                if sector==4096:image.data[base+1024:base+1040]=b'keep-large-sector'[:16]
                value=checksum(image.data[base:base+11*sector],32,(106,107,112))
                image.data[base+11*sector:base+12*sector]=struct.pack('<I',value)*(sector//4)
            target.write_bytes(image.data)
            expected,before=Image(target).inspect();command([a.build/'fsck.exfat','-n',target])
            command(CLI+[target,'--engine',a.build/'defrag.exfat','--fsck',a.build/'fsck.exfat','--journal',a.out/(str(sector)+'-journal')])
            require(Image(target).inspect()==(expected,0),'metadata or boot bytes changed')
            command([a.build/'fsck.exfat','-n',target])
            results.append(dict(sector_bytes=sector,status='PASS',entry_sets=count,attribute_combinations=8,
                                vdl_timestamps_utc_and_boot_preserved=True,before_discontinuities=before,after_discontinuities=0))
    except BaseException as exc:
        results.append(dict(sector_bytes=sector,status='FAIL',error=str(exc)))
        raise
    finally:
        (a.out/'results.json').write_text(json.dumps(results,indent=2)+'\n')



if __name__=='__main__':main()
