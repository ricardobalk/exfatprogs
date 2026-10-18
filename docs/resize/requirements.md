# Requirements, implementation, and evidence

Status terms: implemented means executable code exists. Partial means a required
case or qualification is still open. NOT_RUN is not PASS. See
[qualification](qualification.md) for current counts and evidence files.

| ID | Implementation | Test and evidence | Status and remaining work |
| --- | --- | --- | --- |
| REQ-F01 | `image_resize.py`: explicit image, exact units, size, info, dry-run, no-op, exit states | `test_host.py`; model cases check overflow, rounding, no-op, and whole-image hashes | Implemented; Linux image interface only |
| REQ-F02 | `Image`, regular-file gate, zero-offset check; no truncate or partition call | Device/symlink/hard-link unit cases; actual none/MBR/GPT container counterexamples; backing length checks after each resize | Implemented; direct-device release is disabled |
| REQ-F03 | C `geometry.c`, `grow.c`, `allocation.c`, `directory.c`, `boot_region.c` | Geometry unit tests; compact-FAT image cases; independent reader; ten Linux-driver grows, each with an 80 MiB capacity probe | Implemented; very large real images remain unqualified |
| REQ-F04 | C `shrink.c`: retained-space check, reverse-chain tail moves, system and owner publication | Shrink C suites; measured tail allocations; shrink after capacity probe; nearly full rejection; ten Linux-driver shrinks with 42–55 moved clusters each | Implemented; broad system-layout qualification remains open |
| REQ-F05 | C stream/entry edits preserve unrelated bytes; Python semantic snapshot | External model byte hashes, metadata snapshots, VDL, label, serial, names, timestamps, flags and checksums; Linux-driver content and metadata checks for twenty resizes | Implemented for tested entries; wide vendor/GUID real-image coverage remains open |
| REQ-F06 | Engine rejects unsupported revision/FAT/allocated entries; ownership reconciliation and bad-cluster handling | API/mechanism/C shrink suites; four real inactive-FAT image cases; explicit support matrix | Partial qualification; vendor allocations are rejected; broad benign/vendor and bad-marker image combinations remain open |
| REQ-F07 | Full C preflight plus read-only fsck; shared planning path; advisory lock and visible-loop check | Whole-image hashes for dry-run and rejected input; unit write gate; corrupt input cases | Implemented; locks and namespace detection cannot enforce universal exclusion |
| REQ-S01 | Complete preimage undo log, integrity records, identity/token binding, durable activation/commit, repeatable recovery | Full small-fixture fault sweep; 160 larger-image scenarios; wrong/stale/corrupt/missing journal; interrupted rollback | Implemented for the stated process/storage model; external journal must remain trustworthy |
| REQ-S02 | Old-state rollback or validated new-state commit; explicit storage assumptions | SIGKILL, EIO, ENOSPC, short transfer, EINTR, flush faults, persistent-error retry | Partial qualification; no physical power-loss/cache-order model or hardware claim |
| REQ-S03 | Signal flag, safe C checkpoints, last host checkpoint before the final batch, guarded undo, exact I/O loops, checked flush and close | Cancellation sweep; actual SIGINT/SIGTERM during copy, mutation, and recovery; combined commit-flush/cancel/crash counterexample; I/O and close-error unit cases | Implemented for the stated checkpoints; broader close failure campaigns remain open |
| REQ-S04 | C engine writes source fd in place under mandatory journal gate | Source-write gate test; crash and rollback tests | Implemented; this is not a disposable-candidate wrapper |
| TEST-01 | C primitive and transaction suites; host tests; checker counterexamples | `run.py`, `test_host.py`, `fsck_regression.py` | Implemented; see exact suite counts and baseline hashes |
| TEST-02 | Seeded six-operation external dictionary workload; real image serialization; repeated resize and capacity writes | `run.py --seeds 1000 --iterations 5000`; per-seed JSON and action logs | Model/fixture qualification; does not count as Linux syscalls; full/dense/vendor/huge combinations are not all exhausted |
| TEST-03 | Separate Python reader plus exfatprogs `fsck -n`; byte/namespace model | Before/after checks for each resize and each recovered fault; added-capacity probe | Implemented for supported test entries; serializer/reader helper sharing is disclosed |
| TEST-04 | Disposable loop-image driver workload, unmount/resize/read-only remount, added-capacity write | `driver.py --require --seeds 10 --iterations 5000 --output resize/evidence/vm-driver`; `evidence/driver.json` | PASS in one VM: 50,000 real Linux file-workload iterations, ten grows, ten shrinks, twenty read-only mount comparisons, and ten capacity probes; kernel and geometry scope are in the report |
| TEST-05 | Deterministic per-I/O fault positions and reached traces, explicit recovery tests | Complete selected small-fixture sweep; 160 sampled cases on 128–192 MiB images; persistent errors; corrupt commit and preimage tests | Implemented for the stated process model; a physical power-loss model is not supplied or claimed |
| TEST-06 | Existing library and fsck cases; checked exit status; ASan/UBSan/LeakSanitizer | `regressions.py`, `run.py --sanitize --library-only`, existing `make -C lib check` | Native tests run; no claim of hardware, Windows, or driver sanitizer coverage |

TEST-04 passed for the recorded VM kernel and geometry. The release gate remains
open because the other stated qualification items are incomplete. The
implementation must stay experimental. The driver PASS does not prove physical
power-loss resistance or approve production or direct-device use.
