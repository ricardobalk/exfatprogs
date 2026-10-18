# ADR 003: Allocation movement and preserved semantics

Status: Implemented for experimental review.

Reuse the validated C allocation model. Do not add a competing defragmenter.
Every allocation must have a recognized owner or a valid bad-cluster marker.
Reject cycles, cross-links, references to free bits, and ownerless allocated
clusters. Reject unknown allocation semantics. Never infer that an unknown
allocation is free.

Shrink retains valid fragmentation. It moves only tail allocations. It visits
affected chains in reverse logical order. It first reserves and copies a target,
then publishes its predecessor or owner, then releases the old allocation.
Publication can update file streams, directory streams, root, bitmap, or upcase.
A contiguous stream can receive a complete FAT chain before its NoFatChain flag
is cleared. Grow uses a bijection for cluster renumbering and changes only
necessary data locations.

Keep names, paths, file types, attributes, timestamp bytes and UTC offsets,
lengths, ValidDataLength, volume label, serial number, and upcase bytes. Start
clusters, FAT links, bitmap content/location/length, root location, geometry,
PercentInUse, dirty flags, and dependent checksums can change as required.
Do not treat these changed fields as unvalidated: the independent reader checks
their new bounds, ownership, chains, flags, checksums, and boot agreement.

The engine's publication checkpoints are useful for cancellation. They are not
a crash transaction by themselves. The external undo log remains authoritative
until the host publishes its own durable commit record.
