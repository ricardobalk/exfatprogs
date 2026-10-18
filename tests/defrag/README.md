# Experimental defrag qualification

Read [the complete scope and protocol](../../docs/defrag/README.md) before use.
The normal build/install remains disabled. The C binary built here is an
internal worker without its own journal; the operational image entry point is
`defrag/defrag.exfat`.

From the repository root:

```sh
python3 tests/defrag/qualify.py --out defrag-test-results-smoke
python3 tests/defrag/qualify.py --full --driver --jobs 4 --out defrag-test-results-full
```

The full run executes 1,000 seeds of 5,000 model iterations, plus capacity cases,
natively and with ASan/UBSan and leak detection, all small-fixture worker-write
faults, journal/commit/recovery/publication boundaries, persistence replays,
negative preflight, metadata probes, existing upstream fixtures and (with
`--driver`) ten seeds of 5,000 real driver workload iterations. Without driver
capabilities a NOT_RUN remains a blocker. The smoke run does not claim the full
qualification program.

Results are JSON/JSONL even on failure. Failed cases retain images, journals,
operation logs and expected manifests. Passing large temporary images are
removed. Source/binary hashes and reached fault positions make the counts
reviewable. Historical files under `context/` are inputs, not current evidence.
