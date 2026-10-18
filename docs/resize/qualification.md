# Qualification record

## Reproduce the checks

Build with the commands in [the guide](README.md). Keep each output directory
new. A test runner rejects an existing output directory.

```sh
make -C lib check
python3 resize/tests/regressions.py --output resize/evidence/upstream
python3 resize/tests/run.py --seeds 1000 --iterations 5000 --jobs 3 --faults \
    --output resize/evidence/images
python3 resize/tests/run.py --sanitize --library-only \
    --output resize/evidence/c-sanitizers
python3 resize/tests/regressions.py --sanitize \
    --output resize/evidence/fsck-sanitizers
```

For the exact checker counterexamples, build the baseline without changing the
working checkout:

```sh
baseline=$(mktemp -d)
git archive 1647ed54299ae8c4343a5edf40b892307f7e6459 | tar -x -C "$baseline"
(cd "$baseline" && ./autogen.sh && ./configure && make -j2)
python3 resize/tests/fsck_regression.py --baseline "$baseline/fsck/fsck.exfat" \
    --output resize/evidence/counterexamples
```

Use a shell with `pipefail` for the archive command. The script requires the
baseline checker to reject a fragmented upcase fixture and the new checker to
accept it. It also checks that a repaired upcase allocation has a valid FAT
chain. The baseline repair lacks that chain. The fixed repair passes the
independent reader after orphan rescue.

The native driver check needs a machine with loop devices, the Linux
exFAT driver, root, and CAP_SYS_ADMIN. It creates only private images and detaches
only loop devices returned for those images:

```sh
sudo python3 resize/tests/driver.py --require --seeds 10 --iterations 5000 \
    --output resize/evidence/vm-driver
```

Without `--require`, missing capabilities produce exit 77 and NOT_RUN. The
GitHub Actions driver job uses `--require`. The workflow file is
`.github/workflows/resize.yml`. No Actions run was started from this local task.

## Evidence layout

Each model case has a seed, workload count, sector and cluster size, compact-FAT
choice, measured allocation/tail placement, six resize checks, capacity probe,
write counts, and final image hash. Workload iterations are dictionary operations.
The final model state is serialized into a real image. They are not 5,000 Linux
file calls on the image. The independent logical model includes zero bytes after
ValidDataLength where a fixture tests partial initialization.

`results.json` records each test outcome, code hashes, compiler, Python version,
platform, base commit, parameters, and elapsed time. `actions.jsonl` records
operation/path and generated-data hashes. The seed and pinned runner reproduce
the remaining deterministic choices. Fault traces contain actual reached I/O
positions and injected modes. They contain no copied file contents.

Successful model images are removed to limit storage use. Failing synthetic
images and journals remain in their case directory. Checker counterexample
images remain available. No automatic reducer is implemented. A failed seed is
a reproducible starting point; reduction is open work.

## Current status

The evidence summary is in `evidence-summary.json`. Its manifests identify the
implementation under test for each campaign. Earlier FAIL or preliminary PASS
results do not replace the final results.

The model and fault campaign used implementation commit `21b1ee5` and test commit
`d0930b7`. The VM driver run used clean source commit
`ca49e427cf0a8a5115c1a57aaf2a906041310aa6`. That commit adds documentation and
does not change executable code. The source hashes for the earlier campaign
are in `evidence-summary.json`. The VM source and binary hashes are in
`evidence/driver.json`.

| Check | Recorded result |
| --- | --- |
| External model | PASS: seeds 0–999, 5,000 iterations each; 5,000,000 dictionary operations |
| Real image resize | PASS: six resizes per model seed; seven sector/cluster geometries |
| Small-fixture faults | PASS: 1,016 reached injections; two additional journal-integrity groups |
| Larger-image faults | PASS: 160 reached sampled scenarios on 128 MiB sources |
| Native suites | PASS: ten C suites and eleven Python unit tests; C suites also passed ASan, UBSan, and LeakSanitizer |
| Existing fsck regressions | PASS: 24 cases normally and the same 24 with sanitizers |
| Existing library suites | PASS: two suites |
| Checker counterexamples | PASS: both exact-baseline failures reproduced and fixed |
| Other regressions | PASS: four inactive-FAT cases, three container controls, three combined-failure records, three actual-signal cases |
| Source distribution | PASS: make dist; all resize sources, tests, and committed evidence included; raw journals and temporary images excluded |
| Clean build and install | PASS: default and opt-in out-of-tree builds; make check; install; four installed-CLI resizes with capacity probe |
| Leak detector health | PASS: deliberate leak detected with expected exit 23 |
| Linux driver | PASS in one VM: seeds 0–9, 5,000 real file-workload iterations each; ten grows and ten shrinks |
| VM build and regressions | PASS: requested build options, make check, two library suites, ten C suites, eleven Python unit tests, and 24 fsck cases |
| GitHub Actions | NOT_RUN: workflow supplied; no push or remote execution |
| Physical power loss | NOT_QUALIFIED: no persistent cache/write-order model |

