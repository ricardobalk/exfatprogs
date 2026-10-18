# SPDX-License-Identifier: GPL-2.0-or-later
"""Model workload and direct image serializer. These are not Linux file calls."""
import hashlib
import math
from pathlib import Path
import random
import struct
from reader import Volume, checksum, u32, u64


def workload(seed, iterations):
    rng = random.Random(seed)
    files = {}
    actions = []
    names = [f'{("dir/" if i % 3 == 0 else "other/" if i % 3 == 1 else "")}'
             f'{i:02d}_Δ猫_' + ('long_' * (i % 9)) for i in range(48)]
    for i in range(iterations):
        name, op = rng.choice(names), rng.randrange(6)
        old = files.get(name, b'')
        # Each action uses fresh deterministic bytes. Logs contain hashes only.
        value = rng.randbytes(rng.randrange(0, 1500))
        if op == 0:
            files[name] = value
        elif op == 1:
            files[name] = old + value[:200]
        elif op == 2:
            offset = rng.randrange(0, len(old) + 200)
            data = value[:100]
            files[name] = (old + bytes(max(0, offset - len(old))))[:offset] + data + old[offset + len(data):]
        elif op == 3:
            size = rng.randrange(0, 2000)
            files[name] = old[:size] + bytes(max(0, size - len(old)))
        elif op == 4:
            other = rng.choice(names)
            if name in files and name != other:
                files[other] = files.pop(name)
        else:
            files.pop(name, None)
        actions.append(dict(iteration=i, operation=op, path=name,
                            value_sha256=hashlib.sha256(value).hexdigest()))
    return files, actions


