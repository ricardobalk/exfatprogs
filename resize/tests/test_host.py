# SPDX-License-Identifier: GPL-2.0-or-later
import argparse
import errno
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image_resize as h


class HostTests(unittest.TestCase):
    def test_units_and_overflow(self):
        self.assertEqual(h.size_bytes('1KiB'), 1024)
        self.assertEqual(h.size_bytes('9223372036854775807B'), 2**63 - 1)
        for text in ('1M', '1MB', '-1B', '+1B', '1.5MiB', '0B', '2KiBxxx', '9223372036854775808B'):
            with self.assertRaises(argparse.ArgumentTypeError, msg=text):
                h.size_bytes(text)

    def test_short_read_and_interrupted_read(self):
        with patch.object(os, 'pread', side_effect=[InterruptedError(), b'ab', b'c']):
            self.assertEqual(h.read_exact(9, 3, 0), b'abc')
        with patch.object(os, 'pread', return_value=b''):
            with self.assertRaises(h.ResizeError):
                h.read_exact(9, 1, 0)

    def test_short_and_interrupted_write(self):
        writes = []
        def write(fd, data, offset):
            writes.append((bytes(data), offset))
            if len(writes) == 1:
                raise InterruptedError(errno.EINTR, 'test')
            return min(2, len(data))
        with patch.object(os, 'pwrite', side_effect=write):
            h.write_exact(9, b'ABCDE', 17, h.Faults(), 'source.write')
        self.assertEqual([off for _, off in writes], [17, 17, 19, 21])
        with patch.object(os, 'pwrite', return_value=0):
            with self.assertRaises(h.ResizeError):
                h.write_exact(9, b'x', 0, h.Faults(), 'source.write')

    def test_flush_failure_is_not_success(self):
        with patch.object(os, 'fsync', side_effect=OSError(errno.EIO, 'flush')):
            with self.assertRaises(OSError):
                h.sync(9, h.Faults(), 'source.sync')

    def test_record_checksum(self):
        with tempfile.TemporaryFile() as f:
            f.write(h.record(dict(version=1, token='known')))
            f.flush()
            self.assertEqual(h.read_record(f.fileno()), dict(version=1, token='known'))
            f.seek(8)
            f.write(b'X')
            f.flush()
            with self.assertRaises(h.ResizeError):
                h.read_record(f.fileno())

    def test_regular_file_only(self):
        with self.assertRaises(h.ResizeError):
            h.regular_open('/dev/null', os.O_RDONLY)
        with tempfile.TemporaryDirectory() as d:
            original, alias = Path(d) / 'original', Path(d) / 'alias'
            original.write_bytes(b'x')
            os.link(original, alias)
            with self.assertRaises(h.ResizeError):
                h.regular_open(original, os.O_RDONLY)
            alias.unlink()
            alias.symlink_to(original)
            with self.assertRaises(OSError):
                h.regular_open(alias, os.O_RDONLY)

    def test_journal_space_is_checked_before_creation(self):
        from collections import namedtuple
        Usage = namedtuple('Usage', 'total used free')
        with tempfile.TemporaryDirectory() as d:
            image = type('Image', (), {'size': 1024})()
            path = Path(d) / 'journal'
            with patch.object(h.shutil, 'disk_usage', return_value=Usage(100, 99, 1)):
                with self.assertRaises(h.ResizeError):
                    h.Journal(path, image, h.Faults(), create=True)
            self.assertFalse(path.exists())

    def test_trace_cannot_overwrite_an_existing_image(self):
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / 'image'
            image.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                h.Faults(trace=image)
            self.assertEqual(image.read_bytes(), b'original')

    def test_journal_close_reports_errors_and_closes_both_descriptors(self):
        journal = h.Journal.__new__(h.Journal)
        journal.backup, journal.dirfd = 7, 8
        with patch.object(os, 'close', side_effect=[OSError(errno.EIO, 'close'), None]) as close:
            with self.assertRaises(OSError):
                journal.close()
        self.assertEqual(close.call_count, 2)
        self.assertIsNone(journal.backup)
        self.assertIsNone(journal.dirfd)

    def test_undo_refuses_a_published_commit(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryFile() as backup, tempfile.TemporaryFile() as target:
            old, new = b'O' * 512, b'N' * 512
            backup.write(old)
            target.write(new)
            backup.flush()
            target.flush()
            (Path(d) / 'commit').write_bytes(b'present')
            journal = h.Journal.__new__(h.Journal)
            journal.dirfd = os.open(d, os.O_DIRECTORY)
            journal.backup = backup.fileno()
            journal.image = type('Image', (), {'fd': target.fileno(), 'size': 512})()
            journal.meta = {'sha256': hashlib.sha256(old).hexdigest()}
            journal.faults = h.Faults()
            try:
                with self.assertRaisesRegex(h.ResizeError, 'commit record'):
                    journal.restore()
                self.assertEqual(os.pread(target.fileno(), 512, 0), new)
            finally:
                os.close(journal.dirfd)

    def test_write_gate(self):
        engine = h.Engine.__new__(h.Engine)
        engine.active = False
        engine.error = None
        self.assertEqual(engine.write(None, 0, 1, 0), 1)
        self.assertIn('without active journal', engine.error)


if __name__ == '__main__':
    unittest.main()
