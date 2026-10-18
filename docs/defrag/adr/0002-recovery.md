# ADR 0002: External full-image undo journal

**Decision:** Before the first image write, store and flush one complete
preimage in an external journal. Bind the journal to the host inode and a random
transaction token. After an interruption, select the old or new state only from
verified durable records.

Status: implemented locally and tested with the specified model. It has no
upstream acceptance or block-device qualification.

## Scope and identity

A complete preimage is easier to verify than a new cluster-level journal for
small offline image files. It needs approximately one image of additional
storage. It also makes recovery independent from damaged file-system metadata.
The host accepts Linux regular files up to 256 MiB. This decision makes no
performance or scale claim for physical media.

Format version 1 uses `preimage`, `manifest`, optional `commit.tmp`, and
`commit`. The manifest and commit are canonical ASCII JSON records. Each record
has a SHA-256 digest of its payload. The manifest binds these values to a random
128-bit token:

- host device and inode;
- host file size;
- original volume serial number;
- complete preimage SHA-256 digest.

The image inode also stores the token in the `user.exfatprogs.defrag` xattr. The
journal directory has mode 0700. Its files have mode 0600, the current owner,
and one hard link. The host opens all files and directories without following a
symbolic link.

A copied image has a different inode. An old journal has a different or missing
token. Recovery rejects both conditions. Before recovery starts, it verifies all
records and the complete preimage, including the stored serial number. The live
boot sector can be torn. Thus, it is not an identity requirement for recovery.
If recovery data is missing or unreliable, the host stops. It does not guess.

## Durable sequence

1. Open the image and acquire an exclusive advisory lock. Reject loop
   attachments. Run the layout checks and fsck without writes. Do not make a
   marker or journal for a rejected image.
2. Make a new journal directory. Write the complete preimage. Handle short I/O
   and EINTR. Run fsync on the preimage. Write and flush the manifest.
3. Run fsync on the journal directory and its parent. This makes the recovery
   data and names durable.
4. Add a unique token to the image. Run fsync on the image. Start the worker only
   after this operation succeeds.
5. Let the worker do destructive swaps and metadata writes. Intermediate states
   do not have to be mountable. While the token is active, only the current host
   or recovery can continue.
6. Wait for the worker. Run strict semantic, allocation, and fsck checks. Run
   fsync on the image. The complete new state is durable before commit.
7. Write the complete new image digest to `commit.tmp`. Flush it. Rename it to
   `commit`. Flush the journal directory. This is the durable commit boundary.
8. Remove the token. Flush the image. Then remove the recovery files, flush the
   journal directory, remove the directory, and flush its parent.

Cancellation before the commit batch restores and flushes the old bytes through
normal control flow. During the commit batch, the host does not restore old
bytes after it can have published a commit record. It confirms a valid new state
or reports status 3 or 4 with recovery data. Status 130 or 143 still identifies
a cancellation request.

## Recovery and repeated interruption

Without `commit`, recovery writes the original bytes from the fully verified
preimage. It flushes, rereads, and hashes the complete image. With `commit`, it
accepts the new state only when the token and complete image digest agree. An
invalid commit is not permission to restore old bytes. Recovery stops and keeps
the data.

Recovery does not change the undo source. A kill or EIO during undo leaves the
active token and the same preimage. A repeated recovery writes the same bytes.
After durable marker removal, the image needs no more recovery. Recovery safely
rejects a stale journal or a journal directory that was already removed. A
repeated command does not have to return a second success.

The worker inherits the flock file descriptor. Linux gives it
`PR_SET_PDEATHSIG=SIGKILL`. The child checks the parent identity after it sets
this option. Recovery can acquire the lock only after the worker closes its file
descriptors. A test stops the worker after a write, kills the host, and verifies
that recovery then completes.

## Storage and failure model

The model makes these assumptions:

- A successful file fsync makes all earlier writes to that file durable.
- A successful directory fsync makes earlier namespace changes durable.
- Image fsync also makes the image xattr durable.
- Durable journal data does not later become corrupt without a reported error.
- Other processes respect locks and offline control.
- SHA-256 detects accidental corruption. It does not authenticate data against
  a malicious user.

Before image fsync, an image write can be lost, reordered, or partly retained.
The replay test uses actual worker writes. It tests each prefix, each half write
after a prefix, reverse orders, and deterministic subsets. Every state before
commit must recover the exact old bytes.

After image fsync and before durable commit, either old or new is permitted. A
valid commit selects new. No commit selects old. After durable commit, the
complete new state is required. Process-kill tests also use real journals,
markers, flush errors, and repeated interruption during recovery.

This model does not prove that every host file system or controller keeps these
assumptions during real power loss. Persistent EIO or ENOSPC can temporarily
block recovery. The guarantee is that recovery can continue after that error is
removed. The model excludes loss of both journal and image, corruption of a
durable journal, host metadata tears outside the model, and flush operations
that incorrectly report success.

Rejected alternative: update metadata after each swap only. Without an atomic
protocol, interruption windows still exist between data, FAT, bitmap, and
directory entries. A copy workflow alone also cannot protect a worker that
writes directly to its source.
