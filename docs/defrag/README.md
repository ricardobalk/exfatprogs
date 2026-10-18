# exFAT defragmentation repair and experimental image qualification

**Bottom line:** This branch reproduces and repairs the known allocation and
writeback defects. It adds strict checks, a durable external undo journal, and
verified recovery for Linux image files. A separate copy workflow publishes a
result only after independent validation. **Release status: the function works
in the specified scope. Use it only with small, disposable, offline image
files. Do not use it directly on user volumes.** The normal autotools build
does not build or install the defragmenter.

Qualification evidence is test output and is not stored in the source tree.
Results in `context/` are historical input, not results from this work. See
[qualification.md](qualification.md) for the test program, artifact layout,
and limits.

This document puts decisions and limits before implementation details. It uses
short sentences and consistent terms in the style of ASD-STE100. It has not
had a formal ASD-STE100 conformance review.

## Scope and basis

The base is exfat-next commit
`1647ed54299ae8c4343a5edf40b892307f7e6459`. The branch is
`fix/exfat-defrag`. The `context/` and `resize/` directories were untracked at
the start of the work. This patch does not include or change them.

[Issue 318](https://github.com/exfatprogs/exfatprogs/issues/318) reports data
loss and discusses delayed metadata writeback. These reports are research
inputs. They do not prove one cause for all reported damage.
[Release 1.3.1](https://github.com/exfatprogs/exfatprogs/releases/tag/1.3.1)
states that upstream removed defrag from the build because of reported data
loss. The local `Makefile.am` and `configure.ac` show that it is still disabled
at the selected base. A separate `git ls-remote` check verified the upstream
master and exfat-next revisions. See [sources.md](sources.md).

The result gives one extent for each supported allocation. This can help a
device that requires contiguous files. This work does not test media-player
firmware. It does not prove that such firmware has a defect.

## Components

- [`defrag/defrag.c`](../../defrag/defrag.c) is the repaired internal C worker.
  It moves clusters and writes allocation metadata. The explicit test build
  builds it. The worker has no journal when you start it directly.
- [`defrag/layout.py`](../../defrag/layout.py) checks the supported layout. It
  compares file content, metadata, boot regions, and allocations. It does not
  use the C parser.
- [`defrag/image_defrag.py`](../../defrag/image_defrag.py) and
  [`defrag/defrag.exfat`](../../defrag/defrag.exfat) provide the experimental
  Linux image-file interface. This interface controls the lock, journal,
  commit, and recovery sequence.
- [`tests/defrag/image.py`](../../tests/defrag/image.py) contains the independent
  on-disk reader and the model generator. It does not import the production
  parser or the C virtual mapping.
- [`tests/defrag/defrag_image.py`](../../tests/defrag/defrag_image.py) opens the
  source read-only. It makes a private candidate, defragments it with a journal,
  validates it independently, and publishes it without replacing an output.

The C worker is an internal experimental component. Its write order is not a
crash-recovery protocol. The image-file interface applies the recovery protocol
to the complete operation.

## Confirmed defects and repairs

| Investigation item | Finding at the base | Repair and focused test |
| --- | --- | --- |
| An empty vendor allocation changes the virtual index | The read pass skipped it, but the write pass consumed it | Apply the same selection in both passes; `empty-vendor-index` |
| The worker calculates a vendor checksum before it changes the start cluster and flags | Confirmed | Calculate the checksum after the last entry change; `vendor-checksum` |
| The worker marks an incomplete chain as contiguous | Confirmed during cancellation | Derive NoFatChain from the current links; always use FAT links for the root; `interrupted-directory-fat` |
| A system allocation can move only in part | The original order can leave an inconsistent state | Complete bitmap and upcase moves first; keep the virtual index order; `partial-system-relocation` |
| Directory writeback follows new directory chains too early | Confirmed in the interruption reproducer | Write the new FAT before directory traversal; handle root semantics separately |
| The worker does not handle flush and I/O errors correctly | It ignored a directory flush and fsync result; it did not retry EINTR | Return flush errors, check fsync, and retry EINTR; `directory-flush`, `fsync-status`, `eintr-read` |
| The worker has boot-sector, endian, and boundary defects | A 4096-byte sector reproducer confirms the wrong checksum and backup offset | Write only the root field; use logical-sector geometry; correct endian conversions; use `size_t` before multiplication; `logical-boot-sector` |
| The worker does not verify all allocation owners | It accepts an allocation with no owner | Check owners, cycles, and cross-links before swaps; run strict host checks; `unowned-allocation` and the negative matrix |

Some findings share one historical reproducer. The FAT order and the wrong
contiguous-chain assumption use the same reproducer. The endian repairs and
the wider calculations also use code inspection. No big-endian hardware test
was run.

The baseline build gets all related C sources and headers from the pinned base.
It makes one compatibility change. It adds the missing zero-offset argument to
the old `exfat_write_checksum_sector` call. It does not link repaired shared
sources. `build.py --baseline` saves the source copy and `baseline.json`.

## Support matrix

| Structure or condition | Experimental image-file interface |
| --- | --- |
| Linux regular file, one hard link, no symbolic link | Supported; an open file descriptor pins the inode |
| Volume starts at byte zero, PartitionOffset is zero, container size equals volume size | Supported |
| Image file is larger than 256 MiB, or contains a partition table | Rejected before writes |
| exFAT revision 1.00 with one FAT | Supported |
| Two FATs, TexFAT, or dirty, media-failure, or reserved flags | Rejected before writes |
| FAT chains and NoFatChain files, including stale FAT values for NoFatChain | Supported |
| Root, nested directories, and fragmented directories | Supported to depth 128; the root always uses the FAT |
| Empty files, partial last clusters, and valid data length (VDL) | Supported; logical bytes after VDL are zero |
| Unicode and multiple name entries | Supported with UTF-16 and the stored upcase table; no Unicode normalization |
| Allocation bitmap and upcase table | Initially, each must be contiguous with a complete FAT chain; both are defragmented |
| Label, serial number, attributes, times, and UTC offsets | Preserved; boot regions and normalized entry sets are compared |
| Volume GUID entry, vendor extension entry, TexFAT padding, or unknown active entry | Rejected before writes |
| Empty E1 vendor allocation with a nonzero GUID | Supported; it must have no allocation and no NoFatChain flag |
| Populated E1 vendor allocation | Only the private fixture GUID with bytes `00 01 ... 0f`; its opaque payload must contain no physical references |
| Arbitrary commercial vendor GUID with a payload | Rejected; internal cluster references can have an unknown format |
| Bad cluster or unexplained bitmap allocation | Rejected before writes; the record and complete source stay unchanged |
| Full volume or one free cluster | Supported; swaps do not need a free volume cluster; the external journal still needs space |
| Volume has no fragmentation | No operation; no journal, marker, or file-system write |
| Block device or loop-attached image file | Rejected, including read-only analysis |

The private vendor GUID is only a qualification contract. It does not give
support for all vendor formats. The interface does not defragment a volume that
has bad clusters. This is a limit of REQ-F03.

A supported layout without bad clusters has the same allocation size before
and after the operation. The worker can place all chains contiguously, including
on a full image file. The interface commits only if the new reader reports zero
discontinuities. It has no partial-success state. Cancellation restores the old
state. An I/O error requires recovery.

## Fragmentation and preservation rules

For a nonempty chain `c[0..n-1]`, a discontinuity is an index `i` for which
`c[i+1] != c[i]+1`. The extent count is one plus the discontinuity count. An
empty chain has zero extents. The report counts each allocation separately. It
includes files, directories, vendor streams, and system streams. Free space
between two files is not file fragmentation.

The external workload stores file paths and expected bytes. Before defrag, the
independent reader compares the serialized fixture with that model. After
defrag, it compares content hashes, file types, and entry metadata. VDL does not
change. Storage bytes after VDL can exist, but they are not logical file data.
The operation does not expose them by increasing VDL.

Start clusters, FAT links, the bitmap, NoFatChain flags, and dependent checksums
can change. The validator still checks their range, length, ownership, bitmap
coverage, chain semantics, and checksums before and after the operation. The
boot comparison masks only root pointers and checksum sectors. The reader
validates these masked fields separately. All other boot bytes remain equal.
The entry comparison masks only allocation pointers, NoFatChain, and its
dependent checksum. A second interface run must leave every image byte equal.

## Build and smoke test

Required tools are Linux, Python 3.11 or later, a C compiler, libc headers,
libblkid headers and library, GNU tar, xz, xxd, and the normal autotools tools.
The host file system must support advisory flock, user xattrs, fsync, and hard
links. Store the journal outside the volume that you defragment. Driver tests
also need root or CAP_SYS_ADMIN, the Linux exFAT driver, mount, umount, and
losetup.

Run these commands from the repository root:

```sh
python3 tests/defrag/build.py --baseline
python3 tests/defrag/qualify.py --out defrag-test-results-smoke
```

The smoke test builds explicit test binaries. It reproduces the baseline
defects. It then runs the repaired regressions, negative checks, and three model
seeds. It does not install a program or change the normal build.

The `Experimental defrag qualification` GitHub Actions workflow runs smoke
tests with GCC and Clang. It also runs focused ASan and UBSan tests. A weekly or
manual full job runs the complete rootless program. A separate manual job runs
the privileged Linux-driver workloads on disposable loop images. Each job
uploads its logs and JSON results.

## Analysis, operation, recovery, and copy workflow

Use only disposable image files that you created for this purpose.

```sh
# Analyze without writes. Print discontinuities, extents, feasibility, and limits as JSON.
./defrag/defrag.exfat --dry-run /tmp/test-volume.img

# Use a new journal directory. Do not reuse an existing directory.
./defrag/defrag.exfat /tmp/test-volume.img --journal /tmp/test-defrag-journal

# After status 3 or a kill, use the same inode and the original journal.
./defrag/defrag.exfat /tmp/test-volume.img --recover --journal /tmp/test-defrag-journal

# Keep the source read-only. The output path must not exist.
python3 tests/defrag/defrag_image.py \
  --defrag build-defrag-tests/defrag.exfat \
  --fsck build-defrag-tests/fsck.exfat \
  /tmp/source.img /tmp/defragmented.img
```

The journal interface needs free space for one complete image copy plus 1 MiB.
The copy workflow also needs space for its candidate. A journal is a private
directory with mode 0700. Journal files have mode 0600, one hard link, and the
current owner. The interface rejects symbolic links. See
[ADR 0002](adr/0002-recovery.md) for the protocol.

| Exit status | Meaning |
| --- | --- |
| 0 | Analysis, no operation, verified commit, or completed recovery |
| 1 | The interface stopped before an active transaction; the copy workflow did not publish a candidate |
| 2 | Invalid command-line arguments |
| 3 | Active or unreadable transaction state; keep the recovery data and run recovery |
| 4 | A commit or publication occurred, but cleanup or durability confirmation is incomplete; a result can be visible |
| 130 or 143 | SIGINT or SIGTERM; the report identifies the old state after rollback or the new state after cancellation during the commit batch |

Recovery can return status 3 again after a new error. Keep the same undo data.
After durable marker removal, remaining journal files are stale. Recovery
rejects them without a write. A successful cleanup removes the journal.

The signal handler only records the signal. Normal control waits for the C
worker and restores the source when necessary. On Linux, the worker receives
SIGKILL if its parent dies. It also inherits the lock file descriptor. Thus, a
failed host does not leave a worker that can race with recovery. Tests cover
this sequence. During undo, the host delays a second cancellation until it has
restored the old state. An I/O error has priority over cancellation status.

Locks are advisory. The interface rejects visible loop attachments. It cannot
reliably detect another mount namespace or a process that ignores locks. Keep
the image offline and under exclusive control.

## Full qualification and replay

```sh
# Run native tests, ASan/UBSan tests, upstream tests, and driver tests.
python3 tests/defrag/qualify.py --full --driver --jobs 4 \
  --out defrag-test-results-full

# Replay one model seed. The seed selects the same geometry and vendor variant.
python3 tests/defrag/run.py --cases 1 --start-seed 73 --operations 5000 \
  --out defrag-test-results-replay-73

# Test all mutation boundaries of the small fixture and interrupted recovery.
python3 tests/defrag/faults.py --out defrag-test-results-faults

# Model lost, reordered, and torn writes separately from process kills.
python3 tests/defrag/persistence.py --out defrag-test-results-persistence

# Run only the real driver test in a private mount namespace.
sudo python3 tests/defrag/mounted.py --seeds 10 --operations 5000 \
  --out defrag-test-results-driver
```

Use a new output directory for each command. Use `--build` to select a different
explicit build directory. Reports record seeds, geometry, iterations, effective
model changes, real workload system calls, fragmentation, fsck status, and fault
positions. The complete qualifier also writes `manifest.json` with a SHA-256
digest for each other regular output file. Model iterations are not Linux
file-system operations. The driver count includes explicit `os.*` workload
calls. It does not include runtime, inspection, or remount calls.

A failed test keeps private image files, journals, operation logs, expected
manifests, and logs. A successful rootless seed removes large temporary files
and keeps its case record. Fault tests record planned and reached positions. A
test fails if it does not reach its target. Fault interposition applies only to
the explicitly started C test worker.

`minimize.py --seed N --operations M --match 'exact error text' --out ...`
tries shorter workload prefixes with the same seed and required diagnostic. It
is a heuristic tool. The qualification program does not claim a global minimum
or an executed reduction.

## Evidence limits

Recovery does not cover loss or corruption of both the image and the durable
journal. It does not cover a device that reports a false flush result, arbitrary
torn host metadata, malicious concurrent writers, or hardware damage. The
persistence model is separate from a real device power-loss test. See
[ADR 0002](adr/0002-recovery.md) and [ADR 0004](adr/0004-release.md) for the
release blockers.
