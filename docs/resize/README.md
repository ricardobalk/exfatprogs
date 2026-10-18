# Offline image resize

**This is an experimental image-only implementation. Grow, shrink, and undo
recovery are implemented. Physical power-loss qualification is incomplete.
Direct devices are disabled. Do not use this version on user data.**

## Purpose and scope

`resize.exfat` changes the length of one existing exFAT filesystem in a regular
Linux image file. It preserves the container length. It does not format the
volume, change cluster size, or change a partition table.

The implementation uses the C engine from `huven/exfat-resize`. The MIT license
and source identity are in `resize/vendor/`. The new Python 3 host supplies an
external undo journal. The engine writes the original image through guarded I/O
callbacks. It does not create and rename a replacement filesystem image.

The public interface is the CLI. `image_resize.py`, `bridge.c`, and the shared
library ABI are private. The portable engine header describes a lower-level C
API. That API alone has no durable recovery protocol. The build does not install
it as a public development library. Do not bypass the transaction host.

See [sources](sources.md), [requirements](requirements.md), and
[qualification](qualification.md). All new instructions use short, direct
technical English with ASD-STE100 as the writing guide. No formal STE conformity
review or certification is claimed. Imported upstream documents keep their
original text and scope.

## Build

The default exfatprogs build does not enable this experimental component. This
keeps the existing static and cross-build workflows separate from the Linux
Python host.

On Debian or Ubuntu, install the normal build tools and the test dependencies:

```sh
sudo apt-get update
sudo apt-get install -y build-essential autoconf automake libtool pkgconf \
    libblkid-dev python3 xxd
./autogen.sh
./configure --enable-tests --enable-experimental-resize
make -j2
```

Python 3.9 or later and shared libraries are required for the CLI. The
qualification runners need Python 3.11 or later. Each report records its Python
version.
The host uses only the Python standard library. `fsck.exfat` is a required runtime dependency. A source
build selects the checker in the same checkout. An installed command selects
`fsck.exfat` from `PATH`. `EXFAT_RESIZE_FSCK` can select a specific checker.
`RESIZE_LIBRARY` can select a private shared library for tests.

Each cloud task already has an isolated checkout. Use that checkout. Do not
create a Git worktree unless the user requests one.

## Interface

Use an unsigned integer with one exact suffix: `B`, `KiB`, `MiB`, `GiB`, or
`TiB`. `1MiB` means 1,048,576 bytes. `1M`, `1MB`, fractions, signs, and missing
suffixes are invalid. The maximum input is `INT64_MAX` bytes. The command rounds
down to a whole filesystem sector. It retains cluster size. Heap capacity uses
whole clusters; less than one cluster can remain at the end of the volume.

A writing request needs an image path, a size, and a new journal directory.
A smaller rounded size means shrink. A larger size means grow. An equal size
performs full preflight and returns a no-op. It does not create a journal.
The 64-byte MBR-entry area at boot-sector offsets 446–509 must be zero. This
conservative rule also rejects custom boot code in that area. It prevents an
MBR hybrid from passing as a plain volume image. The minimum volume length is
1 MiB. Metadata, bad clusters, and live allocations can require a larger minimum. Use dry-run to test a specific target.

These commands use only a disposable image that you create:

```sh
mkdir -p /tmp/resize-trial
truncate -s 8MiB /tmp/resize-trial/volume.img
./mkfs/mkfs.exfat -L TRIAL /tmp/resize-trial/volume.img
./resize/resize.exfat /tmp/resize-trial/volume.img --info
./resize/resize.exfat /tmp/resize-trial/volume.img --size 6MiB --dry-run
```

Dry-run validates the complete source allocation graph. Its JSON output gives
the rounded target, cluster size, FAT size, heap offset, journal space, and move
estimate. A shrink move count is exact. A grow move count is an upper bound for
the displaced prefix and can include free clusters. `used_clusters` describes
the source allocation model for shrink and the planned target model for grow.
It is not a final free-space promise.

Prepare sufficient backing storage before grow:

```sh
truncate -s 16MiB /tmp/resize-trial/volume.img
./resize/resize.exfat /tmp/resize-trial/volume.img --size 16MiB \
    --journal /tmp/resize-trial/grow-journal
./fsck/fsck.exfat -n /tmp/resize-trial/volume.img
```

Keep the full backing file until shrink and journal cleanup finish:

```sh
./resize/resize.exfat /tmp/resize-trial/volume.img --size 6MiB \
    --journal /tmp/resize-trial/shrink-journal
./fsck/fsck.exfat -n /tmp/resize-trial/volume.img
```

The command does not truncate the file. A later, separate container change is
outside this transaction. Never truncate an image with an active transaction.

`source_bytes_written` counts bytes accepted by source `pwrite` calls. It includes
repeated metadata writes. It excludes journal writes and reads. It is not a
measurement of physical storage writes. The undo journal writes a complete copy
of the backing file even when the relocation plan is small.

## Support matrix

