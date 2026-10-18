# SPDX-License-Identifier: GPL-2.0-or-later
"""Strict image preflight and semantic verification, independent of the C parser.

This bounded experimental host accepts only the structures understood below.
The test oracle is tests/defrag/image.py and does not import this module.
"""
import hashlib
import struct

# Private qualification fixture contract: opaque bytes, no physical references.
OPAQUE_GUID = bytes(range(16))
MAX_IMAGE = 256 << 20


class LayoutError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LayoutError(message)


def number(b, at, size):
    return int.from_bytes(b[at:at + size], 'little')


def rotate_sum(b, bits, excluded=()):
    value = 0
    mask = (1 << bits) - 1
    for at, byte in enumerate(b):
        if at not in excluded:
            value = (((value & 1) << (bits - 1)) + (value >> 1) + byte) & mask
    return value


class Layout:
    def __init__(self, data):
        self.data = data
        self.records, self.chains, self.owners = {}, {}, set()
        self.systems, self.names = {}, []
        b = data
        require(512 <= len(b) <= MAX_IMAGE, 'supported image size: 512 bytes..256 MiB')
        require(b[3:11] == b'EXFAT   ' and b[11:64] == bytes(53), 'invalid exFAT header')
        require(number(b, 64, 8) == 0 and not any(b[446:510]), 'only a volume at byte zero, without partition boot code')
        require(9 <= b[108] <= 12 and b[108] + b[109] <= 25, 'invalid sector/cluster shifts')
        self.sector, self.cluster = 1 << b[108], 1 << (b[108] + b[109])
        self.count, self.root = number(b, 92, 4), number(b, 96, 4)
        self.fat = number(b, 80, 4) * self.sector
        self.fat_bytes = number(b, 84, 4) * self.sector
        self.heap = number(b, 88, 4) * self.sector
        require(number(b, 72, 8) * self.sector == len(b), 'container must equal the volume length')
        require(number(b, 104, 2) == 0x100 and b[110] == 1, 'only revision 1.00 and one FAT; no TexFAT')
        require(number(b, 106, 2) == 0, 'volume flags must be clean, with no media failure or reserved flags')
        require(0 < self.count <= 0xfffffff5, 'invalid cluster count')
        require(24 * self.sector <= self.fat and (self.count + 2) * 4 <= self.fat_bytes,
                'FAT geometry outside bounds')
        require(self.fat + self.fat_bytes <= self.heap and
                self.count == min((len(b)-self.heap)//self.cluster,0xfffffff5), 'overlapping or out-of-range geometry')
        require(self.link(0) == 0xfffffff8 and self.link(1) == 0xffffffff, 'FAT reserved entries')
        for base in (0, 12 * self.sector):
            boot = b[base:base + 11 * self.sector]
            require(len(boot) == 11 * self.sector and boot[510:512] == b'\x55\xaa', 'boot signature')
            for i in range(1, 9):
                require(boot[(i+1)*self.sector-4:(i+1)*self.sector] == b'\0\0\x55\xaa', 'extended boot signature')
            value = rotate_sum(boot, 32, (106, 107, 112))
            require(b[base+11*self.sector:base+12*self.sector] == value.to_bytes(4, 'little') * (self.sector//4),
                    'boot checksum')
        require(b[:11*self.sector] == b[12*self.sector:23*self.sector], 'main/backup boot mismatch')
        self.boot = bytearray(b[:24*self.sector])
        for base in (0, 12*self.sector):
            self.boot[base+96:base+100] = bytes(4)
            self.boot[base+11*self.sector:base+12*self.sector] = bytes(self.sector)
        queue = [(self.root, None, False, '/', 0)]
        while queue:
            start, length, nofat, path, depth = queue.pop(0)
            require(depth <= 128, 'directory nesting exceeds supported limit 128')
            chain = self.claim(start, length, nofat, path)
            raw = self.payload(chain, len(chain) * self.cluster)
            index, folded = 0, set()
            while index < len(raw):
                e = raw[index:index+32]
                typ = e[0]
                if typ == 0:
                    break
                if not typ & 0x80:
                    index += 32
                    continue
                if typ in (0x81, 0x82):
                    require(path == '/' and typ not in self.systems, 'duplicate/non-root system entry')
                    require(e[1] == 0, 'unsupported system flags')
                    size = number(e, 24, 8)
                    require(size > 0, 'empty system allocation')
                    system = self.claim(number(e, 20, 4), size, False, '$' + str(typ))
                    require(all(y == x+1 for x, y in zip(system, system[1:])), 'fragmented system allocation unsupported')
                    content = self.payload(system, size)
                    if typ == 0x81:
                        require(size == (self.count+7)//8, 'bitmap size must equal cluster count rounded up')
                        self.bitmap = content
                    else:
                        require(size <= 131072 and size % 2 == 0 and rotate_sum(content, 32) == number(e, 4, 4), 'upcase length/checksum')
                        self.upcase = self.decode_upcase(content)
                        self.records['$upcase'] = hashlib.sha256(content).hexdigest()
                    self.systems[typ] = e
                elif typ == 0x83:
                    require(path == '/' and '$label' not in self.records and e[1] <= 11, 'volume label')
                    self.records['$label'] = e.hex()
                elif typ == 0x85:
                    count = e[1] + 1
                    entries = raw[index:index+count*32]
                    require(3 <= count <= 256 and len(entries) == count*32, 'entry-set length')
                    require(rotate_sum(entries, 16, (2, 3)) == number(e, 2, 2), 'entry-set checksum')
                    s = entries[32:64]
                    require(s[0] == 0xc0 and s[1] in (1, 3) and s[3] > 0, 'stream extension')
                    nname = (s[3] + 14)//15
                    require(2+nname <= count and all(entries[j*32] == 0xc1 for j in range(2, 2+nname)), 'name entries')
                    units = b''.join(entries[j*32+2:j*32+32] for j in range(2, 2+nname))[:2*s[3]]
                    try:
                        name = units.decode('utf-16le')
                    except UnicodeError as exc:
                        raise LayoutError('invalid Unicode name') from exc
                    require(name not in ('.', '..') and not any(c in name for c in '\x00/\\:*?"<>|') and
                            all(ord(c) >= 32 for c in name), 'invalid filename')
                    child = path.rstrip('/') + '/' + name
                    size, valid, start = number(s, 24, 8), number(s, 8, 8), number(s, 20, 4)
                    require(valid <= size <= len(b), 'valid-data-length/size')
                    attr = number(e, 4, 2)
                    require(not attr & ~0x37, 'reserved attributes')
                    directory = bool(attr & 0x10)
                    require(not directory or (size > 0 and size % self.cluster == 0 and valid == size), 'directory length')
                    self.names.append((path, units, number(s, 4, 2)))
                    require(child not in self.records, 'duplicate path')
                    normalized = bytearray(entries)
                    normalized[2:4] = bytes(2)
                    normalized[33] &= ~2
                    normalized[52:56] = bytes(4)
                    if directory:
                        queue.append((start, size, bool(s[1] & 2), child, depth+1))
                        contents = 'directory'
                    else:
                        alloc = self.claim(start, size, bool(s[1] & 2), child)
                        visible = self.payload(alloc, valid) + bytes(size-valid)
                        contents = hashlib.sha256(visible).hexdigest()
                    for j in range(2+nname, count):
                        v = entries[j*32:(j+1)*32]
                        require(v[0] == 0xe1 and v[1] in (1, 3) and any(v[2:18]), 'unknown/unsupported secondary entry')
                        amount = number(v, 24, 8)
                        require(amount == 0 or v[2:18] == OPAQUE_GUID, 'unknown allocated vendor GUID')
                        allocation = self.claim(number(v, 20, 4), amount, bool(v[1] & 2), child+':vendor:'+str(j))
                        self.records[child+':vendor:'+str(j)] = hashlib.sha256(self.payload(allocation, amount)).hexdigest()
                        normalized[j*32+1] &= ~2
                        normalized[j*32+20:j*32+24] = bytes(4)
                    self.records[child] = (normalized.hex(), contents)
                    index += count*32
                    continue
                else:
                    raise LayoutError('unsupported active entry ' + hex(typ))
                index += 32
        require(set(self.systems) == {0x81, 0x82}, 'missing bitmap/upcase')
        folded_names = set()
        for parent, raw, expected in self.names:
            upper = b''.join(self.upcase[number(raw, n, 2)].to_bytes(2, 'little') for n in range(0, len(raw), 2))
            require(rotate_sum(upper, 16) == expected, 'filename hash')
            key = (parent, upper)
            require(key not in folded_names, 'duplicate case-insensitive filename')
            folded_names.add(key)
        for c in range(2, self.count+2):
            allocated = bool(self.bitmap[(c-2)//8] & 1 << ((c-2)%8))
            require(allocated == (c in self.owners), 'unowned/missing bitmap allocation; bad clusters unsupported')
            # Invalid FAT fields of NoFatChain streams are deliberately ignored.
            require(c in self.owners or self.link(c) != 0xfffffff7, 'bad clusters unsupported')
        self.breaks = sum(sum(y != x+1 for x, y in zip(c, c[1:])) for c in self.chains.values())
        self.extents = sum(1 + sum(y != x+1 for x, y in zip(c, c[1:])) for c in self.chains.values() if c)

    def link(self, cluster):
        return number(self.data, self.fat+4*cluster, 4)

    def offset(self, cluster):
        require(2 <= cluster < self.count+2, 'cluster outside heap')
        return self.heap + (cluster-2)*self.cluster

    def claim(self, start, size, nofat, owner):
        require(owner not in self.chains, 'duplicate allocation owner')
        if size == 0:
            require(start == 0 and not nofat, 'empty stream allocation/flags')
            self.chains[owner] = []
            return []
        require(size is None or 0 < size <= len(self.data), 'allocation size outside image')
        expected = None if size is None else (size+self.cluster-1)//self.cluster
        chain = []
        while True:
            self.offset(start)
            require(start not in self.owners, 'cycle or cross-linked cluster')
            self.owners.add(start)
            chain.append(start)
            if nofat:
                if len(chain) == expected:
                    break
                start += 1
            else:
                start = self.link(start)
                if start == 0xffffffff:
                    break
            require(len(chain) <= self.count, 'chain exceeds volume')
        require(expected is None or len(chain) == expected, 'chain length differs from stream size')
        self.chains[owner] = chain
        return chain

    def payload(self, chain, length):
        return b''.join(self.data[self.offset(c):self.offset(c)+self.cluster] for c in chain)[:length]

    @staticmethod
    def decode_upcase(data):
        table, words, i = [], list(struct.unpack('<'+'H'*(len(data)//2), data)), 0
        while i < len(words):
            value = words[i]
            i += 1
            if value == 0xffff and len(table) < 65535:
                require(i < len(words) and words[i] > 0, 'upcase skip')
                table.extend(range(len(table), len(table)+words[i]))
                i += 1
            else:
                table.append(value)
            require(len(table) <= 65536, 'upcase overflow')
        require(len(table) == 65536, 'incomplete upcase')
        return table

    def equivalent(self, other):
        return self.records == other.records and self.boot == other.boot

    def report(self):
        return dict(discontinuities=self.breaks, extents=self.extents, allocated_clusters=len(self.owners),
                    target_allocations=sum(bool(c) for c in self.chains.values()),
                    sector_bytes=self.sector, cluster_bytes=self.cluster, feasible=True,
                    journal_bytes=len(self.data), limitations=['Linux regular volume images <=256 MiB',
                    'one FAT; initially contiguous system streams; no bad clusters',
                    'allocated vendors require the private opaque-payload GUID'])
