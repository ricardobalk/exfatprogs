# Qualification evidence and release status

**Bottom line:** All recorded tests passed on 18 October 2026. The results
qualify the function only for the experimental Linux image-file scope. They do
not qualify direct use on user volumes. The normal build does not build or
install the defragmenter.

The verified base is exfat-next commit
`1647ed54299ae8c4343a5edf40b892307f7e6459`. See
[environment.json](evidence/environment.json),
[build.json](evidence/build.json), and
[sanitizer-build.json](evidence/sanitizer-build.json) for the compiler,
platform, dependencies, and source and binary hashes.

| Test | Result | Evidence |
| --- | --- | --- |
| Nine focused historical regressions | All nine show the expected defect on the pinned baseline; all nine pass on the repaired worker | [baseline](evidence/baseline.json), [repaired](evidence/regressions.json), [sanitizers](evidence/sanitizer-regressions.json) |
| Native model | 1,000 seeds with 5,000 iterations, plus two capacity cases; 1,002 valid and fragmented input images; all results have zero discontinuities | [run](evidence/model.json), [case records](evidence/model-cases.jsonl) |
| ASan, UBSan, and leak-detection model | The same 1,002 cases pass their independent checks; no sanitizer diagnostic occurs | [run](evidence/sanitizer-model.json), [case records](evidence/sanitizer-model-cases.jsonl) |
| Geometry, vendor, occupancy, and depth matrix | 288 native and 288 sanitizer cases: 12 geometries, four vendor variants, three occupancy levels, and two directory depths | [native](evidence/matrix.json), [sanitizers](evidence/sanitizer-matrix.json) |
| Linux exFAT driver | Ten seeds with 5,000 iterations, offline defrag, remount, and model comparison; 130,242 explicit workload system calls, 44,629 effective model changes, and 1,280 extra fragmentation actions | [driver](evidence/driver.json) |
| Small-fixture fault matrix | 651 cases and 646 reached injections; all 67 worker write positions use SIGINT, SIGTERM, SIGKILL, and EIO; tests also cover host, retry, flush, persistent EIO and ENOSPC, interrupted recovery, and unreliable journals | [native](evidence/faults.json), [sanitizers](evidence/sanitizer-faults.json), [positions](evidence/faults-cases.jsonl) |
| Explicit persistence model | 154 native and 154 sanitizer replays; prefixes, loss, reordering, and half writes; recovery always restores the exact original bytes | [native](evidence/persistence.json), [sanitizers](evidence/sanitizer-persistence.json) |
| Copy and publication | 68 native and 68 sanitizer cases; unchanged source, no invalid output, real EEXIST race at link, and visible valid output after post-link flush errors | [native](evidence/publication.json), [sanitizers](evidence/sanitizer-publication.json) |
| Negative checks | 29 native and 29 sanitizer cases; cycles, cross-links, bitmap errors, bad-cluster records, unknown allocations and vendors, corruption, overflow values, invalid containers, lock conflicts, and links; the complete source hash stays equal | [native](evidence/negative.json), [sanitizers](evidence/sanitizer-negative.json) |
| Metadata and boot bytes | 512-byte and 4096-byte sectors; eight attribute combinations, times, subseconds, UTC offsets, VDL, and boot bytes outside the root field stay equal | [native](evidence/metadata.json), [sanitizers](evidence/sanitizer-metadata.json) |
| Directory flush and host death | The worker returns a flush error and undo restores exact bytes; the host rejects a FIFO journal without a block or write; after a host kill, the stopped worker dies and releases the lock before recovery | [native](evidence/transactions.json), [sanitizers](evidence/sanitizer-transactions.json) |
| Existing upstream corruption fixtures | 24 native and 24 sanitizer cases, including the existing large sparse fixture; detect, repair, and clean reread pass | [native](evidence/upstream.json), [sanitizers](evidence/sanitizer-upstream.json) |
| Normal autotools build and `make check` | Both existing internal suites pass with zero skips | [log](evidence/autotools.log) |
| Clean patch application | Five commits apply to the base without a three-way merge; the tree is equal; a clean build, smoke test, and upstream suite pass | [check](evidence/clean-apply.json) |
| Short smoke orchestrator | Build, baseline, repair, negative cases, and three model seeds run as one command | [smoke](evidence/smoke.json) |