The main report has 2,030 records. A host-unit record contains eleven Python
unit tests. The sanitizer report repeats the native suites; do not add those
runs to the number of unique suites. Negative controls deliberately run the old
code and require its recorded failure. They are not failures of the final code.

Committed compact reports are in `docs/resize/evidence/`. The complete main
per-case report is `model-and-fault-cases.jsonl`. The raw main report, action
logs, and reached traces were retained in `resize/evidence/verified-final/` in
the original environment. Additional
final runs use the `final-*` paths named in the summary. Raw images and journals
are not embedded in the Git patch. The earlier raw directories are not present
in this VM checkout. Failed and preliminary runs have no final PASS status.

The earlier container could not run the driver suite. Its NOT_RUN record is
retained in `evidence/driver-not-run.json`. The VM run below supplies the driver
result. Earlier raw paths refer to the original qualification environment.
The new raw VM evidence is in `resize/evidence/vm-driver/` and
`resize/evidence/vm-environment/` in this checkout.

Physical power-loss qualification, a persistent cache/write-order model, broad
vendor/GUID combinations, and very large real images remain open. No production or direct-device release is approved.

## Linux-driver qualification in a VM

The specified command passed on 2026-10-18 with exit zero. The runner was not
changed. The source tree was clean before the run. All 175 recorded input-file
hashes remained equal after the run. No executable changes were required.

The VM runs Debian 13 with kernel `6.18.51-1.qubes.fc41.x86_64`. Passwordless
sudo supplied uid zero and CAP_SYS_ADMIN. Effective capabilities were
`000001ffffffffff`. The Linux exFAT module loaded successfully. A free loop
device was available. No loop devices were attached before or after the run.
The build used GCC 14.2.0 and Python 3.13.5. Exact package versions, build
commands, configuration hashes, and binary hashes are in `evidence/driver.json`.

Each seed started with a new 64 MiB image. The filesystem used 512-byte sectors
and 4096-byte clusters. A 48 MiB temporary file placed workload allocations
beyond the 32 MiB shrink target. Seeds with even numbers grew to 96 MiB and then
shrank to 32 MiB. Seeds with odd numbers used the reverse order. The runner
detached the image before each resize. It used only the loop device returned
for that image. It did not change a partition table or use an existing volume.

| Reached check | Count |
| --- | --- |
| Seeds with PASS | 10 |
| Real Linux file-workload iterations | 50,000; 5,000 per seed |
| Committed grow operations | 10 |
| Committed shrink operations | 10; 42–55 allocated clusters moved per shrink |
| Read-only mount and full-content comparisons after resize | 20 |
| Source tail-placement checks | 10 |
| Added-capacity probes | 10; each wrote and hashed 80 MiB |
| Independent reader plus fsck checks | 50 |
| Host preflight and final fsck checks | 40 |

The workload creates, appends, overwrites, truncates, renames, and deletes files.
It uses a stat operation when a rename has no source. Each iteration performs
a real Linux file operation. The counts are workload iterations, not measured
syscall counts or physical writes. The ten action logs each contain 5,000 rows.

After each resize, the reader compared content and metadata with the source
snapshot. It checked the target length, both boot regions, FAT chains, allocation
bitmap, and ownership. Each read-only mount repeated the namespace and content
comparison through the Linux driver. After each grow, an 80 MiB file had to pass
a content hash check and own clusters beyond the old filesystem length. The
file was then deleted. The runner took a new metadata snapshot after this real
directory change.

Reached counts come from the completed PASS paths in the unchanged runner and
the saved action logs and resize records. They are not a separate syscall trace.
The complete raw driver report is `resize/evidence/vm-driver/results.json`.
Its committed copy and provenance are in `evidence/driver.json`. The provenance
includes the source commit, all source hashes, binary hashes, toolchain,
parameters, elapsed time, preflight, action-log hashes, and cleanup result.
The elapsed driver time was 38.89 seconds.

No test failed. There are no failed image or journal artifacts from this run.
Successful images were removed by the existing runner. Action logs, stdout,
stderr, setup logs, and build logs remain in the raw evidence directories.
An initial dependency fetch failed without the existing proxy settings. The
installation then passed with those settings. Both setup logs were retained.

The VM also passed `make check`, `make -C lib check`, and all 24 existing fsck
regressions. See `evidence/vm-verification.json`, `evidence/vm-native.json`, and
`evidence/vm-upstream.json`. These runs repeat existing suites. Do not add them
to the earlier unique-suite counts. No sanitizer campaign was repeated in the VM.

This PASS covers the specified suite on one VM kernel and one sector/cluster
geometry. It does not prove physical power-loss resistance. It does not close
the other release criteria or approve direct-device or production use.

## Failures found during development

The retained baseline checker failed on a legal fragmented upcase chain. A
second counterexample found missing FAT links in a newly repaired upcase stream.
Both have executable before/after checks in `fsck_regression.py`.

Test-fixture corrections were also required. A capacity probe initially left an
end marker before a new root cluster; seed 13 exposed the lost owner. A dense
fixture requested a contiguous run that did not exist; it now uses a FAT chain.
A too-small-target assertion used 1 MiB, which is valid on a compact layout; it
now uses 512 KiB. A compact 4096-byte-sector fixture requested 512-byte alignment;
it now uses one filesystem sector. These were test construction faults. They
are not counted as resize-engine defects. The failed runs were superseded by a
full rerun on the corrected tests.

