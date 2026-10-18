#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent, deliberately small exFAT image reader and fixture generator.

No mounts, FUSE, or defrag implementation internals are used. The fixtures use
ASCII names and a single FAT, with ordinary files, directories and optional
vendor allocation entries. mkfs.exfat supplies the real boot/upcase structures.
This complements, rather than replaces, workloads through a mounted driver.
"""
import hashlib
import math
import mmap
import json
import random
import struct
import subprocess
from pathlib import Path

EOF = 0xFFFFFFFF


def require(condition, message):
    if not condition:
        raise ValueError(message)


def u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def u64(data, offset):
    return struct.unpack_from('<Q', data, offset)[0]


def checksum(data, bits=16, skip=()):
    result = 0
    mask = (1 << bits) - 1
    for i, byte in enumerate(data):
        if i not in skip:
            result = (((result >> 1) | ((result & 1) << (bits - 1))) + byte) & mask
    return result


class Image:
    def __init__(self, path, mutable=False):
        if mutable:
            self.data = bytearray(Path(path).read_bytes())
        else:
            with open(path, 'rb') as stream:
                self.data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        require(self.data[3:11] == b'EXFAT   ', 'not exFAT')
        require(9 <= self.data[108] <= 12 and self.data[108]+self.data[109] <= 25, 'invalid geometry shifts')
        self.sector = 1 << self.data[108]
        self.cluster = self.sector << self.data[109]
        self.fat = u32(self.data, 80) * self.sector
        self.heap = u32(self.data, 88) * self.sector
        self.count = u32(self.data, 92)
        self.root = u32(self.data, 96)
        require(self.data[110] == 1, 'only one FAT supported')
        require(self.heap + self.count * self.cluster <= len(self.data), 'invalid exFAT structure')

    def offset(self, cluster):
        require(2 <= cluster < self.count + 2, f'invalid cluster {cluster}')
        return self.heap + (cluster - 2) * self.cluster

    def chain(self, start, size=None, contiguous=False):
        if not size and size is not None:
            require(start == 0, 'invalid exFAT structure')
            return []
        expected = None if size is None else math.ceil(size / self.cluster)
        result, seen = [], set()
        while start != EOF:
            self.offset(start)
            require(start not in seen, 'cluster cycle')
            seen.add(start)
            result.append(start)
            if contiguous:
                if len(result) == expected:
                    break
                start += 1
            else:
                start = u32(self.data, self.fat + 4 * start)
            require(len(result) <= self.count, 'invalid exFAT structure')
        require(expected is None or len(result) == expected, 'chain length mismatch')
        return result

    def content(self, chain, size):
        return b''.join(self.data[self.offset(c):self.offset(c)+self.cluster]
                        for c in chain)[:size]

    def digest(self, chain, size, valid):
        require(0 <= valid <= size <= len(self.data), 'invalid exFAT structure')
        result = hashlib.sha256()
        for c in chain:
            n = min(size, self.cluster)
            v = min(valid, n)
            result.update(self.data[self.offset(c):self.offset(c)+v])
            result.update(bytes(n-v))
            valid -= v
            size -= n
        return result.hexdigest()

    def inspect(self):
        """Check structures and return path/type/size/content digest + extents."""
        manifest, seen, breaks = {}, set(), 0
        bitmap, upcase, names_to_check = None, None, []
        self.allocations = []
        boot_snapshot = bytearray(self.data[:24*self.sector])
        for base in (0, 12*self.sector):
            boot_snapshot[base+96:base+100] = bytes(4)
            boot_snapshot[base+11*self.sector:base+12*self.sector] = bytes(self.sector)
        manifest['$boot'] = hashlib.sha256(boot_snapshot).hexdigest()

        def claim(chain):
            nonlocal breaks
            require(not seen.intersection(chain), 'cross-linked allocation')
            seen.update(chain)
            self.allocations.append(list(chain))
            breaks += sum(b != a + 1 for a, b in zip(chain, chain[1:]))

        def walk(start, size, contiguous, path):
            nonlocal bitmap, upcase
            chain = self.chain(start, size, contiguous)
            claim(chain)
            raw = self.content(chain, len(chain) * self.cluster)
            i = 0
            while i < len(raw):
                entry = raw[i:i+32]
                kind = entry[0]
                if kind == 0:
                    break
                if kind in (0x81, 0x82):
                    alloc = self.chain(u32(entry, 20), u64(entry, 24))
                    claim(alloc)
                    payload = self.content(alloc, u64(entry, 24))
                    if kind == 0x81:
                        bitmap = payload
                    else:
                        upcase = payload
                        require(checksum(payload, 32) == u32(entry, 4), 'upcase checksum')
                    manifest['$system/' + str(kind)] = hashlib.sha256(payload).hexdigest() if kind == 0x82 else 'bitmap'
                elif kind == 0x85:
                    n = entry[1] + 1
                    entries = raw[i:i + 32*n]
                    require(len(entries) == n*32, 'invalid exFAT structure')
                    require(checksum(entries, skip=(2, 3)) == u16(entries, 2), 'entry checksum')
                    stream = entries[32:64]
                    require(stream[0] == 0xC0, 'invalid exFAT structure')
                    name = b''.join(entries[j+2:j+32] for j in range(64, len(entries), 32)
                                    if entries[j] == 0xC1)
                    name = name[:stream[3]*2].decode('utf-16le')
                    names_to_check.append((name, u16(stream, 4)))
                    child_path = path + '/' + name
                    require(child_path not in manifest, 'duplicate name')
                    normalized = bytearray(entries)
                    normalized[2:4] = bytes(2)
                    normalized[33] &= ~2
                    normalized[52:56] = bytes(4)
                    for j in range(64, len(normalized), 32):
                        if normalized[j] == 0xE1:
                            normalized[j+1] &= ~2
                            normalized[j+20:j+24] = bytes(4)
                    manifest['$metadata'+child_path] = hashlib.sha256(normalized).hexdigest()
                    length, valid = u64(stream, 24), u64(stream, 8)
                    require(valid <= length, 'invalid exFAT structure')
                    child = self.chain(u32(stream, 20), length, bool(stream[1] & 2))
                    if u16(entry, 4) & 0x10:
                        manifest[child_path] = ('directory',)
                        walk(u32(stream, 20), length, bool(stream[1] & 2), child_path)
                    else:
                        claim(child)
                        manifest[child_path] = ('file', length, self.digest(child, length, valid))
                    for j in range(64, len(entries), 32):
                        if entries[j] == 0xE1:
                            vendor = entries[j:j+32]
                            vendor_size = u64(vendor, 24)
                            alloc = self.chain(u32(vendor, 20), vendor_size, bool(vendor[1] & 2))
                            claim(alloc)
                            manifest[child_path + ':vendor:' + str(j)] = (
                                vendor_size, hashlib.sha256(self.content(alloc, vendor_size)).hexdigest())
                    i += (n-1)*32
                elif kind == 0x83:
                    manifest['$label'] = entry.hex()
                else:
                    require(kind < 0x80, f'unsupported entry {kind:#x}')
                i += 32

        walk(self.root, None, False, '')
        require(bitmap is not None, 'invalid exFAT structure')
        require(upcase is not None, 'upcase missing')
        table, at = [], 0
        while at < len(upcase):
            word = u16(upcase, at)
            at += 2
            if word == 0xffff and len(table) < 65535:
                skip = u16(upcase, at)
                at += 2
                table.extend(range(len(table), len(table)+skip))
            else:
                table.append(word)
            require(len(table) <= 65536, 'upcase overflow')
        require(len(table) == 65536, 'upcase length')
        for name, namehash in names_to_check:
            raw = name.encode('utf-16le')
            uppercase = b''.join(struct.pack('<H', table[u16(raw, j)]) for j in range(0, len(raw), 2))
            require(checksum(uppercase) == namehash, 'name hash')
        allocated = {c for c in range(2, self.count+2)
                     if bitmap[(c-2)//8] & (1 << ((c-2)%8))}
        require(allocated == seen, 'bitmap does not match reachable allocations')
        for boot in (0, 12*self.sector):
            boot_data = self.data[boot:boot+11*self.sector]
            value = checksum(boot_data, 32, (106, 107, 112))
            require(self.data[boot+11*self.sector:boot+12*self.sector] == struct.pack('<I', value)*(self.sector//4), 'boot checksum')
        return manifest, breaks


def file_entries(name, size, chain, directory=False, vendor=None, valid=None):
    namebytes = name.encode('utf-16le')
    primary, stream = bytearray(32), bytearray(32)
    primary[0] = 0x85
    struct.pack_into('<H', primary, 4, 0x10 if directory else 0x20)
    # Valid fixed timestamps/UTC offsets exercise byte-for-byte metadata retention.
    struct.pack_into('<III', primary, 8, 0x58216422, 0x58216424, 0x58210000)
    primary[20:25] = bytes((27, 63, 0x80, 0x80, 0x80))
    stream[0], stream[1], stream[3] = 0xC0, 1, len(namebytes)//2
    if chain and all(b == a+1 for a, b in zip(chain, chain[1:])):
        stream[1] |= 2
    struct.pack_into('<H', stream, 4, checksum(name.upper().encode('utf-16le')))
    struct.pack_into('<Q', stream, 8, size if valid is None else valid)
    struct.pack_into('<I', stream, 20, chain[0] if chain else 0)
    struct.pack_into('<Q', stream, 24, size)
    entries = primary + stream
    for offset in range(0, len(namebytes), 30):
        entry = bytearray(32)
        entry[0] = 0xC1
        entry[2:2+len(namebytes[offset:offset+30])] = namebytes[offset:offset+30]
        entries += entry
    if vendor is not None:
        entry = bytearray(32)
        entry[0], entry[1] = 0xE1, 1
        entry[2:18] = bytes(range(16))
        payload, alloc = vendor
        if alloc and all(b == a+1 for a, b in zip(alloc, alloc[1:])):
            entry[1] |= 2
        struct.pack_into('<I', entry, 20, alloc[0] if alloc else 0)
        struct.pack_into('<Q', entry, 24, len(payload))
        entries += entry
    entries[1] = len(entries)//32 - 1
    struct.pack_into('<H', entries, 2, checksum(entries, skip=(2, 3)))
    return entries


def make_fixture(path, mkfs, seed=0, operations=2000, cluster=512, vendor=False, sector=512, stats=None, log=None, occupancy=None, system_tail=False, directory_depth=2):
    """Run a model workload, then serialize its fragmented layout as real exFAT.

    Expected bytes live in the model, independently of the image reader. The
    allocator scatters clusters intentionally; this is not a Linux-driver test.
    """
    rng = random.Random(seed)
    path = Path(path)
    with path.open('wb') as stream:
        stream.truncate(8*1024*1024)
    subprocess.run([str(mkfs), '-L', 'DEFRAG_Δ', '-c', str(cluster), '-s', str(sector), str(path)], check=True, capture_output=True)
    image = Image(path, mutable=True)
    root_offset = image.offset(image.root)
    root = image.content(image.chain(image.root), image.cluster)
    system = b''.join(root[i:i+32] for i in range(0, len(root), 32) if root[i] in (0x81, 0x82))
    label = b''.join(root[i:i+32] for i in range(0, len(root), 32) if root[i] == 0x83)
    require(len(system) == 64 and system[0] == 0x81 and system[32] == 0x82, 'invalid exFAT structure')
    bitmap_start, bitmap_size = u32(system, 20), u64(system, 24)
    if system_tail:
        # Relocate the initially contiguous system streams away from cluster 2.
        system = bytearray(system)
        cursor = image.count + 2
        for at in (32, 0):
            old = image.chain(u32(system, at+20), u64(system, at+24))
            payload = image.content(old, u64(system, at+24))
            cursor -= len(old)
            new = list(range(cursor, cursor+len(old)))
            for i,c in enumerate(new):
                struct.pack_into('<I', image.data, image.fat+4*c, new[i+1] if i+1<len(new) else EOF)
                offset = image.offset(c)
                image.data[offset:offset+cluster] = payload[i*cluster:(i+1)*cluster].ljust(cluster,b'\0')
            struct.pack_into('<I', system, at+20, new[0])
        bitmap_start = u32(system, 20)
    used = set(image.chain(bitmap_start, bitmap_size)) | set(image.chain(u32(system, 52), u64(system, 56))) | {image.root}
    free = [c for c in range(2, image.count+2) if c not in used]
    rng.shuffle(free)

    def alloc(n, contiguous=False):
        require(len(free) >= n, 'fixture full')
        if contiguous and n:
            available = set(free)
            first = next(c for c in sorted(available) if all(c+i in available for i in range(n)))
            result = list(range(first, first+n))
            free[:] = [c for c in free if c not in result]
        else:
            result = [free.pop() for _ in range(n)]
        used.update(result)
        return result

    files = {}
    effective, actions = 0, []
    for iteration in range(operations):
        name = f'f{rng.randrange(60):03d}_Δ猫.bin'
        action = rng.randrange(6)
        state_before = {k:v[0] for k,v in files.items()}
        old, chain = files.get(name, (b'', []))
        if action == 0:
            if name in files:
                used.difference_update(chain)
                free.extend(chain)
                del files[name]
            effective += state_before != {k:v[0] for k,v in files.items()}
            actions.append(dict(iteration=iteration, operation='unlink', path=name))
            continue
        if action == 5:
            other = f'f{rng.randrange(60):03d}_Δ猫.bin'
            if name in files and name != other:
                if other in files:
                    old_chain = files[other][1]
                    used.difference_update(old_chain)
                    free.extend(old_chain)
                files[other] = files.pop(name)
            effective += state_before != {k:v[0] for k,v in files.items()}
            actions.append(dict(iteration=iteration, operation='rename', path=name, target=other))
            continue
        if action == 1:
            content = rng.randbytes(rng.randrange(cluster*5+1))
        elif action == 2:
            content = old + rng.randbytes(rng.randrange(cluster*3+1))
        elif action == 3:
            size = rng.randrange(cluster*7+1)
            content = old[:size].ljust(size, b'\0')
        else:
            offset = rng.randrange(len(old)+cluster+1)
            part = rng.randbytes(rng.randrange(1, cluster+1))
            content = old.ljust(offset, b'\0')[:offset] + part + old[offset+len(part):]
        required = math.ceil(len(content)/cluster)
        if required < len(chain):
            free.extend(chain[required:])
            used.difference_update(chain[required:])
        chain = chain[:required] + alloc(max(0, required-len(chain)))
        files[name] = (content, chain)
        effective += state_before != {k:v[0] for k,v in files.items()}
        actions.append(dict(iteration=iteration, operation=('unlink','create','append','truncate','write','rename')[action],
                            path=name, size=len(content), sha256=hashlib.sha256(content).hexdigest()))
    if stats is not None:
        stats.update(iterations=operations, effective_model_mutations=effective, linux_filesystem_syscalls=0)
    if log:
        Path(log).write_text(''.join(json.dumps(a, ensure_ascii=False)+'\n' for a in actions))
    # Ensure zero-length and multi-cluster allocations always exist.
    files['empty.bin'] = (b'', [])
    files['large.bin'] = (rng.randbytes(cluster*7+17), alloc(8))
    files['contiguous.bin'] = (rng.randbytes(cluster*3+1), alloc(4, True))
    expected = {}

    def write_chain(chain, content):
        for i, c in enumerate(chain):
            struct.pack_into('<I', image.data, image.fat+4*c, chain[i+1] if i+1<len(chain) else EOF)
            offset = image.offset(c)
            image.data[offset:offset+cluster] = content[i*cluster:(i+1)*cluster].ljust(cluster, b'\0')

    require(1 <= directory_depth <= 128, 'fixture directory depth')
    levels = ['album'] + ['album/disc' + '/d'*(n-2) for n in range(2,directory_depth+1)]
    dir_entries = {name: bytearray() for name in ['',*levels,'other']}
    for i, (name, (content, chain)) in enumerate(sorted(files.items())):
        parent = ('', levels[0], levels[-1], 'other')[i % 4]
        full_name = '/' + (parent+'/' if parent else '') + name
        extra = None
        if ((vendor is True and name in ('empty.bin', 'large.bin')) or
                (vendor == 'empty' and name == 'empty.bin') or
                (vendor == 'populated' and name == 'large.bin')):
            payload = rng.randbytes(cluster+13) if name == 'large.bin' else b''
            extra = (payload, alloc(math.ceil(len(payload)/cluster)))
            write_chain(extra[1], extra[0])
        valid = len(content)//2 if i % 7 == 0 else len(content)
        dir_entries[parent] += file_entries(name, len(content), chain, vendor=extra, valid=valid)
        write_chain(chain, content)
        if name == 'contiguous.bin':
            for c in chain:
                struct.pack_into('<I', image.data, image.fat+4*c, 0xfffffff7)
        visible = content[:valid] + bytes(len(content)-valid)
        expected[full_name] = ('file', len(content), hashlib.sha256(visible).hexdigest())
    for dirname in sorted(levels+['other'],key=lambda p:p.count('/'),reverse=True):
        content = dir_entries[dirname] + bytes(32)
        chain = alloc(math.ceil(len(content)/cluster))
        write_chain(chain, content)
        parent, _, name = dirname.rpartition('/')
        dir_entries[parent] += file_entries(name, len(chain)*cluster, chain, directory=True)
        expected['/'+dirname] = ('directory',)
    filler_at = len(system + label) + len(dir_entries[''])
    placeholder = file_entries('fill.bin', 0, []) if occupancy is not None else b''
    content = bytearray(system + label) + dir_entries[''] + placeholder + bytes(32)
    root_chain = [image.root] + alloc(math.ceil(len(content)/cluster)-1)
    if occupancy is not None:
        chain = alloc(max(0, len(free)-int(occupancy)))
        size = max(0, len(chain)*cluster-17)
        payload = (b'full-image-integrity\x00\xff' * ((size//23)+1))[:size]
        payload = payload.ljust(size,b'F')
        write_chain(chain,payload)
        entry = file_entries('fill.bin',size,chain)
        content[filler_at:filler_at+len(entry)] = entry
        expected['/fill.bin'] = ('file',size,hashlib.sha256(payload).hexdigest())
    write_chain(root_chain, content)
    bitmap = bytearray(bitmap_size)
    for c in used:
        bitmap[(c-2)//8] |= 1 << ((c-2)%8)
    write_chain(image.chain(bitmap_start, bitmap_size), bitmap)
    # mkfs's PercentInUse becomes stale after the workload. 0xff is unknown.
    for offset in (0, 12*image.sector):
        image.data[offset+112] = 0xFF
    for base in (0, 12*image.sector):
        struct.pack_into('<I', image.data, base+100, 0xDEF00000 | (seed & 0xffff))
        value = checksum(image.data[base:base+11*image.sector], 32, (106,107,112))
        image.data[base+11*image.sector:base+12*image.sector] = struct.pack('<I', value)*(image.sector//4)
    path.write_bytes(image.data)
    actual, fragmentation = Image(path).inspect()
    require({k:v for k,v in actual.items() if not k.startswith('$') and ':vendor:' not in k} == expected, 'invalid exFAT structure')
    require(fragmentation > 0, 'invalid exFAT structure')
    return actual, fragmentation
