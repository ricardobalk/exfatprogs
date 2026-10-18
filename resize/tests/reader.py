# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent exFAT image reader. No resize-engine imports or C calls.

Offsets and algorithms come from Microsoft exFAT specification sections 3-7.
This reader is a test oracle, not a repair tool. All failures raise AssertionError.
"""
import hashlib
from pathlib import Path
import struct


def u16(b, at):
    return struct.unpack_from('<H', b, at)[0]


def u32(b, at):
    return struct.unpack_from('<I', b, at)[0]


def u64(b, at):
    return struct.unpack_from('<Q', b, at)[0]


def checksum(data, bits=32, omit=()):
    value = 0
    for i, byte in enumerate(data):
        if i not in omit:
            value = ((value >> 1) | ((value & 1) << (bits - 1))) + byte
            value &= (1 << bits) - 1
    return value


class Volume:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        b = self.data
        assert b[3:11] == b'EXFAT   '
        assert b[11:64] == bytes(53) and u64(b, 64) == 0
        assert u16(b, 104) == 0x100 and b[110] == 1
        assert 9 <= b[108] <= 12 and b[108] + b[109] <= 25
        self.sector = 1 << b[108]
        self.cluster = self.sector << b[109]
        self.length = u64(b, 72) * self.sector
        self.fat_at = u32(b, 80) * self.sector
        self.fat_size = u32(b, 84) * self.sector
        self.heap = u32(b, 88) * self.sector
        self.count = u32(b, 92)
        self.root = u32(b, 96)
        assert self.length <= len(b)
        assert 0 < self.count <= 0xfffffff5
        assert self.count == min((self.length - self.heap) // self.cluster, 0xfffffff5)
        assert self.fat_at >= 24 * self.sector
        assert (self.count + 2) * 4 <= self.fat_size
        assert self.fat_at + self.fat_size <= self.heap
        assert u32(b, self.fat_at) == 0xfffffff8
        assert u32(b, self.fat_at + 4) == 0xffffffff
        assert not u16(b, 106) & 7
        for base in (0, 12 * self.sector):
            boot = b[base:base + 11 * self.sector]
            assert u16(boot, 510) == 0xaa55
            for i in range(1, 9):
                assert u32(boot, (i + 1) * self.sector - 4) == 0xaa550000
            crc = checksum(boot, omit=(106, 107, 112))
            assert b[base + 11 * self.sector:base + 12 * self.sector] == struct.pack('<I', crc) * (self.sector // 4)
        for i in range(11 * self.sector):
            if i not in (106, 107, 112):
                assert b[i] == b[12 * self.sector + i], ('boot mismatch', i)
        self.owners = {}
        self.entries = {}
        self.systems = {}
        self.bitmap = None
        self.upcase = None
        self.file_records = []
        self.walk(self.root, 0, False, '/', True)
        assert self.bitmap is not None and self.upcase is not None
        self.table = self.decode_upcase(self.upcase)
        for path, names, expected_hash in self.file_records:
            upper = b''.join(struct.pack('<H', self.table[x]) for x in struct.unpack('<' + 'H' * (len(names) // 2), names))
            assert checksum(upper, 16) == expected_hash, ('name hash', path)
        assert len(self.bitmap) == (self.count + 7) // 8
        self.bad = set()
        for cluster in range(2, self.count + 2):
            allocated = bool(self.bitmap[(cluster - 2) // 8] & (1 << ((cluster - 2) % 8)))
            if cluster not in self.owners and self.fat(cluster) == 0xfffffff7:
                self.bad.add(cluster)
            assert allocated == (cluster in self.owners or cluster in self.bad), ('ownership', cluster)
        self.identity = b[100:104].hex()

    @staticmethod
    def decode_upcase(data):
        result = []
        words = iter(struct.unpack('<' + 'H' * (len(data) // 2), data))
        for value in words:
            if value == 0xffff and len(result) < 0xffff:
                skip = next(words)
                result.extend(range(len(result), len(result) + skip))
            else:
                result.append(value)
        assert len(result) == 65536
        return result

    def fat(self, cluster):
        return u32(self.data, self.fat_at + cluster * 4)

    def offset(self, cluster):
        assert 2 <= cluster < self.count + 2, ('cluster range', cluster)
        return self.heap + (cluster - 2) * self.cluster

    def chain(self, first, length, contiguous=False):
        needed = (length + self.cluster - 1) // self.cluster
        if not length and not first:
            return []
        if contiguous:
            assert needed > 0
            result = list(range(first, first + needed))
            for c in result:
                self.offset(c)
            return result
        result, seen = [], set()
        while True:
            self.offset(first)
            assert first not in seen, 'cycle'
            seen.add(first)
            result.append(first)
            nxt = self.fat(first)
            if nxt == 0xffffffff:
                break
            assert 2 <= nxt < self.count + 2, ('bad FAT link', nxt)
            first = nxt
        if length:
            assert len(result) == needed, ('chain length', len(result), needed)
        return result

    def stream(self, first, length, contiguous, owner):
        chain = self.chain(first, length, contiguous)
        chunks = []
        for c in chain:
            assert c not in self.owners, ('cross link', owner, c)
            self.owners[c] = owner
            at = self.offset(c)
            chunks.append(self.data[at:at + self.cluster])
        raw = b''.join(chunks)
        return raw[:length] if length else raw

    def walk(self, first, length, contiguous, path, root=False):
        raw = self.stream(first, length, contiguous, path)
        assert len(raw) % 32 == 0
        at = 0
        while at < len(raw):
            e = raw[at:at + 32]
            typ = e[0]
            if typ == 0:
                break
            if not typ & 0x80:
                at += 32
                continue
            if typ in (0x81, 0x82):
                assert root and typ not in self.systems
                size = u64(e, 24)
                content = self.stream(u32(e, 20), size, False, hex(typ))
                self.systems[typ] = dict(raw=e, content=content)
                if typ == 0x81:
                    self.bitmap = content
                else:
                    assert checksum(content) == u32(e, 4)
                    self.upcase = content
                at += 32
                continue
            if typ != 0x85:
                # Explicitly known non-allocating primary entries only.
                assert root and typ in (0x83, 0xa0), ('unsupported entry', hex(typ))
                self.systems[(typ, at)] = e
                at += 32
                continue
            count = e[1] + 1
            entryset = raw[at:at + count * 32]
            assert len(entryset) == count * 32 and count >= 3
            assert checksum(entryset, 16, (2, 3)) == u16(e, 2)
            stream = entryset[32:64]
            assert stream[0] == 0xc0 and stream[1] in (1, 3)
            names = b''
            for p in range(64, count * 32, 32):
                assert entryset[p] == 0xc1
                names += entryset[p + 2:p + 32]
            names = names[:stream[3] * 2]
            name = names.decode('utf-16le')
            assert name and '/' not in name and name not in ('.', '..')
            child = (path.rstrip('/') + '/' + name)
            assert child not in self.entries
            self.file_records.append((child, names, u16(stream, 4)))
            data_length, valid = u64(stream, 24), u64(stream, 8)
            assert valid <= data_length
            isdir = bool(u16(e, 4) & 0x10)
            meta = dict(primary=e[4:].hex(), stream=stream[2:20].hex(),
                        length=data_length, valid=valid, directory=isdir)
            if isdir:
                assert data_length and valid == data_length
                self.entries[child] = meta
                self.walk(u32(stream, 20), data_length, bool(stream[1] & 2), child)
            else:
                content = self.stream(u32(stream, 20), data_length, bool(stream[1] & 2), child)
                content = content[:valid] + bytes(data_length - valid)
                meta['sha256'] = hashlib.sha256(content).hexdigest()
                self.entries[child] = meta
            at += count * 32

    def snapshot(self):
        # System entry byte offsets can change when files move; use their bytes.
        stable = sorted(v.hex() for k, v in self.systems.items() if isinstance(v, bytes))
        return dict(entries=self.entries, serial=self.identity, system=stable,
                    upcase=hashlib.sha256(self.upcase).hexdigest(),
                    upcase_entry=(self.systems[0x82]['raw'][:20] + self.systems[0x82]['raw'][24:]).hex())
