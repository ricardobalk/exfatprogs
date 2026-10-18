# ADR 001: Image resize and undo recovery

Status: Implemented for experimental review. No upstream acceptance is implied.

## Decision

Use the C11 engine from huven/exfat-resize at commit
870ca5a66591405cd536556b1114d045c94cefff. Keep its MIT license. Add one
`resize.exfat` interface to exfatprogs. Do not import its device or partition CLI.
Use a Python 3 transaction host and a private shared C library. The C engine
changes the source image in place through host I/O callbacks. It does not format
or replace the image. The host supplies locks, an undo journal, and recovery.

Support regular volume images only. Reject block devices and attached loop
images. Do not change the container length or partition table. Keep cluster size.

Growth can expand the FAT and move the heap by whole clusters. The engine maps
all live references, moves the displaced heap prefix, and creates a new bitmap
in added space. Shrink moves live tail clusters into free retained clusters.
It can convert a contiguous stream to a FAT chain. It retains the full old
bitmap until the final geometry change. Thus a tight target can fail even when
the final bitmap would fit. The dry-run must use the same full preflight.

## Durable invariants

Before the first source-byte write, store the complete original container in a
new private journal directory. Store its SHA-256, file identity, size, a random
transaction ID, and format version in a checksummed manifest. Flush both files,
the journal directory, and its parent. Bind the transaction ID to an image xattr
and flush the image. Refuse filesystems that cannot retain this xattr.

A complete preimage is an undo log for all source writes, including metadata,
relocation destinations, and unused backing bytes. It is not a disposable output
candidate. No source writes can pass the callback gate before journal activation.
The journal requires free space at least equal to the entire container size plus
metadata. It contains private file bytes. Use mode 0700 and files with mode 0600.

After successful engine synchronization, hash the complete result. Publish a
checksummed commit record by atomic rename and directory synchronization. Only
then report a committed transaction. A valid commit record selects the new
state. Without a commit record, recovery restores the complete old bytes and
flushes them before it removes the image token. Recovery must validate the
complete journal, its hash, file identity, and token before its first write.
Each recovery attempt starts at byte zero. An interrupted rollback can repeat.
A corrupt, wrong, stale, or missing journal must cause a stop without writes.
Cleanup removes the token before it deletes journal files. A leftover journal
without a matching token is stale and cannot authorize writes.

## Failure model

The first qualification target is process termination on storage that honors
successful fsync calls and atomic same-directory rename. Source writes can be
partial. An I/O error retains the journal and requires explicit recovery. A
failed source flush cannot commit. The host takes its last cancellation checkpoint after the engine returns. An
observed cancellation requests rollback before final validation begins. Defer
later signals through validation and commit. If rollback fails, report recovery
required. I/O errors take precedence over a pending signal. Never start undo
under a published commit record; retain the journal for state selection. Ignore further cancellation during
rollback, but preserve the non-success result. A kill during rollback leaves the
same journal active. A kill after durable commit recovers the new state.

Do not claim physical power-loss protection. Cache loss, torn journal metadata,
and storage that lies about flush completion need a separate persistent-storage
model and qualification. Corrupt journal records fail closed. SHA-256 detects
accidental corruption, not a malicious user who can change both journal and image.

Advisory locks and Linux loop checks do not exclude a writer that ignores locks,
a privileged writer, or a loop attachment race. The operator must prevent all
other access. This limit is part of the interface contract.

## Independent validation and release

Use exfatprogs fsck and a separately implemented Python on-disk reader. Do not
call the C resize parser from that reader. Compare logical bytes, namespace,
attributes, timestamps, valid-data-length, label, identity, and allocation rules.
Record fixture-model work separately from Linux-driver calls. Keep direct device
access disabled. Release remains experimental until the required 1,000 x 5,000
model workload and 10 x 5,000 driver workload, fault matrix, and regressions pass.


## Commit marker and cancellation invariant

A cancelled engine result and the last host checkpoint can request undo only
before the final validation/commit batch. A signal during that batch is deferred.
An I/O failure must retain its error and journal even when a signal is pending.
`Journal.restore` also refuses any existing commit marker before its first write.
A commit flush can fail after rename. Recovery can then select the valid new
image. It must never start an old-state copy under that new-state marker.
The compound regression interrupts the old unsafe copy after one completed
restore write; the old code cannot recover that mixture. The corrected code
performs no undo and recovers the complete new state.
