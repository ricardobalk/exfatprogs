# ADR 0003: Copy, validate, and publish

**Decision:** Keep the source read-only. Defragment a private candidate. Publish
the candidate with an atomic no-replace hard link only after independent
validation.

Status: implemented locally; not accepted upstream.

The workflow opens the source with O_RDONLY and without symbolic-link following.
It gets a shared advisory lock and checks for loop attachments. The open file
descriptor pins the inode. The workflow accepts only a regular image file in the
host support matrix. An active transaction marker blocks the operation.

The workflow makes a private temporary directory with mode 0700 in the output
parent. The candidate has mode 0600. It copies all source bytes, handles short
I/O, and flushes the candidate. It then checks size, mtime, and ctime. The
journal interface modifies only this copy.

The independent reader and fsck verify the candidate. Content and metadata must
be equal. Fragmentation must be zero. Before publication, the workflow hashes
the complete source again.

Publication uses `link(candidate, output)`. On one file system, this creates the
name atomically and never replaces an existing output. This is also true during
a race. The workflow then flushes the output directory. After it removes the
private directory, it flushes the output directory again. The published file
keeps mode 0600.

Before the link, an error gives no public output. A kill can leave private
files. After the link, a failed directory fsync can leave a visible and valid
file without confirmed durability. Status 4 reports this condition. A kill at
this boundary can also leave a visible file. Thus, the workflow guarantees an
unchanged source and only valid visible candidates. It does not guarantee that
all failures leave no output. Cleanup never removes a published output.

Separate tests cover process kills, candidate corruption, worker errors,
ENOSPC, wrapper reads and writes, publication, and directory flush boundaries.
A parent kill can leave work active only on the private candidate. No wrapper
then exists to publish it. This workflow does not replace ADR 0002.
