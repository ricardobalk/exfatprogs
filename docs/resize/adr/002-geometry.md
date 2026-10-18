# ADR 002: Geometry and container boundary

Status: Implemented for experimental review.

Use one volume at byte zero with PartitionOffset zero. Require a zero MBR-entry
boot-code area. A valid volume signature alone does not exclude an MBR hybrid. Reject direct devices,
partitioned images, multiple FATs, and unsupported revisions. Keep the original
container length, file inode, sector size, and cluster size. Require an explicit
size. Round only to a filesystem sector. Compute usable clusters from the heap.

Grow uses the engine's monotone geometry search. It expands the FAT when needed.
If the FAT enters the source heap, move the heap by whole clusters. Map every
source cluster number to the new geometry. Rotate displaced prefix allocations
into retained target coordinates. Rebuild FAT, bitmap, directory starts, root,
both boot regions, and dependent checksums. Place the replacement bitmap in new
space. Reject a bad-cluster conflict or insufficient bitmap space before writes.

Shrink keeps the heap offset. It uses free retained clusters to evacuate live
clusters past the new boundary. The entire source bitmap must fit during the
move phase. A smaller final bitmap is not sufficient temporary space by itself.
The final commit reduces FAT length, bitmap length, cluster count, and volume
length. No source reference can remain outside the retained geometry.

The same preparation functions serve read-only planning and mutation. The new
`exfat_resize_inspect` API returns after full preflight. It never invokes write
or sync callbacks. It supports equal-size inspection without changing the
existing engine's equal-size resize contract.