| Structure or interface | Current behavior |
| --- | --- |
| Regular Linux image, one volume at byte zero | Supported; one hard link is required |
| Symlink, partitioned disk image, nonzero PartitionOffset, nonzero MBR-entry area | Rejected |
| Direct block or character device | Rejected |
| exFAT revision 1.00, one FAT | Supported |
| Other revision, two FATs, TexFAT | Rejected before image writes |
| Sector sizes 512 through 4096; unchanged cluster size | Engine support; test reports record exercised geometries |
| Empty files, partial final clusters, ValidDataLength | Supported; logical bytes after ValidDataLength are zero |
| FAT chains and NoFatChain streams | Supported; shrink can create a FAT chain |
| Root and multi-cluster directories | Supported; root can move during shrink |
| Allocation bitmap and upcase table | FAT chains are retained or rebuilt as required |
| Volume label and serial number | Preserved |
| Volume GUID | Engine tests cover it; broad real-image qualification is incomplete |
| Vendor Allocation entries | Rejected; no vendor allocation semantics are assumed |
| Unknown critical or allocated entries | Rejected |
| Known non-allocating benign entries | Engine can preserve them; the host also requires fsck acceptance |
| Bad clusters | Engine preserves retained physical locations; grow rejects FAT conflicts; shrink removes excluded bad markers |
| Dirty, cross-linked, cyclic, or inconsistent source | Rejected; resize does not request repair |

The support matrix describes code behavior. It does not grant device or release
qualification. The host runs `fsck.exfat -n` before mutation and before commit.
The C engine also validates geometry, boot checksums, directory entry sets,
chain lengths, ownership, and bitmap consistency. Both boot regions must pass.

## Locking and free space

The host holds a nonblocking exclusive advisory file lock for a write or
recovery. Read-only requests hold a shared lock. It rejects known visible Linux
loop attachments. A loop in another namespace can name a path that this process
cannot inspect. There is also a race with a new attachment. Advisory locks do
not stop processes that ignore locks. The operator must prevent all other use.
Do not mount or attach the image during a transaction.

The journal parent must exist. The new journal uses mode 0700. Its files use mode
0600. It needs free space for the complete backing file plus at least 1 MiB.
The source filesystem can also need space to allocate previously sparse regions.
An ENOSPC error can require more free space before recovery can proceed.
The target filesystem must support the `user.exfatprogs.resize` xattr.
The journal contains original file bytes. Protect it as private data.

## Recovery

The journal stores the original container bytes, their SHA-256, a format version,
file identity, and a random transaction ID. An image xattr binds that ID to the
open file. The preimage, manifest, journal directory, and parent directory are
synchronized before the token is synchronized. Source-byte writes cannot pass
the callback gate before this sequence completes.

After resize and checker validation, the host synchronizes the image. It then
publishes a checksummed commit record with the complete result hash. The commit
record and directory must be synchronized before normal success is reported.
A valid record selects the new state. Without that record, recovery restores
the complete old container. A corrupt record never authorizes a write.

After a crash or I/O error, retain the original file inode, original length, and
journal directory. Stop all other access. Run:

```sh
./resize/resize.exfat /tmp/resize-trial/volume.img --recover \
    --journal /tmp/resize-trial/grow-journal
./fsck/fsck.exfat -n /tmp/resize-trial/volume.img
```

Recovery validates the full preimage before it writes. Rollback starts again at
byte zero. It can repeat after an interrupted recovery. A valid commit record
requires the complete current-image hash to match. Missing, corrupt, wrong, or
stale recovery data causes a stop without recovery writes. Do not remove the
image token to bypass this stop. Do not create a replacement journal by guess.

Cleanup removes and synchronizes the image token before it deletes the journal.
A remaining journal without a matching token is stale. It cannot authorize
replay. After such a cleanup error, check the image with both validators. Then
remove only the stale private journal. A journal made before token activation
can also remain after failure; it does not authorize replay.

SIGINT and SIGTERM request cancellation. The host waits for the C call to leave
its safe checkpoint. The last host checkpoint is after the C call and before
final validation. Cancellation observed there restores and synchronizes the full
old image. Further cancellation does not stop that rollback. A rollback error
leaves an active journal and requires recovery.

The final validation, synchronization, and journal commit form one batch. Later
signals are deferred through that batch. Success can therefore return the new
committed state after a late cancellation request. I/O errors take precedence
over a pending signal and retain the journal. Never undo under an existing
commit record. Use recovery to select the valid old or new state. A hard kill
requires the same recovery command.

| Exit | Meaning |
| --- | --- |
| 0 | Commit, validated plan, no-op, or successful recovery |
| 1 | Rejected input or stopped operation without an active transaction |
| 2 | Invalid CLI syntax |
| 3 | Recovery or retained recovery files require attention |
| 4 | New state committed; cleanup or close failed |
| 130 | Handled cancellation; read the reported recovery state |

## Guarantee and limits

The tested failure model is process termination with retained kernel/storage
state. It assumes successful fsync calls are honored and same-directory rename
is atomic. Short writes can change only part of a requested source range. A
verified full undo log remains available for rollback. Persistent storage errors
must be corrected before recovery can finish. This protocol cannot restore bytes
from irrecoverably failed storage.

SIGKILL does not simulate loss of volatile disk caches. This version makes no
physical power-loss claim. It has no model for arbitrary torn journal records,
reordered device caches, or storage that lies about fsync completion. Corrupt
recovery data causes a stop. A hostile user who can change both the image and
journal is outside the integrity model.

The Linux-driver suite checks grow, shrink, content, metadata, target geometry,
fsck, read-only mounts, and use of added capacity. The larger-image campaign
uses 128 MiB sources and targets of 80 or 192 MiB; it samples reached fault
scenarios and does not represent hardware testing. Direct devices remain
disabled. Broad vendor-layout, very-large-image, storage-exhaustion, and
hardware qualification remain open. See [qualification](qualification.md) for
the commands and generated test reports. Do not use a PASS from an older source
revision after a relevant code change.