## Repeat one model seed or the fault sweep

The fixture templates set volume serial `0x52535a45` with `tune.exfat`. This
removes the time-based mkfs serial from final model-image hashes. Workload bytes,
metadata fixtures, placement, and test choices come from the recorded seed.
Real Linux-driver timestamps can still differ across runs; that suite compares
metadata before and after each operation within the same run.

For one model case, select the recorded seed directly:

```sh
PYTHONPATH=resize/tests python3 - <<'PY'
import json
from pathlib import Path
from run import model_case
output = Path('resize/evidence/repeat-seed-13')
output.mkdir(parents=True, exist_ok=False)
print(json.dumps(model_case(13, 5000, output), indent=2))
PY
```

To repeat all selected small-fixture I/O faults without the model campaign:

```sh
python3 resize/tests/run.py --seeds 0 --faults \
    --output resize/evidence/repeat-faults
```

The test-only CLI accepts `--test-fault MODE:POSITION` and `--trace NEW_FILE`.
Modes are `kill`, `eio`, `enospc`, `short`, `eintr`, `cancel`, `eio-persistent`,
and `enospc-persistent`. Positions count reached mutation/durability boundaries.
A persistent error starts at that position and continues in that process.
`short` and `eintr` are handled through the exact-I/O loops. A trace path must
be new; an existing image or log cannot be selected as the trace file.
These controls are for disposable tests only.


## Additional real-image groups

```sh
python3 resize/tests/large_faults.py --output resize/evidence/large-faults
python3 resize/tests/nofat.py --output resize/evidence/inactive-fat
```

The larger campaign uses a 128 MiB source, 4096-byte sectors, 16 KiB clusters,
an 8 MiB data file, and a 5,000-iteration external workload. It tests shrink to
80 MiB and grow to 192 MiB. It samples journal copying, source writes/flushes,
commit, and cleanup. All 160 scenarios must reach the selected position. Each
recovery must pass the reader, full-content/metadata comparison, geometry check,
and fsck. Rollback also compares the complete backing-file hash.

The inactive-FAT group uses four real geometries. Its valid NoFatChain streams
have inactive FAT values that include free, bad-marker, and out-of-range values.
The FAT must not be interpreted for these streams. The original Python reader
incorrectly treated an inactive bad-marker value as a live bad cluster. It also
accepted FAT32 EOC values that exFAT does not permit. The retained old reader in
`resize/tests/baselines/reader-before.py` reproduces both defects. `nofat.py`
checks the old and new results before it tests three resizes per image. These
are validator corrections, not discovered resize-engine data-loss defects.


## Container recognition counterexample

```sh
python3 resize/tests/container.py --output resize/evidence/containers
```

Upstream `mkfs.exfat -P mbr` can create an MBR hybrid with the exFAT signature
at byte zero and PartitionOffset zero. The earlier host accepted this input.
A signature and partition-offset check alone was insufficient. The final host
also rejects a nonzero MBR-entry area before checker or engine mutation. This
conservative support limit can reject custom boot code in the same area.
The baseline host is retained under `resize/tests/baselines/`. The test requires
its dry-run to accept the hybrid, then requires the final dry-run and writing
interface to reject it with unchanged whole-image hashes and no journal.
A plain volume is the positive control. A real GPT image is also rejected.

The host correction was merged into the feature commit with a fixup rebase.
The final complete model/fault campaign was then started from that commit.
Earlier runs do not stand in for that final campaign.


## Actual signals and combined failures

```sh
python3 resize/tests/signals.py --output resize/evidence/signals
python3 resize/tests/cancel_commit.py --output resize/evidence/compound-cancel
```

The signal group sends actual SIGINT during journal copying and SIGTERM during
source mutation. Both return 130 with the complete old-image hash restored.
It also sends SIGTERM during recovery of an actually changed image. Recovery
ignores the cancellation request until old-state restoration and cleanup finish.
Each row records the observed trace boundary and sent signal. A trigger not
reached before process exit fails the test.

The combined-failure test sets a cancellation request and fails the commit
journal-directory flush after marker rename. The baseline then started undo
under the new-state marker. A hard kill before its second undo write left a
mixed image that its own recovery could not accept. The corrected host gives
I/O errors priority, performs no undo in that case, retains the marker and
journal, and recovers the complete new state. An undo primitive also rejects
any existing commit marker before its first write. The baseline source and
broken synthetic image/journal are retained with the test evidence.

LeakSanitizer was checked with a deliberate 123-byte leak. It detected that leak
and returned the requested exit 23. This is an expected tool-health result,
not an application failure. The native application suites use
`detect_leaks=1:halt_on_error=1` and must return zero.


A failure while reading the transaction token can also hide an earlier I/O
error. The final handler reports transaction state as unavailable and returns a
recovery-required status. It does not infer that no transaction exists. The
compound regression includes a controlled metadata-read failure: the baseline
raises a second exception, and the final handler returns status 3.