def serialize(template, output, files, seed, system_tail=False, fill_bytes=0, inactive_fat=False):
    base = Volume(template)
    data = bytearray(base.data)
    rng = random.Random(seed ^ 0x51a7)
    used = set()
    links = {}
    inactive = set()
    all_clusters = list(range(2, base.count + 2))
    rng.shuffle(all_clusters)

    def allocate(size, contiguous=False, tail=False):
        n = math.ceil(size / base.cluster)
        if not n:
            return []
        if contiguous:
            options = range(base.count + 2 - n, 1, -1) if tail else range(2, base.count + 3 - n)
            chain = next((list(range(c, c + n)) for c in options
                          if not set(range(c, c + n)) & used), None)
            assert chain is not None, 'fixture has no contiguous run'
        else:
            options = sorted(all_clusters, reverse=True) if tail else all_clusters
            chain = [c for c in options if c not in used][:n]
            assert len(chain) == n, 'fixture is full'
        used.update(chain)
        for i, c in enumerate(chain):
            links[c] = chain[i + 1] if i + 1 < len(chain) else 0xffffffff
        return chain

    def store(chain, content):
        for i, c in enumerate(chain):
            off = base.offset(c)
            data[off:off + base.cluster] = content[i * base.cluster:(i + 1) * base.cluster].ljust(base.cluster, b'\0')

    # Allocate system streams independently of the requested sector/cluster size.
    system = []
    for typ in (0x81, 0x82):
        original = base.systems[typ]
        raw = bytearray(original['raw'])
        chain = allocate(len(original['content']), tail=system_tail)
        struct.pack_into('<I', raw, 20, chain[0])
        system.append((typ, raw, chain, original['content']))
    label = next(v for k, v in base.systems.items() if isinstance(k, tuple) and k[0] == 0x83)
    paths = dict(files)
    if fill_bytes:
        paths['filler'] = b'F' * fill_bytes
    children = {'': [], 'dir': [], 'other': []}
    for name, content in sorted(paths.items()):
        parent, _, leaf = name.rpartition('/')
        children[parent].append((leaf, content, False))
    children[''] += [(name, b'', True) for name in ('dir', 'other')]
    table = base.table

    def entry(name, content, isdir, chain, contiguous, valid):
        units = name.encode('utf-16le')
        primary, stream = bytearray(32), bytearray(32)
        count = math.ceil(len(units) / 30)
        primary[0:2] = bytes((0x85, count + 1))
        struct.pack_into('<H', primary, 4, 0x10 if isdir else 0x23)
        # Valid timestamps with distinct UTC offsets and 10 ms fields.
        struct.pack_into('<III', primary, 8, 0x58210000, 0x58210001, 0x58210002)
        primary[20:25] = bytes((12, 34, 0x80, 0x81, 0xfc))
        stream[0:2] = bytes((0xc0, 3 if contiguous else 1))
        stream[3] = len(units) // 2
        upper = b''.join(struct.pack('<H', table[x]) for x in struct.unpack('<' + 'H' * (len(units) // 2), units))
        struct.pack_into('<H', stream, 4, checksum(upper, 16))
        struct.pack_into('<Q', stream, 8, valid)
        struct.pack_into('<I', stream, 20, chain[0] if chain else 0)
        struct.pack_into('<Q', stream, 24, len(content))
        result = primary + stream
        for i in range(count):
            e = bytearray(32)
            e[0] = 0xc1
            e[2:32] = units[i * 30:(i + 1) * 30].ljust(30, b'\0')
            result += e
        struct.pack_into('<H', result, 2, checksum(result, 16, (2, 3)))
        return result

    expected = {}
    def directory(parent):
        entries = bytearray()
        for name, content, isdir in children[parent]:
            full = parent + '/' + name if parent else name
            if isdir:
                content = directory(name)
            contiguous = (rng.randrange(2) == 0) and 0 < len(content) < base.count * base.cluster // 2
            chain = allocate(len(content), contiguous=contiguous)
            if contiguous:
                inactive.update(chain)
            store(chain, content)
            # A subset has uninitialized bytes beyond ValidDataLength.
            valid = len(content) if isdir or rng.randrange(4) else len(content) // 2
            entries += entry(name, content, isdir, chain, contiguous, valid)
            if not isdir:
                expected['/' + full] = hashlib.sha256(content[:valid] + bytes(len(content) - valid)).hexdigest()
        if not parent:
            entries = bytearray(label) + b''.join(e for _, e, _, _ in system) + entries
        entries += bytes(32)
        return bytes(entries).ljust(math.ceil(len(entries) / base.cluster) * base.cluster, b'\0')

    root = directory('')
    root_chain = allocate(len(root), tail=system_tail)
    store(root_chain, root)
    bitmap = bytearray((base.count + 7) // 8)
    for c in used:
        bitmap[(c - 2) // 8] |= 1 << ((c - 2) % 8)
    for typ, raw, chain, content in system:
        store(chain, bitmap if typ == 0x81 else content)
    data[base.fat_at:base.fat_at + base.fat_size] = bytes(base.fat_size)
    struct.pack_into('<II', data, base.fat_at, 0xfffffff8, 0xffffffff)
    for c, nxt in links.items():
        struct.pack_into('<I', data, base.fat_at + c * 4, nxt)
    if inactive_fat:
        values = (0xfffffff7, 0, 0x10000000)
        for i, c in enumerate(sorted(inactive)):
            struct.pack_into('<I', data, base.fat_at + c * 4, values[i % len(values)])
    for start in (0, 12 * base.sector):
        struct.pack_into('<I', data, start + 96, root_chain[0])
        data[start + 112] = min(100, len(used) * 100 // base.count)
        crc = checksum(data[start:start + 11 * base.sector], omit=(106, 107, 112))
        data[start + 11 * base.sector:start + 12 * base.sector] = struct.pack('<I', crc) * (base.sector // 4)
    Path(output).write_bytes(data)
    result = Volume(output)
    actual = {k: v['sha256'] for k, v in result.entries.items() if not v['directory']}
    assert actual == expected, 'fixture differs from external model'
    return dict(used_clusters=len(used), total_clusters=base.count,
                tail_allocations=sum(c >= 2 + (6 * 1024 * 1024 - base.heap) // base.cluster for c in used),
                files=len(expected), root_clusters=len(root_chain)), expected


def capacity_probe(path, old_end):
    """Allocate and read back bytes at a physical location beyond old_end."""
    v = Volume(path)
    data = bytearray(v.data)
    free = [c for c in range(2, v.count + 2) if c not in v.owners and c not in v.bad
            and v.offset(c) >= old_end]
    assert len(free) >= 2, 'no added capacity to test'
    file_cluster = free[-1]
    root_chain = v.chain(v.root, 0)
    raw = b''.join(v.data[v.offset(c):v.offset(c) + v.cluster] for c in root_chain)
    at = next(i for i in range(0, len(raw), 32) if raw[i] == 0)
    if len(raw) - at < 128:
        extension = free[-2]
        struct.pack_into('<I', data, v.fat_at + root_chain[-1] * 4, extension)
        struct.pack_into('<I', data, v.fat_at + extension * 4, 0xffffffff)
        data[v.offset(extension):v.offset(extension) + v.cluster] = bytes(v.cluster)
        root_chain.append(extension)
        allocated = (file_cluster, extension)
    else:
        allocated = (file_cluster,)
    content = b'Added capacity is writable.\x00\xff' * 7
    data[v.offset(file_cluster):v.offset(file_cluster) + len(content)] = content
    struct.pack_into('<I', data, v.fat_at + file_cluster * 4, 0xffffffff)
    name = 'capacity-probe'.encode('utf-16le')
    e = bytearray(96)
    e[0:2] = bytes((0x85, 2))
    struct.pack_into('<H', e, 4, 0x20)
    struct.pack_into('<III', e, 8, 0x58210000, 0x58210000, 0x58210000)
    e[22:25] = b'\x80' * 3
    e[32:34] = bytes((0xc0, 3))
    e[35] = len(name) // 2
    struct.pack_into('<H', e, 36, checksum('CAPACITY-PROBE'.encode('utf-16le'), 16))
    struct.pack_into('<Q', e, 40, len(content))
    struct.pack_into('<I', e, 52, file_cluster)
    struct.pack_into('<Q', e, 56, len(content))
    e[64] = 0xc1
    e[66:96] = name.ljust(30, b'\0')
    struct.pack_into('<H', e, 2, checksum(e, 16, (2, 3)))
    for i, byte in enumerate(e):
        logical = at + i
        off = v.offset(root_chain[logical // v.cluster]) + logical % v.cluster
        data[off] = byte
    bitmap_entry = v.systems[0x81]['raw']
    bitmap_chain = v.chain(u32(bitmap_entry, 20), u64(bitmap_entry, 24))
    for c in allocated:
        logical = (c - 2) // 8
        off = v.offset(bitmap_chain[logical // v.cluster]) + logical % v.cluster
        data[off] |= 1 << ((c - 2) % 8)
    Path(path).write_bytes(data)
    result = Volume(path)
    assert result.entries['/capacity-probe']['sha256'] == hashlib.sha256(content).hexdigest()
    assert v.offset(file_cluster) >= old_end
    return v.offset(file_cluster)
