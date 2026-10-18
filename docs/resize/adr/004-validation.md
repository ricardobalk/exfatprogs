# ADR 004: Independent validation and evidence

Status: Implemented; the specified driver suite passed in a VM. Other release
qualification remains open. See [qualification](../qualification.md).

Use three views: an external byte/namespace model, the C exfatprogs checker, and
a Python on-disk reader. The reader does not import the resize parser or call
its API. It checks boot copies and checksums, geometry, FAT and bitmap ownership,
cycles, chains, entry checksums, name hashes, system streams, metadata, and bytes.
The serializer shares reader geometry and checksum helpers. Record this shared
code. Do not call those two views completely independent.

Run randomized dictionary workloads outside the image. Serialize their final
state into a real image. Call these model/fixture tests. Do not count their
iterations as Linux file calls or physical writes. Save deterministic seeds,
parameters, action hashes, image hashes, measured tail placement, and outcomes.
Use a separate privileged suite for actual Linux-driver file operations.

The existing checker assumed contiguous bitmap and upcase streams. Add checked
FAT traversal for reads and bitmap repair writes. Add FAT links when repair
creates an upcase stream. Keep counterexamples that fail with the exact baseline
binary and pass with the new checker. Run all existing fsck cases with direct
exit-status capture. Run ASan, UBSan, and LeakSanitizer on native test suites and
the changed checker.

Each fault trace records the actual reached I/O boundary and injected mode.
Test all write and durability positions in the selected small grow/shrink
fixtures. Also interrupt rollback. A planned but unreached fault is a failure.
Physical power loss needs a separate model and is not claimed.
