# Qualification tests

Generated test results do not belong in the source repository. Each runner
writes its report, logs, traces, and retained failure fixtures to the directory
selected with `--output`. `resize/evidence/` is ignored and is a convenient
local destination. GitHub Actions uses a runner-temporary directory instead.

## Reproduce the checks

Build with the commands in [the guide](README.md). Keep each output directory
new. A test runner rejects an existing output directory.

```sh
make -C lib check
python3 resize/tests/regressions.py --output resize/evidence/upstream
python3 resize/tests/cancel_commit.py --output resize/evidence/compound-cancel
python3 resize/tests/run.py --seeds 1000 --iterations 5000 --jobs 3 --faults \
    --output resize/evidence/images
python3 resize/tests/container.py --output resize/evidence/containers
python3 resize/tests/nofat.py --output resize/evidence/inactive-fat
python3 resize/tests/signals.py --output resize/evidence/signals
python3 resize/tests/large_faults.py --output resize/evidence/large-faults
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

The native driver check needs a machine with loop devices, the Linux exFAT
driver, root, and CAP_SYS_ADMIN. It creates only private images and detaches
only loop devices returned for those images:

```sh
sudo python3 resize/tests/driver.py --require --seeds 10 --iterations 5000 \
    --output resize/evidence/driver
```

Without `--require`, missing capabilities produce exit 77 and NOT_RUN. The
GitHub Actions driver job uses `--require`.

## Test output

`results.json` is the machine-readable test report. The main runner records
each outcome, source hashes, compiler, Python version, platform, source commit,
parameters, and elapsed time. The focused runners add their case-specific
results. `actions.jsonl` records operation paths and generated-data hashes.
Fault traces contain actual reached I/O positions and injected modes. They
contain no copied file contents.

Each model case records its seed, workload count, sector and cluster size,
compact-FAT choice, measured allocation and tail placement, resize checks,
capacity probe, write counts, and final image hash. Workload iterations are
dictionary operations. The final model state is serialized into a real image;
these iterations are not Linux file calls on the image.

Successful model images are removed to limit storage use. Failing synthetic
images and journals remain in their case directory. Checker counterexample
images remain available. No automatic reducer is implemented. A failed seed is
a reproducible starting point; reduction is open work.

## GitHub Actions artifacts

`.github/workflows/resize.yml` converts every recorded JSON case to JUnit XML.
Each job summary first shows a short `What`, `Why`, `Where`, and `If it failed`
table in technical English. A pinned test-reporter action then publishes the
JUnit cases as a GitHub Check with per-suite totals, case names, durations,
skips, and failure evidence. Repeated model and fault cases include their seed,
geometry, direction, fault mode, or reached boundary in the displayed name.

The converter also creates a failing `campaign completion` case when a runner
records an incomplete or failed campaign without a failed child row. If no
`results.json` exists, it creates a failing report-availability case. This
keeps an early build or test-runner failure visible in the GitHub presentation.
Pull requests from forks still receive the job summary and XML artifact, but
the Check publication is skipped because their token cannot write checks.

The workflow uploads test output with `if: always()`, so a failed campaign
retains the JUnit report, source reports, and synthetic failure fixtures that
were created before the failure. The artifacts are:

- `resize-image-test-output` for image, fault, signal, and checker tests;
- `resize-sanitizer-test-output` for native and checker sanitizer tests;
- `resize-driver-test-output` for the manual privileged driver job.

Push and pull-request runs use 28 model seeds. Scheduled runs and manual runs
with `full` selected use 1,000 seeds. The privileged driver job runs only when a
manual workflow dispatch selects `driver`. Artifacts are retained for seven
days. A result applies only to the exact source revision identified by its
workflow run and generated report; an older PASS does not qualify changed code.

The conversion itself is covered by `tests/test_junit_report.py`. Run it with:

```sh
python3 -m unittest discover -s tests -p 'test_junit_report.py' -v
```

Physical power-loss qualification, a persistent cache/write-order model, broad
vendor/GUID combinations, and very large real images remain open. No production
or direct-device release is approved.

## Regression origins

The baseline checker rejects a legal fragmented upcase chain. A second
counterexample exposes missing FAT links in a newly repaired upcase stream.
`fsck_regression.py` keeps executable before/after checks for both cases.

Test-fixture corrections were also required. A capacity probe initially left an
end marker before a new root cluster; seed 13 exposed the lost owner. A dense
fixture requested a contiguous run that did not exist; it now uses a FAT chain.
A too-small-target assertion used 1 MiB, which is valid on a compact layout; it
now uses 512 KiB. A compact 4096-byte-sector fixture requested 512-byte alignment;
it now uses one filesystem sector. These are test construction regressions, not
resize-engine data-loss cases.

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
