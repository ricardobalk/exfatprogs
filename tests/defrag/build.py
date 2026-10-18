#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit local test build, without re-enabling installation of defrag.exfat.

Requires a C compiler and util-linux libblkid headers/library. On Debian/Ubuntu:
install build-essential libblkid-dev. Normal autotools builds remain unchanged.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('build-defrag-tests'))
    parser.add_argument('--blkid-include', type=Path, default=Path('/usr/include/blkid'))
    parser.add_argument('--baseline', action='store_true', help='compile HEAD defrag with current checksum API adaptation only')
    parser.add_argument('--sanitize', action='store_true')
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--base', default='1647ed54299ae8c4343a5edf40b892307f7e6459')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    common = [os.environ.get('CC', 'cc'), '-O2', '-g', '-Wall', '-Wextra', '-I'+str(root/'include')]
    if sys.byteorder == 'big':
        common += ['-DWORDS_BIGENDIAN']
    if args.sanitize:
        common += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    sources = [str(root/'lib'/name) for name in ('libexfat.c', 'exfat_fs.c', 'exfat_dir.c', 'utils.c')]

    def build(name, extra, flags=()):
        subprocess.run(common + list(flags) + sources + [str(root/x) for x in extra] + ['-o', str(out/name)], check=True)

    if not args.baseline_only:
        build('defrag.exfat', ['defrag/defrag.c'])
    build('fsck.exfat', ['fsck/fsck.c', 'fsck/repair.c'])
    build('dump.exfat', ['dump/dump.c'])
    build('mkfs.exfat', ['mkfs/mkfs.c', 'mkfs/upcase.c', 'mkfs/crc.c'],
          ['-DHAVE_BLKID', '-I'+str(args.blkid_include), '-Wl,--no-as-needed', '-Wl,-l:libblkid.so.1'])
    subprocess.run([os.environ.get('CC', 'cc'), '-O2', '-shared', '-fPIC', '-Wall', '-Wextra',
                    str(root/'tests/defrag/fault.c'), '-ldl', '-o', str(out/'fault.so')], check=True)
    if args.baseline or args.baseline_only:
        # Pin EVERY translation unit and header; no repaired shared library.
        original_root = out / 'baseline-source'
        files = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', args.base], cwd=root, text=True).splitlines()
        for name in files:
            if name.startswith(('include/', 'lib/', 'defrag/')):
                target = original_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(['git', 'show', args.base + ':' + name], cwd=root))
        source = original_root / 'defrag/defrag.c'
        original = source.read_text()
        original = original.replace('exfat_write_checksum_sector(bd, NULL, checksum, is_backup)',
                                    'exfat_write_checksum_sector(bd, NULL, 0, checksum, is_backup)')
        source.write_text(original)
        flags = [x for x in common if x != '-I' + str(root/'include')]
        baseline_sources = [str(original_root / 'lib' / Path(x).name) for x in sources]
        subprocess.run(flags + ['-I' + str(original_root/'include')] + baseline_sources +
                       [str(source), '-o', str(out/'defrag.original')], check=True)
        (out/'baseline.json').write_text(__import__('json').dumps(dict(
            commit=args.base, shared_patched_sources=False,
            adaptation='add zero sector offset argument to exfat_write_checksum_sector'), indent=2) + '\n')
    import hashlib, json, platform
    relevant = sorted(list((root/'defrag').glob('*.c')) + list((root/'defrag').glob('*.h')) +
                      list((root/'lib').glob('*.c')) + list((root/'include').glob('*.h')))
    (out/'build.json').write_text(json.dumps(dict(base=args.base, compiler=subprocess.check_output([common[0],'--version'],text=True).splitlines()[0],
        platform=platform.platform(),python=sys.version,sanitize=args.sanitize,flags=common,
        source_sha256={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in relevant}),indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
