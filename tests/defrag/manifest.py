#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Hash every other regular file in a qualification output directory."""
import argparse
import hashlib
import json
from pathlib import Path


def write_manifest(root):
    root = Path(root).resolve()
    entries = {}
    for path in sorted(root.rglob('*')):
        if path.name == 'manifest.json' or path.is_symlink() or not path.is_file():
            continue
        entries[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root/'manifest.json').write_text(json.dumps(entries, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if not args.output.is_dir():
        parser.error(f'output directory does not exist: {args.output}')
    write_manifest(args.output)


if __name__ == '__main__':
    main()
