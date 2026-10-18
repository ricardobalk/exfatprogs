# Qualification evidence from 18 October 2026

**Bottom line:** This directory contains only results produced by this work. It
does not treat historical context results or tests that did not run as PASS.

See [qualification.md](../qualification.md) for measured results, scope, and
release status. See [requirements.md](../requirements.md) for the mapping from
requirements to code, tests, and evidence.

- `model*.json*` and `sanitizer-model*.json*` record two separate runs of
  1,000 by 5,000 model iterations plus two capacity cases. They do not claim
  driver calls.
- `matrix*.json*` records 288 factorial layouts per build. These layouts are
  separate from the 1,000 seeds.
- `driver.json` records actual Linux exFAT driver use for ten seeds. It covers
  unmount, remount, content, metadata, and rejection of attached image files and
  devices.
- `baseline.json`, `regressions.json`, and `sanitizer-regressions.json` compare
  nine old defects with repaired results. A baseline PASS means that the test
  reproduced the defect.
- `faults*.json*` and `fault-*-boundaries.json` record planned and reached
  injections, real writer positions, recovery, and exit status. Five unreliable
  journal cases are not fault injections. They are not part of the 646 hits.
- `persistence*.json*` records the explicit loss, reordering, and torn-write
  model. It is separate from SIGKILL. `publication.json` also records visibility
  after link and after errors.
- `negative.json`, `transactions.json`, `metadata.json`, and their sanitizer
  versions record boundary and preservation tests. They include nonblocking
  FIFO rejection.
- `upstream.json`, `sanitizer-upstream.json`, `autotools.log`, and
  `internal-tests.log` record existing fixtures and internal build tests. A
  large sparse fsck fixture does not qualify large-volume defrag.
- `clean-apply.json` records the clean application of the complete commit series
  to the base. It also records a clean build, smoke test, and upstream suite in
  that checkout.
- `environment.json`, `build.json`, `sanitizer-build.json`, and
  `baseline-build.json` record the compiler, platform, dependencies, and source
  and binary hashes. Model reports contain the source hashes at their start
  time. `environment.json` contains later test-helper hashes.
- `additional.json`, `sanitizer-additional.json`, and `commands.json` record the
  commands that ran. The full orchestrator is available, but the extensive
  evidence used separate component runs. `smoke.json` records one complete
  short orchestrator run.

Each `*-cases.jsonl` file has one object for each test case. Successful runs
remove their large image files. Failed experiments and large local logs remain
in ignored `build-defrag-tests*` directories. The final evidence does not mark
an unexecuted test as PASS. The prefix reducer is available, but no executed
minimization is claimed.

`manifest.json` contains the SHA-256 digest of each file in this directory,
except itself. Use this command to verify it:

```sh
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('docs/defrag/evidence')
for name, expected in json.loads((p/'manifest.json').read_text()).items():
    assert hashlib.sha256((p/name).read_bytes()).hexdigest() == expected, name
print('artifact hashes match')
PY
```
