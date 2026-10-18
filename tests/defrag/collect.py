#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Collect existing results with hashes; never converts missing evidence to PASS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from run import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',type=Path,required=True)
    p.add_argument('--sanitize',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.native=a.native.resolve();a.sanitize=a.sanitize.resolve();a.out.mkdir(parents=True,exist_ok=True)
    mappings={
      'model.json':a.native/'qualification-model/results.json',
      'model-cases.jsonl':a.native/'qualification-model/cases.jsonl',
      'sanitizer-model.json':a.sanitize/'qualification-model/results.json',
      'sanitizer-model-cases.jsonl':a.sanitize/'qualification-model/cases.jsonl',
      'baseline.json':a.native/'qualification-smoke-final-proof/baseline/results.json',
      'regressions.json':a.native/'qualification-smoke-final-proof/regressions/results.json',
      'smoke.json':a.native/'qualification-smoke-final-proof/results.json',
      'driver.json':a.native/'qualification-driver/results.json',
      'metadata.json':a.native/'qualification-metadata-final/results.json',
      'build.json':a.native/'build.json','sanitizer-build.json':a.sanitize/'build.json',
      'baseline-build.json':a.native/'baseline.json',
      'autotools.log':a.native/'autotools.log',
      'matrix.json':a.native/'qualification-matrix/results.json',
      'matrix-cases.jsonl':a.native/'qualification-matrix/cases.jsonl',
      'sanitizer-matrix.json':a.sanitize/'qualification-matrix/results.json',
      'sanitizer-matrix-cases.jsonl':a.sanitize/'qualification-matrix/cases.jsonl',
      'checkpatch.log':a.native/'checkpatch.log',
      'fault-host-boundaries.json':a.native/'qualification-faults/host-boundaries.json',
      'fault-worker-boundaries.json':a.native/'qualification-faults/worker-boundaries.json',
    }
    for folder,prefix in ((a.native,''),(a.sanitize,'sanitizer-')):
        for case in ('faults','persistence','publication','transaction_regressions','negative','upstream'):
            output_name='transactions' if case=='transaction_regressions' else case
            mappings[prefix+output_name+'.json']=folder/('qualification-'+case)/'results.json'
            if case in ('faults','persistence'):
                mappings[prefix+output_name+'-cases.jsonl']=folder/('qualification-'+case)/'cases.jsonl'
        mappings[prefix+'additional.json']=folder/'additional-results.json'
    mappings['negative.json']=a.native/'qualification-negative-fifo/results.json'
    mappings['sanitizer-negative.json']=a.sanitize/'qualification-negative-fifo/results.json'
    mappings['transactions.json']=a.native/'qualification-transactions-fifo/results.json'
    mappings['sanitizer-transactions.json']=a.sanitize/'qualification-transactions-fifo/results.json'
    mappings['sanitizer-regressions.json']=a.sanitize/'qualification-regressions/results.json'
    mappings['sanitizer-metadata.json']=a.sanitize/'qualification-metadata/results.json'
    missing=[]
    for name,source in mappings.items():
        if source.exists():shutil.copyfile(source,a.out/name)
        else:missing.append(dict(name=name,source=str(source),status='NOT_RUN'))
    def capture(args):
        r=subprocess.run(args,capture_output=True,text=True)
        return dict(argv=args,exit=r.returncode,stdout=r.stdout.strip(),stderr=r.stderr.strip())
    environment=dict(base='1647ed54299ae8c4343a5edf40b892307f7e6459',branch='fix/exfat-defrag',
        client_date='2026-10-18',timezone='Europe/London',platform=platform.platform(),python=sys.version,
        dependencies=[capture(args) for args in ([os.environ.get('CC','cc'),'--version'],
           ['pkg-config','--modversion','blkid'],['autoconf','--version'],['automake','--version'],['tar','--version'])],
        sanitizer_options=dict(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'),
        missing_evidence=missing)
    environment['source_sha256']={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for folder in ('defrag','tests/defrag') for f in sorted((ROOT/folder).iterdir())
        if f.suffix in ('.py','.c','.h') or f.name=='defrag.exfat'}
    environment['context_patch_sha256']={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for f in (ROOT/'context/exfat-defrag-integrity/exfat-defrag-integrity.patch',ROOT/'context/exfat-defrag-documentatie/patches/exfat-defrag-integrity.patch') if f.exists()}
    environment['binary_sha256']={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for folder in (a.native,a.sanitize) for f in sorted(folder.iterdir()) if f.name in ('defrag.exfat','fsck.exfat','mkfs.exfat','defrag.original','fault.so','dump.exfat')}
    (a.out/'environment.json').write_text(json.dumps(environment,indent=2)+'\n')
    manifest={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(a.out.iterdir()) if f.is_file() and f.name!='manifest.json'}
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return int(bool(missing))


if __name__=='__main__':raise SystemExit(main())
