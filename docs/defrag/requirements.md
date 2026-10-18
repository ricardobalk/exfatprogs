# Requirements, evidence, and limits

**Bottom line:** All requirements pass only in the documented experimental
image-file scope. Direct use on user volumes remains blocked. The last column
states each evidence limit.

| Requirement | Implementation | Test | Evidence and limit |
| --- | --- | --- | --- |
| F01: Preserve content, paths, metadata, and VDL | `defrag.c` writeback; `layout.py` comparison | `run.py`, `mounted.py`, `metadata.py` | `model.json`, `driver.json`, `metadata.json`; the validator also checks physical allocation fields |
| F02: Give measurable defragmentation | `layout.py` report; `defrag.c` swaps | Independent `Image.inspect`; second no-op run | `model-cases.jsonl`; extents and discontinuities per allocation; free gaps between files do not count |
| F03: Complete checks before writes | `layout.py`; `BFS_read_file_tree` ownership | `negative.py`; full fixtures | `negative.json`, `matrix.json`, `model-cases.jsonl`; bad-cluster volumes, fragmented input system files, and general vendor formats are not supported |
| F04: Read-only analysis and controlled interface | `Image`, `check_loops`, flock, CLI | Dry-run hash for each model seed; `negative.py`; `mounted.py` | `model-cases.jsonl`, `negative.json`, `driver.json`; locks are advisory and visibility across namespaces is limited |
| S01: Cancellation | `sig_atomic_t` in C; Python handler records signals | Every small worker write; host and recovery boundaries | `fault-cases.jsonl`; status 130 or 143 and exact rollback; cancellation during the commit batch can keep a valid new state |
| S02: Recovery protocol | `image_defrag.py` journal | `faults.py`, `persistence.py`, `transaction_regressions.py` | `faults.json`, `persistence.json`, `transactions.json`; bounded regular-file host; no block-device or hardware power-loss qualification |
| S03: Copy and publication | `defrag_image.py` | `publication.py` | `publication.json`; source hash, corruption, kill, no-replace race, and visibility after a directory-flush error |
| TEST01: Old defects | Pinned baseline in `build.py` | Nine cases in `regressions.py` | `baseline.json` compared with `regressions.json`; raw-worker fault injection promises error propagation only; journal tests verify recovery |
| TEST02: 1,000 by 5,000 | Model in `image.py`; partitions in `parallel.py` | Native and ASan/UBSan; each has 1,000 seeds and two capacity cases | `model.json`, `sanitizer-model.json`; separate iteration, effective-change, and driver-call counts; 288 layouts per build in `matrix.json`; large encoded values in `negative.json`; no large-volume relocation claim |
| TEST03: Independent reader and fsck | `image.py`, `fsck.exfat` | All model and driver images before and after | Case records contain fsck status and full semantic comparison; the reader does not import `layout.py` |
| TEST04: 10 by 5,000 driver workload | Private mount namespace in `mounted.py` | Linux driver, unmount, defrag, and remount | `driver.json`; only owned temporary images and loop devices; explicit workload system calls are counted |
| TEST05: Short I/O, EINTR, zero I/O, EIO, ENOSPC, flush, signals, and kill | `fault.c`, `Faults` | `faults.py`, `persistence.py`, `publication.py` | Only reached positions count; small-fixture boundaries are exhaustive; larger layouts use model and driver tests; faults are not exhaustive on all large fixtures |
| TEST06: Sanitizers and upstream cases | Explicit sanitizer build | Full model; fault, recovery, publication, negative, and upstream suites | `sanitizer-*.json`; ASan, UBSan, and leak detection; a disabled check is not PASS |
| Reproducibility | `build.py`, `qualify.py`, `minimize.py` | Smoke test and separate full components | `environment.json`, `commands.json`, source and binary hashes; the prefix reducer exists, but no minimization result is claimed |
| Normal release | `Makefile.am` and `configure.ac` stay unchanged | Build and source inspection | BLOCKED for direct use on user volumes; see ADR 0004 |

`image.py` contains both the fixture generator and the independent reader. Thus,
the serializer is not independent from its own format helpers. Expected file
bytes come from a separate model. The reader is independent from the C engine
and the production checks. The Linux-driver test supplies an independently
implemented serializer.