The 1,000 main seeds contain 5,000,000 workload iterations. The two capacity
cases increase the run total to 5,010,000 iterations and 4,490,423 effective
model changes. Native and sanitizer runs use the same seeds. They are not 2,000
different seeds. The matrix is also separate from the 1,000-seed claim. A
baseline PASS means that the test reproduced the old defect. It does not mean
that the old implementation is correct.

## Commands used for the recorded evidence

Each component used a separate output directory. This keeps builds and results
independently reviewable. See [additional.json](evidence/additional.json) and
[sanitizer-additional.json](evidence/sanitizer-additional.json) for the exact
arguments of the additional suites.

```sh
python3 tests/defrag/build.py --out build-defrag-tests-final --baseline
python3 tests/defrag/parallel.py --build build-defrag-tests-final \
  --cases 1000 --operations 5000 --jobs 4 \
  --out build-defrag-tests-final/qualification-model
python3 tests/defrag/build.py --sanitize --out build-defrag-tests-sanitize-final
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
python3 tests/defrag/parallel.py --build build-defrag-tests-sanitize-final \
  --cases 1000 --operations 5000 --jobs 4 \
  --out build-defrag-tests-sanitize-final/qualification-model
sudo -n python3 tests/defrag/mounted.py --build build-defrag-tests-final \
  --seeds 10 --operations 5000 --out build-defrag-tests-final/qualification-driver
python3 tests/defrag/qualify.py \
  --out build-defrag-tests-final/qualification-smoke-final-proof
```

For fault injection with ASan, `DEFRAG_ASAN_RUNTIME` is the result of
`cc -print-file-name=libasan.so`. This loads the ASan runtime before the worker
interposer. Python and fsck do not use that interposer.

`qualify.py --full --driver` can run all components with one command. The
recorded full evidence used the separate component commands above. The recorded
short smoke test used the complete short orchestrator. The report does not claim
that the full orchestrator ran as one invocation.

The GitHub Actions workflow repeats the short qualification with GCC and Clang.
It also runs focused sanitizer tests. Its scheduled full job runs the rootless
program. The manual driver job runs the privileged loop-image tests. CI results
are new run artifacts. They do not replace the evidence recorded in this tree.

## Warnings and claims that were not run

The explicit builds show three existing warning types in unchanged code. These
are an unused `ui` parameter without blkid and signedness comparisons in
`lib/exfat_dir.c` and `fsck/fsck.c`. The historical baseline also has signed-char
bitmap warnings. The repaired worker uses unsigned char. It adds no C compiler
warning.

Checkpatch v6.18 reports zero errors and one style warning for a 102-column
line. The additional spelling and const-structure lists were not available.
Those two checks did not run. See [checkpatch.log](evidence/checkpatch.log).

The normal autotools build and internal suites ran without sanitizers. The
explicit C binaries and new image and fault suites also ran with ASan, UBSan,
and leak detection. The evidence does not include a big-endian run, a hardware
power-loss test, large-volume defrag, TexFAT defrag, general vendor defrag, or
bad-cluster defrag.

## Investigation runs that do not count as evidence

The first driver fixture grew from 4 KiB to 12 KiB. It did not fragment with
16-KiB clusters. The final fixture uses the actual cluster size. Every recorded
driver seed has positive fragmentation before defrag.

An earlier model generator selected two random truncate sizes for one operation.
That run stopped. The complete final runs use one correct truncate size. An
early negative vendor test searched only the root. The final test searches
directories recursively. These incomplete or incorrect runs are not PASS
results in the table.

A raw-worker I/O error can leave an inconsistent image. An early test required
a valid final image after this error. That requirement was too strong for the
raw worker. The final test checks error propagation directly. Separate journal
tests check exact safe recovery. This result shows why a local worker repair or
a copy wrapper alone is not sufficient.

Model evidence contains the source hashes from the start of each run.
`environment.json` also contains later test-helper hashes. The only later
operational boundary repair adds O_NONBLOCK when it opens source and journal
files. This prevents a FIFO from blocking before the regular-file check. Native,
sanitizer, and smoke tests cover it. O_NONBLOCK has no effect on regular image
files. The tested C worker and layout parser did not change during the final
runs. [ADR 0004](adr/0004-release.md) still limits the release claim.
