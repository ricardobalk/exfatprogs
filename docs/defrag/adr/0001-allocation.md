# ADR 0001: Allocation and writeback invariants

**Decision:** Use one virtual node for each nonempty allocation. Verify exclusive
cluster ownership before the first move. Complete system-file moves first. Write
the new FAT before code follows a new directory chain.

Status: implemented locally; not accepted upstream.

A virtual node represents exactly one nonempty allocation. The root occurs one
time. An empty stream or empty vendor allocation does not consume a node. The
read and write passes use the same directory order. A different move order must
not change the index order.

Before a move, each physical cluster must have exactly one declared owner. The
checks verify ranges, lengths, cycles, cross-links, active entries, and the
bitmap. This first scope rejects unknown allocations and bad clusters. It never
uses them as free destinations. NoFatChain makes the related FAT fields invalid.
Thus, stale FAT content for a NoFatChain file is not an owner or a bad-cluster
record.

The worker makes the bitmap and upcase chains contiguous first. It completes
these moves after a cancellation request. It can then stop between normal
swaps. Metadata writeback calculates NoFatChain from the current chain. The root
always uses the FAT. The worker writes the new FAT before the iterator follows
new directory chains. It calculates each entry checksum after the last entry
change. It changes only the four-byte root field in each boot sector. It updates
checksum sectors with the logical sector size.

This order does not protect against a crash between writes. ADR 0002 defines
that protection. The interface does not claim that an intermediate state is
valid after a worker error. It keeps the journal active. Success requires an
independent content and metadata comparison and zero remaining discontinuities.

Rejected alternative: use an index boundary such as `interrupt_point` as proof
of contiguity. A swap can change a future chain. Therefore, a processing boundary
does not prove the current physical links of that chain.
