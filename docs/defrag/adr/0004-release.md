# ADR 0004: Release gates and status

**Decision:** Keep the normal build disabled. Give this work experimental status
for small offline Linux image files only. Do not claim qualification for direct
use on volumes.

Status: local release policy; not accepted upstream.

The project uses three separate status levels:

1. **Function repaired in the specified scope.** The pinned baseline fails the
   original corruption regressions. The repaired code passes them. Independent
   tests verify on-disk content, metadata, allocations, and fragmentation.
2. **Experimental use on small offline Linux image files.** The implementation
   has strict support checks, read-only analysis, undo, commit, recovery,
   signals, and copy publication. The current interface has this status after
   the documented local tests pass.
3. **Qualified for direct use on volumes.** This status is not granted. Block
   devices are not implemented. The normal build and installation stay disabled.

Passing local tests is necessary for level 3, but it is not sufficient. These
release gates remain:

- block-device identity and exclusive access;
- recovery on representative storage with real power loss and verified flush
  guarantees;
- large volumes and 64-bit boundaries on real layouts;
- bad-cluster layouts;
- more vendor and system allocation formats;
- other platforms;
- independent review.

TexFAT is not supported. The existing 2-TB sparse upstream fsck fixture does not
qualify the new defrag engine for a 2-TB volume.

NOT_RUN is not PASS. The full qualification runner reports a missing driver test
as NOT_RUN. The related claim stays blocked. See `qualification.md` for measured
counts and machine-readable case records. Historical context counts do not
count as current evidence.

A change to the support matrix, recovery sequence, or writer requires related
tests and a new review of these gates. Enabling only the repaired C worker in a
normal build would bypass the recovery protocol. Do not do this.
